"""Stream simulated trackers to the backend over UDP, to try the live path without hardware.

    python tools/simulate_trackers.py                        # 6 trackers, IDs 240-245, 100 Hz, gentle sway
    python tools/simulate_trackers.py --follow-calibration   # still; holds a T-pose and bows when 「校正身體」 asks
    python tools/simulate_trackers.py --motion squat         # stands a few seconds, then squats every 3.5 s (Squat Rhythm)
    python tools/simulate_trackers.py --motion squat --headset   # plus a Quest headset whose height follows the legs
    python tools/simulate_trackers.py --count 3 --rate 60 --still

The packets use the firmware's v2 format (accelerometer, gyroscope, magnetometer and its
orientation quaternion) and go to UDP 9003, where Wi-Fi trackers send. The backend treats them
like real trackers: new IDs get the free body parts (the six TransPose parts first). The motions
tilt each tracker by the part it was given, which the simulator reads from the backend. When it
stops (Ctrl+C or --seconds) it asks the backend to forget its trackers, unless --keep is given.

With --headset it also sends a Quest headset pose (the bridge's JSON) to UDP 9002. Its height
follows the legs only: a squat bends thighs and shins (--legs gives their lengths), as the
backend's leg calibration assumes, so a seventh tracker on the left thigh makes that calibration
work too (the trackers get the TransPose parts first; assign the thigh on the 準備 tab).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import socket
import struct
import threading
import time

PACKET = struct.Struct('<BBH3f3fB3ff4f')  # firmware RawImuPacketV2, 61 bytes
PACKET_TYPE_IMU_V2 = 0x04
TORSO_BONES = {2, 4}            # chest, head: the calibration reads the bow from these
SHIN_BONES = {11, 21}
THIGH_BONES = {10, 20}
QUEST_PORT = 9002
HEAD_HEIGHT = 1.65              # metres: the simulated headset standing
BOW = math.radians(45)          # forward tilt of the chest and head trackers for the calibration bow
CALIBRATING_PHASES = ('tpose_ready', 'tpose', 'bow_ready', 'bow')
BOW_PHASES = ('bow_ready', 'bow')
# A squat TransPose recognises: shins 60° and torso 35° forward lower the head about 40 cm and
# the pelvis about 17 cm (Squat Rhythm asks for 18 and 12).
SQUAT_SHIN, SQUAT_TORSO = math.radians(60), math.radians(35)
SQUAT_THIGH = math.radians(70)  # thighs tilt (knees forward) further than the shins
SQUAT_STAND, SQUAT_DOWN, SQUAT_RAMP = 2.0, 1.5, 0.3   # seconds
SQUAT_START = 5.0  # extra seconds standing first: a game takes the standing pose before it counts
stop = threading.Event()  # set it to end main() from another thread (the checks do)


GRAVITY = (0.0, 0.0, 9.81)        # what a level tracker at rest reads, m/s^2
MAGNETIC_FIELD = (20.0, 5.0, -40.0)  # uT


def in_sensor_axes(vector, angle: float):
    """A world vector as a tracker tilted `angle` radians about its x axis measures it."""
    x, y, z = vector
    return x, y * math.cos(angle) + z * math.sin(angle), z * math.cos(angle) - y * math.sin(angle)


def packet(tracker_id: int, sequence: int, rate: float, angle: float) -> bytes:
    """One firmware packet for a tracker at rest, tilted `angle` radians about its x axis. Its
    accelerometer reads only gravity (in its own, tilted axes), so the pose service sees no
    linear acceleration from a tracker that holds still."""
    quat = (math.sin(angle / 2), 0.0, 0.0, math.cos(angle / 2))  # [x, y, z, w]
    return PACKET.pack(PACKET_TYPE_IMU_V2, tracker_id, sequence % 65536,
                       0.0, 0.0, 0.0,                         # gyroscope, rad/s
                       *in_sensor_axes(GRAVITY, angle),       # accelerometer, m/s^2
                       90,                                    # battery, %
                       *in_sensor_axes(MAGNETIC_FIELD, angle),  # magnetometer, uT
                       1.0 / rate, *quat)


def squat_depth(t: float) -> float:
    """0 standing, 1 at the bottom: stand a while, then stand, ramp down, hold, ramp up, repeat."""
    if t < SQUAT_START:
        return 0.0
    phase = (t - SQUAT_START) % (SQUAT_STAND + SQUAT_DOWN)
    if phase < SQUAT_STAND - SQUAT_RAMP:
        return 0.0
    if phase < SQUAT_STAND:
        return (phase - (SQUAT_STAND - SQUAT_RAMP)) / SQUAT_RAMP
    if phase < SQUAT_STAND + SQUAT_DOWN - SQUAT_RAMP:
        return 1.0
    return (SQUAT_STAND + SQUAT_DOWN - phase) / SQUAT_RAMP


def tracker_angle(tracker_id: int, t: float, motion: str, watcher: 'BodyWatcher | None') -> float:
    bone = watcher.bones.get(tracker_id) if watcher else None
    if watcher and watcher.phase in CALIBRATING_PHASES:
        # A body calibration: hold the T-pose still, bow the torso when asked.
        return BOW if watcher.phase in BOW_PHASES and bone in TORSO_BONES else 0.0
    if motion == 'squat':
        depth = squat_depth(t)
        tilt = {**dict.fromkeys(SHIN_BONES, SQUAT_SHIN), **dict.fromkeys(THIGH_BONES, SQUAT_THIGH),
                **dict.fromkeys(TORSO_BONES, SQUAT_TORSO)}
        return depth * tilt.get(bone, 0.0)
    if motion == 'still':
        return 0.0
    # sway: each tracker tilts a little about its own horizontal axis, at its own pace.
    return 0.25 * math.sin(t * (0.6 + 0.07 * (tracker_id % 7)) + tracker_id)


def head_height(t: float, motion: str, legs: tuple[float, float]) -> float:
    """The simulated headset's height: standing, lowered in a squat by exactly what the thighs'
    and shins' tilt lowers the hips (lengths `legs`, metres)."""
    if motion != 'squat':
        return HEAD_HEIGHT
    depth = squat_depth(t)
    thigh, shin = legs
    return HEAD_HEIGHT - thigh * (1 - math.cos(depth * SQUAT_THIGH)) - shin * (1 - math.cos(depth * SQUAT_SHIN))


