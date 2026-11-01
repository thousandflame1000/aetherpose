"""Offline video -> the production vision/fusion pipeline. Never opens a camera.

Exports an annotated movie, actual SMPL poses and numerical integrity checks.
The clip's timestamps drive filtering; offline speed is not live camera FPS.
"""
import argparse,json,subprocess,sys,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cv2,numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'frontend'))
import hybrid_runner
from hybrid_runner import HybridRunner
from vision_pose import VisionPose

def analyze(video,output,model='full',max_seconds=60):
    output.mkdir(parents=True,exist_ok=True)
    cap=cv2.VideoCapture(str(video));fps=cap.get(cv2.CAP_PROP_FPS)
    if not cap.isOpened() or not .1<=fps<=240:raise ValueError('Invalid video or frame rate')
    runner=HybridRunner();deadline=time.monotonic()+15
    while runner.fusion is None and time.monotonic()<deadline:time.sleep(.02)
    if runner.fusion is None:raise RuntimeError(runner.status)
    detector=VisionPose(model);rows=[];durations=[];last_version=-1;writer=None
    max_bone_error=0.;max_rotation_error=0.;max_turn=0.;previous=None
    base=time.monotonic()
    try:
        while len(rows)<round(max_seconds*fps):
            ok,frame=cap.read()
            if not ok:break
            i=len(rows);at=base+i/fps;started=time.perf_counter()
            observation=detector.detect(frame,at)
            clock=SimpleNamespace(monotonic=lambda:at,perf_counter=time.perf_counter)
            with patch.object(hybrid_runner,'time',clock):
                runner.push_camera(observation,at);runner.push_frame({})
            elapsed=(time.perf_counter()-started)*1000
            durations.append(elapsed)
            pose,version,status,stats=runner.get_frame_if_new(last_version)
            row=dict(t=round(i/fps,5),status=status,pose=None,joints=None,
                     confidence=None if observation is None else observation[1].tolist(),
                     visible_points=0 if observation is None else int((observation[1]>=.65).sum()))
            if pose is not None and version!=last_version:
                R=np.asarray(pose.rotations).reshape(24,3,3);joints=np.asarray(pose.joints)
                assert np.isfinite(R).all() and np.isfinite(joints).all()
                error=np.max(np.abs(R@R.transpose(0,2,1)-np.eye(3)))
                max_rotation_error=max(max_rotation_error,float(error))
                for j,p in enumerate(runner.fusion.parents):
                    if p>=0:
                        error=abs(np.linalg.norm(joints[j]-joints[p])-np.linalg.norm(runner.fusion.rest[j]-runner.fusion.rest[p]))
                        max_bone_error=max(max_bone_error,float(error))
                if previous is not None:
                    delta=R@previous.transpose(0,2,1)
                    turn=np.degrees(np.arccos(np.clip((np.trace(delta,axis1=1,axis2=2)-1)/2,-1,1)))
                    max_turn=max(max_turn,float(turn.max()))
                previous=R;last_version=version
                row.update(pose=dict(rotations=pose.rotations,translation=pose.translation),joints=joints.round(5).tolist())
            rows.append(row)
            label='FULL' if ' HYBRID ' in status else 'PARTIAL' if ' PARTIAL ' in status else 'NO PERSON'
            h,w=frame.shape[:2];scale=min(1,720/h,720/w)
            preview=cv2.resize(frame,(int(w*scale)//2*2,int(h*scale)//2*2))
            cv2.rectangle(preview,(0,0),(preview.shape[1],52),(20,27,36),-1)
            color=(100,235,100) if label=='FULL' else (80,200,255)
            cv2.putText(preview,f'{label} | {model} | {i/fps:.2f}s',(10,22),cv2.FONT_HERSHEY_SIMPLEX,.52,color,1,cv2.LINE_AA)
            cv2.putText(preview,'PUBLIC VIDEO / OFFLINE REPLAY / 0 IMU',(10,43),cv2.FONT_HERSHEY_SIMPLEX,.37,(220,220,220),1,cv2.LINE_AA)
            if writer is None:
                writer=cv2.VideoWriter(str(output/'annotated.tmp.avi'),cv2.VideoWriter_fourcc(*'MJPG'),fps,(preview.shape[1],preview.shape[0]))
                assert writer.isOpened()
            writer.write(preview)
    finally:
        cap.release();detector.close()
        if writer:writer.release()
        if runner.gp:runner.gp.close()
    assert rows and max_rotation_error<5e-5 and max_bone_error<1e-5
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(output/'annotated.tmp.avi'),
                    '-c:v','libx264','-preset','fast','-crf','22','-pix_fmt','yuv420p','-movflags','+faststart',str(output/'annotated.mp4')],check=True)
    (output/'annotated.tmp.avi').unlink()
    (output/'poses.json').write_text(json.dumps(rows,separators=(',',':')),encoding='utf-8')
    (output/'skin.json').write_text(json.dumps(dict(skin=runner.skin,faces=runner.faces.tolist()),separators=(',',':')),encoding='utf-8')
    report=dict(video=str(video),model=model,frames=len(rows),source_fps=fps,duration_s=round(len(rows)/fps,2),
                detected_fraction=sum(x['pose'] is not None for x in rows)/len(rows),
                full_tracking_fraction=sum(' HYBRID ' in x['status'] for x in rows)/len(rows),
                pipeline_mean_ms=round(float(np.mean(durations[3:])),1),pipeline_p95_ms=round(float(np.percentile(durations[3:],95)),1),
                max_bone_length_error_m=max_bone_error,max_rotation_orthogonality_error=max_rotation_error,
                max_joint_rotation_change_deg=round(max_turn,1),
                integrity_passed=True,scope='Offline video through production MediaPipe and SMPL fusion; no accuracy ground truth or live IMU validation.')
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--model',choices=('full','lite'),default='full')
    parser.add_argument('--max-seconds',type=float,default=60)
    args=parser.parse_args()
    if not 1<=args.max_seconds<=600:parser.error('max-seconds must be 1–600')
    analyze(args.video,args.output_dir,args.model,args.max_seconds)
