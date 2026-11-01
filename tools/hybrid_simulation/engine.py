"""Synthetic AHRS orientation errors, production fusion, and an explicit experimental yaw feedback.

Truth constructs virtual measurements and evaluates estimates. estimate() receives
only camera observations, calibrated sensor rotations, initial calibration and rig.
It never reads the animated ground-truth pose.
"""
from pathlib import Path
import json,sys
import numpy as np
from scipy.spatial.transform import Rotation
PROJECT_ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT_ROOT/'frontend'))
from hybrid_fusion import RotationFusion,heading_from_camera
from anatomical_fusion import AnatomicalFusion
from temporal_filter import RotationOneEuro

NAMES={0:'骨盆',3:'下背',9:'胸口',12:'頸部',15:'頭',1:'左大腿',4:'左小腿',7:'左腳',2:'右大腿',5:'右小腿',8:'右腳',13:'左鎖骨',16:'左上臂',18:'左前臂',20:'左手',14:'右鎖骨',17:'右上臂',19:'右前臂',21:'右手'}
ORDER=[18,19,4,5,15,0,1,2,16,17,7,8,3,9,12,13,14,20,21]
def wrap(a):return (a+np.pi)%(2*np.pi)-np.pi

def globals_from_local(local,parents):
 result=np.empty_like(local)
 for j,p in enumerate(parents):result[j]=local[j] if p<0 else result[p]@local[j]
 return result

