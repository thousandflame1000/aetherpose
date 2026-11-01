"""Offline six-IMU GlobalPose parent-joint stress study. Never opens a camera.

Dynamic truth enters only synthetic input construction and scoring. Estimation
receives rendered-RGB detector results, calibrated IMUs and GlobalPose outputs.
"""
import os
for name in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ.setdefault(name,'1')
import argparse,asyncio,base64,hashlib,json,queue,shutil,subprocess,sys,threading,time
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from motion_suite import FPS,SECONDS,CASES,SENSORS,generate,measurements,ambiguity,globals_and_joints

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[2])
parser.add_argument('--data',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--stage',choices=('generate','render','model','score','all'),default='all')
args=parser.parse_args();ROOT=args.project.resolve();DATA=args.data.resolve();OUT=args.output.resolve()
DATA.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
sys.path[:0]=[str(ROOT/'frontend'),str(ROOT/'tools/hybrid_simulation')]
from external_paths import resolve
from smpl_fk import SMPLForwardKinematics
from hybrid_fusion import RotationFusion,landmarks_to_smpl
from tracking_fusion import RealtimeFusion
from globalpose_client import runtime_paths
fk=SMPLForwardKinematics(str(resolve()[0]['smpl_npz']))
fusion=RotationFusion(fk.J_rest,fk.parents);fusion.bind_foot_skin(fk)

def save(name,value):
 (DATA/name).write_text(json.dumps(value,ensure_ascii=False,separators=(',',':')),encoding='utf-8')

def load_arrays(name):
 # NpzFile decompresses on every key lookup. Materialize once before frame loops.
 with np.load(DATA/name) as archive:return {key:archive[key] for key in archive.files}

def build():
 data=generate(fk);sensors=measurements(data)
 np.savez_compressed(DATA/'truth.npz',**data)
 np.savez_compressed(DATA/'inputs.npz',**sensors)
 # Scene is rendered at 10Hz, IMU/model evaluation remains 60Hz.
 ids=np.arange(0,len(data['local']),6);frames=[]
 for i in ids:
  frames.append(dict(t=float(i/FPS),rotations=data['local'][i].ravel().tolist(),translation=data['translation'][i].tolist(),joints=data['joints'][i].tolist()))
 save('truth.json',dict(fps=10,seconds=len(CASES)*SECONDS,skin=fk.page_skin(),faces=fk.faces.ravel().tolist(),frames=frames,sensor_joints=SENSORS))
 # Reuse the existing scene builder without altering the live simulator.
 np.savez_compressed(DATA/'render-rig.npz',mounts=np.tile(np.eye(3),(6,1,1)))
 code=(ROOT/'tools/hybrid_simulation/build_scene.py').read_text(encoding='utf-8')
 code=code.replace("Path(__file__).resolve().parents[2]",repr(str(ROOT)))
 code=code.replace('root='+repr(str(ROOT)),'root=Path('+repr(str(ROOT))+')')
 code=code.replace("base/'truth.npz'","base/'render-rig.npz'")
 code=code.replace("reshape(19,9)","reshape(6,9)")
 code=code.replace('t>=5&&t<9','(t%6)>=3.0&&(t%6)<4.1').replace('t>=10&&t<12','(t%6)>=4.3&&(t%6)<5.0')
 env={**os.environ,'AETHER_SIM_DATA_DIR':str(DATA)}
 subprocess.run([sys.executable,'-c','__file__='+repr(str(ROOT/'tools/hybrid_simulation/build_scene.py'))+'\n'+code],env=env,check=True)
 save('ambiguity.json',ambiguity(fk.J_rest,fk.parents))
 print('Generated',len(data['local']),'60Hz poses; six complex cases and an exact rigid-segment ambiguity test',flush=True)

async def render():
 import cv2
 from vision_pose import VisionPose
 # Dedicated headless browser, using its normal process sandbox. No existing tab is touched.
 harness=(ROOT/'tools/hybrid_simulation/chrome_harness.py').read_text(encoding='utf-8').replace("'--no-sandbox',",'')
 namespace={};exec(compile(harness,'<isolated simulation browser>','exec'),namespace)
 async with namespace['chrome_page'](DATA/'scene.html',680,880) as (_,js):
  for _ in range(200):
   if await js('window.sceneReady===true'):break
   await asyncio.sleep(.1)
  else:raise RuntimeError('3D source scene failed')
  meta=await js('(()=>{camera.updateMatrixWorld();return {n:data.frames.length,matrix:camera.matrixWorld.elements};})()')
  camera_world=np.array(meta['matrix']).reshape(4,4).T[:3,:3]
  for mode,blocked in (('clear',False),('occluded',True)):
   rows=[];detector=VisionPose('full');avi=DATA/(mode+'.avi')
   writer=cv2.VideoWriter(str(avi),cv2.VideoWriter_fourcc(*'MJPG'),10,(640,800));assert writer.isOpened()
   try:
    for i in range(meta['n']):
     png=base64.b64decode(await js(f'drawFrame({i},{str(blocked).lower()})'))
     frame=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
     observation=detector.detect(frame,100+i/10);row=dict(index=i*6,t=i/10,camera=None,sha256=hashlib.sha256(png).hexdigest())
     if observation is not None:
      q,c=landmarks_to_smpl(*observation)
      row['camera']=dict(points=(q@camera_world.T).tolist(),confidence=c.tolist())
     rows.append(row)
     cv2.putText(frame,f'SYNTHETIC RGB / {mode} / {i/10:.1f}s',(10,24),cv2.FONT_HERSHEY_SIMPLEX,.5,(250,250,250),1,cv2.LINE_AA)
     writer.write(frame)
     if i%60==0:print('RGB',mode,i,'/',meta['n'],'detected',observation is not None,flush=True)
   finally:writer.release();detector.close()
   subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(avi),'-c:v','libx264','-crf','23','-pix_fmt','yuv420p','-movflags','+faststart',str(OUT/f'GlobalPose-complex-{mode}.mp4')],check=True)
   save(mode+'-observations.json',dict(rows=rows,camera_world=camera_world.tolist()))
   print(mode,'detected',sum(r['camera'] is not None for r in rows),'/',len(rows),flush=True)

