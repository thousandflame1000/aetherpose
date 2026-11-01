from pathlib import Path
import sys,unittest,importlib.util
import numpy as np
from scipy.spatial.transform import Rotation
BASE=Path(__file__).resolve().parent;ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE),str(ROOT/'frontend')]
from generic_body import GenericBody
from hybrid_fusion import RotationFusion
from kinematic_fusion import KinematicFusion,global_rotations,rotation
from measured_projection import condition,error

class ExtraMeasurementTests(unittest.TestCase):
 def setUp(self):
  body=GenericBody();self.f=RotationFusion(body.J_rest,body.parents);self.k=KinematicFusion(self.f)
  self.eye=np.tile(np.eye(3),(24,1,1))

 def ankle_fixture(self):
  local=self.eye.copy();local[1]=rotation(0,np.deg2rad(-30));local[4]=rotation(0,np.deg2rad(60));local[7]=rotation(0,np.deg2rad(-20))
  targets={0:np.eye(3),4:rotation(0,np.deg2rad(80)),7:rotation(0,np.deg2rad(50))}
  return local,targets

 def test_root_shin_ankle_rebase_after_parent_changes(self):
  local,targets=self.ankle_fixture();old_global=global_rotations(local,self.f.parents)
  self.assertGreater(error(old_global[4],targets[4]),40)
  output,diagnostics=condition(local,targets,self.k)
  G=global_rotations(output,self.f.parents)
  for j in targets:self.assertLess(error(G[j],targets[j]),1e-6)
  np.testing.assert_allclose(output[4],local[4],atol=1e-10)
  self.assertAlmostEqual(np.degrees(Rotation.from_matrix(output[7]).as_rotvec()[0]),-30,places=5)
  self.assertIn(7,diagnostics['final_measured_reconciliation']['rebased'])
  self.assertEqual(diagnostics['final_measured_reconciliation']['conflicts'],[])

 def test_root_forearm_wrist_rebase_without_free_elbow_counter_rotation(self):
  local=self.eye.copy();local[16]=rotation(2,np.deg2rad(-20));local[18]=rotation(1,-np.deg2rad(60))
  forearm=rotation(2,np.deg2rad(-50))@local[18];wrist=forearm@rotation(0,np.deg2rad(20))
  targets={0:np.eye(3),18:forearm,20:wrist}
  output,diagnostics=condition(local,targets,self.k);G=global_rotations(output,self.f.parents)
  for j in targets:self.assertLess(error(G[j],targets[j]),1e-6)
  np.testing.assert_allclose(output[18],local[18],atol=1e-10)
  np.testing.assert_allclose(output[20],rotation(0,np.deg2rad(20)),atol=1e-8)
  self.assertIn(20,diagnostics['final_measured_reconciliation']['rebased'])

 def test_incompatible_ankle_measurement_reports_residual_instead_of_hiding_it(self):
  local,targets=self.ankle_fixture();targets[7]=targets[4]@rotation(0,np.deg2rad(100))
  output,diagnostics=condition(local,targets,self.k);G=global_rotations(output,self.f.parents)
  self.assertLess(error(G[4],targets[4]),1e-6)
  self.assertGreater(error(G[7],targets[7]),40)
  self.assertIn(7,diagnostics['final_measured_reconciliation']['conflicts'])
  np.testing.assert_allclose(output[4],local[4],atol=1e-10)


if __name__=='__main__':unittest.main()
