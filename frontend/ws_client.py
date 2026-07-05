"""
WebSocket client — runs in a background thread so Dear PyGui can stay on the
main thread.  Thread-safe queues bridge the two worlds.
"""

import asyncio
import json
import queue
import threading

import websockets
import websockets.exceptions


class WsClient:
    def __init__(self, url: str, reconnect_delay: float = 2.0):
        self._url = url
        self._reconnect_delay = reconnect_delay
        self._incoming: queue.Queue = queue.Queue()
        self._outgoing: queue.Queue = queue.Queue()
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
        try:
            return self._incoming.get_nowait()
        except queue.Empty:
            return None

    def send_command(self, cmd) -> None:
        """Enqueue a BackendCommand for delivery to the Rust backend."""
        self._outgoing.put(json.dumps(cmd))

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
                    await asyncio.gather(
                        self._recv_loop(ws),
                        self._send_loop(ws),
                    )
            except (OSError, websockets.exceptions.WebSocketException) as exc:
                pass  # server not up yet or connection dropped
            finally:
                self._connected.clear()
            await asyncio.sleep(self._reconnect_delay)

    async def _recv_loop(self, ws) -> None:
        async for raw in ws:
            try:
                self._incoming.put(json.loads(raw))
            except json.JSONDecodeError:
                pass

    async def _send_loop(self, ws) -> None:
        loop = asyncio.get_event_loop()
        while True:
            # Poll the outgoing queue without blocking the event loop.
            try:
                msg = self._outgoing.get_nowait()
                await ws.send(msg)
            except queue.Empty:
                await asyncio.sleep(0.01)
