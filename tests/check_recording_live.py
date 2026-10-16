"""Verify the running backend records from the page's Start settings into
recordings/, stops on request, and reports a file it cannot create.
Removes the file it made.
"""
import asyncio
import json
import os
import time
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]


async def wait_for(socket, accept, seconds=5):
    deadline = time.monotonic() + seconds
    while (remaining := deadline - time.monotonic()) > 0:
        message = json.loads(await asyncio.wait_for(socket.recv(), remaining))
        if message.get('type') == 'Snapshot' and accept(message['data']):
            return message['data']
    raise TimeoutError('backend did not reach the expected recording state')


async def main():
    name = f'live_check_{os.getpid()}.csv'
    path = ROOT / 'recordings' / name
    huge = ROOT / 'recordings' / f'live_check_{os.getpid()}_huge.csv'
    try:
        async with websockets.connect('ws://127.0.0.1:9009/ws') as socket:
            await socket.send(json.dumps({'SetRecorderConfig': {'enabled': True, 'filename': name,
                                                                'batch_size': 16, 'flush_interval_ms': 100}}))
            started = await wait_for(socket, lambda d: d['is_recording'])
            assert started['recorder_filename'] == f'recordings/{name}', started['recorder_filename']
            await socket.send(json.dumps('StopRecording'))
            await wait_for(socket, lambda d: not d['is_recording'])
            # A name Windows cannot create is reported instead of failing silently.
            await socket.send(json.dumps({'SetRecorderConfig': {'enabled': True, 'filename': 'bad?name.csv'}}))
            refused = await wait_for(socket, lambda d: (d.get('recorder_error') or '').startswith('open:'))
            assert not refused['is_recording'], refused
            await socket.send(json.dumps('StopRecording'))
            await wait_for(socket, lambda d: d.get('recorder_error') is None)
            # A batch far beyond the page's limit sizes a buffer: it must not take the backend down.
            await socket.send(json.dumps({'SetRecorderConfig': {'enabled': True, 'filename': huge.name,
                                                                'batch_size': 10 ** 12, 'flush_interval_ms': 0}}))
            await wait_for(socket, lambda d: d['is_recording'])
            await socket.send(json.dumps('StopRecording'))
            await wait_for(socket, lambda d: not d['is_recording'])
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        assert path.exists(), f'{path} was not written'
        header = path.read_text(encoding='utf-8').splitlines()[0]
        assert header.startswith('timestamp_ms,'), header
    finally:
        path.unlink(missing_ok=True)  # also when a later step failed
        huge.unlink(missing_ok=True)
    print(json.dumps({'ok': True, 'file': f'recordings/{name}', 'columns': header.count(',') + 1}))

if __name__ == '__main__':
    asyncio.run(main())