def model():
 inputs=load_arrays('inputs.npz');source,python=runtime_paths()
 env={**os.environ,'AETHER_GP_DEVICE':'cpu','AETHER_GP_ASYNC':'0','AETHER_GP_REFERENCE':'0'}
 log=(DATA/'globalpose-stderr.log').open('w',encoding='utf-8')
 proc=subprocess.Popen([str(python),'-u',str(ROOT/'frontend/globalpose_worker.py'),str(source),str(os.getpid())],cwd=source,
  env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 replies=queue.Queue()
 def read():
  for line in proc.stdout:
   try:replies.put(json.loads(line))
   except ValueError:pass
  replies.put(dict(error='Model worker ended'))
 threading.Thread(target=read,daemon=True).start();poses=[];trans=[];latencies=[];failed=[]
 try:
  ready=replies.get(timeout=180);assert ready.get('ready'),ready
  for i in range(len(inputs['ori'])):
   frame={name:inputs[name][i].tolist() for name in ('ori','acc','gyro')}
   start=time.perf_counter();proc.stdin.write(json.dumps(dict(reset=i%(FPS*SECONDS)==0,sample_at=100+i/FPS,frames=[frame]))+'\n');proc.stdin.flush()
   reply=replies.get(timeout=30);latencies.append(time.perf_counter()-start)
   if 'error' in reply:
    raise RuntimeError(f"GlobalPose failed at frame {i}: {reply['error']}")
   else:poses.append(np.array(reply['rotations']));trans.append(np.array(reply['translation']))
   if i%180==0:print('GlobalPose',i,'/',len(inputs['ori']),'errors',len(failed),flush=True)
  np.savez_compressed(DATA/'predictions.npz',local=np.array(poses),translation=np.array(trans),latencies=latencies)
  save('model-run.json',dict(ready=ready,errors=failed,frames=len(poses),neural_and_physics='production GlobalPose worker, synchronous offline 60Hz samples; no input dropped; not live FPS',worker_sha256=hashlib.sha256((ROOT/'frontend/globalpose_worker.py').read_bytes()).hexdigest()))
 finally:
  proc.terminate();proc.wait(timeout=10);log.close()

def summarize(values):
 values=np.asarray(values);return dict(mean=round(float(values.mean()),2),p95=round(float(np.percentile(values,95)),2),max=round(float(values.max()),2))

def estimate(imu,prior,observations):
 previous=np.tile(np.eye(3),(24,1,1));tracking=RealtimeFusion(fusion);output=[];accepted=[];last=None
 rows={r['index']:r for r in observations};camera=None;camera_at=None
 for i in range(len(prior)):
  if i%(FPS*SECONDS)==0:tracking=RealtimeFusion(fusion);previous=np.tile(np.eye(3),(24,1,1));camera=None;camera_at=None
  if i in rows:
   row=rows[i];last=row['camera'];camera=None if last is None else (np.array(last['points']),np.array(last['confidence']));camera_at=100+i/FPS
  sensors={j:imu['ori'][i,k] for k,j in enumerate(SENSORS)}
  raw,filtered,_,_=tracking.step(previous,camera,sensors,{},prior[i],100+i/FPS,camera_at)
  previous=raw;output.append(filtered);accepted.append(tracking.diagnostics['camera_fused'])
  if i%(FPS*SECONDS)==0:print('Fusion',i,'/',len(prior),'camera records',len(rows),flush=True)
 return np.array(output),accepted

def score():
 truth=load_arrays('truth.npz');imu=load_arrays('inputs.npz');pred=load_arrays('predictions.npz')
 clear=json.loads((DATA/'clear-observations.json').read_text())['rows'];occluded=json.loads((DATA/'occluded-observations.json').read_text())['rows']
 methods={'GlobalPose':pred['local']};accepted={}
 for name,obs in (('GP_IMU',[]),('Hybrid_clear',clear),('Hybrid_occluded',occluded)):
  print('Scoring',name,flush=True)
  methods[name],accepted[name]=estimate(imu,pred['local'],obs)
 orthogonality=float(np.max(np.abs(pred['local']@pred['local'].transpose(0,1,3,2)-np.eye(3))))
 report=dict(kind='constructed synthetic stress study; not human accuracy',fps=60,rgb_fps=10,warmup_seconds_per_case=2,
  evaluated_seconds_per_case=3,noise=dict(orientation_deg=.5,acceleration_m_s2=.05,angular_velocity_rad_s=.005),
  six_imu_joints=SENSORS,parent_joints=[1,2,3,6,9,13,14,16,17],cases=[],
  ambiguity=json.loads((DATA/'ambiguity.json').read_text()),model=json.loads((DATA/'model-run.json').read_text()),
  all_finite=all(np.isfinite(v).all() for v in methods.values()),limitations=[
   'Kinematic trajectories are constructed, not anatomically or dynamically validated human performances.',
   'Synthetic attachment vertex paths use the project LBS and the official six vertex IDs; no full sensor electronics or AHRS simulation.',
   'Initial coordinate alignment is exactly known from scene calibration; real calibration errors are not tested.',
   'MediaPipe consumes rendered RGB only; no ground-truth landmarks enter fusion.',
   'Offline synchronous model outputs have no dropped samples or transport latency; these are not live throughput numbers.',
   'Full occlusion predictions are assessed, never filled with ground truth.',
   'No translation accuracy claim; MPJPE is pelvis-relative without Procrustes fitting.'])
 groups=dict(upper_arms=[16,17],hips=[1,2],spine=[3,6,9],clavicles=[13,14],measured_segments=SENSORS)
 all_frames={};angles={};global_frames={}
 for name,local in methods.items():
  all_frames[name]=np.array([globals_and_joints(r,fk.J_rest,fk.parents)[1] for r in local])
  G=np.array([globals_and_joints(r,fk.J_rest,fk.parents)[0] for r in local])
  global_frames[name]=G
  angles[name]=np.degrees(Rotation.from_matrix((G@truth['global_r'].transpose(0,1,3,2)).reshape(-1,3,3)).magnitude()).reshape(-1,24)
 for k,(case,label) in enumerate(CASES):
  # Exclude warmup and ramp; score the same three-second interval for all methods.
  ids=np.arange(k*FPS*SECONDS+3*FPS,(k+1)*FPS*SECONDS);item=dict(id=case,label=label,methods={})
  from kinematic_fusion import KinematicFusion
  limits=KinematicFusion(fusion);bound_errors=[]
  for i in ids:
   for j in limits.bounds:
    difference=limits.bounded(truth['local'][i,j],j)@truth['local'][i,j].T
    bound_errors.append(float(np.degrees(Rotation.from_matrix(difference).magnitude())))
  item['truth_engineering_free_joint_limit_residual_deg']=summarize(bound_errors)
  for name in methods:
   stats={group:summarize(angles[name][ids][:,j]) for group,j in groups.items()}
   stats['parent_deg']=summarize(angles[name][ids][:,report['parent_joints']])
   stats['mpjpe_cm']=summarize(np.linalg.norm(all_frames[name][ids]-truth['joints'][ids],axis=-1)*100)
   full=ids[((ids/FPS)%SECONDS>=4.3)&((ids/FPS)%SECONDS<5.0)]
   stats['full_occlusion_parent_deg']=summarize(angles[name][full][:,report['parent_joints']])
   item['methods'][name]=stats
  for mode,rows in (('clear',clear),('occluded',occluded)):
   selected=[r for r in rows if k*SECONDS+3<=r['t']<(k+1)*SECONDS]
   item[mode+'_camera']=dict(frames=len(selected),person_detections=sum(r['camera'] is not None for r in selected),
    upper_arm_confident_frames=int(sum(r['camera'] is not None and min(np.array(r['camera']['confidence'])[[16,17,18,19]])>=.8 for r in selected)))
   blocked=[r for r in selected if 4.3<=r['t']%SECONDS<5.0]
   item[mode+'_camera']['during_full_block']=dict(frames=len(blocked),person_detections=sum(r['camera'] is not None for r in blocked))
  for name,flags in accepted.items():
   item['methods'][name]['camera_used_fraction']=round(float(np.mean(np.array(flags)[ids])),3)
  report['cases'].append(item)
 model_errors={r['index'] for r in report['model']['errors']}
 report['model_rotation_orthogonality_max']=orthogonality
 report['all_model_frames_valid']=len(model_errors)==0 and orthogonality<1e-3
 report['observed_parent_mean_deg']={name:round(float(np.mean([c['methods'][name]['parent_deg']['mean'] for c in report['cases']])),2) for name in methods}
 (OUT/'GlobalPose-complex-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 # No licensed mesh/template is included in the shareable visual report.
 step=4;ids=np.arange(0,len(truth['local']),step)
 view=dict(fps=FPS/step,parents=fk.parents.tolist(),cases=CASES,seconds=SECONDS,
  truth=truth['joints'][ids].round(4).tolist(),methods={n:p[ids].round(4).tolist() for n,p in all_frames.items()},
  truth_globals=truth['global_r'][ids].round(4).tolist(),globals={n:g[ids].round(4).tolist() for n,g in global_frames.items()},
  errors={n:a[ids][:,report['parent_joints']].mean(axis=1).round(2).tolist() for n,a in angles.items()},summary=report)
 from report_view import write_view
 write_view(OUT/'GlobalPose-complex-review.html',view)
 print(json.dumps(dict(all_model_frames_valid=report['all_model_frames_valid'],all_finite=report['all_finite'],parent_means=report['observed_parent_mean_deg'],ambiguity=report['ambiguity']),ensure_ascii=False,indent=2),flush=True)

if args.stage in ('generate','all'):build()
if args.stage in ('render','all'):asyncio.run(render())
if args.stage in ('model','all'):model()
if args.stage in ('score','all'):score()
