"""Aetherpose page server: serves this folder and a small local API for the
tools that need the machine itself (magnetometer calibration records from the
backend, writes the firmware table and flashes a tracker over USB).

    python webui/server.py --port 18080

Binds 127.0.0.1 only. API calls must come from this page: a localhost Host,
a matching Origin and the X-Aetherpose header, which other sites cannot send
without a CORS preflight this server never grants.
"""
import argparse
import codecs
import json
import os
import re
import signal
import subprocess
import sys
import threading
from collections import deque
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEBUI = Path(__file__).resolve().parent
ROOT = WEBUI.parent
FIRMWARE = ROOT / 'src' / 'skeleton' / 'tracker_firmware' / 'tracker_firmware.ino'
CALIBRATE = ROOT / 'tools' / 'calibrate_tracker.py'
LOCAL_HOSTS = {'127.0.0.1', 'localhost'}


def firmware_calibrations(path=FIRMWARE):
    """{tracker id: {"date", "note"}} for the magnetometer entries in the firmware source."""
    try:
        text = Path(path).read_text(encoding='utf-8')
    except OSError:
        return {}
    block = re.search(r'const MagCalibration MAG_CALIBRATIONS\[\] = \{\r?\n(.*?)\r?\n\};', text, re.S)
    if not block:
        return {}
    entries = {}
    for line in block.group(1).splitlines():
        match = re.match(r'\s*\{(\d+),[^/]*(?://\s*(.*))?$', line)
        if match:
            note = (match.group(2) or '').strip()
            date = re.search(r'\d{4}-\d{2}-\d{2}', note)
            entries[int(match.group(1))] = {'date': date.group(0) if date else None, 'note': note}
    return entries


def tool_command(kind, tracker_id, flash):
    command = [sys.executable, '-u', str(CALIBRATE), '--id', str(tracker_id)]
    if kind == 'flash':
        return command + ['--flash-only']
    return command if flash else command + ['--no-flash']


def stop_tree(process):
    """Stops a tool run and everything it started. The calibration tool runs arduino-cli
    (compile, upload); stopping only the tool left that running, still holding the COM port,
    after the page said the run was cancelled."""
    if os.name == 'nt':
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(process.pid)], capture_output=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)  # the run has its own session (see start)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.terminate()


