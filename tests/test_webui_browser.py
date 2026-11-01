"""Real Chromium/WebGL regression checks, with no live tracker or services.

Run: python tests/test_webui_browser.py [--browser PATH] [--screenshot PATH]
Uses the bundled Three.js and the project's websockets dependency.
"""
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request
import websockets


async def browser_result(endpoint, page, screenshot):
    async with websockets.connect(endpoint, max_size=4*1024*1024) as socket:
        sequence = 0
        async def call(method, params=None):
            nonlocal sequence
            sequence += 1
            await socket.send(json.dumps({'id': sequence, 'method': method, 'params': params or {}}))
            while True:
                message = json.loads(await asyncio.wait_for(socket.recv(), 10))
                if message.get('id') == sequence:
                    if 'error' in message:
                        raise RuntimeError(message['error'])
                    return message.get('result', {})
        await call('Page.enable')
        await call('Page.navigate', {'url': page.as_uri()})
        deadline = time.monotonic()+35
        while time.monotonic() < deadline:
            result = await call('Runtime.evaluate', {'expression': 'document.body?.dataset.testResult || null', 'returnByValue': True})
            value = result.get('result', {}).get('value')
            if value:
                report = json.loads(value)
                if screenshot:
                    await asyncio.sleep(.15)
                    capture = await call('Page.captureScreenshot', {'format':'png'})
                    Path(screenshot).resolve().write_bytes(base64.b64decode(capture['data']))
                return report
            await asyncio.sleep(.1)
        state = await call('Runtime.evaluate', {'expression':'JSON.stringify({errors:window.testErrors,stage:document.body?.dataset.captureStage})', 'returnByValue':True})
        raise RuntimeError('Page did not report within 35 seconds: '+str(state.get('result', {}).get('value')))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    parser.add_argument('--screenshot')
    parser.add_argument('--size', default='1440,900', help='Chromium viewport width,height')
    parser.add_argument('--verbose',action='store_true')
    parser.add_argument('--suite',default='webui_integration.js',help='JavaScript suite in tests/')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    candidates = [args.browser, shutil.which('chromium'), shutil.which('google-chrome'),
                  r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                  r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe']
    browser = next((p for p in candidates if p and Path(p).is_file()), None)
    if not browser:
        raise SystemExit('Chromium browser missing; provide --browser PATH')
    source = (root / 'webui/index.html').read_text(encoding='utf-8')
    prelude = '''<script>
window.testClock = 10000;
window.testErrors = [];
window.addEventListener('error',e=>window.testErrors.push(e.message));
Object.defineProperty(performance,'now',{value:()=>window.testClock});
window.testRafRequests = 0;
window.testNativeRaf = window.requestAnimationFrame.bind(window);
window.requestAnimationFrame = () => ++window.testRafRequests;
window.WebSocket = class {
  static OPEN = 1;
  constructor(url) { this.url=url; this.readyState=1; this.sent=[]; }
  send(message) { this.sent.push(message); }
  close() { this.readyState=3; if(this.onclose)this.onclose(); }
};
</script>'''
    source = source.replace('<head>', '<head><base href="' +
                            (root / 'webui').as_uri() + '/">' + prelude)
    if args.screenshot:
        # Keep WebGL pixels until Chromium takes its screenshot; production
        # uses the default buffer lifecycle and its normal animation loop.
        source = source.replace('<script src="avatar.js">', '''<script>
window.testScreenshotMode = true;
const NativeRenderer = THREE.WebGLRenderer;
THREE.WebGLRenderer = class extends NativeRenderer {
  constructor(options) { super({...options,preserveDrawingBuffer:true}); }
};
</script><script src="avatar.js">''')
    suite = (root / 'tests' / args.suite).read_text(encoding='utf-8')
    source = source.replace('</body>', '<script>' + suite + '</script></body>')
    with tempfile.TemporaryDirectory(prefix='aether-webui-qa-') as tmp:
        page = Path(tmp) / 'test.html'
        page.write_text(source, encoding='utf-8')
        cmd = [browser, '--headless=new', '--no-sandbox', '--enable-unsafe-swiftshader',
               '--disable-background-networking', '--no-first-run', '--no-default-browser-check',
               '--allow-file-access-from-files', '--window-size=' + args.size,
               '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
               '--user-data-dir=' + str(Path(tmp) / 'profile'), 'about:blank']
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            port_file=Path(tmp)/'profile/DevToolsActivePort'
            deadline=time.monotonic()+10
            while True:
                if process.poll() is not None or time.monotonic()>deadline:
                    raise RuntimeError('Chromium debug endpoint did not start')
                try:
                    port=int(port_file.read_text().splitlines()[0])
                    break
                except (OSError,ValueError,IndexError):
                    pass  # Chromium can still be writing the endpoint file on Windows.
                time.sleep(.05)
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list',timeout=5) as response:
                tabs=json.load(response)
            endpoint=next(tab['webSocketDebuggerUrl'] for tab in tabs if tab.get('type')=='page')
            report=asyncio.run(browser_result(endpoint,page,args.screenshot))
        finally:
            if os.name=='nt' and process.poll() is None:
                # Kill only this isolated browser and its children, so its profile
                # files are released before TemporaryDirectory removes them.
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            elif process.poll() is None:
                process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=5)
        if args.verbose or not report['ok']:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"PASS: {len(report['checks'])} Chromium/WebGL checks")
        if not report['ok']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
