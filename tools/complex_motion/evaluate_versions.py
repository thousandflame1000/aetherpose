"""Compare causal estimators on fixed recorded inputs; truth is scoring-only."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ.setdefault(key,'1')
from pathlib import Path
import argparse,hashlib,json,sys,time
import numpy as np
from scipy.spatial.transform import Rotation

p=argparse.ArgumentParser();p.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[2]);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--impl',type=Path,required=True);p.add_argument('--data',type=Path,required=True);p.add_argument('--label',required=True)
a=p.parse_args();BASE=a.output_dir.resolve();BASE.mkdir(parents=True,exist_ok=True);ROOT=a.project.resolve()
sys.path[:0]=[str(a.impl.resolve()),str(ROOT/'frontend')]
from hybrid_fusion import RotationFusion
from kinematic_fusion import global_rotations
from tracking_fusion import RealtimeFusion
from smpl_fk import SMPLForwardKinematics
from external_paths import resolve
fk=SMPLForwardKinematics(str(resolve()[0]['smpl_npz']));fusion=RotationFusion(fk.J_rest,fk.parents);fusion.bind_foot_skin(fk)
def load(name):
 with np.load(a.data/name) as z:return {k:z[k] for k in z.files}
imu=load('inputs.npz');pred=load('predictions.npz')['local'];truth=load('truth.npz')
sensor_joints=[18,19,4,5,15,0];parents=[1,2,3,6,9,13,14,16,17]
def estimate(observations):
 # This function deliberately has no truth argument or truth access.
 previous=np.tile(np.eye(3),(24,1,1));tracker=None;camera=None;camera_at=None
 rows={r['index']:r['camera'] for r in observations};result=[];used=[];headings=[];costs=[]
 for i in range(len(pred)):
  if i%360==0:tracker=RealtimeFusion(fusion);previous=np.tile(np.eye(3),(24,1,1));camera=None;camera_at=None
  if i in rows:
   row=rows[i];camera=None if row is None else (np.array(row['points']),np.array(row['confidence']));camera_at=100+i/60
  sensors={j:imu['ori'][i,k] for k,j in enumerate(sensor_joints)}
  start=time.perf_counter();raw,filtered,_,_=tracker.step(previous,camera,sensors,{},pred[i],100+i/60,camera_at);costs.append((time.perf_counter()-start)*1000)
  result.append(filtered);previous=raw;used.append(tracker.diagnostics['camera_fused']);headings.append(tracker.diagnostics['heading_feedback_deg'])
  if i%720==0:print(a.label,i,'/',len(pred),flush=True)
 return np.array(result),np.array(used),np.array(headings),np.array(costs)

def stats(v):return dict(mean=round(float(np.mean(v)),3),p95=round(float(np.percentile(v,95)),3))
reports={};output={}
for mode in ('imu','clear','occluded'):
 rows=[] if mode=='imu' else json.loads((a.data/(mode+'-observations.json')).read_text(encoding='utf-8'))['rows']
 print('Evaluating',a.label,mode,flush=True)
 rotations,used,headings,costs=estimate(rows);output[mode]=rotations
 G=np.array([global_rotations(r,fk.parents) for r in rotations]);angles=np.degrees(Rotation.from_matrix((G@truth['global_r'].transpose(0,1,3,2)).reshape(-1,3,3)).magnitude()).reshape(-1,24)
 positions=np.array([fusion.joints(r) for r in rotations]);position_error=np.linalg.norm(positions-truth['joints'],axis=-1)*100
 cases=[]
 for k in range(len(pred)//360):
  ids=np.arange(k*360+180,(k+1)*360);full=ids[(ids/60%6>=4.3)&(ids/60%6<5.)]
  # Angular velocity changes, measured on estimates themselves; no future use in inference.
  d=Rotation.from_matrix((G[ids[1:]]@G[ids[:-1]].transpose(0,1,3,2)).reshape(-1,3,3)).as_rotvec().reshape(-1,24,3)*60
  cases.append(dict(parent=stats(angles[ids][:,parents]),arms=stats(angles[ids][:,[16,17]]),hips=stats(angles[ids][:,[1,2]]),
   spine=stats(angles[ids][:,[3,6,9]]),mpjpe_cm=stats(position_error[ids]),full_parent=stats(angles[full][:,parents]),
   acceleration_deg_s2=stats(np.degrees(np.linalg.norm(np.diff(d,axis=0)*60,axis=-1))),
   camera_used_fraction=float(used[ids].mean()),heading_abs_max=float(np.max(np.abs(headings[ids])))))
 reports[mode]=dict(cases=cases,parent_mean=float(np.mean([c['parent']['mean'] for c in cases])),arms_mean=float(np.mean([c['arms']['mean'] for c in cases])),
  mpjpe_cm=float(np.mean([c['mpjpe_cm']['mean'] for c in cases])),frame_ms=stats(costs),finite=bool(np.isfinite(rotations).all()))
summary=dict(label=a.label,data=str(a.data),methods=reports,source_hashes={n:hashlib.sha256((a.impl/n).read_bytes()).hexdigest() for n in ('kinematic_fusion.py','tracking_fusion.py')})
np.savez_compressed(BASE/(a.label+'-estimates.npz'),**output)
(BASE/(a.label+'-metrics.json')).write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps({m:{k:v[k] for k in ('parent_mean','arms_mean','mpjpe_cm','frame_ms')} for m,v in reports.items()},indent=2))
