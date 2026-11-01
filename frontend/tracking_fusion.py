"""Causal visual/inertial protections shared by the live HybridRunner.

Only fresh camera events update heading or reacquisition counters. New IMUs
may reuse the last still-valid image constraint, but never count it as another
image. No prerecorded future interpolation is used in the live estimator.
"""
import numpy as np
from scipy.spatial.transform import Rotation
from kinematic_fusion import KinematicFusion,global_rotations
from rotation_filter import RotationOneEuro

CRITICAL=[0,1,2,4,5,7,8,12,15,16,17,18,19,20,21]

def wrap(a):return (a+np.pi)%(2*np.pi)-np.pi


class RealtimeFusion:
 def __init__(self,fusion,profile='smpl_tpose'):
  self.fusion=fusion;self.kinematic=KinematicFusion(fusion,profile=profile)
  self.stabilize=True;self.constraints=True;self.reset()

 def reset(self,initial=None,keep_heading=False):
  self.correction=getattr(self,'correction',0.) if keep_heading else 0.
  self.last_at=None;self.last_camera_at=None
  self.complete_streak=0;self.filter=None if initial is None else RotationOneEuro(initial)
  self.effective_camera=None;self.diagnostics={}
  self.camera_gate=None

 def configure(self,*,stabilize,constraints):
  if type(stabilize) is not bool or type(constraints) is not bool:raise ValueError('追蹤選項必須是開啟或關閉。')
  self.stabilize=stabilize;self.constraints=constraints;self.filter=None

 def step(self,previous,camera,sensors,axes,prior,at,camera_at):
  elapsed=None if self.last_at is None else at-self.last_at
  if elapsed is not None and elapsed<=0:raise ValueError('Pose timestamps must increase')
  dt=1/30 if elapsed is None else elapsed
  if elapsed is not None and elapsed>.35:self.filter=None
  self.last_at=at
  active=False;rejected=[]
  q,c=(None,None) if camera is None else camera
  new_camera=camera is not None and camera_at!=self.last_camera_at
  if new_camera:
   camera_dt=1/30 if self.last_camera_at is None else camera_at-self.last_camera_at
   camera_dt=camera_dt if 0<camera_dt<=.3 else 1/30
   self.last_camera_at=camera_at
   self.complete_streak=self.complete_streak+1 if min(c[CRITICAL])>=.8 else 0
   self.correction,active=self.yaw_feedback(q,c,sensors,self.correction,camera_dt)
  if camera is None:self.complete_streak=0;self.camera_gate=None
  yaw=Rotation.from_rotvec([0,self.correction,0]).as_matrix()
  corrected={j:yaw@R for j,R in sensors.items()}
  base=None if prior is None else np.array(prior,copy=True)
  if base is not None:base[0]=yaw@base[0]
  safe_c,safe_axes=None,{}
  if camera is not None:
   if not sensors or self.complete_streak>=3:safe_c,safe_axes,rejected=c,axes,[]
   elif new_camera or self.camera_gate is None:
    self.camera_gate=self.consistent_camera(q,c,axes,corrected,previous,base)
    safe_c,safe_axes,rejected=self.camera_gate
   else:safe_c,safe_axes,rejected=self.camera_gate
  cam=None if safe_c is None or np.sum(safe_c>=.65)<8 else (q,safe_c)
  self.effective_camera=cam
  if self.constraints:
   constraint_dt=1. if elapsed is None or elapsed>.35 else min(dt,1.)
   raw=self.kinematic.fit(previous,cam,corrected,safe_axes,prior=base,dt=constraint_dt)
   observed=self.kinematic.observed
  else:raw,observed=self.fusion.fit(previous,camera=cam,sensors=corrected,prior=base,camera_axes=safe_axes)
  output=raw
  if self.stabilize:
   if self.filter is None:self.filter=RotationOneEuro(raw)
   output=self.filter.update(raw,dt)
   if self.constraints:
    output=self.kinematic.project(output)
    self.filter.value=output.copy()
  self.diagnostics=dict(joint_constraints=self.constraints,rotation_filter=self.stabilize,
   constraint_profile=self.kinematic.profile,heading_feedback_deg=round(float(np.degrees(self.correction)),3),
   heading_feedback_active=active,camera_rejected_bones=len(rejected),camera_fused=cam is not None,
   tracking_version='realtime-v1',pose_sample_interval_ms=round(dt*1000,2))
  return raw,output,observed,yaw
 def yaw_feedback(self,q,c,sensors,previous,dt):
  # Conservative common-heading feedback needs a central body reference.
  # Forearms alone are ambiguous under monocular depth errors and movement.
  if 0 not in sensors and 9 not in sensors:return previous,False
  candidates=[]
  def add(source,target,measured,quality,weight=1):
   if quality<.8:return
   source=source/max(np.linalg.norm(source),1e-9);target=target/max(np.linalg.norm(target),1e-9)
   predicted=measured@source
   if min(np.linalg.norm(predicted[[0,2]]),np.linalg.norm(target[[0,2]]))<.3:return
   residual=wrap(np.arctan2(target[0],target[2])-np.arctan2(predicted[0],predicted[2]))
   if abs(wrap(residual-previous))>np.deg2rad(25):return
   candidates.append((previous+wrap(residual-previous),weight*quality))
  if 0 in sensors:
   add(self.fusion.rest[1]-self.fusion.rest[2],q[1]-q[2],sensors[0],min(c[1],c[2],c[12]),6)
  for j,R in sensors.items():
   for child in self.fusion.children[j]:
    add(self.fusion.rest[child]-self.fusion.rest[j],q[child]-q[j],R,min(c[j],c[child]))
  if not candidates:return previous,False
  candidates.sort();total=sum(w for _,w in candidates);s=0
  for target,w in candidates:
   s+=w
   if s>=total/2:break
  # Common heading error only. No axial twist/bias oracle or hidden joint truth.
  step=(1-np.exp(-dt/.8))*wrap(target-previous)
  step=np.clip(step,-np.deg2rad(18)*dt,np.deg2rad(18)*dt)
  return previous+float(step),True

 def consistent_camera(self,q,c,axes,sensors,previous,prior=None):
  predicted,_=self.fusion.fit(previous,sensors=sensors,prior=prior)
  G=global_rotations(predicted,self.fusion.parents);filtered=c.copy();rejected=[]
  for j in range(24):
   for child in self.fusion.children[j]:
    if min(c[j],c[child])<.65:continue
    target=q[child]-q[j];expected=G[j]@(self.fusion.rest[child]-self.fusion.rest[j])
    lengths=np.linalg.norm(target)*np.linalg.norm(expected)
    if lengths<1e-8:continue
    angle=np.arccos(np.clip(np.dot(target,expected)/lengths,-1,1))
    if angle>np.deg2rad(40):
     filtered[child]=0;rejected.append([j,child])
     # A bad shin direction also makes camera-derived thigh placement unsafe.
     if j in (4,5):filtered[[1,4,7,10] if j==4 else [2,5,8,11]]=0
  accepted_axes={}
  for j,(R,quality) in axes.items():
   if Rotation.from_matrix(R@G[j].T).magnitude()<=np.deg2rad(45):accepted_axes[j]=(R,quality)
  return filtered,accepted_axes,rejected


