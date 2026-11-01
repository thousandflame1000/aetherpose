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
  self.camera_basis=None
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

 def camera_hinge(self,source,target,distal_orientation,reference,twist,hinge,distal,axis,sign,quality):
  """Two observable ray coordinates, with a finite model prior on both DOFs.

  Close to extension the twist Jacobian vanishes, so its prior is retained.
  No camera bend-plane rotation is substituted for an IMU orientation.
  """
  twist_axis=(self.fusion.rest[distal]-self.fusion.rest[hinge]).copy();twist_axis[1]=0
  twist_axis/=max(np.linalg.norm(twist_axis),1e-9)
  q=quaternion(twist);tau=2*math.atan2(float(np.dot(q[:3],twist_axis)),q[3])
  origin=np.array([reference,tau]);value=origin.copy();weight=3*quality
  prior_precision=getattr(self,'prior_precision',1.)
  metric=getattr(self,'metric_bearing',False)
  basis=self.camera_basis
  if basis is not None:
   target2=basis.T@target;target_length=np.linalg.norm(target2)
   if target_length<1e-4 and not metric:return reference,twist
   if not metric:target2/=target_length
  # Heavy-tailed image innovations: a confident monocular depth outlier must
  # not receive an unbounded quadratic pull against calibrated inertial data.
  scale2=float(np.sin(np.deg2rad(25))**2)
  def evaluate(x,derivatives=False):
   T=Rotation.from_rotvec(twist_axis*x[1]).as_matrix()
   v=rotation(axis,-sign*x[0])@source;w=T.T@v;ray=distal_orientation@w
   if basis is None:residual=ray-target
   else:
    projected=basis.T@ray;projected_length=max(float(np.linalg.norm(projected)),1e-5)
    bearing=projected if metric else projected/projected_length;residual=bearing-target2
   squared=float(np.dot(residual,residual))
   cost=weight*scale2*math.log1p(squared/scale2)+prior_precision*float(np.sum((x-origin)**2))
   if not derivatives:return cost,T
   J=np.column_stack((-sign*distal_orientation@T.T@np.cross(np.eye(3)[axis],v),-distal_orientation@np.cross(twist_axis,w)))
   if basis is not None:J=basis.T@J if metric else (np.eye(2)-np.outer(bearing,bearing))@basis.T@J/projected_length
   return cost,T,residual,J,weight/(1+squared/scale2)
  for _ in range(5):
   cost,T,residual,J,precision=evaluate(value,True)
   step=np.linalg.solve(precision*J.T@J+prior_precision*np.eye(2),precision*J.T@residual+prior_precision*(value-origin))
   if np.linalg.norm(step)<1e-5:break
   improved=False
   for scale in (1.,.5,.25):
    trial=np.clip(value-scale*step,[0,-np.deg2rad(100)],[self.angles[-1],np.deg2rad(100)])
    if evaluate(trial)[0]<cost:value=trial;improved=True;break
   if not improved:break
  return float(value[0]),evaluate(value)[1]

 def fit(self,previous,camera,sensors,axes,prior=None,dt=None,camera_basis=None,camera_image=None):
  dt=1/self.fps if dt is None else dt
  self.camera_basis=None
  if camera_basis is not None:
   camera_basis=np.asarray(camera_basis,float)
   if camera_basis.shape!=(3,3) or not np.isfinite(camera_basis).all():raise ValueError('Invalid calibrated camera basis')
   if not np.allclose(camera_basis.T@camera_basis,np.eye(3),atol=1e-4) or np.linalg.det(camera_basis)<.99:raise ValueError('Camera basis must be a proper rotation')
   self.camera_basis=camera_basis[:,:2]
  if camera_image is not None and self.camera_basis is None:raise ValueError('Image bearings require a calibrated camera basis')
  if camera_image is not None:
   iq,ic=(np.asarray(v,float) for v in camera_image)
   if iq.shape!=(24,2) or ic.shape!=(24,) or not np.isfinite(iq).all() or not np.isfinite(ic).all() or np.any((ic<0)|(ic>1)):
    raise ValueError('Invalid image bearings')
   camera_image=(iq,ic)
  self.camera_image=camera_image
  # Scale is measured from image projections of independently oriented IMU
  # segments, not from pose truth or camera distance. Retain lengths as well
  # as bearings when multiple segments agree on a weak-perspective scale.
  self.image_scale=None
  if self.camera_basis is not None and camera_image is not None:
   iq,ic=camera_image;scales=[]
   for j,F in sensors.items():
    for child in self.fusion.children[j]:
     if child in (3,6,9,13,14) or min(ic[j],ic[child])<.8:continue
     projected=self.camera_basis.T@(F@(self.fusion.rest[child]-self.fusion.rest[j]))
     norm=np.linalg.norm(projected);observed=np.linalg.norm(iq[child]-iq[j])
     if norm>.08 and observed>.015:scales.append(float(observed/norm))
   if len(scales)>=2:
    median=float(np.median(scales));agree=[s for s in scales if abs(s/median-1)<.3]
    if len(agree)>=2:self.image_scale=float(np.median(agree))
  model_global=None if prior is None else global_rotations(prior,self.parents)
  root_inconsistent=prior is not None and 0 in sensors and Rotation.from_matrix(prior[0]@sensors[0].T).magnitude()>np.deg2rad(20)
  # A single index point does not observe palm rotation. Keep unmeasured
  # wrist orientation rather than inventing a full rotation from that ray.
  if camera is not None:
   q,c=camera;c=c.copy();c[[22,23]]=0;camera=(q,c)
  else:q=c=None
  axes={j:value for j,value in axes.items() if j not in sensors}
  R,self.observed=self.fusion.fit(previous,camera=camera,sensors=sensors,prior=prior,camera_axes=axes)
  if prior is not None:
   # The interpolated spine/clavicle points are not independent measurements
   # of each vertebra's twist. Retain their model decomposition unless a
   # real segment orientation observes that joint directly.
   for j in (3,6,9,12,13,14):
    if j not in sensors:
     R[j]=prior[j];self.observed.discard(j)
  for j in self.bounds:R[j]=self.bounded(R[j],j)
  if 0 in sensors:R[0]=sensors[0]
  for j in (3,6,9,12,13,14):
   R[j]=limited(R[j],previous[j],np.deg2rad(300)*dt)
   R[j]=self.bounded(R[j],j)
  G=global_rotations(R,self.parents)
  if prior is not None:
   # Rebase additional measured torso segments after retaining their parents'
   # model decomposition. The default six sensors do not include these joints.
   for j in (3,6,9,12,13,14):
    if j in sensors:
     R[j]=G[self.parents[j]].T@sensors[j]
     G=global_rotations(R,self.parents)
  for proximal,hinge,distal,axis,sign in self.CHAINS:
   self.metric_bearing=False;self.prior_precision=1.
   if model_global is not None and hinge in sensors:
    innovation=Rotation.from_matrix(model_global[hinge]@sensors[hinge].T).magnitude()
    self.prior_precision=max(.03,1/(1+(innovation/np.deg2rad(30))**2))
   if hinge in sensors and prior is not None and (root_inconsistent or proximal in sensors):
    parent=self.parents[proximal]
    # Condition the proximal model hypothesis on the corrected measured root.
    # A physics prior may have the right distal world orientation but the wrong
    # root tilt, compensated by a spurious local knee/elbow rotation. Reusing
    # that local hinge unchanged after replacing the root rotates the parent
    # twice. Re-estimate its relative hinge against the actual distal IMU.
    hypothesis=sensors[proximal] if proximal in sensors else (G[parent]@prior[proximal] if parent>=0 else prior[proximal])
    relative=hypothesis.T@sensors[hinge]
   else:relative=(sensors[proximal].T@sensors[hinge]) if proximal in sensors and hinge in sensors else (prior[hinge] if prior is not None else R[hinge])
   T=self.twist(relative,hinge,distal)
   old=np.clip(hinge_angle(previous[hinge]@self.twist(previous[hinge],hinge,distal).T,axis,sign),0,self.angles[-1])
   cap=np.deg2rad(160)*dt
   if prior is not None and hinge in sensors:
    # Preserve the unobservable axial component of the model hypothesis.
    # Fit the observable hinge angle against a calibrated distal orientation
    # and a camera bone ray, rather than rebuilding twist from monocular depth.
    reference=float(np.clip(hinge_angle(relative@T.T,axis,sign),0,self.angles[-1]))
    desired=reference
    if q is not None and min(c[proximal],c[hinge])>=.8 and proximal not in sensors:
     source=self.fusion.rest[hinge]-self.fusion.rest[proximal]
     target=q[hinge]-q[proximal]
     lengths=np.linalg.norm(source)*np.linalg.norm(target)
     quality=0.
     if lengths>1e-6:
      source=source/max(np.linalg.norm(source),1e-9);target=target/max(np.linalg.norm(target),1e-9)
      quality=float(min(c[proximal],c[hinge]))
      if camera_image is not None:
       image_q,image_c=camera_image
       bearing=image_q[hinge]-image_q[proximal];image_length=float(np.linalg.norm(bearing))
       length=np.linalg.norm(self.fusion.rest[hinge]-self.fusion.rest[proximal])
       # An image segment longer than a physical bone invalidates the common
       # weak-perspective scale (e.g. detector endpoint/anthropometry bias).
       # Keep its bearing, with the original prior strength, in that case.
       metric_valid=self.image_scale is not None and image_length<=1.15*self.image_scale*length
       if metric_valid:
        self.metric_bearing=True
        # A knee's learned bend is not an actual proximal IMU measurement.
        # With independently scaled image lengths, that missing DOF is
        # observable even when the thigh is end-on; use a weak pose prior.
        if hinge in (4,5):self.prior_precision*=.1
        target=self.camera_basis@(bearing/max(self.image_scale*length,1e-9))
       else:target=self.camera_basis@(bearing/max(image_length,1e-9))
       quality*=min(float(image_c[proximal]),float(image_c[hinge]))
       if not self.metric_bearing:quality*=min(1.,(image_length/.025)**2)
      # A distal ray provides an independent consistency check for image depth.
      if c[distal]>=.8:
       b=q[distal]-q[hinge];sb=self.fusion.rest[distal]-self.fusion.rest[hinge]
       predicted=sensors[hinge]@sb
       if self.camera_basis is not None:
        b=(camera_image[0][distal]-camera_image[0][hinge]) if camera_image is not None else self.camera_basis.T@b
        predicted=self.camera_basis.T@predicted
       cosine=np.dot(b,predicted)/max(np.linalg.norm(b)*np.linalg.norm(predicted),1e-9)
       mismatch=math.acos(float(np.clip(cosine,-1,1)))
       quality*=max(0.,1-(mismatch/np.deg2rad(35))**2)
      else:quality*=.25
      if self.camera_basis is not None and not self.metric_bearing:
       expected=sensors[hinge]@T.T@rotation(axis,-sign*reference)@source
       # Bearing direction is poorly observed for an end-on segment.
       quality*=min(1.,(np.linalg.norm(self.camera_basis.T@expected)/.25)**2)
       quality*=min(1.,(np.linalg.norm(self.camera_basis.T@target)/.25)**2)
      if hinge in (18,19) and quality>0:
       desired,T=self.camera_hinge(source,target,sensors[hinge],reference,T,hinge,distal,axis,sign,quality)
      else:
       F=sensors[hinge]@T.T
       rays=np.einsum('nij,j->ni',self.hinges[(axis,sign)].transpose(0,2,1),source)@F.T
       scale2=float(np.sin(np.deg2rad(25))**2)
       if self.camera_basis is None:squared=np.sum((rays-target)**2,axis=1)
       else:
        projected=rays@self.camera_basis;norms=np.linalg.norm(projected,axis=1)
        observed=self.camera_basis.T@target
        if not self.metric_bearing:observed/=max(np.linalg.norm(observed),1e-9)
        estimate=projected if self.metric_bearing else projected/np.maximum(norms[:,None],1e-5)
        squared=np.sum((estimate-observed)**2,axis=1)
       cost=3*quality*scale2*np.log1p(squared/scale2)+self.prior_precision*(self.angles-reference)**2
       desired=float(self.angles[np.argmin(cost)])
    angle=float(np.clip(desired,max(0,old-cap),min(self.angles[-1],old+cap)))
    H=rotation(axis,sign*angle)
    U=sensors[proximal] if proximal in sensors else sensors[hinge]@T.T@H.T
    if proximal in sensors:
     angle=float(np.clip(hinge_angle(U.T@sensors[hinge]@T.T,axis,sign),max(0,old-cap),min(self.angles[-1],old+cap)))
     H=rotation(axis,sign*angle)
    parent=self.parents[proximal]
    R[proximal]=(G[parent].T if parent>=0 else np.eye(3))@U
    R[hinge]=H@T
    G=global_rotations(R,self.parents)
    if distal in sensors:R[distal]=self.bounded(G[self.parents[distal]].T@sensors[distal],distal)
    elif distal in (20,21):R[distal]=self.bounded(prior[distal],distal)
    else:R[distal]=self.bounded(R[distal],distal)
    G=global_rotations(R,self.parents)
    continue
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
  self.pre_measurement_projection=R.copy()
  self.measurement_projection_diagnostics={}
  if prior is not None:
   from measured_projection import condition
   R,self.measurement_projection_diagnostics=condition(R,sensors,self,reference=prior)
  return R
