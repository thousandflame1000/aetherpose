"""Profile inference with no browser, normal rendering, and drawing suppressed.

Uses a disposable Chromium profile; only that page's renderer is instrumented.
Services must already be running. This is a synthetic diagnostic, not acceptance.
"""
import argparse
import asyncio
from collections import deque
import json
import os
import shutil
import statistics
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import websockets


async def backend_trackers():
    async with websockets.connect('ws://127.0.0.1:9009/ws') as socket:
        message = json.loads(await asyncio.wait_for(socket.recv(), 5))
        if message.get('type') != 'Snapshot':
            raise RuntimeError('backend did not supply a snapshot')
        return message['data']['trackers']


class PoseObserver:
    """Drain throughout browser startup/CDP work, not only during timed phases."""
    def __init__(self, socket):
        self.socket = socket
        self.samples = deque(maxlen=6000)
        self.failed = asyncio.Event()
        self.error = None
        self.received_count = 0

    async def __aenter__(self):
        self.task = asyncio.create_task(self.read())
        return self

    async def __aexit__(self, *args):
        # Keep draining until the close handshake has completed, even with
        # max_queue=1; cancelling first can pause reads of the close frame.
        await self.socket.close()
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    async def read(self):
        try:
            async for raw in self.socket:
                msg = json.loads(raw)
                if 'runtime' in msg:
                    self.received_count += 1
                    self.samples.append({'received_at': time.perf_counter(),
                                         'observation': self.received_count,
                                         'version': msg.get('joints_version'),
                                         'status': msg.get('status'), **msg['runtime']})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
        else:
            self.error = 'pose connection closed'
        finally:
            self.failed.set()


async def observe(observer, seconds):
    started = time.perf_counter()
    first_observation = observer.received_count
    try:
        await asyncio.wait_for(observer.failed.wait(), seconds)
    except asyncio.TimeoutError:
        pass
    else:
        raise ConnectionError(observer.error)
    samples = [{**sample, 'elapsed_s': sample['received_at'] - started}
               for sample in observer.samples if sample['observation'] > first_observation]
    # Exclude phase warm-up, with arrival times captured by the continuous reader.
    valid = [s for s in samples if s['elapsed_s'] >= 2 and isinstance(s['version'], int)]
    span = valid[-1]['elapsed_s'] - valid[0]['elapsed_s'] if len(valid) > 1 else 0
    return {'samples': samples,
            'observed_pose_hz': (valid[-1]['version'] - valid[0]['version']) / span if span else None,
            'median_frame_ms': statistics.median(s['frame_ms'] for s in valid) if valid else None}


