from pathlib import Path
import json,sys,time
import cv2,numpy as np
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'frontend'))
from vision_pose import VisionPose
from hybrid_runner import HybridRunner
import argparse
parser=argparse.ArgumentParser(description='Real Full/Lite model recovery on an explicitly supplied full-body photo.')
parser.add_argument('--image',type=Path,required=True)
parser.add_argument('--output',type=Path)
args=parser.parse_args()
image=cv2.imread(str(args.image))
assert image is not None,'Image could not be decoded'
report={'scope':'official sample photo, local real models; no human accuracy claim','models':{}}
runner=HybridRunner()
deadline=time.monotonic()+15
while runner.fusion is None and time.monotonic()<deadline:time.sleep(.02)
assert runner.fusion is not None,runner.status
for mode in ('full','lite'):
 detector=VisionPose(mode);durations=[]
 try:
  for i in range(15):
   start=time.perf_counter();obs=detector.detect(image.copy(),time.monotonic())
   if i>=3:durations.append((time.perf_counter()-start)*1000)
  assert obs is not None
  runner.push_camera(obs,time.monotonic());runner.push_frame({})
  assert 'HYBRID' in runner.status,runner.status
  report['models'][mode]={'mean_ms':round(float(np.mean(durations)),1),'p95_ms':round(float(np.percentile(durations,95)),1),'visible_points':int((obs[1]>=.65).sum())}
  for _ in range(3):
   obs=detector.detect(image[:int(len(image)*.6)].copy(),time.monotonic())
   runner.push_camera(obs,time.monotonic());runner.push_frame({})
  assert 'HYBRID' not in runner.status,runner.status
  report['models'][mode]['cropped_status']=runner.status
  for _ in range(2):
   obs=detector.detect(np.zeros_like(image),time.monotonic())
  assert obs is None,'Empty image retained a person'
  assert detector.filter.points is None
  runner.push_camera(obs,time.monotonic());runner.push_frame({})
  assert runner.status.startswith('Waiting'),runner.status
  for _ in range(4):
   obs=detector.detect(image.copy(),time.monotonic())
  runner.push_camera(obs,time.monotonic());runner.push_frame({})
  assert 'HYBRID' in runner.status,runner.status
  report['models'][mode]['recovery']='full -> cropped (scoring disabled) -> empty (no pose) -> full'
 finally:detector.close()
report['passed']=True
if args.output:
 args.output.parent.mkdir(parents=True,exist_ok=True)
 args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
