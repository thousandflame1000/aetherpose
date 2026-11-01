"""Observability, contradictory image data and additional real segment inputs."""
from pathlib import Path
import os,sys,unittest
import numpy as np
from scipy.spatial.transform import Rotation
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[os.environ.get('AETHER_TEST_FRONTEND',str(ROOT/'frontend')),str(ROOT/'frontend')]
from generic_body import GenericBody
from hybrid_fusion import RotationFusion
from kinematic_fusion import KinematicFusion,global_rotations,rotation
from tracking_fusion import RealtimeFusion

def distance(a,b):return float(np.degrees(Rotation.from_matrix(a@b.T).magnitude()))

class ParentFusionTests(unittest.TestCase):
 def setUp(self):
  body=GenericBody();self.f=RotationFusion(body.J_rest,body.parents);self.eye=np.tile(np.eye(3),(24,1,1))

 def test_repeated_confident_image_cannot_override_measured_forearm_direction(self):
  q=self.f.joints(self.eye);q[20]=q[18]-(q[20]-q[18]);q[22]=q[20]+[.02,0,0]
  state=RealtimeFusion(self.f);previous=self.eye.copy()
  for i in range(8):
   previous,out,_,_=state.step(previous,(q,np.ones(24)),{0:np.eye(3),18:np.eye(3)},{},self.eye,1+i/30,1+i/30)
   self.assertGreater(state.diagnostics['camera_rejected_bones'],0)
   self.assertTrue(state.diagnostics['camera_fused'])
  self.assertEqual(state.effective_camera[1][20],0)

 def test_straight_limb_keeps_unobservable_parent_twist_and_distal_imu(self):
  prior=self.eye.copy();prior[16]=rotation(0,np.deg2rad(35));prior[18]=rotation(0,-np.deg2rad(35))
  q=self.f.joints(prior);fit=KinematicFusion(self.f)
  output=fit.fit(prior,(q,np.ones(24)),{18:np.eye(3)},{},prior=prior,dt=1.)
  G=global_rotations(output,self.f.parents);reference=global_rotations(prior,self.f.parents)
  self.assertLess(distance(G[16],reference[16]),2.)
  self.assertLess(distance(G[18],np.eye(3)),1e-6)

 def test_consistent_bent_limb_image_improves_parent_without_moving_distal_imu(self):
  truth=self.eye.copy();truth[16]=Rotation.from_euler('xyz',[20,10,-35],degrees=True).as_matrix()
  T=rotation(0,np.deg2rad(20));truth[18]=rotation(1,-np.deg2rad(80))@T
  real=global_rotations(truth,self.f.parents);F=real[18]
  prior=truth.copy();prior[18]=rotation(1,-np.deg2rad(60))@T
  prior[16]=F@prior[18].T
  baseline=global_rotations(prior,self.f.parents)
  fit=KinematicFusion(self.f);out=fit.fit(prior,(self.f.joints(truth),np.ones(24)),{18:F},{},prior=prior,dt=1.)
  G=global_rotations(out,self.f.parents)
  self.assertLess(distance(G[16],real[16]),distance(baseline[16],real[16]))
  self.assertLess(distance(G[18],F),1e-6)

 def test_extra_chest_imu_is_rebased_after_preserving_model_spine(self):
  prior=self.eye.copy();prior[3]=rotation(1,.3);prior[6]=rotation(2,.15)
  measured=Rotation.from_euler('xyz',[15,35,10],degrees=True).as_matrix()
  fit=KinematicFusion(self.f);out=fit.fit(prior,None,{9:measured},{},prior=prior,dt=1.)
  self.assertLess(distance(global_rotations(out,self.f.parents)[9],measured),1e-6)

if __name__=='__main__':unittest.main()
