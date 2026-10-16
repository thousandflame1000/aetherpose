"""
Receives the Rust backend's snapshots on a background thread and reconnects
when the backend restarts. mesh_bridge.py reads the newest messages from a
small thread-safe queue; it never sends anything to the backend.
"""

import asyncio
import json
import queue
import threading
import time

import websockets
import websockets.exceptions


class WsClient:
    def __init__(self, url: str, reconnect_delay: float = 2.0):
        self._url = url
        self._reconnect_delay = reconnect_delay
        self._incoming: queue.Queue = queue.Queue(maxsize=16)
        self._connected = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    # ── public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the background I/O thread."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="WsClient")
        self._thread.start()

    def get_update(self) -> dict | None:
        """Return the next server message (non-blocking), or None."""
        item = self.get_update_timed()
        return item[0] if item is not None else None

    def get_update_timed(self):
        """Return (message, monotonic receipt time) without refreshing old data."""
        try:
            return self._incoming.get_nowait()
        except queue.Empty:
            return None

    def is_connected(self) -> bool:
        return self._connected.is_set()

    # ── internals ─────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect_forever())

    async def _connect_forever(self) -> None:
        while True:
            try:
                async with websockets.connect(self._url) as ws:
                    self._connected.set()
                    await self._recv_loop(ws)  # returns when the backend closes the connection
            except (OSError, websockets.exceptions.WebSocketException):
                pass  # server not up yet or connection dropped
            finally:
                self._connected.clear()
            await asyncio.sleep(self._reconnect_delay)

    async def _recv_loop(self, ws) -> None:
        async for raw in ws:
            try:
                message = json.loads(raw)
                if not isinstance(message, dict): continue
                item = (message, time.monotonic())
                # Latest snapshots matter; a slow viewer must not accumulate
                # an unbounded backlog and later treat old IMU input as new.
                if self._incoming.full():
                    try: self._incoming.get_nowait()
                    except queue.Empty: pass
                self._incoming.put_nowait(item)
            except json.JSONDecodeError:
                pass
