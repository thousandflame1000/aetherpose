"""Verify the running mesh_bridge reports body calibration and accepts the
start/cancel commands from the page. Cancels before any pose is captured.
"""
import asyncio
import json
import time

import websockets


async def next_calibration(socket, accept, seconds=5):
    deadline = time.monotonic() + seconds
    while (remaining := deadline - time.monotonic()) > 0:
        message = await asyncio.wait_for(socket.recv(), remaining)
        if isinstance(message, str):
            state = json.loads(message).get('calibration')
            if isinstance(state, dict) and accept(state):
                return state
    raise TimeoutError('no matching calibration state')


async def origin_rules(uri):
    """Pages from other sites must not reach the local services; the Aetherpose page may."""
    try:
        async with websockets.connect(uri, origin='https://evil.example', max_size=None):
            foreign_refused = False
    except websockets.exceptions.InvalidStatus as exc:
        foreign_refused = exc.response.status_code == 403
    async with websockets.connect(uri, origin='http://127.0.0.1:18080', max_size=None) as socket:
        page_allowed = bool(await asyncio.wait_for(socket.recv(), 10))
    return {'foreign_refused': foreign_refused, 'page_allowed': page_allowed}


async def main():
    async with websockets.connect('ws://127.0.0.1:9010', max_size=None) as socket:
        initial = await next_calibration(socket, lambda s: True)
        await socket.send(json.dumps({'cmd': 'calibrate_body'}))
        started = await next_calibration(socket, lambda s: s['phase'] == 'tpose_ready')
        assert 'T-pose' in started['message'] and started['seconds_left'] > 0, started
        await socket.send(json.dumps({'cmd': 'cancel_body_calibration'}))
        await next_calibration(socket, lambda s: s['phase'] in ('idle', 'done') and s['message'].startswith('已取消'))
    origins = await origin_rules('ws://127.0.0.1:9010')
    assert all(origins.values()), origins
    print(json.dumps({'ok': True, 'initial_phase': initial['phase'], 'calibrated_trackers': initial['trackers'], 'origins': origins}))


if __name__ == '__main__':
    asyncio.run(main())
