"""
mesh_bridge.py — headless service, no window, no GUI at all.

Runs the TransPose neural-net pose estimator (still PyTorch, still
Python — a browser can't run that) and re-broadcasts its output over its
own WebSocket so the web UI (webui/index.html) can draw the TP joint
skeleton and skin the SMPL body mesh: the mesh's triangles and skinning
data go out once, then joint positions and rotations with every pose
(JSON only; no binary messages). Everything a person actually looks at is
the browser page; this is just the inference engine running in the
background, the same way the Rust backend runs in the background.

Usage:
    python mesh_bridge.py
"""

import asyncio
import http
import json
import re
import threading
import time

import websockets

from ws_client import WsClient
from transpose_runner import TransPoseRunner

WS_BACKEND  = "ws://127.0.0.1:9009/ws"
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 9010
HEARTBEAT_SECONDS = 0.5
SNAPSHOT_STALE_SECONDS = 1.0

tp        = TransPoseRunner()
ws_client = WsClient(WS_BACKEND)
CLIENTS: set = set()
HIDDEN: set = set()  # clients whose page is in a background browser tab
CALIBRATING_PHASES = ('tpose_ready', 'tpose', 'bow_ready', 'bow')
NEW_FRAME = asyncio.Event()  # set (from the model's thread) when a new pose is ready


def _inference_wanted():
    """Inference runs for a page someone can see, or while a body calibration runs (it
    needs the frames even if its page went to the background). Otherwise it would keep
    about two CPU cores busy for nobody."""
    clients = list(CLIENTS)
    if any(client not in HIDDEN for client in clients):
        return True
    try:
        return bool(clients) and tp.body_calibration_state().get('phase') in CALIBRATING_PHASES
    except Exception:
        return False


# Browsers let any web page open a WebSocket to localhost: only pages served from this
# machine may connect (same rule as the backend). No Origin header means a local program.
_LOCAL_ORIGIN = re.compile(r"http://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?")


def origin_allowed(origin):
    return origin is None or _LOCAL_ORIGIN.fullmatch(origin) is not None


def _check_origin(connection, request):
    origin = request.headers.get("Origin")
    if origin_allowed(origin):
        return None
    print(f"[mesh_bridge] refused a connection from origin {origin!r}", flush=True)
    return connection.respond(http.HTTPStatus.FORBIDDEN, "Forbidden origin\n")


def _fresh_trackers(snapshot, snapshot_at, now, connected):
    if not connected or now - snapshot_at > SNAPSHOT_STALE_SECONDS:
        return {}
    trackers = snapshot.get("trackers", {}) if isinstance(snapshot, dict) else {}
    if not isinstance(trackers, dict): return {}
    elapsed_ms = max(0, now - snapshot_at) * 1000
    result = {}
    for key, tracker in trackers.items():
        if not isinstance(tracker, dict): continue
        try: age = float(tracker.get('last_update_ms', 0))
        except (TypeError, ValueError, OverflowError): age = float('inf')
        result[key] = {**tracker, 'last_update_ms': age + elapsed_ms}
    return result


def _pump_backend():
    """Feed the newest backend tracker snapshot to the TransPose model 60 times
    a second, the rate it was trained on. The model takes every frame waiting
    since its last pass, so a slow inference catches up in one pass instead of
    skipping frames. Only while _inference_wanted()."""
    snapshot = {}
    snapshot_at = -float('inf')
    last_error_at = 0.0
    next_at = time.perf_counter()
    while True:
        try:
            item = ws_client.get_update_timed()
            while item is not None:
                msg, received_at = item
                if isinstance(msg, dict) and msg.get("type") == "Snapshot":
                    snapshot = msg.get("data", {})
                    snapshot_at = received_at
                item = ws_client.get_update_timed()
            connected = ws_client.is_connected()
            if not connected:
                snapshot = {}
                snapshot_at = -float('inf')
            if _inference_wanted():
                tp.push_frame(_fresh_trackers(snapshot, snapshot_at, time.monotonic(), connected))
        except Exception as e:
            now = time.time()
            if now - last_error_at > 1.0:
                print(f"[mesh_bridge] backend pump error (continuing): {e}", flush=True)
                last_error_at = now
        # A fixed schedule: sleeping 1/60 s after the work gave about 58 frames a second.
        next_at += 1 / 60
        now = time.perf_counter()
        if next_at < now - 0.1:
            next_at = now  # far behind (a busy machine): start the schedule afresh
        time.sleep(max(0.0, next_at - now))


async def _next_frame(timeout):
    """Waits until the model has a new pose, or `timeout` seconds. Sending each pose as
    it is made, not on a fixed 30 Hz sleep: on Windows, whose timers round to 15.6 ms, that
    sleep plus the sending sent about 17 poses a second while the model made about 50."""
    try:
        await asyncio.wait_for(NEW_FRAME.wait(), timeout)
    except asyncio.TimeoutError:
        pass
    NEW_FRAME.clear()


def _pose_fields(pose, version):
    """A pose for the page: joint positions for the games, rotations to skin the mesh with."""
    return {"joints": pose.joints.tolist(), "joints_version": version,
            "pose": {"rotations": pose.rotations, "translation": pose.translation}}


def _topology(faces):
    """The mesh's triangles and skinning data, sent once; the page then skins each pose itself."""
    return {"faces": faces.tolist(), "skin": tp.skin}


