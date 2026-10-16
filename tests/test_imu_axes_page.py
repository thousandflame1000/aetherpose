"""Real Chromium check of webui/imu_axes.html reading backend snapshots directly
(the web UI's Monitor > Axes link), with a scripted WebSocket and no services.

Run: python tests/test_imu_axes_page.py [--browser PATH]
"""
import argparse
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

PRELUDE = '''<script>
window.testSockets = [];
window.WebSocket = class {
  constructor(url) { this.url = url; window.testSockets.push(this); setTimeout(() => this.onopen && this.onopen(), 0); }
  send() {}
  close() { if (this.onclose) this.onclose(); }
};
</script>'''

SUITE = '''<script>
setTimeout(() => {
  const checks = [], $ = id => document.getElementById(id);
  const assert = (ok, name) => { if (!ok) throw Error(name); checks.push(name); };
  const snapshot = trackers => ({data: JSON.stringify({type: 'Snapshot', data: {trackers}})});
  const tracker = (id, rotation) => ({id, rotation, last_update_ms: 4, received_packets: 10, lost_packets: 1, last_sequence: 3});
  let result;
  try {
    const socket = window.testSockets[0];
    assert(window.testSockets.length === 1 && socket.url === 'ws://127.0.0.1:9009/ws', 'connects to the backend WebSocket');
    socket.onmessage(snapshot({77: tracker(77, [0, 0, 0, 1])}));
    assert($('status').textContent === '追蹤器 76 沒有連上後端，目前有：77' && $('roll').textContent === '—', 'other trackers are listed, not shown');
    const s = Math.SQRT1_2;
    socket.onmessage(snapshot({76: tracker(76, [0, 0, 2*s, 2*s]), 77: tracker(77, [0, 0, 0, 1])}));
    draw();
    assert($('yaw').textContent === '90.00°' && $('roll').textContent === '0.00°', 'requested tracker rotation is normalized and shown');
    assert($('stats').textContent.includes('追蹤器 76') && $('stats').textContent.includes('遺失 1'), 'tracker statistics shown');
    assert(!$('reference').disabled, 'fresh backend data enables the reference button');
    socket.onmessage(snapshot({76: tracker(76, [0, 0, 0, 0])}));
    assert($('status').textContent.includes('76') && $('yaw').textContent === '90.00°', 'invalid quaternion keeps the last pose');
    socket.close();
    assert($('status').textContent.includes('中斷'), 'disconnect is reported');
    setTimeout(() => {
      try { assert(window.testSockets.length === 2, 'reconnects after a disconnect'); result = {ok: true, checks}; }
      catch (e) { result = {ok: false, checks, error: String(e)}; }
      document.body.dataset.testResult = JSON.stringify(result);
    }, 2500);
  } catch (e) {
    document.body.dataset.testResult = JSON.stringify({ok: false, checks, error: String(e)});
  }
}, 50);
</script>'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    candidates = [args.browser, shutil.which('chromium'), shutil.which('google-chrome'),
                  r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                  r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe']
    browser = next((p for p in candidates if p and Path(p).is_file()), None)
    if not browser:
        raise SystemExit('Chromium browser missing; provide --browser PATH')
    source = (root / 'webui/imu_axes.html').read_text(encoding='utf-8')
    source = source.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + PRELUDE, 1)
    source = source.replace('</html>', SUITE + '</html>')
    with tempfile.TemporaryDirectory(prefix='aether-axes-qa-') as tmp:
        page = Path(tmp) / 'imu_axes.html'  # the page picks backend mode by this name
        page.write_text(source, encoding='utf-8')
        cmd = [browser, '--headless=new', '--no-sandbox', '--disable-background-networking', '--no-first-run',
               '--no-default-browser-check', '--dump-dom', '--virtual-time-budget=5000',
               '--user-data-dir=' + str(Path(tmp) / 'profile'), page.as_uri() + '?id=76']
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45)
    match = re.search(r'data-test-result="([^"]*)"', result.stdout)
    if not match:
        raise SystemExit('Page did not report a result: ' + result.stderr[-2000:])
    report = json.loads(html.unescape(match.group(1)))
    if not report['ok']:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    print(f"PASS: {len(report['checks'])} IMU axes page checks")


if __name__ == '__main__':
    main()