class ToolJob:
    """One tool run at a time; its output is kept for the page to poll.
    A carriage return (progress redrawn in place) replaces `progress`
    instead of adding a line."""

    def __init__(self, command_for=tool_command):
        self.command_for = command_for
        self.lock = threading.Lock()
        self.process = None
        self.reading = False  # until the output is read to the end and the exit code known
        self.lines = deque(maxlen=200)
        self.progress = ''
        self.exit_code = None
        self.kind = None
        self.tracker_id = None
        self.cancelled = False

    def running(self):
        return self.reading

    def start(self, kind, tracker_id, flash=True):
        with self.lock:
            if self.running():
                return False
            self.lines.clear()
            self.progress = ''
            self.exit_code = None
            self.kind, self.tracker_id, self.cancelled = kind, tracker_id, False
            self.reading = True
            env = {**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8'}
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            session = {} if os.name == 'nt' else {'start_new_session': True}  # a process group for stop_tree
            self.process = subprocess.Popen(self.command_for(kind, tracker_id, flash), cwd=ROOT, env=env,
                                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, creationflags=flags, **session)
            threading.Thread(target=self._read, args=(self.process,), daemon=True).start()
            return True

    def _read(self, process):
        decoder = codecs.getincrementaldecoder('utf-8')('replace')
        pending = ''
        while True:
            chunk = process.stdout.read1(4096)
            pending += decoder.decode(chunk, final=not chunk)
            # A lone \r at the end may be the first half of \r\n: wait for more.
            while (match := re.search(r'\r\n|\n|\r(?!$)', pending)) or (not chunk and pending):
                if match:
                    segment, separator, pending = pending[:match.start()], match.group(), pending[match.end():]
                else:
                    segment, separator, pending = pending, '\n', ''
                with self.lock:
                    if separator == '\r':
                        if segment.strip():
                            self.progress = segment.strip()
                    else:
                        if segment.strip():
                            self.lines.append(segment.rstrip())
                        self.progress = ''
            if not chunk:
                break
        process.stdout.close()
        code = process.wait()
        with self.lock:
            if process is self.process:
                self.exit_code = code
                self.reading = False

    def cancel(self):
        with self.lock:
            if not self.running() or self.process.poll() is not None:
                return False
            self.cancelled = True
            stop_tree(self.process)
            return True

    def state(self):
        with self.lock:
            return {'running': self.running(), 'kind': self.kind, 'tracker_id': self.tracker_id,
                    'lines': list(self.lines), 'progress': self.progress,
                    'exit_code': self.exit_code, 'cancelled': self.cancelled}


class PageHandler(SimpleHTTPRequestHandler):
    job = None  # ToolJob shared by every request

    def send_response(self, *args, **kwargs):
        self._cache_control_sent = False
        super().send_response(*args, **kwargs)

    def send_header(self, keyword, value):
        if keyword.lower() == 'cache-control':
            self._cache_control_sent = True
        super().send_header(keyword, value)

    def end_headers(self):
        # The page is several files that change together with every update: revalidate them
        # (a cheap 304 when unchanged) so a reload never mixes new and cached versions.
        if not getattr(self, '_cache_control_sent', True):
            super().send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def send_json(self, data, status=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def api_allowed(self):
        host = self.headers.get('Host', '')
        origin = self.headers.get('Origin')
        return (host.rsplit(':', 1)[0] in LOCAL_HOSTS and self.headers.get('X-Aetherpose') == '1'
                and origin in (None, 'http://' + host))

    def send_head(self):
        # open() raises ValueError for a path with a NUL byte (/index.html%00.png); the base class
        # only handles OSError, so the client lost its connection and the log got a traceback.
        try:
            return super().send_head()
        except ValueError:
            self.send_error(400, 'Bad path')
            return None

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/calibrations':
            return self.send_json({'trackers': firmware_calibrations()})
        if path == '/api/tool':
            return self.send_json(self.job.state())
        return super().do_GET()

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        # Read the whole (small) body before answering: closing a socket with
        # unread data makes Windows reset the connection and lose the reply.
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= 1024:
            self.close_connection = True
            return self.send_json({'error': '請求內容最多 1024 位元組'}, 413)
        body = self.rfile.read(length)
        if not self.api_allowed():
            return self.send_json({'error': '工具 API 只接受 Aetherpose 頁面發出的請求'}, 403)
        if path == '/api/tool/cancel':
            return self.send_json({'cancelled': self.job.cancel()})
        if path != '/api/tool/start':
            return self.send_json({'error': '未知的 API'}, 404)
        try:
            request = json.loads(body)
            kind, tracker_id = request.get('kind'), request.get('id')
            flash = request.get('flash', True)
            if kind not in ('calibrate', 'flash') or type(tracker_id) is not int or not 0 <= tracker_id <= 255 \
                    or type(flash) is not bool:
                raise ValueError('kind, id or flash')
        except (ValueError, AttributeError) as exc:
            return self.send_json({'error': f'請求無效：{exc}'}, 400)
        if not self.job.start(kind, tracker_id, flash):
            return self.send_json({'error': '已有其他工具正在執行'}, 409)
        return self.send_json(self.job.state(), 202)


class PageServer(ThreadingHTTPServer):
    # HTTPServer sets SO_REUSEADDR. On Windows that lets a second socket bind a port that is
    # already listening, so a second page server would quietly share it with the first.
    allow_reuse_address = os.name != 'nt'


def make_server(port, job=None, bind='127.0.0.1'):
    handler = type('Handler', (PageHandler,), {'job': job or ToolJob()})
    return PageServer((bind, port), partial(handler, directory=str(WEBUI)))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=18080)
    args = parser.parse_args()
    try:
        server = make_server(args.port)
    except OSError as exc:  # typically the port is taken by another program
        raise SystemExit(f'Aetherpose page server cannot listen on 127.0.0.1:{args.port}: {exc}')
    print(f'Aetherpose page server: http://127.0.0.1:{args.port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.RequestHandlerClass.job.cancel()
        server.server_close()


if __name__ == '__main__':
    main()
