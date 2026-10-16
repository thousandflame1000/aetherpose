"""Verify the running page server (webui/server.py) serves the page and its
local tool API, and refuses tool calls that do not come from the page.

Does not start a tool run.
"""
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:18080'


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=5) as response:
        return response.status, response.read()


def main():
    status, page = get('/')
    assert status == 200 and b'id="mag-tracker"' in page, 'page server does not serve the current page'
    status, body = get('/api/calibrations')
    trackers = json.loads(body)['trackers']
    assert status == 200 and isinstance(trackers, dict), body
    status, body = get('/api/tool')
    assert status == 200 and 'running' in json.loads(body), body
    request = urllib.request.Request(BASE + '/api/tool/start', method='POST', headers={'Content-Type': 'application/json'},
                                     data=json.dumps({'kind': 'calibrate', 'id': 1}).encode())
    try:
        urllib.request.urlopen(request, timeout=5)
        raise AssertionError('tool start without the page header was accepted')
    except urllib.error.HTTPError as error:
        assert error.code == 403, error.code
    print(json.dumps({'ok': True, 'firmware_mag_entries': sorted(int(k) for k in trackers)}))


if __name__ == '__main__':
    main()
