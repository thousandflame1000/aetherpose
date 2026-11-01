"""Independent constructed-rig regressions for root-conditioned v6 inference.

Only tiny fixed fixtures are used: no multiview benchmark truth is read here.
Known poses construct sensor/image observations, then remain scoring-only.
"""
from pathlib import Path
import os,sys,unittest,json
import numpy as np
from scipy.spatial.transform import Rotation

ROOT=Path(__file__).resolve().parents[1]
BASE=Path(__file__).resolve().parent
IMPL=Path(os.environ.get('AETHER_TEST_FRONTEND',str(ROOT/'frontend')))
sys.path[:0]=[str(IMPL),str(ROOT/'frontend')]
from generic_body import GenericBody
from hybrid_fusion import RotationFusion
from kinematic_fusion import KinematicFusion,global_rotations,rotation,hinge_angle
from tracking_fusion import RealtimeFusion

def distance(A,B):return float(np.degrees(Rotation.from_matrix(A@B.T).magnitude()))

class ParentConditioningTests(unittest.TestCase):
 def setUp(self):
  body=GenericBody();self.f=RotationFusion(body.J_rest,body.parents)
  self.eye=np.tile(np.eye(3),(24,1,1))

 def observations(self,pose):
  G=global_rotations(pose,self.f.parents)
  return {j:G[j].copy() for j in (0,4,5,15,18,19)}

 def bent_pose(self):
  pose=self.eye.copy()
  pose[1]=rotation(0,np.deg2rad(-60));pose[2]=rotation(0,np.deg2rad(-60))
  pose[4]=rotation(0,np.deg2rad(100));pose[5]=rotation(0,np.deg2rad(100))
  pose[16]=Rotation.from_euler('xyz',[15,10,-35],degrees=True).as_matrix()
  pose[17]=Rotation.from_euler('xyz',[-10,-15,35],degrees=True).as_matrix()
  pose[18]=rotation(1,-np.deg2rad(70))@rotation(0,np.deg2rad(20))
  pose[19]=rotation(1,np.deg2rad(70))@rotation(0,-np.deg2rad(20))
  return pose

 def test_corrected_root_does_not_apply_compensating_knee_rotation_twice(self):
  actual=self.bent_pose();sensors=self.observations(actual);target=global_rotations(actual,self.f.parents)
  prior=actual.copy();prior[0]=rotation(0,np.deg2rad(45))
  prior[4]=rotation(0,np.deg2rad(55));prior[5]=rotation(0,np.deg2rad(55))
  # The bad root and knee compensate exactly at the two observed shin IMUs.
  predicted=global_rotations(prior,self.f.parents)
  np.testing.assert_allclose(predicted[[4,5]],target[[4,5]],atol=1e-10)
  fitter=KinematicFusion(self.f)
  output=fitter.fit(prior,None,sensors,{},prior=prior,dt=1.)
  G=global_rotations(output,self.f.parents)
  np.testing.assert_allclose(G[0],sensors[0],atol=1e-10)
  for parent,hinge in ((1,4),(2,5)):
   self.assertLess(distance(G[parent],target[parent]),.51)
   self.assertLess(distance(G[hinge],sensors[hinge]),1e-6)
   self.assertAlmostEqual(np.degrees(hinge_angle(output[hinge],0)),100,delta=.51)

 def test_exact_prior_and_sensors_do_not_regress_with_arbitrary_camera_basis(self):
  actual=self.bent_pose();actual[0]=Rotation.from_euler('xyz',[75,25,-10],degrees=True).as_matrix()
  sensors=self.observations(actual);target=global_rotations(actual,self.f.parents)
  points=self.f.joints(actual);confidence=np.ones(24)
  for yaw,pitch in ((0,0),(90,0),(180,0),(45,60),(-45,-20)):
   basis=Rotation.from_euler('yx',[yaw,pitch],degrees=True).as_matrix()
   image=(points@basis[:,:2])*.3+np.array([.2,-.1])
   fitter=KinematicFusion(self.f)
   output=fitter.fit(actual,(points,confidence),sensors,{},prior=actual,dt=1.,camera_basis=basis,camera_image=(image,confidence))
   G=global_rotations(output,self.f.parents)
   for j in (1,2,16,17):self.assertLess(distance(G[j],target[j]),.51,msg=f'joint {j}, camera {yaw}/{pitch}')
   for j in (0,4,5,18,19):self.assertLess(distance(G[j],sensors[j]),1e-6)

 def end_on_fixture(self):
  actual=self.eye.copy();actual[1]=rotation(0,-np.pi/2);actual[4]=rotation(0,np.deg2rad(100))
  prior=actual.copy();prior[1]=rotation(0,-np.pi/4);prior[4]=rotation(0,np.deg2rad(55))
  sensors=self.observations(actual);points=self.f.joints(actual)
  image=(points[:,:2])*.3;confidence=np.ones(24)
  self.assertLess(np.linalg.norm(image[4]-image[1]),1e-7)
  return actual,prior,sensors,points,image,confidence

 def test_end_on_thigh_recovers_knee_when_measured_image_scale_is_available(self):
  actual,prior,sensors,points,image,confidence=self.end_on_fixture()
  fitter=KinematicFusion(self.f)
  output=fitter.fit(prior,(points,confidence),sensors,{},prior=prior,dt=1.,camera_basis=np.eye(3),camera_image=(image,confidence))
  self.assertIsNotNone(fitter.image_scale)
  self.assertAlmostEqual(fitter.image_scale,.3,places=6)
  actual_knee=100;old_knee=55;new_knee=float(np.degrees(hinge_angle(output[4],0)))
  self.assertGreater(new_knee,85)
  self.assertLess(abs(new_knee-actual_knee),abs(old_knee-actual_knee)*.2)
  G=global_rotations(output,self.f.parents)
  self.assertLess(distance(G[4],sensors[4]),1e-6)

 def test_unobservable_short_projection_without_scale_keeps_prior(self):
  _,prior,sensors,points,image,confidence=self.end_on_fixture()
  confidence=confidence.copy();confidence[0]=0
  # Only one independently scaled shin ray is left: no usable scale estimate.
  fitter=KinematicFusion(self.f)
  output=fitter.fit(prior,(points,confidence),{4:sensors[4]}, {},prior=prior,dt=1.,camera_basis=np.eye(3),camera_image=(image,confidence))
  self.assertIsNone(fitter.image_scale)
  self.assertAlmostEqual(float(np.degrees(hinge_angle(output[4],0))),55,delta=.51)

 def test_no_image_preserves_unobserved_axial_twist_hypothesis(self):
  for hypothesis in (-40,40):
   prior=self.eye.copy();prior[16]=rotation(0,np.deg2rad(hypothesis));prior[18]=rotation(0,-np.deg2rad(hypothesis))
   expected=global_rotations(prior,self.f.parents)
   output=KinematicFusion(self.f).fit(prior,None,{18:np.eye(3)},{},prior=prior,dt=1.)
   G=global_rotations(output,self.f.parents)
   self.assertLess(distance(G[16],expected[16]),1e-6)
   self.assertLess(distance(G[18],np.eye(3)),1e-6)

 def hip_midpoint_observation(self,wrong_width=False):
  rest=self.f.rest.copy()
  # Hip centers are lower than the rig root. The detector's pelvis is their
  # midpoint, so its root-to-hip rays deliberately differ from the rig's rays.
  for j in (1,2,4,5,7,8,10,11):rest[j,1]-=.08
  fusion=RotationFusion(rest,self.f.parents)
  points=fusion.joints(self.eye);midpoint=(points[1]+points[2])*.5
  points-=midpoint;points[0]=0.
  if wrong_width:
   difference=points[1]-points[2];difference=rotation(2,np.pi/2)@difference
   points[1]=difference*.5;points[2]=-difference*.5
  return fusion,points

 def test_hip_midpoint_mapping_does_not_reject_correct_measured_hip_width(self):
  fusion,points=self.hip_midpoint_observation()
  state=RealtimeFusion(fusion);previous=self.eye.copy()
  for i in range(5):
   previous,_,_,_=state.step(previous,(points,np.ones(24)),{0:np.eye(3)},{},self.eye,1+i/30,1+i/30)
   self.assertIsNotNone(state.effective_camera)
   np.testing.assert_allclose(state.effective_camera[1][[1,2]],1.,atol=1e-12)

 def test_hip_width_disagreement_still_rejects_the_actual_measured_direction(self):
  fusion,points=self.hip_midpoint_observation(wrong_width=True)
  state=RealtimeFusion(fusion)
  state.step(self.eye,(points,np.ones(24)),{0:np.eye(3)},{},self.eye,1.,1.)
  self.assertIsNotNone(state.effective_camera)
  np.testing.assert_allclose(state.effective_camera[1][[1,2]],0.,atol=1e-12)

 def test_hip_width_gate_accepts_matching_image_projection_including_end_on_view(self):
  fusion,points=self.hip_midpoint_observation()
  for yaw,pitch in ((0,0),(90,0),(180,0),(45,50)):
   basis=Rotation.from_euler('yx',[yaw,pitch],degrees=True).as_matrix()
   image=points@basis[:,:2]*.3
   state=RealtimeFusion(fusion)
   state.step(self.eye,(points,np.ones(24)),{0:np.eye(3)},{},self.eye,1.,1.,camera_basis=basis,camera_image=(image,np.ones(24)))
   self.assertIsNotNone(state.effective_camera)
   np.testing.assert_allclose(state.effective_camera[1][[1,2]],1.,atol=1e-12)

if __name__=='__main__':unittest.main()
