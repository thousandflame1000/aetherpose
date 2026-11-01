"""Render RGB, then run the unmodified production detector. No truth joints enter vision."""
from pathlib import Path
import os
import asyncio,base64,json,subprocess,sys,time,hashlib
import cv2,numpy as np
BASE=Path(os.environ.get('AETHER_SIM_DATA_DIR',str(Path(__file__).parent/'data')));BASE.mkdir(parents=True,exist_ok=True);sys.path.insert(0,str(BASE.parent))
from chrome_harness import chrome_page
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'frontend'))
from vision_pose import VisionPose
from hybrid_fusion import landmarks_to_smpl,head_orientation

async def main():
 async with chrome_page(BASE/'scene.html',680,880) as (call,js):
  for _ in range(150):
   if await js('window.sceneReady===true'):break
   await asyncio.sleep(.1)
  else:raise RuntimeError('Scene initialization failed')
  meta=await js("(()=>{camera.updateMatrixWorld();return {fps:data.fps,n:data.frames.length,cameraMatrix:camera.matrixWorld.elements,cameraPosition:camera.position.toArray()};})()")
  camera_world=np.array(meta['cameraMatrix']).reshape(4,4).T[:3,:3]
  for mode,blocked in (('clear',False),('occluded',True)):
   folder=BASE/mode;folder.mkdir(exist_ok=True);raw_folder=folder/'rgb';raw_folder.mkdir(exist_ok=True)
   detector=VisionPose();rows=[];writer=cv2.VideoWriter(str(folder/'camera.tmp.avi'),cv2.VideoWriter_fourcc(*'MJPG'),meta['fps'],(640,800))
   assert writer.isOpened()
   try:
    for i in range(meta['n']):
     png=base64.b64decode(await js(f'drawFrame({i},{str(blocked).lower()})'))
     (raw_folder/f'{i:04d}.png').write_bytes(png)
     frame=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
     obs=detector.detect(frame,100+i/meta['fps'])
     row=dict(t=i/meta['fps'],camera=None,confidence33=None,sha256=hashlib.sha256(png).hexdigest())
     if obs is not None:
      q,c=landmarks_to_smpl(*obs);head=head_orientation(*obs)
      row.update(camera=dict(points=(q@camera_world.T).round(7).tolist(),confidence=c.tolist(),
                             face=None if head is None else [(camera_world@head[0]).round(7).tolist(),head[1]]),confidence33=obs[1].tolist())
     rows.append(row)
     cv2.rectangle(frame,(0,0),(640,28),(30,39,46),-1)
     cv2.putText(frame,f'SYNTHETIC RGB | {i/meta["fps"]:.2f}s | {mode}',(12,20),cv2.FONT_HERSHEY_SIMPLEX,.5,(230,240,245),1,cv2.LINE_AA)
     writer.write(frame)
     if i%45==0:print(mode,i,'/',meta['n'],'camera',obs is not None,flush=True)
   finally:detector.close();writer.release()
   subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(folder/'camera.tmp.avi'),'-c:v','libx264','-crf','22','-pix_fmt','yuv420p','-movflags','+faststart',str(folder/'camera.mp4')],check=True)
   (folder/'camera.tmp.avi').unlink()
   (folder/'observations.json').write_text(json.dumps(dict(meta=meta,rows=rows),separators=(',',':')),encoding='utf-8')
   print(mode,'finished; observed',sum(r['camera'] is not None for r in rows),'/',len(rows),flush=True)
asyncio.run(main())
