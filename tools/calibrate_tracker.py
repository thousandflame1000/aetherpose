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
        return ["樣本沒有形成橢球：請把追蹤器轉過更多方向"]
    problems = []
    if n < MIN_SAMPLES:
        problems.append(f"只有 {n} 筆樣本（需要 {MIN_SAMPLES} 筆）")
    for axis, cov in zip("xyz", fit["coverage"]):
        if cov < MIN_COVERAGE:
            problems.append(f"{axis} 軸涵蓋率 {cov:.0%}（需要 {MIN_COVERAGE:.0%}）：請轉得更完整")
    lo, hi = FIELD_RANGE_UT
    if not lo <= fit["field"] <= hi:
        problems.append(f"擬合磁場 {fit['field']:.1f} uT 不在 {lo:.0f}–{hi:.0f} uT 之間")
    if fit["rel_rms"] > MAX_REL_RMS:
        problems.append(f"擬合殘差 {fit['rel_rms']:.1%}（上限 {MAX_REL_RMS:.0%}）："
                        "請遠離金屬與電子產品，並慢慢轉動")
    return problems


async def record(backend: str, tracker_id: int, max_seconds: float) -> np.ndarray:
    import websockets
    samples, previous = [], None
    last_report = 0.0
    async with websockets.connect(backend, max_size=None) as ws:
        print(f"已連線後端。請慢慢把追蹤器 {tracker_id} 轉過各個方向"
              f"（三軸涵蓋率達 {TARGET_COVERAGE:.0%} 自動停止，最多 {max_seconds:.0f} 秒）。")
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
                    print(f"\r  {len(samples):4d} 筆  繼續轉動…".ljust(78), end="", flush=True)
                    continue
                cov = fit["coverage"]
                print(f"\r  {len(samples):4d} 筆  涵蓋率 x {cov[0]:4.0%} y {cov[1]:4.0%} "
                      f"z {cov[2]:4.0%}  磁場 {fit['field']:5.1f} uT".ljust(78), end="", flush=True)
                if len(samples) >= MIN_SAMPLES and np.all(cov >= TARGET_COVERAGE):
                    break
    print()
    return np.array(samples)


def write_calibration(tracker_id: int, fit) -> None:
    text = FIRMWARE.read_text(encoding="utf-8")
    block = re.search(r"(const MagCalibration MAG_CALIBRATIONS\[\] = \{\n)(.*?)(\n\};)", text, re.S)
    if not block:
        sys.exit(f"在 {FIRMWARE} 找不到 MAG_CALIBRATIONS 校正表")
    o, s = fit["offset"], fit["scale"]
    entry = (f"  {{{tracker_id}, {{{o[0]:.2f}f, {o[1]:.2f}f, {o[2]:.2f}f}}, "
             f"{{{s[0]:.4f}f, {s[1]:.4f}f, {s[2]:.4f}f}}}},  "
             f"// {datetime.date.today()}, tools/calibrate_tracker.py, field {fit['field']:.1f} uT")
    lines = [l for l in block.group(2).split("\n") if not re.match(rf"\s*\{{{tracker_id},", l)]
    lines.append(entry)
    lines.sort(key=lambda l: int(re.match(r"\s*\{(\d+),", l).group(1)) if re.match(r"\s*\{(\d+),", l) else 0)
    text = text[:block.start(2)] + "\n".join(lines) + text[block.end(2):]
    FIRMWARE.write_text(text, encoding="utf-8", newline="\n")
    where = FIRMWARE.relative_to(ROOT) if FIRMWARE.is_relative_to(ROOT) else FIRMWARE
    print(f"已把追蹤器 {tracker_id} 的校正值寫入 {where}：\n{entry}")


def arduino_cli() -> str:
    local = ROOT / ".arduino-cli" / "arduino-cli.exe"
    found = str(local) if local.exists() else shutil.which("arduino-cli")
    if not found:
        sys.exit("找不到 arduino-cli（應在 .arduino-cli/arduino-cli.exe 或 PATH 中）")
    return found


def nano_port(cli: str) -> str | None:
    out = subprocess.run([cli, "board", "list"], capture_output=True, text=True).stdout
    return next((line.split()[0] for line in out.splitlines() if "Nano 33" in line), None)


def flash() -> str:
    cli = arduino_cli()
    port = nano_port(cli)
    if not port:
        sys.exit("USB 上沒有 Nano 33 BLE。校正值已儲存；插上追蹤器後按「只燒錄」（--flash-only）再燒一次。")
    print(f"正在編譯並透過 {port} 燒錄（開機做陀螺儀校正時請讓追蹤器保持靜止）…")
    build = subprocess.run([cli, "compile", "--fqbn", FQBN, str(SKETCH)], capture_output=True, text=True)
    if build.returncode != 0:
        sys.exit("編譯失敗：\n" + build.stdout[-2000:] + build.stderr[-2000:])
    for attempt in range(2):
        up = subprocess.run([cli, "upload", "--fqbn", FQBN, "-p", port, str(SKETCH)],
                            capture_output=True, text=True)
        if up.returncode == 0:
            break
        time.sleep(2)
        port = nano_port(cli) or port  # the bootloader can come up on another COM port
    else:
        sys.exit("燒錄失敗：\n" + (up.stdout + up.stderr)[-2000:])
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
    print("開機訊息：\n  " + "\n  ".join(lines or ["（沒有收到）"]))
    board = next((int(m.group(1)) for l in lines if (m := re.match(r"Tracker ID: (\d+)", l))), None)
    if board is None:
        print("讀不到追蹤器 ID，請看上方的開機訊息。")
    elif board != tracker_id:
        print(f"注意：USB 上的是追蹤器 {board}，不是 {tracker_id}。它的韌體現在也帶著 {tracker_id} 的校正值；"
              f"請把追蹤器 {tracker_id} 接上 USB 按「只燒錄」（--flash-only）才會生效。")
    elif any("Magnetometer: calibrated" in l for l in lines):
        print(f"追蹤器 {tracker_id}：磁力計已校正並啟用。")
    else:
        print(f"追蹤器 {tracker_id} 已開機，但沒有回報磁力計已啟用。")
    if any("Gyro calibration skipped" in l for l in lines):
        print("開機時追蹤器有移動，陀螺儀校正被略過：把它平放後按 RESET。")


def record_or_exit(backend: str, tracker_id: int, max_seconds: float) -> np.ndarray:
    try:
        return asyncio.run(record(backend, tracker_id, max_seconds))
    except OSError as exc:
        sys.exit(f"連不到後端 {backend}（{exc}）。\n"
                 "請先啟動：webui\\run.ps1，或 target\\release\\aetherpose.exe")


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
            sys.exit(f"沒有收到追蹤器 {args.id} 的磁力計資料（只有 {len(samples)} 筆）。"
                     "它有開機並連上後端嗎？")
        fit = fit_ellipsoid(samples)
        problems = quality_problems(fit, len(samples))
        if problems:
            sys.exit("校正結果不合格，沒有寫入：\n  - " + "\n  - ".join(problems))
        print(f"擬合結果：磁場 {fit['field']:.1f} uT，殘差 {fit['rel_rms']:.1%}，"
              f"涵蓋率 {', '.join(f'{c:.0%}' for c in fit['coverage'])}")
        write_calibration(args.id, fit)
    if not args.no_flash:
        verify(flash(), args.id)


if __name__ == "__main__":
    main()
