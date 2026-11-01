"""Causal speed-adaptive filtering on SO(3), based on Casiez et al., CHI 2012.

This is our rotation-space adaptation of the 1 Euro filter, not the authors'
scalar implementation. No truth, future samples or visibility oracle are used.
All rotations are local; geodesic interpolation preserves the declared hinge
axes and angle intervals. Parameters use Hz and degrees/second explicitly.
"""
import numpy as np
from scipy.spatial.transform import Rotation


class RotationOneEuro:
 def __init__(self,initial,min_cutoff=1.8,beta=.045,derivative_cutoff=1.):
  self.value=np.array(initial,dtype=float,copy=True)
  self.previous=self.value.copy()
  self.velocity=np.zeros((len(self.value),3))
  self.min_cutoff=min_cutoff;self.beta=beta;self.derivative_cutoff=derivative_cutoff

 @staticmethod
 def alpha(cutoff,dt):return 1/(1+1/(2*np.pi*np.asarray(cutoff)*dt))

 def update(self,rotations,dt):
  if not np.isfinite(dt) or dt<=0:raise ValueError('dt must be finite and positive')
  raw=np.asarray(rotations,dtype=float)
  derivative=Rotation.from_matrix(raw@self.previous.transpose(0,2,1)).as_rotvec()/dt
  ad=self.alpha(self.derivative_cutoff,dt)
  self.velocity+=ad*(derivative-self.velocity)
  cutoff=self.min_cutoff+self.beta*np.degrees(np.linalg.norm(self.velocity,axis=1))
  a=self.alpha(cutoff,dt)
  delta=Rotation.from_matrix(raw@self.value.transpose(0,2,1)).as_rotvec()
  self.value=Rotation.from_rotvec(delta*a[:,None]).as_matrix()@self.value
  self.previous=raw.copy()
  return self.value.copy()
