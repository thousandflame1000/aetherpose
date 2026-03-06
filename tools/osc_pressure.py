#!/usr/bin/env python3
"""
Simple UDP OSC pressure-test script.
Sends sequential integer messages to an OSC address over UDP.

Usage:
    python tools/osc_pressure.py --ip 127.0.0.1 --port 9000 --address /test --rate 100 --count 1000

No external dependencies required.
"""
import socket
import struct
import time
import argparse


def pad_str(s: str) -> bytes:
    b = s.encode('utf-8') + b'\0'
    while len(b) % 4 != 0:
        b += b'\0'
    return b


def build_osc_int(address: str, i: int) -> bytes:
    # OSC: address, padded; type tag string (e.g. ",i"), padded; 32-bit big-endian int
    addr = pad_str(address)
    typetag = pad_str(',i')
    arg = struct.pack('>i', int(i))
    return addr + typetag + arg


def main():
    ap = argparse.ArgumentParser(description='OSC UDP pressure test')
    ap.add_argument('--ip', default='127.0.0.1', help='Target IP')
    ap.add_argument('--port', type=int, default=9000, help='Target UDP port')
    ap.add_argument('--address', default='/test', help='OSC address')
    ap.add_argument('--rate', type=float, default=100.0, help='Messages per second')
    ap.add_argument('--count', type=int, default=1000, help='Number of messages to send')
    ap.add_argument('--burst', action='store_true', help='Send as fast as possible (ignore rate)')
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (args.ip, args.port)

    interval = 1.0 / args.rate if args.rate > 0 else 0

    print(f"Sending {args.count} OSC messages to {target} at {args.rate} msg/s (burst={args.burst})")
    sent = 0
    start = time.time()
    try:
        for n in range(args.count):
            msg = build_osc_int(args.address, n)
            sock.sendto(msg, target)
            sent += 1
            if not args.burst and interval > 0:
                time.sleep(interval)
        elapsed = time.time() - start
        print(f"Done: sent={sent} elapsed={elapsed:.3f}s avg={sent/elapsed:.1f} msg/s")
    except KeyboardInterrupt:
        print(f"Interrupted, sent={sent}")
    finally:
        sock.close()


if __name__ == '__main__':
    main()
