"""Explicit software-only acceptance with real installed models.

No tracker is contacted or impersonated. Optional --image runs MediaPipe on
the named local image; --globalpose sends synthetic six-IMU frames through the
actual isolated native model. These checks do not measure human tracking error.
"""
import argparse,json,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'frontend'))
from hybrid_runner import HybridRunner
from hybrid_fusion import GP_BONES


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path)
    parser.add_argument('--globalpose',action='store_true')
    parser.add_argument('--seconds',type=float,default=30)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not args.image and not args.globalpose:parser.error('Select --image and/or --globalpose')
    if not 5<=args.seconds<=600:parser.error('--seconds must be between 5 and 600')
    report={'input_source':'explicit software test, not human accuracy validation','checks':[]}
    runner=HybridRunner()
    deadline=time.monotonic()+15
    while runner.fusion is None and time.monotonic()<deadline:time.sleep(.02)
    assert runner.fusion is not None,runner.status
    try:
        observation=None
        if args.image:
            import cv2
            from vision_pose import VisionPose
            image=cv2.imread(str(args.image))
            assert image is not None,'Image could not be decoded'
            detector=VisionPose()
            try:observation=detector.detect(image,time.monotonic())
            finally:detector.close()
            assert observation is not None,'No person detected'
            runner.push_camera(observation,time.monotonic());runner.push_frame({})
            assert runner._pose is not None,'No camera-derived SMPL pose'
            assert np.isfinite(runner._pose.joints).all()
            report['checks'].append('real image -> MediaPipe -> SMPL rotations and joints')
            report['vision_visible_points']=int(np.sum(observation[1]>=.65))
        if args.globalpose:
            # All synthetic devices share a known identity T-pose mounting.
            with runner._calib_lock:
                runner.body.smpl2imu=np.eye(3)
                for bone in GP_BONES:
                    runner.body.device2bone[bone]=np.eye(3);runner.body.offsets[bone]=np.zeros(3)
            trackers={b:{'id':b,'assigned_bone':b,'last_update_ms':0,'rotation':[0,0,0,1],
                         'accel':[0,0,9.81],'gyro':[0,0,0]} for b in GP_BONES}
            if observation is not None:
                runner.push_frame(trackers);runner.push_camera(observation,time.monotonic());runner.align_camera()
            # Loading may include the first exact SMPL physical-property cache.
            startup=time.monotonic();deadline=startup+600
            while time.monotonic()<deadline:
                runner.push_frame(trackers)
                if runner.stats.get('globalpose'):break
                if runner.gp and runner.gp.stopped:raise RuntimeError(runner.gp.error)
                time.sleep(1/60)
            assert runner.stats.get('globalpose'),'GlobalPose did not provide a fresh result'
            report['globalpose_startup_s']=round(time.monotonic()-startup,2)
            completed_before=runner.gp.completed_frames
            start=time.monotonic();next_at=start;active=total=combined=0
            while time.monotonic()-start<args.seconds:
                if observation is not None:runner.push_camera(observation,time.monotonic())
                runner.push_frame(trackers);total+=1
                if runner.stats.get('globalpose'):active+=1
                if runner.stats.get('globalpose') and runner.stats.get('camera'):combined+=1
                next_at+=1/60
                if next_at<time.monotonic()-.1:next_at=time.monotonic()
                time.sleep(max(0,next_at-time.monotonic()))
            report.update(globalpose_model_hz=round((runner.gp.completed_frames-completed_before)/(time.monotonic()-start),2),
                          globalpose_active_fraction=active/max(1,total),input_frames=total,
                          measured_input_hz=round(total/(time.monotonic()-start),2),combined_frames=combined,
                          status=runner.status,runtime=runner.get_runtime_stats())
            assert active>0,'GlobalPose never participated'
            assert active/total>=.9,'GlobalPose could not sustain fresh results at the requested input rate'
            if observation is not None:assert combined>0,'Camera and GlobalPose never fused together'
            runner.push_camera(None,time.monotonic());runner.push_frame({})
            assert not runner.stats['globalpose'] and runner.status.startswith('Waiting')
            report['checks'].append('real GlobalPose participates under six synthetic inputs and drops out when missing')
        report['passed']=True
    finally:
        if runner.gp:runner.gp.close()
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
