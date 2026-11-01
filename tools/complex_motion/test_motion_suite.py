import unittest
import numpy as np
from motion_suite import ambiguity,globals_and_joints,trajectory,CASES

class MotionSuiteTests(unittest.TestCase):
 def test_sequences_begin_at_identical_tpose_and_stay_on_so3(self):
  for name,_ in CASES:
   for t in (0,1,2,2.5,3,4,5,5.99):
    R=trajectory(name,t)
    self.assertTrue(np.isfinite(R).all())
    np.testing.assert_allclose(R@R.transpose(0,2,1),np.tile(np.eye(3),(24,1,1)),atol=1e-12)
    np.testing.assert_allclose(np.linalg.det(R),1,atol=1e-12)
    if t<=2:np.testing.assert_allclose(R,np.tile(np.eye(3),(24,1,1)))

 def test_twist_counterexample_changes_parent_but_not_distal_measurements(self):
  # Independent constructed rig, not the implementation's SMPL data.
  parents=np.array([-1]+[0]*23);parents[16]=13;parents[18]=16;parents[20]=18
  rest=np.zeros((24,3));rest[16]=[.2,.4,0];rest[18]=[.5,.42,0];rest[20]=[.8,.44,0]
  result=ambiguity(rest,parents)
  self.assertAlmostEqual(result['parent_separation_deg'],80,places=6)
  self.assertLess(result['measured_orientation_max_difference'],1e-12)
  self.assertLess(result['joint_center_max_difference_m'],1e-12)

 def test_forward_kinematics_preserves_lengths_under_parent_rotation(self):
  parents=np.array([-1]+list(range(23)));rest=np.arange(72).reshape(24,3)*.01
  R=trajectory('squat_twist',4)
  _,points=globals_and_joints(R,rest,parents)
  np.testing.assert_allclose(np.linalg.norm(points[1:]-points[parents[1:]],axis=1),np.linalg.norm(rest[1:]-rest[parents[1:]],axis=1),atol=1e-12)

if __name__=='__main__':unittest.main()
