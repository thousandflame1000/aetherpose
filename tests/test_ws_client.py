"""Real local WebSocket regression: normal close must reconnect an idle client."""
import asyncio
import importlib.util
import json
from pathlib import Path
import unittest
import types
from unittest.mock import patch

import websockets

spec = importlib.util.spec_from_file_location('aether_ws_client_test',
    Path(__file__).resolve().parents[1] / 'frontend/ws_client.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_consumer_keeps_bounded_recent_messages_and_receipt_times(self):
        class Stream:
            def __init__(self): self.index = -1
            def __aiter__(self): return self
            async def __anext__(self):
                self.index += 1
                if self.index >= 100: raise StopAsyncIteration
                return json.dumps({'type':'Snapshot','data':{'packet_count':self.index}})
        client = module.WsClient('ws://unused')
        stream = Stream()
        clock = types.SimpleNamespace(monotonic=lambda:float(stream.index))
        with patch.object(module,'time',clock): await client._recv_loop(stream)
        self.assertEqual(client._incoming.qsize(),16)
        first, received_at = client.get_update_timed()
        self.assertEqual(first['data']['packet_count'],84)
        self.assertEqual(received_at,84)
        latest = None
        while (item := client.get_update_timed()) is not None: latest = item
        self.assertEqual(latest[0]['data']['packet_count'],99)
        self.assertEqual(latest[1],99)

    async def test_normal_close_reconnects_and_clears_the_connected_flag(self):
        connected_again = asyncio.Event()
        hold_second = asyncio.Event()
        connection_count = 0

        async def server_handler(socket):
            nonlocal connection_count
            connection_count += 1
            await socket.send(json.dumps({'type':'Snapshot','data':{'packet_count':connection_count}}))
            if connection_count == 1:
                await socket.close()
            else:
                connected_again.set()
                await hold_second.wait()

        async with websockets.serve(server_handler,'127.0.0.1',0) as server:
            port = server.sockets[0].getsockname()[1]
            client = module.WsClient(f'ws://127.0.0.1:{port}',reconnect_delay=.05)
            task = asyncio.create_task(client._connect_forever())
            try:
                await asyncio.wait_for(connected_again.wait(),2)
                for _ in range(50):
                    if client.is_connected(): break
                    await asyncio.sleep(.01)
                self.assertTrue(client.is_connected())
                self.assertEqual(client.get_update()['data']['packet_count'],1)
                # Give recv_loop time to deliver the second connection's data.
                message = None
                for _ in range(50):
                    message = client.get_update()
                    if message: break
                    await asyncio.sleep(.01)
                self.assertEqual(message['data']['packet_count'],2)
            finally:
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)
                hold_second.set()
            self.assertFalse(client.is_connected())


if __name__ == '__main__': unittest.main()
