"""Verify real bridge message handlers without importing the inference model."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import patch


class Data:
    def __init__(self, value): self.value = value
    def tolist(self): return self.value


class Model:
    status = 'Streaming #7 LIVE 6/6'
    faces = Data([[0,1,2]])
    skin = {'template': [0, 0, 0], 'parents': [-1]}
    pose = types.SimpleNamespace(joints=Data([[0,0,0]] * 24), rotations=[1, 0, 0, 0, 1, 0, 0, 0, 1] * 24,
                                 translation=[0, 0, 0])
    def get_pose_if_new(self, version): return (None if version == 7 else self.pose), 7
    def get_frame_if_new(self, version):
        pose, current = self.get_pose_if_new(version)
        stats = getattr(self, 'get_runtime_stats', lambda: None)()
        return pose, current, self.status, stats
    def reset_origin(self): self.reset = True


class Client:
    def __init__(self, messages=()): self.messages = iter(messages); self.sent = []
    async def send(self, payload): self.sent.append(payload)
    def __aiter__(self): return self
    async def __anext__(self):
        try: return next(self.messages)
        except StopIteration: raise StopAsyncIteration


def load_bridge():
    model = types.ModuleType('transpose_runner'); model.TransPoseRunner = Model
    ws = types.ModuleType('ws_client'); ws.WsClient = lambda url: None
    websockets = types.ModuleType('websockets')
    websockets.exceptions = types.SimpleNamespace(ConnectionClosed=ConnectionError)
    path = Path(__file__).resolve().parents[1] / 'frontend/mesh_bridge.py'
    spec = importlib.util.spec_from_file_location('aether_bridge_test', path)
    bridge = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, transpose_runner=model, ws_client=ws, websockets=websockets):
        spec.loader.exec_module(bridge)
    return bridge


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_handshake_and_broadcast_use_one_consistent_frame_capture(self):
        bridge=load_bridge()
        class AtomicModel(Model):
            @property
            def status(self): raise AssertionError('separate status read can race')
            def get_pose_if_new(self, version): raise AssertionError('separate pose read can race')
            def get_frame_if_new(self, version):
                return self.pose,7,'Streaming #7 LIVE 6/6',{'pose_fps':30,'frame_ms':20,'device':'cpu'}
        bridge.tp=AtomicModel()
        handshake=Client()
        await bridge._handler(handshake)
        message=json.loads(handshake.sent[-1])
        self.assertEqual(message['joints_version'],7)
        self.assertEqual(message['status'],'Streaming #7 LIVE 6/6')
        self.assertEqual(message['runtime']['pose_fps'],30)
        broadcast=Client();bridge.CLIENTS.add(broadcast)
        calls=0
        async def tick(_):
            nonlocal calls
            calls+=1
            if calls>1: raise asyncio.CancelledError()
        bridge._next_frame=tick
        with self.assertRaises(asyncio.CancelledError): await bridge._broadcaster()
        self.assertEqual(json.loads(broadcast.sent[0])['status'],message['status'])

    async def test_idle_broadcaster_keeps_a_positive_wait(self):
        bridge=load_bridge()
        waits=[]
        async def tick(timeout):
            waits.append(timeout)
            if len(waits)>1: raise asyncio.CancelledError()
        bridge._next_frame=tick
        with self.assertRaises(asyncio.CancelledError): await bridge._broadcaster()
        self.assertGreater(waits[1],bridge.HEARTBEAT_SECONDS*.9)

    def test_only_local_pages_and_programs_may_connect(self):
        bridge = load_bridge()
        for origin in (None, 'http://127.0.0.1:18080', 'http://localhost', 'http://[::1]:18090'):
            self.assertTrue(bridge.origin_allowed(origin), origin)
        for origin in ('https://evil.example', 'http://127.0.0.1.evil.example', 'http://localhost.evil.example:80', 'null'):
            self.assertFalse(bridge.origin_allowed(origin), origin)
        class Connection:
            def respond(self, status, text): return status, text
        refused = bridge._check_origin(Connection(), types.SimpleNamespace(headers={'Origin': 'https://evil.example'}))
        self.assertEqual(refused[0], 403)
        self.assertIsNone(bridge._check_origin(Connection(), types.SimpleNamespace(headers={'Origin': 'http://127.0.0.1:18080'})))

    async def test_failed_sender_is_closed_so_browser_can_reconnect(self):
        bridge=load_bridge()
        class SlowClient(Client):
            async def send(self,payload): raise TimeoutError('blocked write')
            async def close(self,**kwargs): self.closed=kwargs
        slow=SlowClient(); healthy=Client()
        bridge.CLIENTS.update([slow,healthy])
        ticks=0
        async def next_tick(_):
            nonlocal ticks
            ticks+=1
            if ticks>1: raise asyncio.CancelledError()
        bridge._next_frame=next_tick
        bridge.asyncio=types.SimpleNamespace(wait_for=asyncio.wait_for,gather=asyncio.gather)
        with self.assertRaises(asyncio.CancelledError): await bridge._broadcaster()
        self.assertNotIn(slow,bridge.CLIENTS)
        self.assertIn(healthy,bridge.CLIENTS)
        self.assertEqual(slow.closed['code'],1013)
        self.assertEqual(len(healthy.sent),1)

    async def test_client_connected_before_model_ready_gets_status_then_topology(self):
        bridge = load_bridge()
        client = Client()
        bridge.CLIENTS.add(client)
        ticks = 0
        async def next_tick(_):
            nonlocal ticks
            ticks += 1
            if ticks > 2: raise asyncio.CancelledError()
        class ColdModel(Model):
            @property
            def status(self): return 'Loading model' if ticks<2 else 'Streaming #7 LIVE 6/6'
            @property
            def faces(self): return None if ticks<2 else Model.faces
            def get_pose_if_new(self, version):
                return (None,version) if ticks<2 else super().get_pose_if_new(version)
        bridge.tp = ColdModel()
        bridge._next_frame = next_tick
        bridge.asyncio = types.SimpleNamespace(wait_for=asyncio.wait_for,gather=asyncio.gather)
        bridge.time = types.SimpleNamespace(time=lambda:ticks)
        with self.assertRaises(asyncio.CancelledError): await bridge._broadcaster()
        self.assertEqual(len(client.sent),2)
        initial,ready = [json.loads(p) for p in client.sent]
        self.assertEqual(initial['status'],'Loading model')
        self.assertNotIn('faces',initial)
        self.assertEqual(ready['faces'],[[0,1,2]])
        self.assertEqual(ready['skin'],Model.skin,'the skinning data comes with the faces')
        self.assertEqual(len(ready['pose']['rotations']),216)
        self.assertEqual(ready['joints_version'],7)

    def test_backend_pump_uses_receipt_time_and_drops_cache_across_reconnect(self):
        bridge = load_bridge()
        tick = 0
        sent = set()
        trackers = {'76':{'last_update_ms':0}}
        frames = []
        def next_message():
            if tick in sent or tick not in (0,1,4): return None
            sent.add(tick)
            receipt = 8 if tick == 0 else 10+tick/60
            return {'type':'Snapshot','data':{'trackers':trackers}},receipt
        def next_tick(_):
            nonlocal tick
            tick += 1
            if tick == 5: raise StopIteration()
        bridge.ws_client = types.SimpleNamespace(get_update_timed=next_message,is_connected=lambda:tick!=2)
        bridge.tp = types.SimpleNamespace(push_frame=frames.append)
        bridge.time = types.SimpleNamespace(monotonic=lambda:10+tick/60,time=lambda:10+tick/60,perf_counter=lambda:10+tick/60,sleep=next_tick)
        bridge.CLIENTS.add(Client())  # a page is connected
        with self.assertRaises(StopIteration): bridge._pump_backend()
        self.assertEqual(frames[0],{}) # queued snapshot already too old
        self.assertEqual(frames[1],trackers)
        self.assertEqual(frames[2],{}) # disconnected
        self.assertEqual(frames[3],{}) # reconnect cannot revive old snapshot
        self.assertEqual(frames[4],trackers)

    def test_nothing_is_inferred_while_no_page_is_connected(self):
        bridge = load_bridge()
        frames, ticks = [], 0
        def next_tick(_):
            nonlocal ticks
            ticks += 1
            if ticks == 3: bridge.CLIENTS.add(Client())
            if ticks == 5: raise StopIteration()
        bridge.ws_client = types.SimpleNamespace(get_update_timed=lambda: None, is_connected=lambda: True)
        bridge.tp = types.SimpleNamespace(push_frame=frames.append)
        bridge.time = types.SimpleNamespace(monotonic=lambda: 10, time=lambda: 10, perf_counter=lambda: 10, sleep=next_tick)
        with self.assertRaises(StopIteration): bridge._pump_backend()
        self.assertEqual(len(frames), 2)  # only the ticks after the page connected

    async def test_a_background_tab_pauses_inference_unless_calibrating(self):
        bridge = load_bridge()
        phase = 'idle'
        bridge.tp.body_calibration_state = lambda: {'phase': phase}
        page = Client([json.dumps({'cmd': 'visibility', 'visible': False})])
        await bridge._handler(page)          # the page reports a background tab, then disconnects
        self.assertFalse(bridge.HIDDEN)      # a closed connection is forgotten
        bridge.CLIENTS.add(page); bridge.HIDDEN.add(page)
        self.assertFalse(bridge._inference_wanted())
        phase = 'bow'
        self.assertTrue(bridge._inference_wanted(), 'a running body calibration still gets its frames')
        phase = 'idle'
        bridge.HIDDEN.discard(page)
        self.assertTrue(bridge._inference_wanted())

    def test_tracker_cache_is_rejected_on_disconnect_or_snapshot_expiry(self):
        bridge = load_bridge()
        trackers = {'76':{'last_update_ms':0}}
        snapshot = {'trackers':trackers}
        self.assertEqual(bridge._fresh_trackers(snapshot,10,10.5,True)['76']['last_update_ms'],500)
        self.assertEqual(trackers['76']['last_update_ms'],0)
        self.assertEqual(bridge._fresh_trackers(snapshot,10,10.5,False),{})
        self.assertEqual(bridge._fresh_trackers(snapshot,10,11.1,True),{})
        self.assertEqual(bridge._fresh_trackers({'trackers':None},10,10.5,True),{})

    async def test_initial_packet_version_and_recenter(self):
        bridge = load_bridge()
        client = Client(['invalid json', '{"cmd":"reset_origin"}'])
        await bridge._handler(client)
        pose = next(json.loads(p) for p in client.sent if 'joints' in p)
        self.assertEqual(pose['joints_version'], 7)
        self.assertEqual(len(pose['joints']), 24)
        self.assertEqual(pose['pose'], {'rotations': Model.pose.rotations, 'translation': [0, 0, 0]})
        topology = json.loads(client.sent[0])
        self.assertEqual((topology['faces'], topology['skin']), ([[0,1,2]], Model.skin))
        self.assertTrue(all(isinstance(p, str) for p in client.sent), 'JSON only: the page skins the mesh itself')
        self.assertTrue(bridge.tp.reset)
        self.assertNotIn(client, bridge.CLIENTS)

    async def test_heartbeat_retains_original_pose_version(self):
        bridge = load_bridge()
        client = Client()
        bridge.CLIENTS.add(client)
        ticks = 0
        async def next_tick(_):
            nonlocal ticks
            ticks += 1
            if ticks > 2: raise asyncio.CancelledError()
        clock = types.SimpleNamespace(time=lambda: ticks)
        # Only replace dependencies used by this bridge; asyncio's send tasks
        # and wait_for keep their real scheduling behavior.
        scheduler = types.SimpleNamespace(wait_for=asyncio.wait_for, gather=asyncio.gather)
        with patch.object(bridge,'asyncio',scheduler), patch.object(bridge,'time',clock), patch.object(bridge,'_next_frame',next_tick):
            with self.assertRaises(asyncio.CancelledError): await bridge._broadcaster()
        self.assertEqual(len(client.sent), 2)
        packets = [json.loads(p) for p in client.sent]
        self.assertEqual([p['joints_version'] for p in packets], [7,7])
        self.assertEqual(packets[0]['joints'], packets[1]['joints'])


    async def test_a_new_pose_wakes_the_sender_at_once(self):
        bridge = load_bridge()
        loop = asyncio.get_running_loop()
        # The model signals from its own thread; the sender must not wait out a timer.
        start = loop.time()
        threading.Timer(0.05, lambda: loop.call_soon_threadsafe(bridge.NEW_FRAME.set)).start()
        await bridge._next_frame(5.0)
        self.assertLess(loop.time() - start, 1.0)
        self.assertFalse(bridge.NEW_FRAME.is_set())
        # Nothing new: it returns after the timeout, for the heartbeat.
        start = loop.time()
        await bridge._next_frame(0.1)
        self.assertGreaterEqual(loop.time() - start, 0.07)


    async def test_the_service_does_not_compress(self):
        bridge = load_bridge()
        served = {}
        class Started(Exception): pass
        def serve(handler, host, port, **options):
            served.update(options, host=host, port=port)
            raise Started()
        async def no_broadcast(): pass
        bridge.websockets.serve = serve
        bridge.ws_client = types.SimpleNamespace(start=lambda: None)
        bridge._broadcaster = no_broadcast
        idle_thread = types.SimpleNamespace(start=lambda: None)
        with patch.object(bridge, 'threading', types.SimpleNamespace(Thread=lambda **kwargs: idle_thread)):
            with self.assertRaises(Started): await bridge.main()
        self.assertEqual((served['host'], served['port']), ('127.0.0.1', 9010))
        self.assertIsNone(served['compression'])
        self.assertIs(served['process_request'], bridge._check_origin)


if __name__ == '__main__': unittest.main()
