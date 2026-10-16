"""Verify the running backend supplies state to new and reconnected clients,
reports its saved settings, saves a settings change to config.json, and
reports the headset and leg calibration state.

The settings round trip changes IK smoothness briefly and restores it. An
unusable OSC target is refused and the working one kept. The leg
calibration is started and stopped; without a headset it reports no_samples
and leaves the leg ratio unchanged.
"""
import asyncio
import json
import time
from pathlib import Path

import websockets

CONFIG = Path(__file__).resolve().parents[1] / 'config.json'
SETTINGS = {'ik_smoothness', 'prop_leg', 'prop_arm', 'prop_spine', 'drift_correction',
            'smoothing_min_cutoff', 'smoothing_beta', 'trajectory_integration_mode', 'osc_ip', 'osc_port',
            'zupt_enabled', 'zupt_window_size', 'zupt_accel_var_threshold', 'zupt_gyro_threshold',
            'serial_enabled', 'serial_port', 'serial_baud'}


async def next_snapshot(socket, accept=lambda data: True):
    deadline = time.monotonic() + 5
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('no matching Snapshot within 5 s')
        message = json.loads(await asyncio.wait_for(socket.recv(), remaining))
        if message.get('type') == 'Snapshot' and accept(message['data']):
            data = message['data']
            assert isinstance(data['trackers'], dict), data
            assert 'packet_count' in data, data
            assert SETTINGS <= set(data.get('settings', {})), data.get('settings')
            assert 'ble_status' in data, 'snapshot lacks ble_status'
            assert {'headset_age_ms', 'leg_calibrating', 'leg_calibration_samples', 'leg_calibration_result'} <= set(data),                 'snapshot lacks the headset or leg calibration state'
            assert 'config_warning' in data and data['config_warning'] is None, f"config.json problem: {data.get('config_warning')}"
            return data


async def snapshot():
    async with websockets.connect('ws://127.0.0.1:9009/ws') as socket:
        return await next_snapshot(socket)


async def settings_round_trip():
    async with websockets.connect('ws://127.0.0.1:9009/ws') as socket:
        original = (await next_snapshot(socket))['settings']['ik_smoothness']
        probe = round(original + (0.05 if original <= 0.5 else -0.05), 2)
        for value in (probe, original):
            await socket.send(json.dumps({'SetIkSmoothness': value}))
            await next_snapshot(socket, lambda d: abs(d['settings']['ik_smoothness'] - value) < 1e-4)
        # Out of range from another client: clamped to the slider's range, then restored.
        await socket.send(json.dumps({'SetIkSmoothness': 7.5}))
        await next_snapshot(socket, lambda d: abs(d['settings']['ik_smoothness'] - 1.0) < 1e-4)
        await socket.send(json.dumps({'SetIkSmoothness': original}))
        await next_snapshot(socket, lambda d: abs(d['settings']['ik_smoothness'] - original) < 1e-4)
    deadline = time.monotonic() + 3
    while True:
        saved = json.loads(CONFIG.read_text(encoding='utf-8'))['ik_smoothness']
        if abs(saved - original) < 1e-4:
            return original
        if time.monotonic() > deadline:
            raise AssertionError(f'config.json ik_smoothness {saved}, expected {original}')
        await asyncio.sleep(0.2)


async def shake_assign_round_trip():
    async with websockets.connect('ws://127.0.0.1:9009/ws') as socket:
        await next_snapshot(socket)
        await socket.send(json.dumps({'StartShakeAssign': 32}))
        await next_snapshot(socket, lambda d: d.get('pending_shake_bone') == 32)
        await socket.send(json.dumps('CancelShakeAssign'))
        await next_snapshot(socket, lambda d: d.get('pending_shake_bone') is None)
    return True


async def osc_target_refused():
    async with websockets.connect('ws://127.0.0.1:9009/ws') as socket:
        before = await next_snapshot(socket)
        settings = before['settings']
        await socket.send(json.dumps({'SetOscTarget': ['300.1.1.1', settings['osc_port']]}))
        refused = await next_snapshot(socket, lambda d: (d.get('osc_error') or '').startswith('300.1.1.1:'))
        assert refused['osc_active'] == before['osc_active'], refused
        assert refused['settings']['osc_ip'] == settings['osc_ip'], 'a refused target must not be saved'
        if before['osc_active']:
            await socket.send(json.dumps({'SetOscTarget': [settings['osc_ip'], settings['osc_port']]}))
            await next_snapshot(socket, lambda d: d.get('osc_error') is None)
    return refused['osc_error']


async def leg_calibration_round_trip():
    async with websockets.connect('ws://127.0.0.1:9009/ws') as socket:
        await next_snapshot(socket)
        await socket.send(json.dumps('StartLegCalibration'))
        await next_snapshot(socket, lambda d: d['leg_calibrating'] and d['leg_calibration_result'] is None)
        await socket.send(json.dumps('StopLegCalibration'))
        data = await next_snapshot(socket, lambda d: not d['leg_calibrating'] and d['leg_calibration_result'])
    if data['headset_age_ms'] is None:
        assert data['leg_calibration_result'] == 'no_samples', data['leg_calibration_result']
    return data['leg_calibration_result'], data['headset_age_ms']


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


async def malformed_commands_are_ignored():
    """Garbage and wrongly typed commands (none of which can apply) leave the backend answering."""
    garbage = ['{', '[]', 'null', '"Unknown"', 'x' * 5000, '{"SetIkSmoothness":}', '{"SetIkSmoothness":"high"}',
               '{"AssignTracker":[300,1]}', '{"SetOscTarget":["127.0.0.1",70000]}', '{"SetZuptEnabled":1}',
               '{"SetTrajectoryIntegrationMode":"bogus"}', '{"StartShakeAssign":{}}', '{"SetProportions":{"leg":1}}']
    async with websockets.connect('ws://127.0.0.1:9009/ws') as socket:
        for text in garbage:
            await socket.send(text)
        await socket.send(json.dumps('RequestSnapshot'))
        await next_snapshot(socket)
    return len(garbage)


async def main():
    for _ in range(3):
        data = await snapshot()
    restored = await settings_round_trip()
    leg_result, headset_age = await leg_calibration_round_trip()
    osc_refused = await osc_target_refused()
    shake_assign = await shake_assign_round_trip()
    origins = await origin_rules('ws://127.0.0.1:9009/ws')
    malformed = await malformed_commands_are_ignored()
    assert all(origins.values()), origins
    trackers = data['trackers']
    print(json.dumps({'ok': True, 'connections': 3, 'known_trackers': len(trackers),
                      'fresh_trackers': sum(isinstance(t.get('last_update_ms'), (int, float))
                                            and 0 <= t['last_update_ms'] <= 500
                                            for t in trackers.values()),
                      'settings_saved': True, 'ik_smoothness': restored, 'ble_status': data['ble_status'],
                      'headset_age_ms': headset_age, 'leg_calibration': leg_result, 'osc_refused': osc_refused,
                      'shake_assign': shake_assign, 'origins': origins,
                      'malformed_ignored': malformed}))


if __name__ == '__main__':
    asyncio.run(main())