class Simulator:
 def __init__(self,folder):
  self.folder=Path(folder);self.truth=np.load(self.folder/'truth.npz')
  self.scene=json.loads((self.folder/'truth.json').read_text(encoding='utf-8'))
  self.fps=self.scene['fps'];self.n=len(self.scene['frames'])
  self.fusion=RotationFusion(self.truth['rest'],self.truth['parents'])
  # The four-weight display skin permits exact sole contact without loading ML.
  skin=self.scene['skin'];weights=np.zeros((len(skin['template'])//3,24))
  bones=np.array(skin['bones']).reshape(-1,4);w=np.array(skin['weights']).reshape(-1,4)
  for k in range(4):weights[np.arange(len(weights)),bones[:,k]]=w[:,k]
  from types import SimpleNamespace
  self.fusion.bind_foot_skin(SimpleNamespace(weights=weights,v_template=np.array(skin['template']).reshape(-1,3)))
  self.anatomical=AnatomicalFusion(self.fusion,self.fps)
  self.observations={mode:json.loads((self.folder/mode/'observations.json').read_text(encoding='utf-8'))['rows'] for mode in ('clear','occluded')}
  self.sensor_index={int(j):i for i,j in enumerate(self.truth['sensor_joints'])}
  self.noise=np.random.default_rng(7312026).normal(0,1,(self.n,19,3))

 def measurements(self,noise_deg,drift_deg_s):
  bank=[]
  for i in range(self.n):
   per_frame={};t=i/self.fps
   for j,k in self.sensor_index.items():
    mounting=self.truth['mounts'][k]
    drift=Rotation.from_rotvec([0,np.deg2rad(drift_deg_s*(1+.04*np.sin(k*.8))*t),0]).as_matrix()
    noise=Rotation.from_rotvec(np.deg2rad(noise_deg)*self.noise[i,k]).as_matrix()
    # A body-bound sensor observes world<-sensor, including its fixed mount.
    measured_sensor=drift@self.truth['global_r'][i,j]@mounting@noise
    per_frame[j]=measured_sensor@mounting.T
   bank.append(per_frame)
  return bank

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

 def consistent_camera(self,q,c,axes,sensors,previous):
  predicted,_=self.fusion.fit(previous,sensors=sensors)
  G=globals_from_local(predicted,self.fusion.parents);filtered=c.copy();rejected=[]
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

 def estimate(self,observations,measurements,selected,initial):
  states={name:initial.copy() for name in ('raw_imu','imu','weighted','feedback')}
  filters={name:RotationOneEuro(initial) for name in ('imu','feedback')}
  output=[];correction=0.;complete_streak=0
  # Same standing-heading alignment used by the application. The known
  # initial calibration is allowed; no later true pose is read here.
  alignment=np.eye(3)
  if observations[0]['camera'] is not None:
   first=observations[0]['camera']
   alignment=initial[0]@heading_from_camera(np.array(first['points']),np.array(first['confidence'])).T
  for i,row in enumerate(observations):
   sensors={j:measurements[i][j] for j in selected}
   camera=row['camera'];q=c=None;axes={}
   if camera is not None:
    q=np.array(camera['points'])@alignment.T;c=np.array(camera['confidence'])
    if np.sum(c>=.65)<8:q=c=None
    elif camera['face'] is not None:axes={15:(alignment@np.array(camera['face'][0]),camera['face'][1])}
   feedback_active=False
   if q is not None and sensors:correction,feedback_active=self.yaw_feedback(q,c,sensors,correction,1/self.fps)
   critical=[0,1,2,4,5,7,8,12,15,16,17,18,19,20,21]
   complete_streak=complete_streak+1 if c is not None and min(c[critical])>=.8 else 0
   yaw=Rotation.from_rotvec([0,correction,0]).as_matrix()
   corrected={j:yaw@r for j,r in sensors.items()}
   safe_c,safe_axes,rejected=(None,{},[]) if q is None else self.consistent_camera(q,c,axes,corrected,states['feedback'])
   # A camera-only estimate has no independent inertial disagreement test.
   # Stable complete reacquisition must also be allowed to escape an old pose.
   if q is not None and (not sensors or complete_streak>=3):safe_c,safe_axes,rejected=c,axes,[]
   frame={'camera_points':0 if c is None else int((c>=.65).sum()),'camera_available':q is not None,
          'camera_min_required':None if c is None else round(float(min(c[critical])),4),
          'feedback_active':feedback_active,'correction_deg':round(np.degrees(correction),3),'rejected_bones':rejected}
   for name in states:
    cam=None if name in ('raw_imu','imu') or q is None else (q,c)
    use_axes=axes if name not in ('raw_imu','imu') else {}
    if name=='feedback':
     cam=None if safe_c is None or np.sum(safe_c>=.65)<8 else (q,safe_c)
     use_axes=safe_axes
    inp=sensors if name!='feedback' else corrected
    if name in ('imu','feedback'):R=self.anatomical.fit(states[name],cam,inp,use_axes)
    else:R,_=self.fusion.fit(states[name],camera=cam,sensors=inp,camera_axes=use_axes)
    states[name]=R
    outputs={name:R}
    if name in filters:
     outputs[name+'_unfiltered']=R
     outputs[name]=filters[name].update(R,1/self.fps)
    for output_name,pose in outputs.items():
     P=self.fusion.joints(pose);height=self.fusion.foot_floor_translation(pose,P)
     frame[output_name]=dict(aa=Rotation.from_matrix(pose).as_rotvec().round(5).ravel().tolist(),height=round(float(height),5))
   output.append(frame)
  return output

 def run(self,selected=None,noise_deg=.8,drift_deg_s=2.,occluded=True):
  if selected is None:selected=ORDER[:6]
  if len(set(selected))!=len(selected) or any(j not in self.sensor_index for j in selected):raise ValueError('Invalid sensor selection')
  selected=sorted(selected);mode='occluded' if occluded else 'clear'
  measurements=self.measurements(noise_deg,drift_deg_s)
  # A known initial calibration pose is shared by all estimators.
  estimates=self.estimate(self.observations[mode],measurements,selected,self.truth['local'][0])
  errors={name:[] for name in ('raw_imu','imu','weighted','feedback','imu_unfiltered','feedback_unfiltered')};angles={name:[] for name in errors}
  for i,frame in enumerate(estimates):
   for name in errors:
    R=Rotation.from_rotvec(np.array(frame[name]['aa']).reshape(24,3)).as_matrix()
    P=self.fusion.joints(R)
    error=float(np.linalg.norm(P-self.truth['joints'][i],axis=1).mean()*1000)
    errors[name].append(error);frame[name]['error_mm']=round(error,2)
    vectors=Rotation.from_matrix(R).as_rotvec();warnings=[]
    for j,axis,sign in ((4,0,1),(5,0,1),(18,2,1),(19,2,-1)):
     off=np.degrees(np.linalg.norm(np.delete(vectors[j],axis)))
     bend=np.degrees(vectors[j,axis])*sign
     if off>5 or bend< -5 or bend>150:warnings.append(j)
    frame[name]['joint_warnings']=warnings
    G=globals_from_local(R,self.truth['parents'])
    angle=0 if not selected else float(np.degrees(Rotation.from_matrix(G[selected]@self.truth['global_r'][i,selected].transpose(0,2,1)).magnitude()).mean())
    angles[name].append(angle);frame[name]['sensor_error_deg']=round(angle,2)
  segments=[('clear_start',0,5),('partial',5,9),('clear_gap',9,10),('full',10,12),('recovery',12,18)]
  summary={name:dict(mpjpe_mm=round(float(np.mean(values)),2),sensor_error_deg=round(float(np.mean(angles[name])),2),phases={label:round(float(np.mean(values[int(a*self.fps):int(b*self.fps)])),2) for label,a,b in segments}) for name,values in errors.items()}
  return dict(model_version='anatomical-v3-temporal',selected=selected,noise_deg=noise_deg,drift_deg_s=drift_deg_s,occluded=occluded,frames=estimates,summary=summary,
              temporal_filter=dict(type='causal local-SO(3) One Euro adaptation',min_cutoff_hz=1.8,beta_hz_per_deg_s=.045,derivative_cutoff_hz=1.,future_samples=0),
              camera_observed_frames=sum(r['camera'] is not None for r in self.observations[mode]),
              camera_source='rendered RGB -> actual MediaPipe Full -> production rotation fusion',
              truth_usage='measurement generation, initial calibration and evaluation only; estimate() has no animated truth input')

if __name__=='__main__':
 sim=Simulator(Path(__file__).parent)
 result=sim.run()
 (sim.folder/'default-result.json').write_text(json.dumps(result,separators=(',',':')),encoding='utf-8')
 print(json.dumps(result['summary'],indent=2))
