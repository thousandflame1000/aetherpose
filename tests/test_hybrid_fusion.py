"""Behavioral checks for variable-count fusion and real runner freshness gates."""
from pathlib import Path
import sys,threading,time,unittest
from unittest.mock import patch
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'frontend'))
from hybrid_fusion import RotationFusion,BONE_TO_JOINT,GP_BONES,landmarks_to_smpl
from hybrid_runner import HybridRunner
import body_calibration

PARENTS=np.array([-1,0,0,0,1,2,3,4,5,6,7,8,9,9,9,12,13,14,16,17,18,19,20,21])
REST=np.zeros((24,3))
for j in range(1,24):REST[j]=REST[PARENTS[j]]+np.array([.05*(-1 if j%2 else 1),.1,.03])

class GP:
    def __init__(self):self.calls=[];self.invalidated=0
    def submit(self,*args):self.calls.append(args)
    def invalidate(self):self.invalidated+=1
    def latest(self,now):return None,None

def runner():
    with patch.object(HybridRunner,'_init',lambda self:None):r=HybridRunner()
    r.fusion=RotationFusion(REST,PARENTS);r.gp=GP()
    r.body.smpl2imu=np.eye(3)
    return r

def tracker(bone,ident=None,age=0):
    return {'id':bone if ident is None else ident,'assigned_bone':bone,'last_update_ms':age,
            'rotation':[0,0,0,1],'accel':[0,0,9.81],'gyro':[0,0,0]}

def calibrate(r,trackers):
    for t in trackers.values():
        r.body.device2bone[t['id']]=np.eye(3);r.body.offsets[t['id']]=np.zeros(3)

