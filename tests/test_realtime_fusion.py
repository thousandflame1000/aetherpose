"""Live path regressions: sparse sources, causal timing and SMPL joint motion."""
from pathlib import Path
import sys,unittest
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'frontend'))
from hybrid_fusion import RotationFusion
from kinematic_fusion import KinematicFusion,hinge_angle,rotation,quaternion,limited
from tracking_fusion import RealtimeFusion
from rotation_filter import RotationOneEuro
from test_hybrid_fusion import runner,tracker,calibrate,REST,PARENTS

class RealtimeTests(unittest.TestCase):
 def setUp(self):self.fusion=RotationFusion(REST,PARENTS);self.eye=np.tile(np.eye(3),(24,1,1))

 def test_fresh_camera_events_are_not_multiplied_by_imu_ticks(self):
  f=RealtimeFusion(self.fusion);q=REST.copy();c=np.ones(24)
  # Patch only this residual estimator to count real calls, not the whole fit.
  calls=[]
  def feedback(q,c,s,p,dt):calls.append(dt);return p+.001,True
  f.yaw_feedback=feedback
  for i in range(10):f.step(self.eye,(q,c),{0:np.eye(3)},{},None,1+i/120,1.)
  self.assertEqual(len(calls),1);self.assertEqual(f.complete_streak,1)
  self.assertAlmostEqual(f.correction,.001)
  f.step(self.eye,None,{0:np.eye(3)},{},None,1.1,None)
  self.assertEqual(len(calls),1);self.assertFalse(f.diagnostics['heading_feedback_active'])
  self.assertAlmostEqual(f.correction,.001)

 def test_elbow_flexion_and_forearm_roll_survive_constraint_projection(self):
  f=KinematicFusion(self.fusion)
  for j,sign in ((18,-1),(19,1)):
   distal=j+2;axis=(REST[distal]-REST[j]).copy();axis[1]=0;axis/=np.linalg.norm(axis)
   R=self.eye.copy();R[j]=rotation(1,sign*np.deg2rad(70))@Rotation.from_rotvec(axis*np.deg2rad(60)).as_matrix()
   projected=f.project(R)
   np.testing.assert_allclose(projected,R,atol=1e-8)
   np.testing.assert_allclose(f.project(projected),projected,atol=1e-8)
  bad=self.eye.copy();bad[4]=Rotation.from_euler('xyz',[-40,30,20],degrees=True).as_matrix()
  bounded=f.project(bad);self.assertGreaterEqual(hinge_angle(bounded[4],0),-1e-8)
  self.assertLess(np.linalg.norm(Rotation.from_matrix(bounded[4]).as_rotvec()[1:]),1e-8)

 def test_variable_dt_limits_and_sparse_inputs_do_not_require_six(self):
  for count in (0,1,2,6,19):
   f=RealtimeFusion(self.fusion);sensors={j:np.eye(3) for j in list(range(24))[:count]}
   camera=(REST.copy(),np.ones(24))
   raw,out,seen,_=f.step(self.eye,camera,sensors,{},None,1,1)
   self.assertTrue(np.isfinite(out).all());self.assertTrue(seen)
   np.testing.assert_allclose(np.linalg.det(out),np.ones(24),atol=1e-7)
   P=self.fusion.joints(out)
   for j in range(1,24):self.assertAlmostEqual(np.linalg.norm(P[j]-P[PARENTS[j]]),np.linalg.norm(REST[j]-REST[PARENTS[j]]))
  f=KinematicFusion(self.fusion);prior=self.eye.copy();prior[4]=rotation(0,np.deg2rad(100))
  for dt in (1/120,1/15):
   out=f.fit(self.eye,None,{}, {},prior=prior,dt=dt)
   self.assertLessEqual(np.degrees(hinge_angle(out[4],0)),160*dt+1e-7)

 def test_camera_only_preserves_elbow_bend_in_different_observed_planes(self):
  rest=REST.copy();rest[16]=[.2,.5,0];rest[18]=[.5,.5,0];rest[20]=[.8,.5,0]
  fusion=RotationFusion(rest,PARENTS)
  for roll in (-90,0,90):
   truth=self.eye.copy();truth[16]=rotation(0,np.deg2rad(roll));truth[18]=rotation(1,-np.deg2rad(70))
   q=fusion.joints(truth);f=KinematicFusion(fusion)
   out=f.fit(self.eye,(q,np.ones(24)),{}, {},dt=1.)
   self.assertAlmostEqual(np.degrees(hinge_angle(out[18]@f.twist(out[18],18,20).T,1,-1)),70,delta=2)
   self.assertLess(np.linalg.norm(fusion.joints(out)[20]-q[20]),.025)

 def test_filter_reprojects_flexion_roll_and_resets_after_long_gap(self):
  f=RealtimeFusion(self.fusion);old=self.eye.copy()
  for i in range(25):
   prior=self.eye.copy();prior[18]=rotation(1,-np.deg2rad(60+20*np.sin(i)))@rotation(0,np.deg2rad(70*np.cos(i)))
   old,out,_,_=f.step(old,None,{}, {},prior,1+i/60,None)
   np.testing.assert_allclose(f.kinematic.project(out),out,atol=1e-8)
  raw,out,_,_=f.step(old,None,{}, {},self.eye,4,None)
  np.testing.assert_allclose(out,raw,atol=1e-8)

 def test_runner_options_reset_and_globalpose_dropout_continuity(self):
  r=runner();ts={b:tracker(b) for b in (32,42,11,21,4,0)};calibrate(r,ts)
  r.configure_tracking(stabilize=False,constraints=False);r.push_frame(ts)
  self.assertFalse(r.stats['rotation_filter']);self.assertFalse(r.stats['joint_constraints'])
  with self.assertRaises(ValueError):r.configure_tracking(stabilize='yes',constraints=True)
  r._tracking.correction=.2;r._reset_tracking(keep_heading=True);self.assertAlmostEqual(r._tracking.correction,.2)
  r.reset_camera_alignment();self.assertEqual(r._tracking.correction,0)
  r.gp.latest=lambda now:((self.eye,np.array([2.,0.,0.])),None);r.push_frame(ts)
  r.gp.latest=lambda now:((self.eye,np.array([2.4,0.,0.])),None);r.push_frame(ts)
  self.assertAlmostEqual(r._pose.translation[0],.4)
  ts.pop(0);r.push_frame(ts);self.assertAlmostEqual(r._pose.translation[0],.4)
  ts[0]=tracker(0);r.gp.latest=lambda now:((self.eye,np.array([4.,0.,0.])),None);r.push_frame(ts)
  self.assertAlmostEqual(r._pose.translation[0],.4)

 def test_rotation_filter_reduces_noise_without_future_samples(self):
  rng=np.random.default_rng(22);f=RotationOneEuro(self.eye);values=[];raws=[]
  for _ in range(200):
   raw=Rotation.from_rotvec(rng.normal(0,np.deg2rad(.8),(24,3))).as_matrix()
   out=f.update(raw,1/60);raws.append(Rotation.from_matrix(raw).magnitude());values.append(Rotation.from_matrix(out).magnitude())
  self.assertLess(np.mean(np.square(values[20:])),np.mean(np.square(raws[20:]))*.5)

 def test_fast_rotation_math_matches_reference_including_half_turns(self):
  f=KinematicFusion(self.fusion);rng=np.random.default_rng(123)
  matrices=Rotation.random(60,random_state=rng).as_matrix()
  matrices=np.concatenate([matrices,Rotation.from_rotvec(np.eye(3)*np.pi).as_matrix()])
  for R in matrices:
   np.testing.assert_allclose(Rotation.from_quat(quaternion(R)).as_matrix(),R,atol=1e-10)
   for j in (1,3,7,16,20):
    e=Rotation.from_matrix(R).as_euler('xyz',degrees=True)
    reference=Rotation.from_euler('xyz',np.clip(e,*f.bounds[j]),degrees=True).as_matrix()
    np.testing.assert_allclose(f.bounded(R,j),reference,atol=1e-9)
   cap=.4;v=Rotation.from_matrix(R).as_rotvec()
   reference=Rotation.from_rotvec(v*min(1,cap/max(np.linalg.norm(v),1e-12))).as_matrix()
   np.testing.assert_allclose(limited(R,np.eye(3),cap),reference,atol=1e-9)

if __name__=='__main__':unittest.main()
