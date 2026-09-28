"""One-shot magnetometer calibration: record -> fit -> write firmware -> flash -> verify.

    python tools/calibrate_tracker.py --id 76

Needs the backend running (reads the tracker's raw magnetometer from
ws://127.0.0.1:9009/ws) and, for flashing, a tracker on USB. Any tracker on USB
is fine: the firmware looks its calibration up by ID, so one build carries every
board's values. Tumble the tracker slowly through every orientation until each
axis reaches ~85 % coverage; recording then stops by itself.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import math
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "src" / "skeleton" / "tracker_firmware"
FIRMWARE = SKETCH / "tracker_firmware.ino"
FQBN = "arduino:mbed_nano:nano33ble"

MIN_SAMPLES = 300
TARGET_COVERAGE = 0.85   # share of each axis' full diameter swept by the samples
MIN_COVERAGE = 0.60      # below this the fit is refused
FIELD_RANGE_UT = (20.0, 70.0)
MAX_REL_RMS = 0.06       # corrected samples must lie this close to one sphere


def fit_ellipsoid(samples: np.ndarray):
    """Axis-aligned ellipsoid fit: a x^2 + b y^2 + c z^2 + d x + e y + f z = 1.
    Unlike per-axis min/max it does not need every extreme to be reached."""
    design = np.column_stack([samples ** 2, samples])
    p, *_ = np.linalg.lstsq(design, np.ones(len(samples)), rcond=None)
    quad, lin = p[:3], p[3:]
    if np.any(quad <= 0):
        return None
    center = -lin / (2 * quad)
    radii = np.sqrt((1 + np.sum(quad * center ** 2)) / quad)
    field = float(radii.mean())
    scale = field / radii
    corrected = np.linalg.norm((samples - center) * scale, axis=1)
    rel_rms = float(np.sqrt(np.mean((corrected / field - 1) ** 2)))
    coverage = (samples.max(axis=0) - samples.min(axis=0)) / (2 * radii)
    return dict(offset=center, scale=scale, field=field, rel_rms=rel_rms, coverage=coverage)


def quality_problems(fit, n: int) -> list[str]:
    if fit is None:
        return ["samples do not form an ellipsoid; tumble through more orientations"]
    problems = []
    if n < MIN_SAMPLES:
        problems.append(f"only {n} samples (need {MIN_SAMPLES})")
    for axis, cov in zip("xyz", fit["coverage"]):
        if cov < MIN_COVERAGE:
            problems.append(f"{axis} axis covered {cov:.0%} (need {MIN_COVERAGE:.0%}): rotate it further")
    lo, hi = FIELD_RANGE_UT
    if not lo <= fit["field"] <= hi:
        problems.append(f"fitted field {fit['field']:.1f} uT outside {lo:.0f}-{hi:.0f} uT")
    if fit["rel_rms"] > MAX_REL_RMS:
        problems.append(f"fit residual {fit['rel_rms']:.1%} (max {MAX_REL_RMS:.0%}); "
                        "keep away from metal/electronics and move slowly")
    return problems


async def record(backend: str, tracker_id: int, max_seconds: float) -> np.ndarray:
    import websockets
    samples, previous = [], None
    last_report = 0.0
    async with websockets.connect(backend, max_size=None) as ws:
        print(f"Connected to backend. Tumble tracker {tracker_id} now "
              f"(stops at {TARGET_COVERAGE:.0%} coverage, max {max_seconds:.0f}s).")
        end = time.monotonic() + max_seconds
        while time.monotonic() < end:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 2))
            except asyncio.TimeoutError:
                continue
            if msg.get("type") != "Snapshot":
                continue
            tracker = next((t for t in msg.get("data", {}).get("trackers", {}).values()
                            if t.get("id") == tracker_id), None)
            if tracker is None or tracker.get("mag") is None:
                continue
            if float(tracker.get("last_update_ms", 0)) > 500:
                continue  # stale: tracker not streaming
            mag = tuple(float(v) for v in tracker["mag"])
            if mag == previous:
                continue  # the magnetometer only refreshes at ~20 Hz
            previous = mag
            samples.append(mag)
            now = time.monotonic()
            if now - last_report >= 1 and len(samples) >= 30:
                last_report = now
                fit = fit_ellipsoid(np.array(samples))
                if fit is None:
                    print(f"\r  {len(samples):4d} samples  keep tumbling...".ljust(78), end="", flush=True)
                    continue
                cov = fit["coverage"]
                print(f"\r  {len(samples):4d} samples  coverage x {cov[0]:4.0%} y {cov[1]:4.0%} "
                      f"z {cov[2]:4.0%}  field {fit['field']:5.1f} uT".ljust(78), end="", flush=True)
                if len(samples) >= MIN_SAMPLES and np.all(cov >= TARGET_COVERAGE):
                    break
    print()
    return np.array(samples)


def write_calibration(tracker_id: int, fit) -> None:
    text = FIRMWARE.read_text(encoding="utf-8")
    block = re.search(r"(const MagCalibration MAG_CALIBRATIONS\[\] = \{\n)(.*?)(\n\};)", text, re.S)
    if not block:
        sys.exit(f"MAG_CALIBRATIONS table not found in {FIRMWARE}")
    o, s = fit["offset"], fit["scale"]
    entry = (f"  {{{tracker_id}, {{{o[0]:.2f}f, {o[1]:.2f}f, {o[2]:.2f}f}}, "
             f"{{{s[0]:.4f}f, {s[1]:.4f}f, {s[2]:.4f}f}}}},  "
             f"// {datetime.date.today()}, tools/calibrate_tracker.py, field {fit['field']:.1f} uT")
    lines = [l for l in block.group(2).split("\n") if not re.match(rf"\s*\{{{tracker_id},", l)]
    lines.append(entry)
    lines.sort(key=lambda l: int(re.match(r"\s*\{(\d+),", l).group(1)) if re.match(r"\s*\{(\d+),", l) else 0)
    text = text[:block.start(2)] + "\n".join(lines) + text[block.end(2):]
    FIRMWARE.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote tracker {tracker_id} into {FIRMWARE.relative_to(ROOT)}:\n{entry}")


def arduino_cli() -> str:
    local = ROOT / ".arduino-cli" / "arduino-cli.exe"
    found = str(local) if local.exists() else shutil.which("arduino-cli")
    if not found:
        sys.exit("arduino-cli not found (expected .arduino-cli/arduino-cli.exe or on PATH)")
    return found


def nano_port(cli: str) -> str | None:
    out = subprocess.run([cli, "board", "list"], capture_output=True, text=True).stdout
    return next((line.split()[0] for line in out.splitlines() if "Nano 33" in line), None)


def flash() -> str:
    cli = arduino_cli()
    port = nano_port(cli)
    if not port:
        sys.exit("No Nano 33 BLE on USB. Calibration is saved; plug a tracker in and rerun with --flash-only.")
    print(f"Compiling and flashing via {port} (keep the tracker still for the boot gyro calibration)...")
    build = subprocess.run([cli, "compile", "--fqbn", FQBN, str(SKETCH)], capture_output=True, text=True)
    if build.returncode != 0:
        sys.exit("Compile failed:\n" + build.stdout[-2000:] + build.stderr[-2000:])
    for attempt in range(2):
        up = subprocess.run([cli, "upload", "--fqbn", FQBN, "-p", port, str(SKETCH)],
                            capture_output=True, text=True)
        if up.returncode == 0:
            break
        time.sleep(2)
        port = nano_port(cli) or port  # the bootloader can come up on another COM port
    else:
        sys.exit("Upload failed:\n" + (up.stdout + up.stderr)[-2000:])
    time.sleep(1)
    return nano_port(cli) or port


def boot_log(port: str, seconds: float = 10) -> list[str]:
    import serial
    deadline = time.monotonic() + 5
    while True:
        try:
            ser = serial.Serial(port, 115200, timeout=0.5)
            break
        except serial.SerialException:
            if time.monotonic() > deadline:
                return [f"(could not open {port})"]
            time.sleep(0.2)
    ser.dtr = True  # the sketch waits for a serial host before printing
    lines, end = [], time.monotonic() + seconds
    with ser:
        while time.monotonic() < end:
            line = ser.readline().decode("utf-8", "replace").strip()
            if line:
                lines.append(line)
    return lines


def verify(port: str, tracker_id: int) -> None:
    lines = boot_log(port)
    print("Boot log:\n  " + "\n  ".join(lines or ["(nothing received)"]))
    board = next((int(m.group(1)) for l in lines if (m := re.match(r"Tracker ID: (\d+)", l))), None)
    if board is None:
        print("Could not read the tracker ID; check the boot log above.")
    elif board != tracker_id:
        print(f"Note: the tracker on USB is {board}, not {tracker_id}. Its firmware now carries "
              f"{tracker_id}'s calibration too; flash tracker {tracker_id} with --flash-only to apply it.")
    elif any("Magnetometer: calibrated" in l for l in lines):
        print(f"Tracker {tracker_id}: magnetometer calibrated and enabled.")
    else:
        print(f"Tracker {tracker_id} booted but did not report the magnetometer as enabled.")
    if any("Gyro calibration skipped" in l for l in lines):
        print("Gyro calibration was skipped (tracker moved during boot): lay it flat and press RESET.")


def record_or_exit(backend: str, tracker_id: int, max_seconds: float) -> np.ndarray:
    try:
        return asyncio.run(record(backend, tracker_id, max_seconds))
    except OSError as exc:
        sys.exit(f"Backend not reachable at {backend} ({exc}).\n"
                 "Start it first: webui\\run.ps1, or target\\release\\aetherpose.exe")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--id", type=int, required=True, help="Tracker ID (last byte of its BLE MAC)")
    parser.add_argument("--seconds", type=float, default=120, help="Maximum recording time")
    parser.add_argument("--backend", default="ws://127.0.0.1:9009/ws")
    parser.add_argument("--no-flash", action="store_true", help="Only record and write the calibration")
    parser.add_argument("--flash-only", action="store_true", help="Skip recording; flash and verify")
    args = parser.parse_args()

    if not args.flash_only:
        samples = record_or_exit(args.backend, args.id, args.seconds)
        if len(samples) < 10:
            sys.exit(f"No magnetometer data from tracker {args.id} (got {len(samples)} samples). "
                     "Is it powered on and connected to the backend?")
        fit = fit_ellipsoid(samples)
        problems = quality_problems(fit, len(samples))
        if problems:
            sys.exit("Calibration rejected, nothing written:\n  - " + "\n  - ".join(problems))
        print(f"Fit: field {fit['field']:.1f} uT, residual {fit['rel_rms']:.1%}, "
              f"coverage {', '.join(f'{c:.0%}' for c in fit['coverage'])}")
        write_calibration(args.id, fit)
    if not args.no_flash:
        verify(flash(), args.id)


if __name__ == "__main__":
    main()