class FusionTests(unittest.TestCase):
    def test_variable_counts_and_no_fake_globalpose_slots(self):
        for count in (0,1,2,4,6,7,12,19):
            r=runner();bones=list(BONE_TO_JOINT)[:count]
            trackers={b:tracker(b) for b in bones};calibrate(r,trackers)
            r.push_frame(trackers)
            self.assertEqual(r.stats['imu_count'],count)
            self.assertEqual(len(r.gp.calls),int(all(b in bones for b in GP_BONES)))
            if count:
                self.assertTrue(np.isfinite(r._pose.joints).all())
                R=np.array(r._pose.rotations).reshape(24,3,3)
                np.testing.assert_allclose(R@R.transpose(0,2,1),np.tile(np.eye(3),(24,1,1)),atol=3e-5)
    def test_camera_grounding_tracks_skinned_soles_when_knees_bend(self):
        from types import SimpleNamespace
        fusion=RotationFusion(REST,PARENTS)
        weights=np.zeros((2,24));weights[0,7]=1;weights[1,8]=1
        template=REST[[7,8]]+np.array([0,-.1,0])
        fusion.bind_foot_skin(SimpleNamespace(weights=weights,v_template=template))
        for angle in (0,45,90):
            rotations=np.tile(np.eye(3),(24,1,1))
            rotations[4]=Rotation.from_euler('z',angle,degrees=True).as_matrix()
            positions=fusion.joints(rotations)
            shift=fusion.foot_floor_translation(rotations,positions)
            left=positions[7]+rotations[4]@np.array([0,-.1,0])
            right=positions[8]+np.array([0,-.1,0])
            self.assertAlmostEqual(min(left[1],right[1])+shift,-.97)

    def test_face_plane_drives_leaf_head_and_yields_to_head_imu(self):
        from hybrid_fusion import head_orientation
        world=np.zeros((33,3));confidence=np.ones(33)
        world[7]=[.1,0,0];world[8]=[-.1,0,0]
        world[[2,5],1]=-.05;world[[9,10],1]=.05
        axes,quality=head_orientation(world,confidence)
        np.testing.assert_allclose(axes,np.eye(3),atol=1e-6)
        confidence[7]=0;self.assertIsNone(head_orientation(world,confidence))
        fusion=RotationFusion(REST,PARENTS);old=np.tile(np.eye(3),(24,1,1))
        face=Rotation.from_euler('x',45,degrees=True).as_matrix()
        imu=Rotation.from_euler('x',-45,degrees=True).as_matrix()
        fitted,seen=fusion.fit(old,camera_axes={15:(face,1.)})
        self.assertIn(15,seen)
        self.assertLess(Rotation.from_matrix(fitted[15]@face.T).magnitude(),.1)
        fitted,_=fusion.fit(old,sensors={15:imu},camera_axes={15:(face,1.)})
        self.assertLess(Rotation.from_matrix(fitted[15]@imu.T).magnitude(),Rotation.from_matrix(fitted[15]@face.T).magnitude())

    def test_globalpose_requires_pelvis_and_real_gyro(self):
        r=runner();ts={b:tracker(b) for b in GP_BONES};calibrate(r,ts)
        r.push_frame(ts);self.assertEqual(len(r.gp.calls),1)
        resets=r.gp.invalidated
        ts[2]=ts.pop(0);ts[2]['assigned_bone']=2
        r.push_frame(ts);self.assertEqual(len(r.gp.calls),1);self.assertEqual(r.gp.invalidated,resets+1)
        ts[0]=tracker(0);ts[0].pop('gyro');r.push_frame(ts)
        self.assertEqual(len(r.gp.calls),1)
    def test_stale_uncalibrated_and_duplicate_inputs_are_excluded(self):
        r=runner();ts={0:tracker(0),1:tracker(4,age=251),2:tracker(32)};calibrate(r,{0:ts[0],1:ts[1]})
        r.push_frame(ts);self.assertEqual(r.stats['imu_count'],1);self.assertEqual(r.stats['uncalibrated'],1)
        ts[3]=tracker(0,ident=200);calibrate(r,{3:ts[3]})
        r.push_frame(ts);self.assertEqual(r.stats['imu_count'],0)
    def test_camera_expiry_stops_new_camera_only_poses(self):
        r=runner();r.camera=(REST.copy(),np.ones(24),time.monotonic());r.push_frame({})
        self.assertIn('HYBRID',r.status);version=r._version
        r.camera=(REST.copy(),np.ones(24),time.monotonic()-1);r.push_frame({})
        self.assertTrue(r.status.startswith('Waiting'));self.assertEqual(r._version,version)
    def test_camera_and_imu_require_alignment_and_lose_scoring_when_partial(self):
        r=runner();ts={32:tracker(32)};calibrate(r,ts)
        r.camera=(REST.copy(),np.ones(24),time.monotonic());r.push_frame(ts)
        self.assertIn('PARTIAL',r.status);self.assertTrue(r.stats['waiting_alignment'])
        r.alignment=np.eye(3);r.push_frame(ts)
        self.assertIn('HYBRID',r.status)
    def test_sensor_rotates_segment_and_preserves_all_bone_lengths(self):
        fusion=RotationFusion(REST,PARENTS);old=np.tile(np.eye(3),(24,1,1))
        target=Rotation.from_euler('z',90,degrees=True).as_matrix()
        rotations,_=fusion.fit(old,sensors={18:target})
        positions=fusion.joints(rotations)
        for j in range(1,24):
            self.assertAlmostEqual(np.linalg.norm(positions[j]-positions[PARENTS[j]]),np.linalg.norm(REST[j]-REST[PARENTS[j]]))
        self.assertGreater(np.linalg.norm(positions[20]-REST[20]),.05)
    def test_unobserved_descendants_keep_local_orientation(self):
        fusion=RotationFusion(REST,PARENTS);old=np.tile(np.eye(3),(24,1,1))
        target=Rotation.from_euler('z',70,degrees=True).as_matrix()
        fitted,_=fusion.fit(old,sensors={16:target})
        np.testing.assert_allclose(fitted[18],np.eye(3),atol=1e-6)
        np.testing.assert_allclose(fitted[20],np.eye(3),atol=1e-6)

    def test_identity_changes_invalidate_globalpose_even_at_same_bone(self):
        r=runner();ts={b:tracker(b) for b in GP_BONES};calibrate(r,ts)
        r.push_frame(ts);before=r.gp.invalidated
        ts[32]=tracker(32,ident=200);calibrate(r,{32:ts[32]})
        r.push_frame(ts);self.assertEqual(r.gp.invalidated,before+1)

    def test_translation_holds_through_model_dropout_and_recenters(self):
        r=runner();ts={b:tracker(b) for b in GP_BONES};calibrate(r,ts)
        r.gp.latest=lambda now:((np.tile(np.eye(3),(24,1,1)),np.array([2.,0.,0.])),None)
        r.push_frame(ts)
        r.gp.latest=lambda now:((np.tile(np.eye(3),(24,1,1)),np.array([2.4,0.,0.])),None)
        r.push_frame(ts);self.assertAlmostEqual(r._pose.translation[0],.4)
        ts.pop(0);r.push_frame(ts)
        self.assertAlmostEqual(r._pose.translation[0],.4)
        self.assertFalse(r.stats['globalpose'])
        r.reset_origin();r.push_frame(ts);self.assertEqual(r._pose.translation,[0.,0.,0.])

    def test_camera_restart_invalidates_extrinsics(self):
        r=runner();r.camera=(REST.copy(),np.ones(24),time.monotonic());r.alignment=np.eye(3)
        r.reset_camera_alignment();self.assertIsNone(r.camera);self.assertIsNone(r.alignment)

    def test_camera_nonfinite_and_wrong_landmark_count_rejected(self):
        for p,c in ((np.zeros((32,3)),np.ones(33)),(np.full((33,3),np.nan),np.ones(33))):
            with self.assertRaises(ValueError):landmarks_to_smpl(p,c)

if __name__=='__main__':unittest.main()
