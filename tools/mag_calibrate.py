"""Magnetometer hard/soft-iron calibration: python tools/mag_calibrate.py

Needs tools/imu_axes.py already running and BLE-connected (reads its /state).
Slowly tumble the tracker through every orientation, then Ctrl+C to print the
MAG_OFFSET_UT / MAG_SCALE lines for tracker_firmware.ino (native LSM9DS1 frame).
"""
from __future__ import annotations

import argparse
import json
import math
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8767/state")
    parser.add_argument("--seconds", type=float, help="Stop automatically after this long")
    args = parser.parse_args()

    lo, hi = [math.inf] * 3, [-math.inf] * 3
    samples, previous = 0, None
    deadline = time.monotonic() + args.seconds if args.seconds else math.inf
    print("Tumble the tracker slowly: every face up/down, full turns on each axis. Ctrl+C to finish.")
    try:
        while time.monotonic() < deadline:
            time.sleep(0.05)
            try:
                with urllib.request.urlopen(args.url, timeout=2) as response:
                    state = json.loads(response.read())
            except OSError as exc:
                print(f"\rviewer not reachable: {exc}", end="", flush=True)
                continue
            mag = state.get("mag")
            if mag is None or state.get("age_ms", 1e9) > 500:
                print(f"\r{state.get('status')}", end="", flush=True)
                continue
            if mag == previous:  # mag refreshes at ~20 Hz; skip repeats
                continue
            previous = mag
            samples += 1
            for i in range(3):
                lo[i], hi[i] = min(lo[i], mag[i]), max(hi[i], mag[i])
            span = [hi[i] - lo[i] for i in range(3)]
            print(f"\rsamples {samples:5d}  span x/y/z {span[0]:6.1f} {span[1]:6.1f} {span[2]:6.1f} uT"
                  f"  |raw| {math.hypot(*mag):5.1f}", end="", flush=True)
    except KeyboardInterrupt:
        print()

    if samples < 100:
        print("Too few samples; tumble longer and retry.")
        return
    span = [hi[i] - lo[i] for i in range(3)]
    if min(span) < 20:
        print("Tracker barely rotated (an axis spans < 20 uT); no calibration written. Retry while tumbling.")
        return
    if min(span) < 0.6 * max(span):
        print("WARNING: one axis has much less coverage; result may be poor. Tumble more evenly.")
    offset = [(hi[i] + lo[i]) / 2 for i in range(3)]
    mean_radius = sum(span) / 6
    scale = [mean_radius / (s / 2) for s in span]
    print(f"Estimated field strength ~{mean_radius:.1f} uT (Taiwan is roughly 45 uT).\n")
    print("Paste into tracker_firmware.ino:")
    print("const float MAG_OFFSET_UT[3] = {%.2ff, %.2ff, %.2ff};" % tuple(offset))
    print("const float MAG_SCALE[3] = {%.4ff, %.4ff, %.4ff};" % tuple(scale))


if __name__ == "__main__":
    main()
