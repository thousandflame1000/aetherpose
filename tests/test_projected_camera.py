from pathlib import Path
import sys,unittest
import numpy as np
from scipy.spatial.transform import Rotation
BASE=Path(__file__).resolve().parent;ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'frontend'),str(ROOT/'frontend')]
from camera_alignment import estimate_camera_alignment
from generic_body import GenericBody
from hybrid_fusion import RotationFusion,image_landmarks_to_smpl
from kinematic_fusion import global_rotations
from vision_pose import PoseObservation,undo_image_rotation

class IntegrationTests(unittest.TestCase):
 def setUp(self):
  self.body=GenericBody();self.f=RotationFusion(self.body.J_rest,self.body.parents);self.f.bind_foot_skin(self.body)

 def test_camera_extrinsic_from_measured_rays_is_posture_and_view_independent(self):
  for pose in ([0,0,0],[90,0,0],[-90,0,0],[0,0,90],[30,50,10]):
   local=np.tile(np.eye(3),(24,1,1));local[0]=Rotation.from_euler('xyz',pose,degrees=True).as_matrix()
   local[18]=Rotation.from_euler('y',-60,degrees=True).as_matrix();local[19]=Rotation.from_euler('y',45,degrees=True).as_matrix()
   G=global_rotations(local,self.f.parents);q=self.f.joints(local);sensors={j:G[j] for j in (0,4,5,18,19,15)}
   for view in ([0,0,0],[30,80,10],[-20,180,0],[70,-30,15]):
    basis=Rotation.from_euler('xyz',view,degrees=True).as_matrix()
    estimated,diagnostics=estimate_camera_alignment(self.f,sensors,q@basis,np.ones(24))
    np.testing.assert_allclose(estimated,basis,atol=1e-7)
    self.assertGreaterEqual(diagnostics['inliers'],2)

 def test_parallel_rays_are_rejected_without_upright_guess(self):
  q=self.f.joints(np.tile(np.eye(3),(24,1,1)))
  with self.assertRaises(ValueError):estimate_camera_alignment(self.f,{4:np.eye(3),5:np.eye(3)},q,np.ones(24))

 def test_rotation_undo_preserves_world_depth_and_image_correspondence(self):
  p=np.array([[.2,-.4,.7],[-.1,.3,-.2]]);uv=np.array([[.2,.4],[.8,.7]])
  for k in range(4):
   w=p.copy();r=uv.copy()
   for _ in range(k):w=np.column_stack((w[:,1],-w[:,0],w[:,2]));r=np.column_stack((r[:,1],1-r[:,0]))
   restored,image=undo_image_rotation(w,r,k)
   np.testing.assert_allclose(restored,p,atol=1e-12);np.testing.assert_allclose(image,uv,atol=1e-12)

 def test_image_metadata_preserves_two_item_api_and_aspect(self):
  observation=PoseObservation(np.zeros((33,3)),np.ones(33),np.tile([.4,.3],(33,1)),(640,800))
  self.assertEqual(len(observation),2);points,confidence=observation
  q,c=image_landmarks_to_smpl(observation.image_points,confidence,observation.image_size)
  np.testing.assert_allclose(q,0,atol=1e-12);self.assertEqual(c.shape,(24,))

 def test_floor_contact_handles_supine_prone_and_side_lying_surface(self):
  for euler in ([90,0,0],[-90,0,0],[0,0,90]):
   R=np.tile(np.eye(3),(24,1,1));R[0]=Rotation.from_euler('xyz',euler,degrees=True).as_matrix()
   P=self.f.joints(R);shift=self.f.body_floor_translation(R,P)
   # Independent full mesh skinning rather than the contact helper's samples.
   mesh=self.body.lbs_frame(R)-self.body.J_rest[0]
   self.assertAlmostEqual(float(mesh[:,1].min()+shift+.97),0,places=5)

if __name__=='__main__':unittest.main()
