"""webui/server.py: static pages, firmware calibration listing, tool runs and
the guards that keep other websites from starting a flash.

Run with the project Python environment.
"""
import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'webui'))
import server  # noqa: E402

TABLE = '''const MagCalibration MAG_CALIBRATIONS[] = {
  {43, {25.70f, 22.09f, 10.04f}, {0.9158f, 1.1117f, 0.9915f}},  // D4:3F:A8:D9:D3:2B, 2026-09-28
  // {12, {0f, 0f, 0f}, {1f, 1f, 1f}},
  {76, {1.00f, 2.00f, 3.00f}, {1.0000f, 1.0000f, 1.0000f}},
};
'''

# Progress redrawn with \r, Windows line endings, then a final line.
SCRIPT = ("import sys,time\n"
          "print('Connected', flush=True)\n"
          "for n in (30, 31): print(f'\\r  {n} samples', end='', flush=True); time.sleep(.05)\n"
          "print()\n"
          "print('Fit: field 45.0 uT')\n"
          "sys.exit(int(sys.argv[1]))\n")


# Like the calibration tool running arduino-cli: a child with its own output pipe that
# would leave a mark if it outlived the cancelled run.
CHILD = ("import subprocess,sys,time\n"
         "subprocess.Popen([sys.executable,'-c','import time,pathlib,sys; time.sleep(3); pathlib.Path(sys.argv[1]).write_text(\"x\")', sys.argv[1]],"
         " stdout=subprocess.PIPE, stderr=subprocess.PIPE)\n"
         "print('child started', flush=True)\n"
         "time.sleep(30)\n")


def fake_command(kind, tracker_id, flash):
    if kind == 'flash':
        return [sys.executable, '-c', 'import time; time.sleep(30)']
    if kind == 'tree':
        return [sys.executable, '-c', CHILD, str(tracker_id)]
    return [sys.executable, '-c', SCRIPT, '0' if flash else '3']


def wait_done(job, seconds=10):
    deadline = time.monotonic() + seconds
    while job.state()['running']:
        if time.monotonic() > deadline:
            raise AssertionError('tool run did not finish')
        time.sleep(0.02)
    return job.state()


class FirmwareTableTests(unittest.TestCase):
    def test_lists_entries_with_dates_and_skips_commented_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fw.ino'
            path.write_text('// header\r\n' + TABLE.replace('\n', '\r\n'), encoding='utf-8')
            entries = server.firmware_calibrations(path)
        self.assertEqual(sorted(entries), [43, 76])
        self.assertEqual(entries[43]['date'], '2026-09-28')
        self.assertIsNone(entries[76]['date'])

    def test_real_firmware_table_parses(self):
        self.assertIn(43, server.firmware_calibrations())

    def test_commands_map_to_the_calibration_tool(self):
        self.assertEqual(server.tool_command('calibrate', 76, True)[-2:], ['--id', '76'])
        self.assertEqual(server.tool_command('calibrate', 76, False)[-1], '--no-flash')
        self.assertEqual(server.tool_command('flash', 76, True)[-1], '--flash-only')


