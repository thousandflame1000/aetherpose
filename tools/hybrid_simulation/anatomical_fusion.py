"""Constrained two-link retargeting for this declared synthetic articulated rig.

Axes and limits describe the rig, not its animated ground-truth trajectory.
Distal IMU orientations constrain proximal joints through the hinge, instead
of letting an unconstrained child counter-rotate an incorrectly fitted parent.
"""
import numpy as np
from scipy.spatial.transform import Rotation

def global_rotations(local,parents):
 result=np.empty_like(local)
 for j,p in enumerate(parents):result[j]=local[j] if p<0 else result[p]@local[j]
 return result

def rotation(axis,angle):
 v=np.zeros(3);v[axis]=angle
 return Rotation.from_rotvec(v).as_matrix()

def hinge_angle(R,axis,sign=1):
 q=Rotation.from_matrix(R).as_quat()
 return (sign*2*np.arctan2(q[axis],q[3])+np.pi)%(2*np.pi)-np.pi

class AnatomicalFusion:
 # These are explicit rig degrees of freedom, also used by its motion script.
 CHAINS=((1,4,7,0,1),(2,5,8,0,1),(16,18,20,2,1),(17,19,21,2,-1))
 def __init__(self,fusion,fps):
  self.fusion=fusion;self.parents=fusion.parents;self.fps=fps
  self.angles=np.linspace(0,np.deg2rad(145),291)
  self.hinges={(axis,sign):Rotation.from_rotvec(np.eye(3)[axis][None,:]*self.angles[:,None]*sign).as_matrix() for axis,sign in ((0,1),(2,1),(2,-1))}
  self.bounds={1:([-110,-60,-35],[60,60,35]),2:([-110,-60,-35],[60,60,35]),
               16:([-80,-100,-155],[110,100,80]),17:([-80,-100,-80],[110,100,155]),
               3:([-35,-40,-30],[50,40,30]),6:([-30,-35,-25],[40,35,25]),9:([-35,-50,-30],[45,50,30]),
               12:([-45,-65,-40],[45,65,40]),13:([-35,-40,-40],[35,40,40]),14:([-35,-40,-40],[35,40,40]),
               7:([-60,-20,-20],[50,20,20]),8:([-60,-20,-20],[50,20,20]),
               15:([-60,-80,-45],[60,80,45]),20:([-70,-35,-35],[70,35,35]),21:([-70,-35,-35],[70,35,35])}

 def bounded(self,R,j):
  if j not in self.bounds:return R
  e=Rotation.from_matrix(R).as_euler('xyz',degrees=True)
  return Rotation.from_euler('xyz',np.clip(e,*self.bounds[j]),degrees=True).as_matrix()

 def fit(self,previous,camera,sensors,axes):
  # A single index point does not observe palm rotation. Keep unmeasured
  # wrist orientation rather than inventing a full rotation from that ray.
  if camera is not None:
   q,c=camera;c=c.copy();c[[22,23]]=0;camera=(q,c)
  else:q=c=None
  axes={j:value for j,value in axes.items() if j not in sensors}
  R,_=self.fusion.fit(previous,camera=camera,sensors=sensors,camera_axes=axes)
  for j in self.bounds:R[j]=self.bounded(R[j],j)
  if 0 in sensors:R[0]=sensors[0]
  for j in (3,6,9,12,13,14):
   delta=Rotation.from_matrix(R[j]@previous[j].T).as_rotvec();size=np.linalg.norm(delta);cap=np.deg2rad(300)/self.fps
   if size>cap:R[j]=Rotation.from_rotvec(delta*cap/size).as_matrix()@previous[j]
   R[j]=self.bounded(R[j],j)
  G=global_rotations(R,self.parents)
  for proximal,hinge,distal,axis,sign in self.CHAINS:
   old=np.clip(hinge_angle(previous[hinge],axis,sign),0,self.angles[-1])
   cap=np.deg2rad(160)/self.fps
   if hinge in sensors:
    F=sensors[hinge]
    if proximal in sensors:
     U=sensors[proximal]
     desired=np.clip(hinge_angle(U.T@F,axis,sign),0,self.angles[-1])
    elif q is not None and min(c[proximal],c[hinge])>=.8:
     observed=q[hinge]-q[proximal]
     source=self.fusion.rest[hinge]-self.fusion.rest[proximal]
     observed/=max(np.linalg.norm(observed),1e-9);source/=max(np.linalg.norm(source),1e-9)
     candidates=np.einsum('nij,j->ni',self.hinges[(axis,sign)].transpose(0,2,1),source)@F.T
     cost=3*min(c[proximal],c[hinge])*np.sum((candidates-observed)**2,axis=1)+.2*(self.angles-old)**2
     desired=self.angles[np.argmin(cost)]
    else:
     parent=self.parents[proximal]
     priorU=G[parent]@previous[proximal] if parent>=0 else previous[proximal]
     desired=np.clip(hinge_angle(priorU.T@F,axis,sign),0,self.angles[-1])
    angle=float(np.clip(desired,max(0,old-cap),min(self.angles[-1],old+cap)))
    H=rotation(axis,sign*angle)
    U=sensors[proximal] if proximal in sensors else F@H.T
    parent=self.parents[proximal]
    R[proximal]=(G[parent].T if parent>=0 else np.eye(3))@U
    R[hinge]=H
   else:
    if proximal in sensors:
     parent=self.parents[proximal];R[proximal]=G[parent].T@sensors[proximal]
    desired=np.clip(hinge_angle(R[hinge],axis,sign),0,self.angles[-1])
    angle=np.clip(desired,max(0,old-cap),min(self.angles[-1],old+cap))
    R[hinge]=rotation(axis,sign*angle)
   G=global_rotations(R,self.parents)
   if distal in sensors:R[distal]=self.bounded(G[self.parents[distal]].T@sensors[distal],distal)
   elif distal in (20,21):R[distal]=self.bounded(previous[distal],distal)
   else:R[distal]=self.bounded(R[distal],distal)
   G=global_rotations(R,self.parents)
  if 15 in sensors:R[15]=self.bounded(G[self.parents[15]].T@sensors[15],15)
  # Rate-limit only free joint updates. Hinge angles already have their own
  # bounded update, and measured distal directions should not be overwritten.
  for j in (7,8,20,21):
   delta=Rotation.from_matrix(R[j]@previous[j].T).as_rotvec();size=np.linalg.norm(delta)
   maximum=np.deg2rad(300)/self.fps
   if size>maximum:R[j]=Rotation.from_rotvec(delta*maximum/size).as_matrix()@previous[j]
   R[j]=self.bounded(R[j],j)
  return R
