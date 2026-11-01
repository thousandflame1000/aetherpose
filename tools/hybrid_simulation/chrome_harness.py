"""Isolated, hidden Chromium test process; never claims an existing browser/Studio."""
import asyncio,base64,json,subprocess,tempfile,time,urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
import websockets

@asynccontextmanager
async def chrome_page(page,width=1000,height=900):
 with tempfile.TemporaryDirectory(prefix='aether-simulation-') as tmp:
  cmd=[r'C:\Program Files\Google\Chrome\Application\chrome.exe','--headless=new','--no-sandbox','--enable-unsafe-swiftshader','--disable-background-networking','--no-first-run','--allow-file-access-from-files','--autoplay-policy=no-user-gesture-required',f'--window-size={width},{height}','--remote-debugging-port=0','--user-data-dir='+str(Path(tmp)/'profile'),'about:blank']
  process=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
  try:
   port_file=Path(tmp)/'profile/DevToolsActivePort';deadline=time.monotonic()+20
   while not port_file.exists() and time.monotonic()<deadline:await asyncio.sleep(.05)
   port=int(port_file.read_text().splitlines()[0])
   with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list',timeout=5) as response:tabs=json.load(response)
   endpoint=next(t['webSocketDebuggerUrl'] for t in tabs if t.get('type')=='page')
   async with websockets.connect(endpoint,max_size=40*1024*1024) as ws:
    sequence=0
    async def call(method,params=None):
     nonlocal sequence
     sequence+=1;await ws.send(json.dumps(dict(id=sequence,method=method,params=params or {})))
     while True:
      msg=json.loads(await asyncio.wait_for(ws.recv(),40))
      if msg.get('id')==sequence:
       if 'error' in msg:raise RuntimeError(msg['error'])
       return msg.get('result',{})
    async def js(code):
     result=await call('Runtime.evaluate',dict(expression=code,awaitPromise=True,returnByValue=True))
     if 'exceptionDetails' in result:raise RuntimeError(result['exceptionDetails'])
     return result.get('result',{}).get('value')
    url=str(page) if str(page).startswith(('http://','https://')) else Path(page).resolve().as_uri()
    await call('Page.enable');await call('Page.navigate',{'url':url})
    yield call,js
  finally:
   subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
   process.wait(timeout=10)
