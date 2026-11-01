"""Local-only interactive simulation service; fixed cached RGB observations, no camera I/O."""
import argparse,json,math,threading,time,re
from collections import OrderedDict
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from scipy.spatial.transform import Rotation
from engine import Simulator,NAMES,ORDER

def serve(folder,static,port=18082):
 sim=Simulator(folder);lock=threading.Lock();cache=OrderedDict()
 truth=[dict(aa=Rotation.from_matrix(sim.truth['local'][i]).as_rotvec().round(5).ravel().tolist(),height=f['translation'][1]) for i,f in enumerate(sim.scene['frames'])]
 meta=dict(fps=sim.fps,seconds=sim.scene['seconds'],skin=sim.scene['skin'],faces=sim.scene['faces'],truth=truth,
           devices=[dict(joint=j,name=NAMES[j]) for j in ORDER],mounts=sim.truth['mounts'].reshape(19,9).tolist(),mount_joint=sim.truth['sensor_joints'].tolist())
 def calculate(params):
  selected=params.get('selected',ORDER[:6]);noise=float(params.get('noise_deg',.8));drift=float(params.get('drift_deg_s',2));occ=params.get('occluded',True)
  if not isinstance(selected,list) or len(selected)>19 or any(type(j)!=int for j in selected) or type(occ)!=bool:raise ValueError('Invalid configuration')
  if not math.isfinite(noise) or not 0<=noise<=3 or not math.isfinite(drift) or not 0<=drift<=4:raise ValueError('Noise/drift outside limits')
  key=(tuple(sorted(selected)),noise,drift,occ)
  with lock:
   if key in cache:return cache[key]
   started=time.perf_counter();result=sim.run(selected,noise,drift,occ);result['compute_s']=round(time.perf_counter()-started,2)
   body=json.dumps(result,separators=(',',':')).encode();cache[key]=body
   while len(cache)>8:cache.popitem(last=False)
   return body
 class Handler(SimpleHTTPRequestHandler):
  def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(static),**kwargs)
  def json(self,body,status=200):
   if not isinstance(body,bytes):body=json.dumps(body,separators=(',',':')).encode()
   self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
  def do_GET(self):
   path=self.path.split('?')[0]
   if path in ('/clear.mp4','/occluded.mp4'):
    file=static/path.lstrip('/');size=file.stat().st_size;start=0;end=size-1
    byte_range=self.headers.get('Range')
    if byte_range:
     match=re.fullmatch(r'bytes=(\d+)-(\d*)',byte_range)
     if not match:self.send_error(416);return
     start=int(match[1]);end=min(end,int(match[2])) if match[2] else end
     if start> end or start>=size:self.send_error(416);return
    self.send_response(206 if byte_range else 200);self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
    if byte_range:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
    self.end_headers()
    try:
     with file.open('rb') as stream:
      stream.seek(start);remaining=end-start+1
      while remaining:
       chunk=stream.read(min(65536,remaining))
       if not chunk:break
       self.wfile.write(chunk);remaining-=len(chunk)
    except (BrokenPipeError,ConnectionResetError):pass
   elif path=='/api/meta':self.json(meta)
   else:super().do_GET()
  def do_POST(self):
   if self.path!='/api/simulate':self.json({'error':'Unknown route'},404);return
   origin=self.headers.get('Origin')
   if origin and origin not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):
    self.json({'error':'Invalid origin'},403);return
   try:
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<8192:raise ValueError('Invalid request size')
    params=json.loads(self.rfile.read(length))
    if not isinstance(params,dict):raise ValueError('Invalid parameters')
    self.json(calculate(params))
   except (ValueError,TypeError,KeyError) as exc:self.json({'error':str(exc)},400)
   except (BrokenPipeError,ConnectionResetError):pass
  def log_message(self,format,*args):pass
 static=Path(static);static.mkdir(exist_ok=True,parents=True)
 # A saved default remains inspectable without a running API.
 default=json.loads(calculate({}))
 (static/'bootstrap-data.js').write_text('window.simulationBootstrap='+json.dumps(dict(meta=meta,result=default),separators=(',',':'))+';',encoding='utf-8')
 print(f'Simulation http://127.0.0.1:{port}/',flush=True)
 ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--static-dir',type=Path,required=True);p.add_argument('--port',type=int,default=18082)
 a=p.parse_args();serve(a.data_dir,a.static_dir,a.port)
