"""Standalone firmware attitude viewer: python tools/imu_axes.py [--id 76].

BLE: pip install bleak. Existing backend: --ws ws://127.0.0.1:9009/ws
Offline UI check: --demo. No host filter, IK, smoothing, or firmware writes.
"""
from __future__ import annotations

import argparse
import asyncio
import binascii
import json
import math
import struct
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SERVICE = "19b10000-e8f2-537e-4f6c-d104768a1214"
CHARACTERISTIC = "19b10001-e8f2-537e-4f6c-d104768a1214"
PACKET = struct.Struct("<BBH6fB8f")  # 61 bytes, quat is x/y/z/w


def unit_quaternion(values):
    if not isinstance(values, (list, tuple)) or len(values) != 4:
        raise ValueError("Missing quaternion")
    q = [float(x) for x in values]
    norm = math.hypot(*q)
    if not math.isfinite(norm) or norm < 1e-6:
        raise ValueError("Invalid quaternion")
    return [x / norm for x in q]


class FrameDecoder:
    """Recover framed v2 packets across split/coalesced BLE notifications."""
    def __init__(self):
        self.buffer = bytearray()
        self.errors = 0

    def feed(self, data):
        self.buffer.extend(data)
        packets = []
        while len(self.buffer) >= 3:
            if self.buffer[:3] != b"\xaa\x55\x3d":
                del self.buffer[0]
                continue
            if len(self.buffer) < 66:
                break
            payload = self.buffer[3:64]
            crc = int.from_bytes(self.buffer[64:66], "little")
            if binascii.crc_hqx(payload, 0xFFFF) != crc:
                self.errors += 1
                del self.buffer[0]
                continue
            del self.buffer[:66]
            v = PACKET.unpack(payload)
            try:
                if v[0] != 4 or v[9] > 100 or not 0 < v[13] <= 1:
                    raise ValueError("Invalid packet")
                if not all(math.isfinite(x) for x in (*v[3:9], *v[10:])):
                    raise ValueError("Non-finite sensor reading")
                packets.append(dict(id=v[1], sequence=v[2], gyro=v[3:6],
                                    accel=v[6:9], battery=v[9], mag=v[10:13],
                                    dt=v[13], quat=unit_quaternion(v[14:18])))
            except ValueError:
                self.errors += 1
        return packets


class LiveState:
    def __init__(self, source):
        self.lock = threading.Lock()
        self.status = "Waiting for data"
        self.source = source
        self.latest = None
        self.arrivals = deque()
        self.received = 0
        self.errors = 0

    def set_status(self, message):
        with self.lock:
            if message != self.status:
                print(message, flush=True)
            self.status = message

    def accept(self, packet, age=0):
        try:
            q = unit_quaternion(packet.get("quat"))
            if not math.isfinite(age) or age < 0:
                raise ValueError("Invalid age")
        except (ValueError, TypeError, OverflowError):
            with self.lock:
                self.errors += 1
            return
        now = time.monotonic()
        with self.lock:
            self.latest = dict(packet, quat=q, arrived=now - age)
            self.arrivals.append(now)
            self.received += 1

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            while self.arrivals and self.arrivals[0] < now - 1:
                self.arrivals.popleft()
            result = dict(status=self.status, source=self.source,
                          received=self.received, errors=self.errors, hz=len(self.arrivals))
            if self.latest is not None:
                result.update(self.latest)
                result["age_ms"] = round((now - result.pop("arrived")) * 1000)
            return result