async def profile(args, browser, profile_path):
    report = {'input': 'current service input; no tracker commands sent', 'phases': [],
              'completed': False, 'reader_mode': 'continuous'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)

    def save_progress():
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')

    async with websockets.connect('ws://127.0.0.1:9010', max_size=4 * 1024 * 1024,
                                  max_queue=16, compression=None) as pose_socket, PoseObserver(pose_socket) as observer:
        report['phases'].append({'name': 'no_test_browser', **await observe(observer, args.seconds)})
        save_progress()
        process = subprocess.Popen([browser, '--headless=new', '--no-sandbox', '--enable-unsafe-swiftshader',
                                    '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0',
                                    '--window-size=1440,900', '--user-data-dir=' + str(profile_path), args.url],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 25
            while True:
                if process.poll() is not None:
                    raise RuntimeError('profile browser exited before debugger startup')
                try:
                    port = int((profile_path / 'DevToolsActivePort').read_text().splitlines()[0])
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=2) as response:
                        targets = json.load(response)
                    endpoint = next(t['webSocketDebuggerUrl'] for t in targets
                                    if t.get('type') == 'page' and t.get('url', '').startswith(args.url))
                    break
                except (OSError, ValueError, IndexError, StopIteration):
                    if time.monotonic() >= deadline:
                        raise TimeoutError('profile browser startup timeout')
                    await asyncio.sleep(.1)
            async with websockets.connect(endpoint) as cdp:
                sequence = 0

                async def evaluate(expression):
                    nonlocal sequence
                    sequence += 1
                    await cdp.send(json.dumps({'id': sequence, 'method': 'Runtime.evaluate',
                                               'params': {'expression': expression, 'returnByValue': True}}))
                    while True:
                        message = json.loads(await asyncio.wait_for(cdp.recv(), 15))
                        if message.get('id') == sequence:
                            if 'error' in message or 'exceptionDetails' in message.get('result', {}):
                                raise RuntimeError(message)
                            return message['result']['result'].get('value')

                ready_deadline = time.monotonic() + 30
                while not await evaluate("typeof avatar!=='undefined' && avatar.fresh()"):
                    if time.monotonic() >= ready_deadline:
                        raise TimeoutError('profile page did not receive a pose')
                    await asyncio.sleep(.2)
                report['renderer'] = await evaluate("(()=>{const gl=renderer.getContext(),info=gl.getExtension('WEBGL_debug_renderer_info');return {name:softwareRendererName(),rawName:String(gl.getParameter(info?info.UNMASKED_RENDERER_WEBGL:gl.RENDERER)),quality:document.getElementById('scene-quality').value,pixelRatio:renderer.getPixelRatio(),hardwareConcurrency:navigator.hardwareConcurrency}})()")
                await evaluate("window.profileRender={original:renderer.render,skip:false,count:0,cost:0};renderer.render=function(...args){const t=performance.now();if(!window.profileRender.skip)window.profileRender.original.apply(this,args);window.profileRender.cost+=performance.now()-t;window.profileRender.count++;}")
                await evaluate("window.profileBackend={original:onMessage,renderOriginal:renderBackendSnapshot,count:0,cost:0,renderCount:0,renderCost:0};renderBackendSnapshot=function(...args){const t=performance.now();window.profileBackend.renderOriginal.apply(this,args);window.profileBackend.renderCost+=performance.now()-t;window.profileBackend.renderCount++;};onMessage=function(...args){const t=performance.now(),before=window.profileBackend.renderCost;window.profileBackend.original.apply(this,args);window.profileBackend.cost+=performance.now()-t-(window.profileBackend.renderCost-before);window.profileBackend.count++;}")
                for name, skip in [('drawing', False), ('drawing_suppressed', True), ('drawing_restored', False)] * args.cycles:
                    await evaluate(f'Object.assign(window.profileRender,{{skip:{str(skip).lower()},count:0,cost:0}})')
                    await evaluate('Object.assign(window.profileBackend,{count:0,cost:0,renderCount:0,renderCost:0})')
                    result = await observe(observer, args.seconds)
                    result['draw'] = await evaluate('({count:window.profileRender.count,total_cpu_ms:window.profileRender.cost})')
                    result['backend_page_handler'] = await evaluate('({count:window.profileBackend.count,intake_cpu_ms:window.profileBackend.cost,panel_count:window.profileBackend.renderCount,panel_cpu_ms:window.profileBackend.renderCost,total_cpu_ms:window.profileBackend.cost+window.profileBackend.renderCost})')
                    report['phases'].append({'name': name, **result})
                    save_progress()
                await evaluate('renderer.render=window.profileRender.original;delete window.profileRender')
                await evaluate('onMessage=window.profileBackend.original;renderBackendSnapshot=window.profileBackend.renderOriginal;delete window.profileBackend')
        except Exception as exc:
            report['error'] = f'{type(exc).__name__}: {exc}'
            save_progress()
            raise
        finally:
            if process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    process.terminate()
                process.wait(timeout=10)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=10)
    parser.add_argument('--url', default='http://127.0.0.1:18080/')
    parser.add_argument('--browser')
    parser.add_argument('--cycles', type=int, default=2)
    parser.add_argument('--simulate', action='store_true', help='run six simulated UDP trackers and clean them up afterward')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 60:
        parser.error('--seconds must be between 5 and 60')
    if not 1 <= args.cycles <= 5:
        parser.error('--cycles must be between 1 and 5')
    if args.output.exists():
        parser.error('--output must be a new file')
    candidates = [args.browser, shutil.which('chromium'), shutil.which('google-chrome'),
                  r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                  r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe']
    browser = next((p for p in candidates if p and Path(p).is_file()), None)
    if not browser:
        parser.error('Chromium missing; use --browser')
    simulator_thread = None
    simulator_outcome = []
    if args.simulate:
        if asyncio.run(backend_trackers()):
            parser.error('--simulate requires an empty backend tracker list; existing devices are left untouched')
        import simulate_trackers

        def run_simulator():
            try:
                simulator_outcome.append(simulate_trackers.main(['--motion', 'still']))
            except BaseException as exc:
                simulator_outcome.append(str(exc))

        simulator_thread = threading.Thread(target=run_simulator)
        simulator_thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='aether-profile-') as directory:
            report = asyncio.run(profile(args, browser, Path(directory) / 'profile'))
        report['input'] = 'six simulated UDP trackers' if args.simulate else report['input']
    finally:
        if simulator_thread:
            simulate_trackers.stop.set()
            simulator_thread.join(timeout=15)
            if simulator_thread.is_alive():
                raise RuntimeError('profile simulator did not finish cleanup')
            if simulator_outcome != [0]:
                raise RuntimeError(f'profile simulator failed: {simulator_outcome}')
            remaining = set(asyncio.run(backend_trackers())) & {str(i) for i in range(240, 246)}
            if remaining:
                raise RuntimeError(f'profile simulator left trackers behind: {sorted(remaining)}')
    report['completed'] = True
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    for phase in report['phases']:
        print(phase['name'], phase['observed_pose_hz'], phase['median_frame_ms'], phase.get('draw', {}))


if __name__ == '__main__':
    main()
