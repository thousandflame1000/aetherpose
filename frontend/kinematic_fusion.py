"""Constrained two-link retargeting for calibrated SMPL T-pose inputs.

The engineering SMPL profile uses X knees, mirrored Y elbow flexion and
forearm axial twist. Limits approximate a rig, not individual human anatomy.
The old synthetic Z-elbow profile remains explicit and separate.
Distal IMU orientations constrain proximal joints through the hinge, instead
of letting an unconstrained child counter-rotate an incorrectly fitted parent.
"""
import numpy as np
import math
from scipy.spatial.transform import Rotation
from hybrid_fusion import proper_rotation

def global_rotations(local,parents):
 result=np.empty_like(local)
 for j,p in enumerate(parents):result[j]=local[j] if p<0 else result[p]@local[j]
 return result

def rotation(axis,angle):
 c=math.cos(angle);s=math.sin(angle)
 if axis==0:return np.array([[1.,0,0],[0,c,-s],[0,s,c]])
 if axis==1:return np.array([[c,0,s],[0,1.,0],[-s,0,c]])
 return np.array([[c,-s,0],[s,c,0],[0,0,1.]])

def quaternion(R):
 # Stable matrix-to-quaternion conversion for internally fitted rotations.
 # Largest-component branches also handle 180-degree rotations.
 tr=float(np.trace(R))
 if tr>0:
  s=2*math.sqrt(1+tr)
  return np.array([(R[2,1]-R[1,2])/s,(R[0,2]-R[2,0])/s,(R[1,0]-R[0,1])/s,s/4])
 i=int(np.argmax(np.diag(R)));j=(i+1)%3;k=(i+2)%3
 s=2*math.sqrt(max(1e-20,1+R[i,i]-R[j,j]-R[k,k]));q=np.empty(4)
 q[i]=s/4;q[j]=(R[i,j]+R[j,i])/s;q[k]=(R[i,k]+R[k,i])/s;q[3]=(R[k,j]-R[j,k])/s
 return q

def limited(current,previous,cap):
 delta=current@previous.T
 if cap>=np.pi or (np.trace(delta)-1)*.5>=math.cos(cap):return current
 v=Rotation.from_matrix(delta).as_rotvec();size=np.linalg.norm(v)
 return Rotation.from_rotvec(v*cap/max(size,1e-12)).as_matrix()@previous

def hinge_angle(R,axis,sign=1):
 q=quaternion(R)
 return (sign*2*np.arctan2(q[axis],q[3])+np.pi)%(2*np.pi)-np.pi

