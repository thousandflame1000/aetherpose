"""Small deterministic regressions for rotation noise, motion lag and wrapping."""
import unittest
import numpy as np
from scipy.spatial.transform import Rotation
from temporal_filter import RotationOneEuro

class TemporalFilterTests(unittest.TestCase):
 def test_stationary_noise_is_reduced(self):
  rng=np.random.default_rng(31415);f=RotationOneEuro(np.eye(3)[None]);raw=[];out=[]
  for _ in range(600):
   r=Rotation.from_rotvec(np.deg2rad(.8)*rng.normal(size=(1,3))).as_matrix()
   raw.append(Rotation.from_matrix(r).magnitude()[0])
   out.append(Rotation.from_matrix(f.update(r,1/15)).magnitude()[0])
  self.assertLess(np.sqrt(np.mean(np.square(out[30:])))/np.sqrt(np.mean(np.square(raw[30:]))),.65)

 def test_fast_motion_retains_amplitude_without_a_frame_of_lag(self):
  dt=1/15;t=np.arange(150)*dt;target=np.deg2rad(45)*np.sin(2*np.pi*t)
  f=RotationOneEuro(np.eye(3)[None]);out=[]
  for a in target:
   r=Rotation.from_rotvec([[0,0,a]]).as_matrix()
   out.append(Rotation.from_matrix(f.update(r,dt)).as_rotvec()[0,2])
  out=np.array(out);use=slice(30,None);lags=np.linspace(0,.15,601)
  loss=[np.mean((out[use]-np.deg2rad(45)*np.sin(2*np.pi*(t[use]-lag)))**2) for lag in lags]
  self.assertLess(lags[np.argmin(loss)],dt)
  self.assertGreater(np.ptp(out[use])/np.ptp(target[use]),.9)

 def test_wrapping_and_hinge_constraint(self):
  f=RotationOneEuro(Rotation.from_rotvec([[0,0,np.deg2rad(179)]]).as_matrix())
  end=Rotation.from_rotvec([[0,0,np.deg2rad(-179)]]).as_matrix()
  out=f.update(end,1/15)
  self.assertLess(np.degrees(Rotation.from_matrix(out@end.transpose(0,2,1)).magnitude())[0],2)
  f=RotationOneEuro(np.eye(3)[None])
  for angle in [0,90,145,0,50,145]*3:
   r=f.update(Rotation.from_rotvec([[np.deg2rad(angle),0,0]]).as_matrix(),1/15)
   v=Rotation.from_matrix(r).as_rotvec()[0]
   self.assertLess(np.linalg.norm(v[1:]),1e-10)
   self.assertGreaterEqual(v[0],0)
   self.assertLessEqual(v[0],np.deg2rad(145))
   self.assertAlmostEqual(np.linalg.det(r[0]),1,places=10)

if __name__=='__main__':unittest.main()
