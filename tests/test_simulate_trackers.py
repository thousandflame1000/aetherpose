"""tools/simulate_trackers.py sends packets the backend accepts: the firmware's 61-byte v2
format, the requested IDs and rate, finite readings and unit quaternions; when it stops, it
waits until the backend no longer lists its trackers."""
import asyncio
import contextlib
import importlib.util
import io
import json
import math
import socket
import threading
import types
import unittest
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('simulate_trackers', ROOT / 'tools' / 'simulate_trackers.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def capture(*args):
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(('127.0.0.1', 0))
    receiver.settimeout(0.5)
    port = receiver.getsockname()[1]
    sender = threading.Thread(target=lambda: tool.main([*args, '--port', str(port)]))
    with contextlib.redirect_stdout(io.StringIO()):
        sender.start()
        packets = []
        while True:
            try:
                packets.append(receiver.recvfrom(256)[0])
            except socket.timeout:
                if not sender.is_alive():
                    break
        sender.join()
    receiver.close()
    return packets


class FakeBackend(threading.Thread):
    """A backend websocket that lists trackers 240 and 241 until both are forgotten; with
    confirm=False it keeps listing them."""

    def __init__(self, confirm):
        super().__init__(daemon=True)
        self.confirm, self.forgotten = confirm, []
        self.ready, self.stopped = threading.Event(), threading.Event()

    def run(self):
        asyncio.run(self.serve())

    async def serve(self):
        async with websockets.serve(self.handler, '127.0.0.1', 0) as server:
            self.url = f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/ws'
            self.ready.set()
            while not self.stopped.is_set():
                await asyncio.sleep(0.05)

    async def handler(self, ws):
        listed = {'240': {}, '241': {}}
        await ws.send(json.dumps({'data': {'trackers': listed}}))
        async for raw in ws:
            self.forgotten.append(json.loads(raw)['ForgetTracker'])
            # The first answer still lists both, like a snapshot the backend sent mid-tick.
            done = self.confirm and len(self.forgotten) == 2
            await ws.send(json.dumps({'data': {'trackers': {'1': {}} if done else listed}}))


class SimulatorTests(unittest.TestCase):
    def test_packets_match_the_firmware_format(self):
        packets = capture('--count', '3', '--rate', '50', '--seconds', '0.6')
        self.assertTrue(packets)
        self.assertTrue(all(len(p) == 61 for p in packets))
        decoded = [tool.PACKET.unpack(p) for p in packets]
        self.assertEqual({d[1] for d in decoded}, {240, 241, 242})
        self.assertTrue(all(d[0] == 0x04 for d in decoded))
        per_tracker = len(decoded) / 3
        self.assertTrue(20 <= per_tracker <= 40, per_tracker)  # ~50 Hz for 0.6 s
        for d in decoded:
            values = d[3:9] + d[10:]
            self.assertTrue(all(math.isfinite(v) for v in values))
            self.assertAlmostEqual(sum(v * v for v in d[-4:]), 1.0, places=5)
            self.assertAlmostEqual(d[13], 1 / 50, places=6)

    def test_still_trackers_do_not_move(self):
        decoded = [tool.PACKET.unpack(p) for p in capture('--count', '1', '--still', '--seconds', '0.2')]
        self.assertTrue(decoded)
        self.assertTrue(all(d[-4:] == (0.0, 0.0, 0.0, 1.0) for d in decoded))

    def test_the_calibration_bow_tilts_only_the_chest_and_head(self):
        watcher = types.SimpleNamespace(bones={240: 2, 241: 32, 243: 4}, phase='bow')
        degrees = {i: math.degrees(tool.tracker_angle(i, 0.0, 'squat', watcher)) for i in (240, 241, 243)}
        self.assertEqual(degrees, {240: 45.0, 241: 0.0, 243: 45.0})
        bowed = tool.PACKET.unpack(tool.packet(240, 1, 100, tool.BOW))
        quat = bowed[-4:]
        self.assertAlmostEqual(math.degrees(2 * math.acos(quat[3])), 45.0, places=4)
        # Held still while tilted, the accelerometer reads gravity in the tilted axes: turned
        # back into the world by the tracker's orientation it is plain gravity, no motion.
        ax, ay, az = bowed[6:9]
        c, s = quat[3] ** 2 - quat[0] ** 2, 2 * quat[0] * quat[3]  # cos and sin of the tilt
        world = (ax, c * ay - s * az, s * ay + c * az)
        for got, want in zip(world, tool.GRAVITY):
            self.assertAlmostEqual(got, want, places=4)
        watcher.phase = 'tpose'
        self.assertEqual(tool.tracker_angle(240, 0.0, 'squat', watcher), 0.0, 'a T-pose is held still, even mid-squat')

    def test_a_squat_tilts_shins_and_torso_and_holds_at_the_bottom(self):
        first = tool.SQUAT_START + tool.SQUAT_STAND - tool.SQUAT_RAMP  # when the first squat begins
        self.assertTrue(all(tool.squat_depth(step / 100) == 0.0 for step in range(0, int(first * 100))),
                        'it stands first, long enough for a game to take the standing pose')
        depths = [tool.squat_depth(first + step / 100) for step in range(0, 700)]
        self.assertTrue(all(0.0 <= d <= 1.0 for d in depths))
        self.assertGreaterEqual(sum(d == 1.0 for d in depths) / 100 / 2, 0.8, 'each bottom is held long enough to score')
        watcher = types.SimpleNamespace(bones={244: 11, 240: 2, 241: 32}, phase='done')
        bottom = tool.SQUAT_START + tool.SQUAT_STAND + 0.5
        self.assertAlmostEqual(math.degrees(tool.tracker_angle(244, bottom, 'squat', watcher)), 60.0)
        self.assertAlmostEqual(math.degrees(tool.tracker_angle(240, bottom, 'squat', watcher)), 35.0)
        self.assertEqual(tool.tracker_angle(241, bottom, 'squat', watcher), 0.0)

    def test_forget_waits_until_the_backend_no_longer_lists_the_trackers(self):
        for confirm in (True, False):
            backend = FakeBackend(confirm)
            backend.start()
            backend.ready.wait(5)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                result = tool.forget([241, 240], backend.url, timeout=1.5)
            backend.stopped.set()
            backend.join(5)
            self.assertEqual(backend.forgotten, [240, 241])
            self.assertIs(result, confirm, output.getvalue())
            self.assertEqual('Could not' in output.getvalue(), not confirm)

    def test_the_headset_height_follows_the_legs(self):
        bottom = tool.SQUAT_START + tool.SQUAT_STAND + 0.5
        self.assertEqual(tool.head_height(0.0, 'squat', (0.45, 0.43)), tool.HEAD_HEIGHT)
        expected = tool.HEAD_HEIGHT - 0.45 * (1 - math.cos(math.radians(70))) - 0.43 * (1 - math.cos(math.radians(60)))
        self.assertAlmostEqual(tool.head_height(bottom, 'squat', (0.45, 0.43)), expected)
        self.assertEqual(tool.head_height(bottom, 'sway', (0.45, 0.43)), tool.HEAD_HEIGHT)
        watcher = types.SimpleNamespace(bones={246: 10}, phase='done')
        self.assertAlmostEqual(math.degrees(tool.tracker_angle(246, bottom, 'squat', watcher)), 70.0)
        datagram = tool.headset_datagram(1.234567)
        self.assertLess(len(datagram), 2048)  # the backend's buffer
        self.assertEqual(json.loads(datagram), {'head': {'pos': [0.0, 1.23457, 0.0], 'rot': [0.0, 0.0, 0.0, 1.0]},
                                                'left_hand': None, 'right_hand': None})
        for bad in (['--legs', '0.45'], ['--legs', '2,0.4'], ['--legs', 'a,b']):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                tool.main(bad)

    def test_out_of_range_options_are_refused(self):
        for args in (['--count', '0'], ['--first-id', '250', '--count', '10'], ['--rate', '0']):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                tool.main(args)


if __name__ == '__main__':
    unittest.main()