async def _broadcaster():
    """An uncaught exception here silently ends this asyncio task — the
    process keeps running (looks alive), but nothing gets broadcast to
    any client ever again. That failure mode is invisible from outside,
    so every tick is wrapped: one bad tick logs and moves on instead of
    killing the whole loop."""
    last_pose_v = 0
    last_faces = None
    last_heartbeat_at = 0.0
    while True:
        await _next_frame(max(0.0, last_heartbeat_at + HEARTBEAT_SECONDS - time.time()))
        try:
            if not CLIENTS:
                # Keep a positive heartbeat wait while idle instead of
                # repeatedly calling _next_frame(0) on an expired deadline.
                last_heartbeat_at = time.time()
                continue

            now = time.time()
            heartbeat_due = now - last_heartbeat_at >= HEARTBEAT_SECONDS
            pose, version, status, runtime_stats = tp.get_frame_if_new(-1 if heartbeat_due else last_pose_v)
            if pose is not None: last_pose_v = version
            payload = {"status": status}
            if runtime_stats is not None: payload['runtime'] = runtime_stats
            calibration = getattr(tp, 'body_calibration_state', None)
            if callable(calibration): payload['calibration'] = calibration()
            faces = tp.faces
            faces_changed = faces is not None and faces is not last_faces
            if faces_changed:
                # A browser can connect while the model is still loading.
                # Initial handler data is not enough: deliver topology as soon
                # as it becomes available (and if it later changes).
                payload.update(_topology(faces))
                last_faces = faces
            if pose is not None:
                payload.update(_pose_fields(pose, last_pose_v))
            elif not faces_changed and not heartbeat_due:
                continue
            if heartbeat_due or faces_changed: last_heartbeat_at = now

            msg = json.dumps(payload, separators=(",", ":"))
            # Iterate a snapshot, not the live set — CLIENTS can gain/lose
            # entries from _handler() while this loop awaits a send, and
            # iterating the set directly raises "Set changed size during
            # iteration" the moment that happens. Sending in parallel keeps
            # one slow or stale tab from throttling every other client.
            async def send_client(client):
                try:
                    await asyncio.wait_for(client.send(msg), timeout=0.25)
                    return None
                except Exception:
                    return client
            dead = [
                client for client in await asyncio.gather(
                    *(send_client(client) for client in list(CLIENTS))
                )
                if client is not None
            ]
            for client in dead:
                CLIENTS.discard(client)
                # A removed-but-open socket leaves the browser waiting forever.
                # Close it so the existing reconnect path can recover.
                try:
                    await asyncio.wait_for(client.close(code=1013, reason="Client fell behind; reconnect"), timeout=1)
                except Exception:
                    transport = getattr(client, "transport", None)
                    if transport is not None:
                        transport.abort()
        except Exception as e:
            print(f"[mesh_bridge] broadcast tick error (continuing): {e}")


async def _handler(websocket):
    CLIENTS.add(websocket)
    try:
        faces = tp.faces
        if faces is not None:
            await websocket.send(json.dumps(_topology(faces), separators=(",", ":")))
        pose, version, status, runtime_stats = tp.get_frame_if_new(-1)
        payload = {"status": status}
        if runtime_stats is not None: payload['runtime'] = runtime_stats
        if pose is not None:
            payload.update(_pose_fields(pose, version))
        await websocket.send(json.dumps(payload, separators=(",", ":")))
        async for raw in websocket:
            # The browser mostly listens; inbound commands: recenter, body calibration, visibility.
            try:
                message = json.loads(raw)
                command = message.get("cmd")
                if command == "visibility":
                    (HIDDEN.discard if message.get("visible", True) else HIDDEN.add)(websocket)
                elif command == "reset_origin":
                    tp.reset_origin()
                    print("[mesh_bridge] player position reset", flush=True)
                elif command == "calibrate_body":
                    tp.start_body_calibration()
                    print("[mesh_bridge] body calibration started", flush=True)
                elif command == "cancel_body_calibration":
                    tp.cancel_body_calibration()
            except (ValueError, AttributeError, TypeError):
                pass
    except websockets.exceptions.ConnectionClosed:
        pass  # normal on tab reload/close — not worth logging
    finally:
        CLIENTS.discard(websocket)
        HIDDEN.discard(websocket)


async def main():
    ws_client.start()
    loop = asyncio.get_running_loop()
    tp.on_new_frame = lambda: loop.call_soon_threadsafe(NEW_FRAME.set)
    threading.Thread(target=_pump_backend, daemon=True, name="pump-backend").start()
    asyncio.create_task(_broadcaster())
    # No permessage-deflate: the pages are on this machine, and compressing every pose and mesh
    # once per client took about a quarter of a core from the thread the model shares the GIL with.
    async with websockets.serve(_handler, BRIDGE_HOST, BRIDGE_PORT, process_request=_check_origin,
                                compression=None):
        print(f"[mesh_bridge] listening on ws://{BRIDGE_HOST}:{BRIDGE_PORT}  "
              f"(reading trackers from {WS_BACKEND})", flush=True)
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except OSError as e:  # typically the port is taken by another program
        print(f"[mesh_bridge] cannot listen on {BRIDGE_HOST}:{BRIDGE_PORT}: {e}", flush=True)
        raise SystemExit(1)