class ToolJobTests(unittest.TestCase):
    def test_progress_lines_exit_code_and_single_run(self):
        job = server.ToolJob(fake_command)
        self.assertTrue(job.start('calibrate', 76, True))
        self.assertFalse(job.start('calibrate', 76, True), 'second run refused while one is active')
        state = wait_done(job)
        self.assertEqual(state['lines'], ['Connected', '  31 samples', 'Fit: field 45.0 uT'])
        self.assertEqual((state['exit_code'], state['progress'], state['tracker_id']), (0, '', 76))
        job.start('calibrate', 7, False)
        self.assertEqual(wait_done(job)['exit_code'], 3)

    def test_cancel_stops_the_run(self):
        job = server.ToolJob(fake_command)
        job.start('flash', 76, True)
        self.assertTrue(job.cancel())
        state = wait_done(job)
        self.assertTrue(state['cancelled'])
        self.assertNotEqual(state['exit_code'], 0)
        self.assertFalse(job.cancel())

    def test_cancel_also_stops_what_the_tool_started(self):
        with tempfile.TemporaryDirectory() as folder:
            mark = Path(folder) / 'child_still_running'
            job = server.ToolJob(lambda kind, tracker_id, flash: fake_command('tree', mark, flash))
            job.start('calibrate', 76, True)
            deadline = time.monotonic() + 5
            while 'child started' not in job.state()['lines'] and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(job.cancel())
            self.assertTrue(wait_done(job, seconds=5)['cancelled'])
            time.sleep(4)
            self.assertFalse(mark.exists(), 'the tool\'s child kept running after cancel')


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.job = server.ToolJob(fake_command)
        cls.server = server.make_server(0, cls.job)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.job.cancel()
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        default = {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json'}
        connection.request(method, path, json.dumps(body) if body is not None else None, {**default, **(headers or {})})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, (json.loads(data) if response.getheader('Content-Type', '').startswith('application/json') else data)

    def page_headers(self, **extra):
        return {'X-Aetherpose': '1', 'Origin': f'http://127.0.0.1:{self.port}', **extra}

    def test_serves_pages_and_lists_calibrations(self):
        status, body = self.request('GET', '/index.html')
        self.assertEqual(status, 200)
        self.assertIn(b'id="tp-status"', body)
        for path, expected in (('/index.html', 'no-cache'), ('/games.js', 'no-cache'), ('/app.css', 'no-cache'), ('/api/tool', 'no-store')):
            connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
            connection.request('GET', path)
            response = connection.getresponse(); response.read(); connection.close()
            self.assertEqual(response.getheader('Cache-Control'), expected, path)
        status, data = self.request('GET', '/api/calibrations')
        self.assertEqual(status, 200)
        self.assertIn('43', data['trackers'])

    def test_odd_paths_get_an_answer_and_stay_inside_webui(self):
        for path, expected in (('/index.html%00.png', 400), ('/../config.json', 404), ('/%2e%2e/HANDOFF.md', 404)):
            status, _ = self.request('GET', path)
            self.assertEqual(status, expected, path)

    def test_a_second_server_cannot_take_the_port(self):
        with self.assertRaises(OSError):
            server.make_server(self.port).server_close()

    def test_rejects_calls_other_sites_could_make(self):
        start = {'kind': 'calibrate', 'id': 76, 'flash': True}
        for headers in ({}, {'X-Aetherpose': '1', 'Origin': 'http://evil.example'},
                        self.page_headers(Host='evil.example:%d' % self.port, Origin='http://evil.example:%d' % self.port)):
            status, _ = self.request('POST', '/api/tool/start', start, headers)
            self.assertEqual(status, 403, headers)
        self.assertFalse(self.job.state()['running'])

    def test_validates_requests(self):
        for body in ({'kind': 'erase', 'id': 1}, {'kind': 'calibrate', 'id': 300}, {'kind': 'calibrate', 'id': '7'},
                     {'kind': 'calibrate', 'id': 1, 'flash': 'yes'}):
            status, _ = self.request('POST', '/api/tool/start', body, self.page_headers())
            self.assertEqual(status, 400, body)

    def test_runs_one_tool_and_reports_output(self):
        status, state = self.request('POST', '/api/tool/start', {'kind': 'calibrate', 'id': 76, 'flash': True},
                                     self.page_headers())
        self.assertEqual((status, state['running']), (202, True))
        status, _ = self.request('POST', '/api/tool/start', {'kind': 'flash', 'id': 76}, self.page_headers())
        self.assertEqual(status, 409)
        wait_done(self.job)
        status, state = self.request('GET', '/api/tool')
        self.assertEqual((status, state['exit_code']), (200, 0))
        self.assertIn('Fit: field 45.0 uT', state['lines'])


if __name__ == '__main__':
    unittest.main()
