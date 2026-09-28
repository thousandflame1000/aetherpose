"""
mesh_bridge.py — headless service, no window, no GUI at all.

Runs the TransPose neural-net pose/mesh estimator (still PyTorch, still
Python — a browser can't run that) and re-broadcasts its output over its
own WebSocket so the web UI (webui/index.html) can render the SMPL body
mesh and the TP joint skeleton. Everything a person actually looks at is
the browser page; this is just the inference engine running in the
background, the same way the Rust backend runs in the background.

Usage:
    python mesh_bridge.py
"""

import asyncio
import json
import threading
import time

import websockets

from ws_client import WsClient
from transpose_runner import TransPoseRunner

WS_BACKEND  = "ws://127.0.0.1:9009/ws"
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 9010
BROADCAST_HZ = 30
HEARTBEAT_SECONDS = 0.5

tp        = TransPoseRunner()
ws_client = WsClient(WS_BACKEND)
CLIENTS: set = set()


def _pump_backend():
    """Drain the Rust backend's tracker snapshots into the TransPose model,
    the same way the native app's refresh loop used to."""
    snapshot = {}
    last_error_at = 0.0
    while True:
        try:
            msg = ws_client.get_update()
            while msg is not None:
                if isinstance(msg, dict) and msg.get("type") == "Snapshot":
                    snapshot = msg.get("data", {})
                msg = ws_client.get_update()
            tp.push_frame(snapshot.get("trackers", {}))
        except Exception as e:
            now = time.time()
            if now - last_error_at > 1.0:
                print(f"[mesh_bridge] backend pump error (continuing): {e}", flush=True)
                last_error_at = now
        time.sleep(1 / 60)


async def _broadcaster():
    """An uncaught exception here silently ends this asyncio task — the
    process keeps running (looks alive), but nothing gets broadcast to
    any client ever again. That failure mode is invisible from outside,
    so every tick is wrapped: one bad tick logs and moves on instead of
    killing the whole loop."""
    last_joints_v = 0
    last_verts_v  = 0
    last_heartbeat_at = 0.0
    while True:
        await asyncio.sleep(1 / BROADCAST_HZ)
        try:
            if not CLIENTS:
                continue

            joints, last_joints_v = tp.get_joints_if_new(last_joints_v)
            verts,  last_verts_v  = tp.get_latest_verts_if_new(last_verts_v)
            verts_bytes = None
            payload = {"status": tp.status}
            if joints is not None:
                payload["joints"] = joints.tolist()
            if verts is not None:
                verts_bytes = verts.astype("float32", copy=False).tobytes()
            if len(payload) <= 1 and verts_bytes is None:
                now = time.time()
                if now - last_heartbeat_at < HEARTBEAT_SECONDS:
                    continue
                joints, _ = tp.get_joints_if_new(-1)
                if joints is None:
                    continue
                payload["joints"] = joints.tolist()
                last_heartbeat_at = now
            else:
                last_heartbeat_at = time.time()

            msg = json.dumps(payload, separators=(",", ":")) if len(payload) > 1 else None
            # Iterate a snapshot, not the live set — CLIENTS can gain/lose
            # entries from _handler() while this loop awaits a send, and
            # iterating the set directly raises "Set changed size during
            # iteration" the moment that happens. Sending in parallel keeps
            # one slow or stale tab from throttling every other client.
            async def send_client(client):
                try:
                    if msg is not None:
                        await asyncio.wait_for(client.send(msg), timeout=0.25)
                    if verts_bytes is not None:
                        await asyncio.wait_for(client.send(verts_bytes), timeout=0.25)
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
        except Exception as e:
            print(f"[mesh_bridge] broadcast tick error (continuing): {e}")


async def _handler(websocket):
    CLIENTS.add(websocket)
    try:
        faces = tp.faces
        if faces is not None:
            await websocket.send(json.dumps({"faces": faces.tolist()}, separators=(",", ":")))
        joints, _ = tp.get_joints_if_new(-1)
        verts, _ = tp.get_latest_verts_if_new(-1)
        payload = {"status": tp.status}
        if joints is not None:
            payload["joints"] = joints.tolist()
        if len(payload) > 1:
            await websocket.send(json.dumps(payload, separators=(",", ":")))
        if verts is not None:
            await websocket.send(verts.astype("float32", copy=False).tobytes())
        async for raw in websocket:
            # The browser mostly listens; the only inbound command is a recenter request.
            try:
                if json.loads(raw).get("cmd") == "reset_origin":
                    tp.reset_origin()
                    print("[mesh_bridge] player position reset", flush=True)
            except (ValueError, AttributeError, TypeError):
                pass
    except websockets.exceptions.ConnectionClosed:
        pass  # normal on tab reload/close — not worth logging
    finally:
        CLIENTS.discard(websocket)


async def main():
    ws_client.start()
    threading.Thread(target=_pump_backend, daemon=True, name="pump-backend").start()
    asyncio.create_task(_broadcaster())
    async with websockets.serve(_handler, BRIDGE_HOST, BRIDGE_PORT):
        print(f"[mesh_bridge] listening on ws://{BRIDGE_HOST}:{BRIDGE_PORT}  "
              f"(reading trackers from {WS_BACKEND})", flush=True)
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