async def ble_source(args, state, stop):
    from bleak import BleakClient, BleakScanner
    while not stop.is_set():
        try:
            state.set_status("Scanning BLE…")
            devices = await BleakScanner.discover(timeout=5, return_adv=True)
            candidates = []
            for device, adv in devices.values():
                name = adv.local_name or device.name or ""
                if args.address:
                    matches = device.address.casefold() == args.address.casefold()
                else:
                    matches = name.startswith("Aetherpose Tracker") or SERVICE in [s.lower() for s in adv.service_uuids]
                    if args.id is not None:
                        matches = matches and name == f"Aetherpose Tracker {args.id}"
                if matches:
                    candidates.append(device)
            if len(candidates) != 1:
                found = "; ".join(f"{d.name} [{d.address}]" for d in candidates)
                state.set_status("No tracker found; power on the IMU / close the other BLE app." if not candidates
                                 else f"Multiple trackers: {found}. Restart with --address ADDRESS or --id ID.")
                await asyncio.sleep(2)
                continue
            device = candidates[0]
            decoder = FrameDecoder()
            async with BleakClient(device, timeout=15) as client:
                def notify(_characteristic, data):
                    before = decoder.errors
                    for packet in decoder.feed(data):
                        if args.id is None or packet["id"] == args.id:
                            state.accept(packet)
                    with state.lock:
                        state.errors += decoder.errors - before
                await client.start_notify(CHARACTERISTIC, notify)
                state.set_status(f"BLE connected: {device.name} [{device.address}]")
                while client.is_connected and not stop.is_set():
                    await asyncio.sleep(0.1)
            state.set_status("BLE disconnected; reconnecting…")
        except Exception as exc:
            state.set_status(f"BLE error: {exc}")
            await asyncio.sleep(2)


async def ws_source(args, state, stop):
    import websockets
    while not stop.is_set():
        try:
            async with websockets.connect(args.ws) as ws:
                state.set_status("Backend connected; reading unmodified device rotation")
                previous = None
                while not stop.is_set():
                    try:
                        message = json.loads(await asyncio.wait_for(ws.recv(), 1))
                    except asyncio.TimeoutError:
                        continue
                    if message.get("type") != "Snapshot":
                        continue
                    trackers = message.get("data", {}).get("trackers", {})
                    choices = [v for v in trackers.values() if args.id is None or v["id"] == args.id]
                    if len(choices) != 1:
                        state.set_status("Select one tracker with --id ID. Available: " + ", ".join(trackers))
                        continue
                    t = choices[0]
                    key = (t["id"], t.get("received_packets"), t.get("last_sequence"))
                    if key == previous:
                        continue
                    previous = key
                    state.accept(dict(id=t["id"], sequence=t.get("last_sequence"),
                                      quat=t.get("rotation"), accel=t.get("accel"),
                                      mag=t.get("mag"), battery=t.get("battery")),
                                 age=float(t.get("last_update_ms", 0)) / 1000)
                    state.set_status(f"Backend tracker {t['id']}")
        except Exception as exc:
            state.set_status(f"Backend connection error: {exc}")
            await asyncio.sleep(2)


async def demo_source(_args, state, stop):
    state.set_status("DEMO — synthetic rotation, not a real IMU")
    started = time.monotonic()
    while not stop.is_set():
        t = time.monotonic() - started
        # Independent analytic unit quaternion, rotates about an oblique axis.
        h = t * 0.25
        k = math.sin(h) / math.sqrt(3)
        state.accept(dict(id=0, sequence=int(t*60) % 65536, quat=[k, k, k, math.cos(h)],
                          accel=[0, 0, 9.81], gyro=[0.5/math.sqrt(3)]*3,
                          mag=[20, 0, -40], battery=100))
        await asyncio.sleep(1/60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, help="Tracker ID printed by firmware")
    parser.add_argument("--address", help="Full BLE address (handles duplicate IDs)")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--ws", metavar="URL", help="Use existing Rust backend instead of BLE")
    source.add_argument("--demo", action="store_true", help="Synthetic data; no hardware access")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.id is not None and not 0 <= args.id <= 255:
        parser.error("--id must be 0..255")
    try:
        if args.ws:
            import websockets  # noqa: F401
        elif not args.demo:
            import bleak  # noqa: F401
    except ImportError:
        parser.error("Install the dependency: python -m pip install " + ("websockets" if args.ws else "bleak"))
    state = LiveState("DEMO" if args.demo else ("Backend" if args.ws else "Direct BLE"))
    stop = threading.Event()
    page = Path(__file__).with_suffix(".html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                body, content_type = page, "text/html; charset=utf-8"
            elif self.path == "/state":
                body = json.dumps(state.snapshot(), allow_nan=False).encode()
                content_type = "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    worker_fn = demo_source if args.demo else (ws_source if args.ws else ble_source)
    worker = threading.Thread(target=lambda: asyncio.run(worker_fn(args, state, stop)), daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{args.port}"
    print(f"IMU axes: {url}\nCtrl+C to exit.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        worker.join(timeout=6)


if __name__ == "__main__":
    main()
