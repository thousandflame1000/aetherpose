"""Headset path with simulated input (tools/simulate_trackers.py --headset --motion squat): Quest
bridge datagrams to UDP 9002 reach the backend (a fresh headset age, the IK head at the headset's
height), a leg calibration over the simulated squats finds the thigh/shin ratio the simulated legs
were given, SetLegRatio puts the saved ratio back, and once the simulator stops the headset counts
as gone. Then drift compensation turns a hips tracker that drifted 30 degrees toward the headset's
heading. No tracker or setting is left behind.
"""
import asyncio
import contextlib
import importlib.util
import io
import json
import math
import socket
import threading
import time
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config.json'
spec = importlib.util.spec_from_file_location('simulate_trackers', ROOT / 'tools' / 'simulate_trackers.py')
simulator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulator)
RATIO = 1.25        # thigh/shin of the simulated legs; the backend's default is 0.9
THIGH_TRACKER = 246  # the seventh tracker; the first six take the TransPose parts


async def next_snapshot(ws, accept=lambda data: True, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if message.get('type') == 'Snapshot' and accept(message['data']):
            return message['data']
    raise AssertionError('no matching snapshot')


def left_leg_length(bones):
    position = {bone['id']: bone['pos'] for bone in bones}
    return math.dist(position[10], position[11]) + math.dist(position[11], position[12])


async def check(started):
    report = {}
    async with websockets.connect('ws://127.0.0.1:9009/ws', max_size=None) as ws:
        data = await next_snapshot(ws, lambda d: str(THIGH_TRACKER) in d['trackers'] and
                                   d['headset_age_ms'] is not None and d['headset_age_ms'] < 200, 15)
        report['headset_age_ms'] = data['headset_age_ms']
        await ws.send(json.dumps({'AssignTracker': [THIGH_TRACKER, 10]}))
        await next_snapshot(ws, lambda d: d['trackers'].get(str(THIGH_TRACKER), {}).get('assigned_bone') == 10)
        # Standing (the squats begin SQUAT_START + SQUAT_STAND - SQUAT_RAMP after the start):
        # the IK puts the head where the headset is.
        while time.monotonic() - started < 3.0:
            data = await next_snapshot(ws)
        head = next(bone['pos'] for bone in data['bones'] if bone['id'] == 4)
        report['head_height'] = round(head[1] - data['floor_offset'], 3)
        assert abs(report['head_height'] - simulator.HEAD_HEIGHT) < 0.05, report
        await ws.send(json.dumps('StartLegCalibration'))
        await next_snapshot(ws, lambda d: d['leg_calibrating'])
        # Two squats, then stop while standing again.
        first_squat = simulator.SQUAT_START + simulator.SQUAT_STAND - simulator.SQUAT_RAMP
        stop_at = first_squat + 2 * (simulator.SQUAT_STAND + simulator.SQUAT_DOWN) - 1.0
        while time.monotonic() - started < stop_at:
            data = await next_snapshot(ws)
        report['samples'] = data['leg_calibration_samples']
        await ws.send(json.dumps('StopLegCalibration'))
        data = await next_snapshot(ws, lambda d: not d['leg_calibrating'] and d['leg_calibration_result'])
        report['result'] = data['leg_calibration_result']
    return report


async def snapshot():
    async with websockets.connect('ws://127.0.0.1:9009/ws', max_size=None) as ws:
        return await next_snapshot(ws)


def hips_heading(data):
    """Degrees the hips are turned about the vertical, from the two hip joints."""
    position = {bone['id']: bone['pos'] for bone in data['bones']}
    across = (position[20][0] - position[10][0], position[20][2] - position[10][2])
    return math.degrees(math.atan2(-across[1], across[0]))


async def set_drift_correction(value):
    async with websockets.connect('ws://127.0.0.1:9009/ws', max_size=None) as ws:
        await ws.send(json.dumps({'SetDriftCorrection': value}))
        await next_snapshot(ws, lambda d: d['settings']['drift_correction'] == value)


DRIFT_TRACKER = 250


async def drift_phase():
    async with websockets.connect('ws://127.0.0.1:9009/ws', max_size=None) as ws:
        await next_snapshot(ws, lambda d: str(DRIFT_TRACKER) in d['trackers'])
        await ws.send(json.dumps({'AssignTracker': [DRIFT_TRACKER, 0]}))
        await next_snapshot(ws, lambda d: d['trackers'][str(DRIFT_TRACKER)].get('assigned_bone') == 0)
        began = time.monotonic()
        while time.monotonic() - began < 1.5:  # the hips settle on the drifted heading
            data = await next_snapshot(ws)
        start = hips_heading(data)
        await ws.send(json.dumps({'SetDriftCorrection': 1.0}))
        await next_snapshot(ws, lambda d: d['settings']['drift_correction'] == 1.0)
        began = time.monotonic()
        while time.monotonic() - began < 6:
            data = await next_snapshot(ws)
        return round(start, 1), round(hips_heading(data), 1)


def check_drift_compensation(drift_before):
    """A hips tracker whose heading drifted 30 degrees, a headset facing ahead: at full strength,
    drift compensation turns the hips most of the way within 6 s (about 10 s to converge)."""
    drift = math.radians(30)
    stop = threading.Event()

    def send():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        turned = (0.0, math.sin(drift / 2), 0.0, math.cos(drift / 2))
        sequence = 0
        while not stop.is_set():
            sock.sendto(simulator.PACKET.pack(simulator.PACKET_TYPE_IMU_V2, DRIFT_TRACKER, sequence % 65536, 0, 0, 0,
                                              0, 0, 9.81, 90, 20, 5, -40, 0.01, *turned), ('127.0.0.1', 9003))
            sock.sendto(simulator.headset_datagram(simulator.HEAD_HEIGHT), ('127.0.0.1', simulator.QUEST_PORT))
            sequence += 1
            time.sleep(0.01)

    sender = threading.Thread(target=send, daemon=True)
    sender.start()
    try:
        return asyncio.run(drift_phase())
    finally:
        # Put the setting back (confirmed) and drop the tracker, before anything else can fail.
        asyncio.run(set_drift_correction(drift_before))
        stop.set()
        sender.join()
        assert simulator.forget([DRIFT_TRACKER]), 'the drift tracker was not forgotten'


async def set_leg_ratio(value):
    async with websockets.connect('ws://127.0.0.1:9009/ws', max_size=None) as ws:
        await ws.send(json.dumps({'SetLegRatio': value}))
        return await next_snapshot(ws, lambda d: d['leg_ratio'] == value)


def main():
    config_before = CONFIG.read_text(encoding='utf-8')
    before = asyncio.run(snapshot())
    length = left_leg_length(before['bones'])
    legs = f'{length * RATIO / (1 + RATIO):.4f},{length / (1 + RATIO):.4f}'
    simulator.stop.clear()
    run = threading.Thread(target=lambda: simulator.main(
        ['--count', '7', '--motion', 'squat', '--headset', '--legs', legs, '--seconds', '60']))
    with contextlib.redirect_stdout(io.StringIO()) as output:
        started = time.monotonic()
        run.start()
        try:
            report = asyncio.run(check(started))
        finally:
            # Put the saved ratio back before anything else can fail.
            restored = asyncio.run(set_leg_ratio(before['leg_ratio']))
            simulator.stop.set()
            run.join()
    assert report['result'].startswith('done:'), report
    found = float(report['result'].split(':')[1])
    assert abs(found - RATIO) < 0.05, (found, RATIO, report)
    assert restored['leg_ratio'] == before['leg_ratio'], (restored['leg_ratio'], before['leg_ratio'])
    assert 'forgot the simulated trackers' in output.getvalue(), output.getvalue()
    time.sleep(0.6)  # the backend ignores headset input older than 500 ms
    after = asyncio.run(snapshot())
    assert after['headset_age_ms'] is None or after['headset_age_ms'] > 500, after['headset_age_ms']
    assert not {str(i) for i in range(240, 247)} & set(after['trackers']), sorted(after['trackers'])
    drift_start, drift_after = check_drift_compensation(before['settings']['drift_correction'])
    assert drift_start > 25 and drift_after < drift_start * 0.75, (drift_start, drift_after)
    assert str(DRIFT_TRACKER) not in asyncio.run(snapshot())['trackers']
    deadline = time.monotonic() + 3  # config.json is saved shortly after a change
    while CONFIG.read_text(encoding='utf-8') != config_before and time.monotonic() < deadline:
        time.sleep(0.2)
    assert CONFIG.read_text(encoding='utf-8') == config_before, 'config.json changed'
    print(json.dumps({'ok': True, **report, 'expected_ratio': RATIO, 'leg_length': round(length, 3),
                      'headset_age_after_ms': after['headset_age_ms'],
                      'hips_heading_drifted': drift_start, 'hips_heading_after_6s': drift_after}, ensure_ascii=False))


if __name__ == '__main__':
    main()
