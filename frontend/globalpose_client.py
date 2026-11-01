"""Bounded, asynchronous GlobalPose prior. Never fills missing sensor inputs."""
import atexit
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import numpy as np
import app_paths

ROOT=app_paths.data_dir()

def runtime_paths():
    """Machine paths stay outside source control, just like external_paths.json."""
    config={}
    path=ROOT/'hybrid_paths.json'
    if path.is_file():
        config=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(config,dict):raise ValueError('hybrid_paths.json 必須是 JSON 物件。')
    def get(key,env,default):
        raw=os.environ.get(env) or config.get(key) or default
        if not isinstance(raw,str):raise ValueError('無效 Hybrid 外部路徑：'+key)
        value=Path(raw).expanduser()
        return value if value.is_absolute() else ROOT/value
    return (get('globalpose_dir','AETHER_GLOBALPOSE_DIR','external/GlobalPose'),
            get('globalpose_python','AETHER_GLOBALPOSE_PYTHON','external/python38/python.exe'))


class GlobalPoseClient:
    def __init__(self):
        self.lock=threading.Lock();self.frames=queue.Queue(maxsize=8)
        self.result=None;self.error='正在載入 GlobalPose';self.process=None
        self.generation=0;self.stopped=False;self._last_submit_at=None;self.device="loading";self.quantized=False;self.dropped_frames=0;self.completed_frames=0;self.last_latency_ms=0.;self.epoch=0;self.step_s=1/60
        atexit.register(self.close)
        threading.Thread(target=self._run,daemon=True,name='globalpose-worker').start()

    def close(self):
        self.stopped=True
        p=self.process
        if p is not None and p.poll() is None:p.terminate()

    def invalidate(self):
        with self.lock:
            self.generation+=1;self.result=None

    def submit(self, acc, gyro, ori, at):
        with self.lock:
            # Windows monotonic clocks can repeat within one timer tick.
            # Do not fabricate a later capture time or send duplicate/older
            # observations into the native recurrent state.
            if not np.isfinite(at) or (self._last_submit_at is not None and at<=self._last_submit_at):
                self.dropped_frames+=1
                return
            # Reinitialize recurrent/physics state across a paused browser or
            # long input gap instead of integrating across unobserved time.
            if self._last_submit_at is not None and at-self._last_submit_at>.15:
                self.generation+=1
                # The previous completed observation remains usable until its
                # own freshness deadline; only future recurrent state resets.
            self._last_submit_at=at
            generation=self.generation
        item=(generation,at,{'acc':np.asarray(acc).tolist(),'gyro':np.asarray(gyro).tolist(),'ori':np.asarray(ori).tolist()})
        try:self.frames.put_nowait(item)
        except queue.Full:
            # A bounded latest-sample mailbox: discarded queued measurements
            # do not invalidate an already-computed, still-fresh result.
            while True:
                try:self.frames.get_nowait();self.dropped_frames+=1
                except queue.Empty:break
            self.frames.put_nowait(item)

    def latest(self, now):
        with self.lock:
            result=self.result
            if result is None:return None,self.error
            if now-result[0]>.3:return None,'GlobalPose 更新較慢，暫時改用其他有效來源。'
            if now<result[0]:return None,'GlobalPose 時間戳無效。'
            return (result[1].copy(),result[2].copy()),None

    def _run(self):
        try:
            source,python=runtime_paths()
            if not python.is_file() or not (source/'data/weights.pt').is_file():
                raise ValueError('GlobalPose 尚未安裝，請執行 tools/setup_hybrid.ps1。')
            env={**os.environ,'PYTHONPATH':str(source),'PYTHONUNBUFFERED':'1'}
            # Embeddable Python uses its _pth file, so the worker adds the source explicitly.
            self.process=subprocess.Popen([str(python),'-u',str(app_paths.asset_dir()/'frontend/globalpose_worker.py'),str(source),str(os.getpid())],
                cwd=source,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=open(ROOT/'logs/globalpose.err.log','a'),
                text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            responses=queue.Queue()
            def read():
                for line in self.process.stdout:
                    try:responses.put(json.loads(line))
                    except ValueError:pass
                responses.put({'error':'GlobalPose 子程序已結束'})
            threading.Thread(target=read,daemon=True).start()
            message=responses.get(timeout=600)
            if not message.get('ready'):raise ValueError(message.get('error','GlobalPose 未就緒'))
            with self.lock:
                self.error=None;self.device=message.get("device","unknown");self.quantized=message.get("quantized",False)
            active=-1
            while not self.stopped:
                try:item=self.frames.get(timeout=.5)
                except queue.Empty:continue
                # Synchronize each prediction to the newest available input.
                # The worker integrates using these real sample timestamps.
                while True:
                    try:item=self.frames.get_nowait();self.dropped_frames+=1
                    except queue.Empty:break
                gen,at,frame=item
                with self.lock:
                    if gen!=self.generation:continue
                self.process.stdin.write(json.dumps({'reset':gen!=active,'sample_at':at,'frames':[frame]})+'\n');self.process.stdin.flush()
                message=responses.get(timeout=20)
                if message.get('stale'):
                    active=gen
                    continue
                if 'error' in message:raise ValueError(message['error'])
                r,t=np.asarray(message['rotations']),np.asarray(message['translation'])
                if r.shape!=(24,3,3) or t.shape!=(3,) or not np.isfinite(r).all() or not np.isfinite(t).all():
                    raise ValueError('GlobalPose 傳回無效姿態')
                with self.lock:
                    if gen==self.generation:
                        self.result=(at,r,t);self.epoch=message.get("epoch",0);self.step_s=message.get("step_s",1/60);self.completed_frames+=1;self.last_latency_ms=round((time.monotonic()-at)*1000,1)
                active=gen
        except Exception as exc:
            with self.lock:self.error=str(exc);self.result=None
        finally:self.close()
