"""Real Chromium/WebGL regression checks, with no live tracker or services.

Run: python tests/test_webui_browser.py [--browser PATH] [--screenshot PATH]
Uses the bundled Three.js and only Python's standard library.
"""
import argparse
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    parser.add_argument('--screenshot')
    parser.add_argument('--size', default='1440,900', help='Chromium viewport width,height')
    parser.add_argument('--verbose',action='store_true')
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
    suite = (root / 'tests/webui_integration.js').read_text(encoding='utf-8')
    source = source.replace('</body>', '<script>' + suite + '</script></body>')
    with tempfile.TemporaryDirectory(prefix='aether-webui-qa-') as tmp:
        page = Path(tmp) / 'test.html'
        page.write_text(source, encoding='utf-8')
        cmd = [browser, '--headless=new', '--no-sandbox', '--enable-unsafe-swiftshader',
               '--disable-background-networking', '--no-first-run', '--no-default-browser-check',
               '--allow-file-access-from-files', '--dump-dom', '--window-size=' + args.size,
               '--run-all-compositor-stages-before-draw', '--virtual-time-budget=1000',
               '--user-data-dir=' + str(Path(tmp) / 'profile')]
        if args.screenshot:
            cmd += ['--screenshot=' + str(Path(args.screenshot).resolve())]
        result = subprocess.run(cmd + [page.as_uri()], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=45)
        match = re.search(r'data-test-result="([^"]*)"', result.stdout)
        if not match:
            stage=re.search(r'data-capture-stage="([^"]*)"',result.stdout)
            raise SystemExit('Page did not report a result ('+(stage.group(1) if stage else 'initialization')+'): ' + result.stderr[-2000:])
        report = json.loads(html.unescape(match.group(1)))
        if args.verbose or not report['ok']:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"PASS: {len(report['checks'])} Chromium/WebGL checks")
        if not report['ok']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
