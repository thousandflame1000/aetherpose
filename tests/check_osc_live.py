"""Verify the running backend's OSC output uses the addresses VRChat accepts:
/tracking/trackers/1..8 and /head, each with position and rotation. Then a headset pose off to
one side (a Quest bridge datagram to UDP 9002) moves the body under it: /head is where the
headset is and the hips (/1) are straight below.

Listens where config.json points the OSC output. Skips (exit 0) when that is
not this machine or the port is taken, e.g. by VRChat itself.
"""
import json
import socket
import struct
import threading
import time
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / 'config.json'
HEADSET = (0.4, 1.6, -0.3)  # metres, Y up; OSC sends z negated
HEAD_ABOVE_HIPS = 0.75      # the backend skeleton's spine, neck and head, standing
EXPECTED = {f'/tracking/trackers/{name}/{kind}'
            for name in [*map(str, range(1, 9)), 'head'] for kind in ('position', 'rotation')}


def osc_message(packet):
    """(address, floats) of a single OSC message."""
    end = packet.index(b'\0')
    address = packet[:end].decode('ascii')
    offset = (end + 4) // 4 * 4
    tags_end = packet.index(b'\0', offset)
    tags = packet[offset + 1:tags_end].decode('ascii')
    offset = (tags_end + 4) // 4 * 4
    values = struct.unpack('>' + 'f' * len(tags), packet[offset:offset + 4 * len(tags)]) if set(tags) <= {'f'} else ()
    return address, tags, values


def main():
    config = json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.exists() else {}
    host, port = config.get('osc_ip', '127.0.0.1'), config.get('osc_port', 9000)
    if host not in ('127.0.0.1', 'localhost'):
        print(json.dumps({'ok': True, 'skipped': f'OSC goes to {host}:{port}'}))
        return
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        listener.bind(('127.0.0.1', port))
    except OSError as exc:
        print(json.dumps({'ok': True, 'skipped': f'port {port} in use ({exc.strerror})'}))
        return
    listener.settimeout(0.5)
    seen, bad, deadline = set(), set(), time.monotonic() + 3
    while time.monotonic() < deadline and seen != EXPECTED:
        try:
            address, tags, values = osc_message(listener.recv(4096))
        except socket.timeout:
            continue
        if address in EXPECTED and tags == 'fff' and all(v == v for v in values):
            seen.add(address)
        else:
            bad.add(f'{address} {tags}')
    assert not bad, f'unexpected OSC messages: {sorted(bad)}'
    assert seen == EXPECTED, f'missing OSC addresses: {sorted(EXPECTED - seen)}'
    head, hips = follow_headset(listener, config.get('floor_offset', 0.0))
    listener.close()
    print(json.dumps({'ok': True, 'addresses': len(seen), 'head': head, 'hips': hips}))


def follow_headset(listener, floor):
    stop = threading.Event()

    def send():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        datagram = json.dumps({'head': {'pos': list(HEADSET), 'rot': [0, 0, 0, 1]}}).encode()
        while not stop.is_set():
            sock.sendto(datagram, ('127.0.0.1', 9002))
            time.sleep(0.01)

    sender = threading.Thread(target=send, daemon=True)
    sender.start()
    latest, began = {}, time.monotonic()
    try:
        while time.monotonic() - began < 2:
            try:
                address, _, values = osc_message(listener.recv(4096))
            except socket.timeout:
                continue
            if time.monotonic() - began > 0.5:  # the backend has the headset by now
                latest[address] = values
    finally:
        stop.set()
        sender.join()
    head = latest['/tracking/trackers/head/position']
    hips = latest['/tracking/trackers/1/position']
    expected_head = (HEADSET[0], HEADSET[1] + floor, -HEADSET[2])
    assert all(abs(a - b) < 0.01 for a, b in zip(head, expected_head)), (head, expected_head)
    expected_hips = (HEADSET[0], HEADSET[1] + floor - HEAD_ABOVE_HIPS, -HEADSET[2])
    assert all(abs(a - b) < 0.05 for a, b in zip(hips, expected_hips)), (hips, expected_hips)
    return [round(v, 3) for v in head], [round(v, 3) for v in hips]


if __name__ == '__main__':
    main()
