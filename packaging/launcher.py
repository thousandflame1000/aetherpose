"""Windows entry point: owns only its child services; camera always starts off."""
import argparse
import asyncio
import json
import multiprocessing
import os
# Tiny per-joint matrix solves do not benefit from a large BLAS thread pool.
# Apply this before importing numerical libraries; keep explicit user settings.
for _thread_env in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
 os.environ.setdefault(_thread_env,'1')
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

if not getattr(sys,'frozen',False):
 sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'frontend')]
import app_paths

VERSION='0.2.0-preview.2'
URL='http://127.0.0.1:18080/'

def listening(port):
 try:
  with socket.create_connection(('127.0.0.1',port),timeout=.3):return True
 except OSError:return False

class Services:
 def __init__(self):self.children=[];self.streams=[];self.message='尚未啟動';self.lock=threading.RLock();self.cancel=threading.Event()
 def _spawn(self,command,label):
  folder=app_paths.data_dir();(folder/'logs').mkdir(parents=True,exist_ok=True)
  log=(folder/'logs'/f'{label}.log').open('ab')
  env={**os.environ,'PYTHONUTF8':'1','AETHER_DATA_DIR':str(folder)}
  if app_paths.frozen():env['PATH']=str(app_paths.asset_dir())+os.pathsep+env.get('PATH','')
  process=subprocess.Popen(command,cwd=str(folder),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
      creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  self.children.append(process);self.streams.append(log)
  return process
 def _service_command(self,role):
  if app_paths.frozen():return [sys.executable,'--service',role]
  return [sys.executable,str(Path(__file__).resolve()),'--service',role]
 def start(self):
  with self.lock:
   if self.children:return
   self.cancel.clear()
   ports=[9009,9010,18080]
   if any(listening(port) for port in ports):
    raise RuntimeError('已有服務占用 AetherPose 連接埠。請先關閉另一個版本，或按「開啟網頁」使用現有服務。')
   backend=(app_paths.asset_dir()/'bin/aetherpose.exe') if app_paths.frozen() else app_paths.project_dir()/'target/release/aetherpose.exe'
   if not backend.is_file():raise RuntimeError('缺少後端程式，請重新下載完整 Windows ZIP 並解壓縮。')
   try:
    for role,port in (('backend',9009),('bridge',9010),('web',18080)):
     self.message={'backend':'正在啟動追蹤服務…','bridge':'正在載入人體與影像服務…','web':'正在開啟操作介面…'}[role]
     command=[str(backend)] if role=='backend' else self._service_command(role)
     process=self._spawn(command,role)
     deadline=time.monotonic()+(45 if role=='bridge' else 20)
     while not listening(port):
      if self.cancel.is_set():raise RuntimeError('已取消啟動。')
      if process.poll() is not None:raise RuntimeError(f'{role} 啟動失敗。請按「開啟記錄資料夾」查看原因。')
      if time.monotonic()>deadline:raise RuntimeError(f'{role} 啟動逾時。請按「開啟記錄資料夾」查看原因。')
      time.sleep(.15)
    self.message='已就緒。到網頁按「開啟影像骨架」即可使用。'
   except BaseException:self.stop();raise
 def stop(self):
  with self.lock:
   for process in reversed(self.children):
    if process.poll() is None:
     process.terminate()
     try:process.wait(timeout=5)
     except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
   self.children.clear()
   for stream in self.streams:stream.close()
   self.streams.clear();self.message='已停止，攝影機已釋放。'

def run_service(role):
 folder=app_paths.data_dir();(folder/'logs').mkdir(parents=True,exist_ok=True)
 stream=(folder/'logs'/f'{role}-python.log').open('a',encoding='utf-8',buffering=1)
 sys.stdout=sys.stderr=stream
 if role=='bridge':
  import mesh_bridge
  asyncio.run(mesh_bridge.main())
 elif role=='web':
  if app_paths.frozen():os.environ['AETHER_PORTABLE']='1'
  from webui.server import make_server
  server=make_server(18080)
  try:server.serve_forever()
  finally:server.server_close()

def self_test(report_path):
 import tempfile
 import numpy as np
 from generic_body import GenericBody
 body=GenericBody();skin=body.page_skin()
 assert len(skin['parents'])==24 and np.allclose(body.weights.sum(axis=1),1)
 assert body.faces.max()<len(body.v_template)
 pose=np.tile(np.eye(3),(24,1,1));assert np.isfinite(body.lbs_frame(pose)).all()
 from vision_pose import VisionPose
 detector=VisionPose('full')
 try:detector.detect(np.zeros((480,640,3),dtype=np.uint8),time.monotonic())
 finally:detector.close()
 from webui.server import make_server
 server=make_server(0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 try:
  base=f'http://127.0.0.1:{server.server_port}'
  for path in ('/','/hybrid.js','/pose_follow.js','/vendor/three/three.min.js'):
   with urllib.request.urlopen(base+path,timeout=5) as response:assert response.status==200
 finally:server.shutdown();server.server_close();thread.join(5)
 with tempfile.TemporaryDirectory(prefix='aetherpose-clean-user-') as temp:
  old=os.environ.get('AETHER_SMPL_NPZ');os.environ['AETHER_SMPL_NPZ']=str(Path(temp)/'absent.npz')
  try:
   from hybrid_runner import HybridRunner
   runner=HybridRunner();deadline=time.monotonic()+10
   while runner.fusion is None and time.monotonic()<deadline:time.sleep(.02)
   assert runner.fusion is not None,runner.status
   assert runner.get_runtime_stats()['avatar_model']=='generic'
   assert runner.camera is None
   async def check_bridge():
    import mesh_bridge
    import websockets
    mesh_bridge.tp=runner
    assert mesh_bridge.camera_anchor.snapshot()['enabled'] is False
    async with websockets.serve(mesh_bridge._handler,'127.0.0.1',0,process_request=mesh_bridge._check_origin) as bridge:
     port=bridge.sockets[0].getsockname()[1]
     async with websockets.connect(f'ws://127.0.0.1:{port}',max_size=2*1024*1024) as client:
      topology=json.loads(await asyncio.wait_for(client.recv(),5))
      state=json.loads(await asyncio.wait_for(client.recv(),5))
      assert len(topology['skin']['parents'])==24
      assert state['runtime']['avatar_model']=='generic'
      assert state['position_anchor']['enabled'] is False
   asyncio.run(check_bridge())
  finally:
   if old is None:os.environ.pop('AETHER_SMPL_NPZ',None)
   else:os.environ['AETHER_SMPL_NPZ']=old
 import tkinter
 assert tkinter.TkVersion>=8.6
 assert tkinter.Tcl().eval('info patchlevel')
 if app_paths.frozen():
  import mediapipe
  for module in (np,mediapipe):assert Path(module.__file__).resolve().is_relative_to(app_paths.asset_dir().resolve())
 result=dict(passed=True,version=VERSION,frozen=app_paths.frozen(),camera_opened=False,
  checks=['procedural mannequin without licensed models','finite skinning and valid joint weights',
          'bundled MediaPipe model loads and runs on a blank image','page and local 3D assets serve',
          'production HybridRunner initializes without SMPL','production WebSocket serves generic skin and camera-off status',
          'Tk launcher dependency available'])
 if app_paths.frozen():result['checks'].append('frozen numerical and vision imports resolve inside the bundle')
 if report_path:Path(report_path).write_text(json.dumps(result,indent=2),encoding='utf-8')
 if sys.stdout is not None:print(json.dumps(result,indent=2))
 return result

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--service',choices=('bridge','web'))
 parser.add_argument('--self-test',action='store_true');parser.add_argument('--report');args=parser.parse_args()
 if args.service:return run_service(args.service)
 if args.self_test:return self_test(args.report)
 import tkinter as tk
 from tkinter import ttk,messagebox,filedialog
 root=tk.Tk();root.title('AetherPose');root.geometry('650x420');root.minsize(580,380)
 root.configure(bg='#102034');style=ttk.Style();style.theme_use('clam')
 style.configure('TFrame',background='#102034');style.configure('TLabel',background='#102034',foreground='#edf5ff',font=('Microsoft JhengHei UI',11))
 style.configure('TButton',font=('Microsoft JhengHei UI',11),padding=9)
 panel=ttk.Frame(root,padding=25);panel.pack(fill='both',expand=True)
 ttk.Label(panel,text='AetherPose',font=('Segoe UI',27,'bold')).pack(anchor='w')
 ttk.Label(panel,text='單鏡頭動作追蹤 · 可選配 IMU',font=('Microsoft JhengHei UI',13)).pack(anchor='w',pady=(3,16))
 status=tk.StringVar(value='正在準備…');ttk.Label(panel,textvariable=status,wraplength=570).pack(anchor='w',pady=(0,16))
 manager=Services();busy=[False]
 def task(action):
  if busy[0]:return
  busy[0]=True
  def run():
   try:
    action()
    if manager.children:webbrowser.open(URL)
   except Exception as exc:
    manager.message=str(exc)
   finally:busy[0]=False
  threading.Thread(target=run,daemon=True).start()
 buttons=ttk.Frame(panel);buttons.pack(fill='x',pady=4)
 ttk.Button(buttons,text='啟動',command=lambda:task(manager.start)).pack(side='left',padx=(0,8))
 ttk.Button(buttons,text='開啟網頁',command=lambda:webbrowser.open(URL)).pack(side='left',padx=(0,8))
 def stop():
  manager.cancel.set()
  if not busy[0]:task(manager.stop)
 ttk.Button(buttons,text='停止追蹤',command=stop).pack(side='left')
 def logs():
  folder=app_paths.data_dir()/'logs';folder.mkdir(parents=True,exist_ok=True)
  if os.name=='nt':os.startfile(str(folder))
 ttk.Button(panel,text='開啟記錄資料夾',command=logs).pack(anchor='w',pady=(15,8))
 def import_smpl():
  file=filedialog.askopenfilename(title='選擇你已取得授權的 SMPL .npz（選用）',filetypes=[('SMPL NumPy model','*.npz')])
  if not file:return
  path=app_paths.data_dir()/'external_paths.json';path.parent.mkdir(parents=True,exist_ok=True)
  try:
   config=json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
   config['smpl_npz']=file;path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
   messagebox.showinfo('AetherPose','已記住模型位置。停止並重新啟動追蹤後生效。')
  except Exception as exc:messagebox.showerror('無法匯入',str(exc))
 ttk.Button(panel,text='匯入已授權 SMPL 人體（選用）',command=import_smpl).pack(anchor='w')
 ttk.Label(panel,text='基本模式不需要 SMPL；攝影機只會在網頁手動開啟。\nGlobalPose 為另行安裝的研究功能。',wraplength=570).pack(anchor='w',pady=(17,0))
 def refresh():
  status.set(manager.message)
  if root.winfo_exists():root.after(300,refresh)
 def close():
  manager.cancel.set()
  if busy[0]:root.after(150,close);return
  manager.stop();root.destroy()
 root.protocol('WM_DELETE_WINDOW',close);refresh();root.after(200,lambda:task(manager.start))
 try:root.mainloop()
 finally:manager.stop()

if __name__=='__main__':
 multiprocessing.freeze_support()
 if app_paths.frozen():
  folder=app_paths.data_dir()/'logs';folder.mkdir(parents=True,exist_ok=True)
  if sys.stdout is None:sys.stdout=(folder/'launcher.log').open('a',encoding='utf-8',buffering=1)
  if sys.stderr is None:sys.stderr=sys.stdout
 try:main()
 except Exception:
  import traceback
  folder=app_paths.data_dir()/'logs';folder.mkdir(parents=True,exist_ok=True)
  (folder/'launcher-error.log').write_text(traceback.format_exc(),encoding='utf-8')
  if '--self-test' in sys.argv:
   if '--report' in sys.argv:
    output=Path(sys.argv[sys.argv.index('--report')+1]);output.write_text(json.dumps(dict(passed=False,error=traceback.format_exc()),indent=2),encoding='utf-8')
   raise SystemExit(1)
  raise