def headset_datagram(height: float) -> bytes:
    """A Quest bridge datagram: the head level, facing ahead, at `height`; no hands."""
    head = {'pos': [0.0, round(height, 5), 0.0], 'rot': [0.0, 0.0, 0.0, 1.0]}
    return json.dumps({'head': head, 'left_hand': None, 'right_hand': None}).encode()


def leg_lengths(text: str) -> tuple[float, float]:
    try:
        thigh, shin = (float(value) for value in text.split(','))
    except ValueError:
        raise argparse.ArgumentTypeError('two lengths in metres, thigh and shin, like 0.45,0.43') from None
    if not (0.1 <= thigh <= 1.0 and 0.1 <= shin <= 1.0):
        raise argparse.ArgumentTypeError('each length must be 0.1-1.0 m')
    return thigh, shin


class BodyWatcher(threading.Thread):
    """Reads which body part each simulated tracker was given (backend) and the body
    calibration phase (pose service), so the motions tilt the right trackers."""

    def __init__(self, ids):
        super().__init__(daemon=True, name='body-watcher')
        self.ids, self.bones, self.phase = set(ids), {}, 'idle'

    def run(self):
        while True:
            try:
                asyncio.run(self.watch())
            except Exception:
                time.sleep(1)  # a service restarting: try again

    async def watch(self):
        import websockets

        async def calibration():
            async with websockets.connect('ws://127.0.0.1:9010/', max_size=None) as ws:
                # A program, not a page someone looks at: it should not keep inference running.
                await ws.send(json.dumps({'cmd': 'visibility', 'visible': False}))
                async for raw in ws:
                    if isinstance(raw, str):
                        state = json.loads(raw).get('calibration')
                        if state:
                            self.phase = state.get('phase', 'idle')

        async def assignments():
            async with websockets.connect('ws://127.0.0.1:9009/ws', max_size=None) as ws:
                async for raw in ws:
                    trackers = json.loads(raw).get('data', {}).get('trackers') or {}
                    self.bones = {int(key): tracker.get('assigned_bone') for key, tracker in trackers.items()
                                  if int(key) in self.ids}

        await asyncio.gather(calibration(), assignments())


