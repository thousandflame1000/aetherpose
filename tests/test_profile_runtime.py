"""A profiler must drain poses even outside its timed observation phases."""
import asyncio
import importlib.util
import json
from pathlib import Path
import unittest

import websockets

spec = importlib.util.spec_from_file_location('profile_runtime', Path(__file__).resolve().parents[1] / 'tools/profile_runtime.py')
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class ObserverTests(unittest.IsolatedAsyncioTestCase):
    async def test_continuous_drain_phase_boundaries_and_task_cleanup(self):
        async def handler(socket):
            index = 0
            try:
                while True:
                    await socket.send(json.dumps({'joints_version': index, 'status': 'Streaming',
                                                   'runtime': {'frame_ms': 10, 'pose_fps': 100}}))
                    index += 1
                    await asyncio.sleep(.005)
            except websockets.exceptions.ConnectionClosed:
                pass
        async with websockets.serve(handler, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(f'ws://127.0.0.1:{port}', max_queue=1) as socket:
                async with profile.PoseObserver(socket) as observer:
                    async def wait_for_background_reads():
                        while len(observer.samples) < 10:
                            await asyncio.sleep(.005)
                    # No observe() running yet, as during browser startup.
                    await asyncio.wait_for(wait_for_background_reads(), 2)
                    previous = observer.samples[-1]['version']
                    result = await profile.observe(observer, .1)
                    self.assertTrue(result['samples'])
                    self.assertTrue(all(s['version'] > previous for s in result['samples']))
                    self.assertTrue(all(s['elapsed_s'] >= 0 for s in result['samples']))
                    self.assertIsNone(result['observed_pose_hz'], 'under two seconds is insufficient warm-up')
                self.assertTrue(observer.task.done())

    async def test_closed_connection_fails_instead_of_returning_a_green_phase(self):
        async def handler(socket):
            await socket.close()
        async with websockets.serve(handler, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(f'ws://127.0.0.1:{port}') as socket:
                async with profile.PoseObserver(socket) as observer:
                    with self.assertRaisesRegex(ConnectionError, 'closed'):
                        await profile.observe(observer, 1)


if __name__ == '__main__':
    unittest.main()
