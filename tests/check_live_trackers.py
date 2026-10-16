"""Live path with simulated trackers (tools/simulate_trackers.py --follow-calibration): six UDP
trackers are assigned to the six TransPose parts, the pose service reports LIVE 6/6 with finite
joints, a body calibration runs through T-pose and bow to done (the status then has no
"uncalibrated"), and when the simulator stops it leaves no tracker and no assignment behind.
"""
import asyncio
import contextlib
import importlib.util
import io
import json
import math
import threading
import time
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config.json'
spec = importlib.util.spec_from_file_location('simulate_trackers', ROOT / 'tools' / 'simulate_trackers.py')
simulator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulator)
IDS = [str(i) for i in range(240, 246)]


def saved_assignments():
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    return config.get('tracker_assignments'), config.get('unassigned_trackers', [])


async def watch_pose(seconds):
    """Waits for LIVE 6/6, runs a body calibration, and returns the statuses before and after."""
    status, joints, phases = None, None, []
    async with websockets.connect('ws://127.0.0.1:9010/', max_size=None) as ws:
        deadline = time.monotonic() + seconds
        before = None
        while time.monotonic() < deadline:
            raw = await asyncio.wait_for(ws.recv(), 5)
            if isinstance(raw, bytes):
                continue
            message = json.loads(raw)
            status = message.get('status', status)
            joints = message.get('joints', joints)
            calibration = message.get('calibration')
            if before is None and status and 'LIVE 6/6' in status and joints:
                before = status
                await ws.send(json.dumps({'cmd': 'calibrate_body'}))
            elif before is not None and calibration:
                if not phases or phases[-1] != calibration['phase']:
                    phases.append(calibration['phase'])
                if calibration['phase'] in ('done', 'failed') and len(phases) > 1 and 'uncalibrated' not in status:
                    break
    return before, status, joints, phases


async def backend_trackers():
    async with websockets.connect('ws://127.0.0.1:9009/ws') as ws:
        return set(json.loads(await asyncio.wait_for(ws.recv(), 5))['data']['trackers'])


def main():
    before = saved_assignments()
    run = threading.Thread(target=lambda: simulator.main(['--follow-calibration', '--seconds', '22']))
    with contextlib.redirect_stdout(io.StringIO()) as output:
        run.start()
        time.sleep(1.5)
        status_before, status, joints, phases = asyncio.run(watch_pose(19))
        run.join()
    # The pose service keeps a body calibration per tracker ID until it restarts, so these IDs may
    # already be calibrated from an earlier run; the run below must end calibrated either way.
    assert status_before and 'LIVE 6/6' in status_before, status_before
    assert phases and phases[-1] == 'done' and 'bow' in phases, phases
    assert status and 'LIVE 6/6' in status and 'uncalibrated' not in status, status
    assert joints and len(joints) == 24 and all(math.isfinite(v) for joint in joints for v in joint), 'joints'
    assert 'forgot the simulated trackers' in output.getvalue(), output.getvalue()
    leftover = asyncio.run(backend_trackers()) & set(IDS)
    assert not leftover, leftover
    deadline = time.monotonic() + 3  # config.json is saved shortly after a change
    while saved_assignments() != before and time.monotonic() < deadline:
        time.sleep(0.2)
    assert saved_assignments() == before, (saved_assignments(), before)
    print(json.dumps({'ok': True, 'before': status_before, 'calibration': phases, 'after': status, 'joints': len(joints),
                      'left_behind': sorted(leftover)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