class KinematicFusion:
 PROFILES={
  'smpl_tpose':((1,4,7,0,1),(2,5,8,0,1),(16,18,20,1,-1),(17,19,21,1,1)),
  'synthetic_z':((1,4,7,0,1),(2,5,8,0,1),(16,18,20,2,1),(17,19,21,2,-1))}
 def __init__(self,fusion,fps=60,profile='smpl_tpose'):
  if profile not in self.PROFILES:raise ValueError('Unknown kinematic profile')
  self.profile=profile;self.CHAINS=self.PROFILES[profile]
  self.allow_twist=profile=='smpl_tpose';self.observed=set()
  self.fusion=fusion;self.parents=fusion.parents;self.fps=fps
  self.angles=np.linspace(0,np.deg2rad(145),291)
  self.hinges={(axis,sign):Rotation.from_rotvec(np.eye(3)[axis][None,:]*self.angles[:,None]*sign).as_matrix() for axis,sign in set((a,s) for _,_,_,a,s in self.CHAINS)}
  self.bounds={1:([-110,-60,-35],[60,60,35]),2:([-110,-60,-35],[60,60,35]),
               16:([-80,-100,-155],[110,100,80]),17:([-80,-100,-80],[110,100,155]),
               3:([-35,-40,-30],[50,40,30]),6:([-30,-35,-25],[40,35,25]),9:([-35,-50,-30],[45,50,30]),
               12:([-45,-65,-40],[45,65,40]),13:([-35,-40,-40],[35,40,40]),14:([-35,-40,-40],[35,40,40]),
               7:([-60,-20,-20],[50,20,20]),8:([-60,-20,-20],[50,20,20]),
               15:([-60,-80,-45],[60,80,45]),20:([-70,-35,-35],[70,35,35]),21:([-70,-35,-35],[70,35,35])}

 def bounded(self,R,j):
  if j not in self.bounds:return R
  cy=math.hypot(R[0,0],R[1,0]);y=math.atan2(-R[2,0],cy)
  x=math.atan2(R[2,1],R[2,2]) if cy>1e-8 else math.atan2(-R[1,2],R[1,1])
  z=math.atan2(R[1,0],R[0,0]) if cy>1e-8 else 0.
  e=np.array([x,y,z]);bounds=np.deg2rad(self.bounds[j]);clipped=np.clip(e,*bounds)
  if np.max(np.abs(clipped-e))<1e-12:return R
  return rotation(2,clipped[2])@rotation(1,clipped[1])@rotation(0,clipped[0])

 def twist(self,R,hinge,distal):
  if not self.allow_twist or hinge not in (18,19):return np.eye(3)
  axis=(self.fusion.rest[distal]-self.fusion.rest[hinge]).copy();axis[1]=0
  if np.linalg.norm(axis)<1e-9:axis=np.array([1.,0,0])
  axis=axis/np.linalg.norm(axis)
  q=quaternion(R);angle=2*np.arctan2(np.dot(q[:3],axis),q[3])
  angle=(angle+np.pi)%(2*np.pi)-np.pi
  return Rotation.from_rotvec(axis*np.clip(angle,-np.deg2rad(100),np.deg2rad(100))).as_matrix()

 def project(self,local):
  local=np.array(local,copy=True)
  for _,hinge,distal,axis,sign in self.CHAINS:
   T=self.twist(local[hinge],hinge,distal)
   angle=np.clip(hinge_angle(local[hinge]@T.T,axis,sign),0,self.angles[-1])
   local[hinge]=rotation(axis,sign*angle)@T
  return local

 def fit(self,previous,camera,sensors,axes,prior=None,dt=None):
  dt=1/self.fps if dt is None else dt
  # A single index point does not observe palm rotation. Keep unmeasured
  # wrist orientation rather than inventing a full rotation from that ray.
  if camera is not None:
   q,c=camera;c=c.copy();c[[22,23]]=0;camera=(q,c)
  else:q=c=None
  axes={j:value for j,value in axes.items() if j not in sensors}
  R,self.observed=self.fusion.fit(previous,camera=camera,sensors=sensors,prior=prior,camera_axes=axes)
  for j in self.bounds:R[j]=self.bounded(R[j],j)
  if 0 in sensors:R[0]=sensors[0]
  for j in (3,6,9,12,13,14):
   R[j]=limited(R[j],previous[j],np.deg2rad(300)*dt)
   R[j]=self.bounded(R[j],j)
  G=global_rotations(R,self.parents)
  for proximal,hinge,distal,axis,sign in self.CHAINS:
   relative=(sensors[proximal].T@sensors[hinge]) if proximal in sensors and hinge in sensors else (prior[hinge] if prior is not None else R[hinge])
   T=self.twist(relative,hinge,distal)
   old=np.clip(hinge_angle(previous[hinge]@self.twist(previous[hinge],hinge,distal).T,axis,sign),0,self.angles[-1])
   cap=np.deg2rad(160)*dt
   geometry=None
   if self.allow_twist and q is not None and min(c[proximal],c[hinge],c[distal])>=.8 and proximal not in sensors:
    a=q[hinge]-q[proximal];b=q[distal]-q[hinge]
    sa=self.fusion.rest[hinge]-self.fusion.rest[proximal];sb=self.fusion.rest[distal]-self.fusion.rest[hinge]
    if min(np.linalg.norm(a),np.linalg.norm(b),np.linalg.norm(sa),np.linalg.norm(sb))>.015:
     a=a/np.linalg.norm(a);b=b/np.linalg.norm(b);sa=sa/np.linalg.norm(sa);sb=sb/np.linalg.norm(sb)
     candidates=self.hinges[(axis,sign)]@sb
     cost=3*(candidates@sa-np.dot(a,b))**2+.0002*(self.angles-old)**2
     desired=float(self.angles[np.argmin(cost)])
     angle=float(np.clip(desired,max(0,old-cap),min(self.angles[-1],old+cap)))
     H=rotation(axis,sign*angle);parent=self.parents[proximal]
     oldU=G[parent]@previous[proximal] if parent>=0 else previous[proximal]
     # The bend plane belongs to shoulder/hip orientation, not a synthetic
     # fixed world axis. Two observed directions determine it when bent;
     # a small prior resolves the near-straight degeneracy.
     U=proper_rotation(np.outer(a,sa)+np.outer(b,H@sb)+.01*oldU)
     geometry=(U,angle)
     if hinge in sensors:T=self.twist(U.T@sensors[hinge],hinge,distal)
   if hinge in sensors:
    F=sensors[hinge]@T.T
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
     prior_local=previous[proximal] if prior is None else prior[proximal]
     priorU=G[parent]@prior_local if parent>=0 else prior_local
     desired=np.clip(hinge_angle(priorU.T@F,axis,sign),0,self.angles[-1])
    angle=float(np.clip(desired,max(0,old-cap),min(self.angles[-1],old+cap)))
    H=rotation(axis,sign*angle)
    U=sensors[proximal] if proximal in sensors else F@H.T
    parent=self.parents[proximal]
    R[proximal]=(G[parent].T if parent>=0 else np.eye(3))@U
    R[hinge]=H@T
   elif geometry is not None:
    U,angle=geometry;parent=self.parents[proximal]
    R[proximal]=(G[parent].T if parent>=0 else np.eye(3))@U
    R[hinge]=rotation(axis,sign*angle)@T
   else:
    if proximal in sensors:
     parent=self.parents[proximal];R[proximal]=G[parent].T@sensors[proximal]
    desired=np.clip(hinge_angle(R[hinge]@T.T,axis,sign),0,self.angles[-1])
    angle=np.clip(desired,max(0,old-cap),min(self.angles[-1],old+cap))
    R[hinge]=rotation(axis,sign*angle)@T
   G=global_rotations(R,self.parents)
   if distal in sensors:R[distal]=self.bounded(G[self.parents[distal]].T@sensors[distal],distal)
   elif distal in (20,21):R[distal]=self.bounded(previous[distal] if prior is None else prior[distal],distal)
   else:R[distal]=self.bounded(R[distal],distal)
   G=global_rotations(R,self.parents)
  if 15 in sensors:R[15]=self.bounded(G[self.parents[15]].T@sensors[15],15)
  # Rate-limit only free joint updates. Hinge angles already have their own
  # bounded update, and measured distal directions should not be overwritten.
  for j in (7,8,20,21):
   maximum=np.deg2rad(300)*dt
   R[j]=limited(R[j],previous[j],maximum)
   R[j]=self.bounded(R[j],j)
  return R
