"""Causal visual/inertial protections shared by the live HybridRunner.

Only fresh camera events update heading or reacquisition counters. New IMUs
may reuse the last still-valid image constraint, but never count it as another
image. No prerecorded future interpolation is used in the live estimator.
"""
import numpy as np
from scipy.spatial.transform import Rotation
from kinematic_fusion import KinematicFusion,global_rotations
from rotation_filter import RotationOneEuro
from measured_projection import condition

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
  self.has_model_prior=False
  self.sensor_filters={}

 def configure(self,*,stabilize,constraints):
  if type(stabilize) is not bool or type(constraints) is not bool:raise ValueError('追蹤選項必須是開啟或關閉。')
  self.stabilize=stabilize;self.constraints=constraints;self.filter=None
  self.sensor_filters={}

 def step(self,previous,camera,sensors,axes,prior,at,camera_at,camera_basis=None,camera_image=None):
  elapsed=None if self.last_at is None else at-self.last_at
  if elapsed is not None and elapsed<=0:raise ValueError('Pose timestamps must increase')
  dt=1/30 if elapsed is None else elapsed
  if elapsed is not None and elapsed>.35:self.filter=None
  self.last_at=at
  active=False;rejected=[]
  if self.has_model_prior!=(prior is not None):self.sensor_filters={}
  self.has_model_prior=prior is not None
  self.camera_basis=None
  if camera_basis is not None:
   camera_basis=np.asarray(camera_basis,float)
   if camera_basis.shape!=(3,3) or not np.isfinite(camera_basis).all() or not np.allclose(camera_basis.T@camera_basis,np.eye(3),atol=1e-4) or np.linalg.det(camera_basis)<.99:
    raise ValueError('Camera basis must be a proper rotation')
   self.camera_basis=camera_basis[:,:2]
  self.camera_image=None
  if camera_image is not None:
   if camera_basis is None:raise ValueError('Image bearings require a calibrated camera basis')
   image_q,image_c=(np.asarray(v,float) for v in camera_image)
   if image_q.shape!=(24,2) or image_c.shape!=(24,) or not np.isfinite(image_q).all() or not np.isfinite(image_c).all():raise ValueError('Invalid image bearings')
   if np.any((image_c<0)|(image_c>1)):raise ValueError('Invalid image confidence')
   self.camera_image=(image_q,image_c)
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
  # These WORLD-frame targets have an explicit, separately measurable causal
  # filter delay. They are not presented as the current raw IMU observation.
  if elapsed is not None and elapsed>.35:self.sensor_filters={}
  self.sensor_filters={j:f for j,f in self.sensor_filters.items() if j in corrected}
  measured_targets={}
  for j,R in corrected.items():
   if not self.stabilize or prior is None:measured_targets[j]=R;continue
   if j not in self.sensor_filters:self.sensor_filters[j]=RotationOneEuro(np.array([R]))
   measured_targets[j]=self.sensor_filters[j].update(np.array([R]),dt)[0]
  base=None if prior is None else np.array(prior,copy=True)
  if base is not None:base[0]=yaw@base[0]
  safe_c,safe_axes=None,{}
  if camera is not None:
   if not sensors:safe_c,safe_axes,rejected=c,axes,[]
   elif new_camera or self.camera_gate is None:
    self.camera_gate=self.consistent_camera(q,c,axes,corrected,previous,base)
    safe_c,safe_axes,rejected=self.camera_gate
   else:safe_c,safe_axes,rejected=self.camera_gate
  cam=None if safe_c is None or np.sum(safe_c>=.65)<8 else (q,safe_c)
  self.effective_camera=cam
  if self.constraints:
   constraint_dt=1. if elapsed is None or elapsed>.35 else min(dt,1.)
   raw=self.kinematic.fit(previous,cam,corrected,safe_axes,prior=base,dt=constraint_dt,camera_basis=camera_basis,camera_image=self.camera_image)
   observed=self.kinematic.observed
  else:raw,observed=self.fusion.fit(previous,camera=cam,sensors=corrected,prior=base,camera_axes=safe_axes)
  output=raw
  if self.stabilize:
   if self.filter is None:self.filter=RotationOneEuro(raw)
   output=self.filter.update(raw,dt)
   if self.constraints:
    output=self.kinematic.project(output)
  projection={}
  if self.constraints and prior is not None:
   output,projection=condition(output,measured_targets,self.kinematic)
  if self.constraints and self.filter is not None:self.filter.value=output.copy()
  G=global_rotations(output,self.fusion.parents)
  rawG=global_rotations(raw,self.fusion.parents)
  def residuals(left,right):return {str(j):round(float(np.degrees(Rotation.from_matrix(left[j]@R.T).magnitude())),6) for j,R in right.items()}
  self.diagnostics=dict(joint_constraints=self.constraints,rotation_filter=self.stabilize,
   constraint_profile=self.kinematic.profile,heading_feedback_deg=round(float(np.degrees(self.correction)),3),
   heading_feedback_active=active,camera_rejected_bones=len(rejected),camera_fused=cam is not None,
   tracking_version='realtime-v3-measured-candidate',camera_bearing_constraints=camera_basis is not None,camera_image_constraints=camera_image is not None,pose_sample_interval_ms=round(dt*1000,2),
   raw_fit_measurement_error_deg=residuals(rawG,corrected),current_measurement_error_deg=residuals(G,corrected),
   filtered_target_measurement_error_deg=residuals(G,measured_targets),measurement_filter_error_deg=residuals(measured_targets,corrected),
   measured_target_type=('legacy_local_filtered' if prior is None else 'causal_world_filtered' if self.stabilize else 'current_raw'),measurement_projection=projection)
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
   if j==0:continue
   for child in self.fusion.children[j]:
    add(self.fusion.rest[child]-self.fusion.rest[j],q[child]-q[j],R,min(c[j],c[child]))
  if not candidates:return previous,False
  candidates.sort();total=sum(w for _,w in candidates);s=0
  for target,w in candidates:
   s+=w
   if s>=total/2:break
  if getattr(self,'has_model_prior',False):
   agreeing=[v for v,_ in candidates if abs(wrap(v-target))<np.deg2rad(8)]
   if len(agreeing)<3 or abs(wrap(target-previous))<np.deg2rad(5):return previous,False
  # Common heading error only. No axial twist/bias oracle or hidden joint truth.
  step=(1-np.exp(-dt/.8))*wrap(target-previous)
  step=np.clip(step,-np.deg2rad(18)*dt,np.deg2rad(18)*dt)
  return previous+float(step),True

 def consistent_camera(self,q,c,axes,sensors,previous,prior=None):
  predicted,_=self.fusion.fit(previous,sensors=sensors,prior=prior)
  G=global_rotations(predicted,self.fusion.parents);filtered=c.copy();rejected=[]
  # Keep the validated sparse-camera solver's 3D consistency gate. Its
  # geometry has not yet been replaced by the projected GP+IMU solver;
  # accepting extra 2D-consistent/depth-inconsistent rays made it jitter.
  basis=self.camera_basis if prior is not None else None
  for j in range(24):
   if j in sensors:orientation=sensors[j]
   elif prior is not None or self.complete_streak>=3:continue
   else:orientation=G[j]
   if j==0 and prior is not None:
    # The visual pelvis is the midpoint of two detected hips. Its rays to
    # either hip are NOT SMPL pelvis-to-hip bone offsets (which also descend).
    # Only the actual inter-hip axis is an independent pelvis measurement.
    if min(c[1],c[2])>=.65:
     source=self.fusion.rest[1]-self.fusion.rest[2]
     expected=orientation@source;target=q[1]-q[2]
     if basis is not None:
      expected=basis.T@expected
      target=(self.camera_image[0][1]-self.camera_image[0][2]) if self.camera_image is not None else basis.T@target
     observable=np.linalg.norm(expected)>max(1e-5,.2*np.linalg.norm(source))
     lengths=np.linalg.norm(target)*np.linalg.norm(expected)
     if observable and lengths>1e-8 and np.dot(target,expected)/lengths<np.cos(np.deg2rad(40)):
      filtered[[1,2]]=0;rejected.append([1,2])
    continue
   for child in self.fusion.children[j]:
    if min(c[j],c[child])<.65:continue
    target=q[child]-q[j];expected=orientation@(self.fusion.rest[child]-self.fusion.rest[j])
    if basis is not None:
     target=(self.camera_image[0][child]-self.camera_image[0][j]) if self.camera_image is not None else basis.T@target
     expected=basis.T@expected
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