def forget(ids, backend='ws://127.0.0.1:9009/ws', timeout=5.0) -> bool:
    """Asks the backend to drop the simulated trackers from its list and config.json, and
    waits until its tracker list no longer has them."""
    # Packets sent just before stopping may still wait in the backend's socket buffer; read
    # after the forget, they would bring the trackers (and their assignments) straight back.
    time.sleep(0.5)
    ids = set(ids)

    async def send():
        import websockets
        async with websockets.connect(backend, open_timeout=3, max_size=None) as ws:
            for tracker_id in sorted(ids):
                await ws.send(json.dumps({'ForgetTracker': tracker_id}))
            # The backend may take the commands over two of its ticks, and a snapshot sent in
            # between still lists some trackers: wait for one that has none of them.
            async for raw in ws:
                trackers = json.loads(raw).get('data', {}).get('trackers')
                if trackers is not None and not ids & {int(key) for key in trackers}:
                    return
            raise ConnectionError('the backend closed the connection')
    try:
        asyncio.run(asyncio.wait_for(send(), timeout))
        return True
    except Exception as exc:  # backend not running, websockets missing, no confirmation, ...
        print(f'Could not make the backend forget the simulated trackers ({exc or type(exc).__name__}).', flush=True)
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--count', type=int, default=6, help='number of trackers (1-16)')
    parser.add_argument('--first-id', type=int, default=240, help='ID of the first tracker')
    parser.add_argument('--rate', type=float, default=100.0, help='packets per second per tracker (1-200)')
    parser.add_argument('--motion', choices=('sway', 'still', 'squat'), default='sway')
    parser.add_argument('--still', action='store_true', help='same as --motion still')
    parser.add_argument('--follow-calibration', action='store_true',
                        help='stay still and bow the chest and head trackers when 「校正身體」 asks for the bow')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9003)
    parser.add_argument('--seconds', type=float, default=0.0, help='stop after this long (0: until Ctrl+C)')
    parser.add_argument('--keep', action='store_true', help='leave the trackers and their assignments when stopping')
    parser.add_argument('--headset', action='store_true', help='also send a Quest headset pose to UDP 9002')
    parser.add_argument('--legs', type=leg_lengths, default=(0.45, 0.43),
                        help='thigh and shin length in metres for the headset height in a squat (default 0.45,0.43)')
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 16:
        parser.error('--count must be 1-16')
    if not 0 <= args.first_id <= 255 - (args.count - 1):
        parser.error('the tracker IDs must stay within 0-255')
    if not 1 <= args.rate <= 200:
        parser.error('--rate must be 1-200')
    if args.still or (args.follow_calibration and args.motion == 'sway'):
        args.motion = 'still'  # a swaying T-pose would be refused as unsteady

    ids = range(args.first_id, args.first_id + args.count)
    # The motions and the calibration need to know which tracker is on which part.
    watcher = None
    if args.follow_calibration or args.motion == 'squat':
        watcher = BodyWatcher(ids)
        watcher.start()
    print(f'Sending {args.count} simulated trackers (IDs {ids[0]}-{ids[-1]}) at {args.rate:g} Hz to '
          f'{args.host}:{args.port}, motion: {args.motion}{", following 「校正身體」" if watcher else ""}'
          f'{f", headset to UDP {QUEST_PORT}" if args.headset else ""}. Ctrl+C stops.',
          flush=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    start = time.monotonic()
    sequence = 0
    try:
        while not stop.is_set() and (not args.seconds or time.monotonic() - start < args.seconds):
            t = time.monotonic() - start
            for tracker_id in ids:
                angle = tracker_angle(tracker_id, t, args.motion, watcher)
                sock.sendto(packet(tracker_id, sequence, args.rate, angle), (args.host, args.port))
            if args.headset:
                sock.sendto(headset_datagram(head_height(t, args.motion, args.legs)), (args.host, QUEST_PORT))
            sequence += 1
            # Keep the average rate even when a send or the clock is late.
            delay = start + sequence / args.rate - time.monotonic()
            if delay > 0:
                time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    print(f'Stopped after {sequence} packets per tracker.', flush=True)
    if not args.keep and args.port == 9003 and args.host in ('127.0.0.1', 'localhost') and forget(ids):
        print('The backend forgot the simulated trackers.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
