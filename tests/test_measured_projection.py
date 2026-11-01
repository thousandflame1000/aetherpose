from pathlib import Path
import sys,unittest
import numpy as np
from scipy.spatial.transform import Rotation
BASE=Path(__file__).resolve().parent;ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE),str(ROOT/'frontend')]
from generic_body import GenericBody
from hybrid_fusion import RotationFusion
from kinematic_fusion import KinematicFusion,global_rotations,rotation
from tracking_fusion import RealtimeFusion
from measured_projection import condition,bounded,error

class MeasuredProjectionTests(unittest.TestCase):
 def setUp(self):
  body=GenericBody();self.f=RotationFusion(body.J_rest,body.parents);self.k=KinematicFusion(self.f)
  self.eye=np.tile(np.eye(3),(24,1,1))

 def test_parent_changes_while_filtered_local_hinge_remains_fixed(self):
  local=self.eye.copy();local[18]=rotation(1,-np.deg2rad(70))@rotation(0,np.deg2rad(20))
  measured=rotation(2,-np.deg2rad(30))@local[18]
  output,diagnostics=condition(local,{18:measured},self.k)
  np.testing.assert_allclose(output[18],local[18],atol=1e-12)
  self.assertLess(error(global_rotations(output,self.f.parents)[18],measured),1e-6)
  self.assertEqual(diagnostics['parent_bound_conflicts'],[])

 def test_incompatible_measured_pair_is_reported_instead_of_free_child_rotation(self):
  target=rotation(2,np.deg2rad(50))
  output,diagnostics=condition(self.eye,{16:np.eye(3),18:target},self.k)
  self.assertIn([16,18],diagnostics['measured_pair_conflicts'])
  self.assertGreater(error(global_rotations(output,self.f.parents)[18],target),1.)
  np.testing.assert_allclose(self.k.project(output)[18],output[18],atol=1e-8)

 def test_valid_world_head_repairs_bounded_unmeasured_neck_head_pair(self):
  prior=self.eye.copy();prior[12]=rotation(1,np.deg2rad(60));target=rotation(1,-np.deg2rad(60))
  output=self.k.fit(prior,None,{0:np.eye(3),15:target},{},prior=prior,dt=1.)
  self.assertLess(error(global_rotations(output,self.f.parents)[15],target),.01)
  for j in (12,15):self.assertLess(error(output[j],bounded(output[j],j,self.k)),.01)
  self.assertTrue(self.k.measurement_projection_diagnostics['head_neck_hypothesis'])

 def test_filtered_targets_are_coherent_and_raw_measurement_lag_is_not_hidden(self):
  f=RealtimeFusion(self.f);previous=self.eye.copy();max_raw=0.;max_target=0.
  for i in range(45):
   pose=self.eye.copy();pose[0]=rotation(1,np.deg2rad(35*np.sin(i/8)))
   pose[16]=rotation(2,-.4);pose[18]=rotation(1,-np.deg2rad(60+20*np.sin(i/7)))
   G=global_rotations(pose,self.f.parents);sensors={j:G[j] for j in (0,4,5,15,18,19)}
   previous,out,_,_=f.step(previous,None,sensors,{},pose,1+i/60,None)
   d=f.diagnostics
   max_target=max(max_target,max(d['filtered_target_measurement_error_deg'].values()))
   max_raw=max(max_raw,max(d['current_measurement_error_deg'].values()))
   self.assertEqual(d['measured_target_type'],'causal_world_filtered')
   for j in sensors:
    self.assertAlmostEqual(d['current_measurement_error_deg'][str(j)],d['measurement_filter_error_deg'][str(j)],delta=1e-5)
  self.assertLess(max_target,.01)
  self.assertGreater(max_raw,1.)

if __name__=='__main__':unittest.main()
