"""Read-only backend evidence capture. No assignment/calibration/config changes.

Snapshots are observations of counters, not individual packet arrival times.
Declared physical input is never certified from the LIVE label alone.
"""
import argparse
import asyncio
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BODY_BONES = [4, 2, 32, 42, 11, 21]


def command_output(command):
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=20)
        return {'exit_code': result.returncode, 'output': result.stdout.strip(),
                'error': result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'error': str(exc)}


def percentile(values, fraction):
    """Linear interpolation, same convention as NumPy's default percentile."""
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low = math.floor(index)
    return ordered[low] + (ordered[math.ceil(index)] - ordered[low]) * (index - low)


def source_fingerprints():
    """Include untracked implementation too: HEAD alone does not identify this worktree."""
    result = {}
    suffixes = {'.py', '.rs', '.ps1', '.js', '.cjs', '.ino', '.c', '.cpp', '.h',
                '.html', '.css', '.toml', '.lock'}
    candidates = list(ROOT.iterdir())
    for directory in ('src', 'frontend', 'webui', 'tools', 'tests'):
        candidates.extend((ROOT / directory).rglob('*'))
    for path in sorted(candidates):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        result[path.relative_to(ROOT).as_posix()] = digest.hexdigest()
    return result


def summarize(rows, tracker_ids, duration):
    result = {'observed_duration_s': duration, 'samples': len(rows), 'trackers': {},
              'automatic_hardware_acceptance': False,
              'limitations': ['Input kind is operator-declared; UDP can be simulated.',
                              'Counter rates use sampled snapshots, not raw packet timestamps.',
                              'Freshness is conservatively estimated between observations.',
                              'Calibration, pose accuracy and end-to-end latency are not measured.']}
    for tracker_id in tracker_ids:
        key = str(tracker_id)
        fresh_time = 0.0
        rates = []
        reset_count = 0
        transports = set()
        assigned_bones = set()
        anchor = None
        previous_count = None
        for index, row in enumerate(rows):
            tracker = row.get('trackers', {}).get(key)
            if tracker:
                transports.add(str(tracker.get('connection_type', 'unknown')).casefold())
                assigned_bones.add(tracker.get('assigned_bone'))
            interval_end = rows[index + 1]['elapsed_s'] if index + 1 < len(rows) else duration
            interval = max(0.0, interval_end - row['elapsed_s'])
            if tracker:
                # Snapshot age plus time since receipt; do not extend a fresh
                # sample through an unobserved outage as though packets continued.
                age = tracker.get('last_update_ms')
                received_at = row.get('snapshot_received_s')
                if isinstance(age, (int, float)) and age >= 0 and received_at is not None:
                    age_s = age / 1000 + max(0.0, row['elapsed_s'] - received_at)
                    fresh_time += min(interval, max(0.0, 0.5 - age_s))
                count = tracker.get('received_packets')
                if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                    if anchor is None:
                        anchor = (row['elapsed_s'], count)
                    elif previous_count is not None and count < previous_count:
                        reset_count += 1
                        anchor = (row['elapsed_s'], count)
                    elif row['elapsed_s'] - anchor[0] >= 1.0:
                        rates.append((count - anchor[1]) / (row['elapsed_s'] - anchor[0]))
                        anchor = (row['elapsed_s'], count)
                    previous_count = count
            else:
                # Absence is not a zero-valued counter. Do not bridge windows
                # over disappearance/reappearance of a tracker.
                anchor = None
                previous_count = None
        result['trackers'][key] = {
            'connection_types_observed': sorted(transports),
            'assigned_bones_observed': sorted(assigned_bones, key=lambda value: -1 if value is None else value),
            'fresh_time_fraction_lower_estimate': fresh_time / duration if duration > 0 else None,
            'counter_rate_hz_p5': percentile(rates, 0.05),
            'counter_rate_hz_median': percentile(rates, 0.5),
            'rate_windows': len(rates), 'counter_resets_observed': reset_count,
        }
    return result


def source_warnings(summary, tracker_ids, input_kind):
    warnings = []
    expected_transport = {'physical-ble': 'ble', 'physical-udp': 'udp', 'simulated-udp': 'udp'}.get(input_kind)
    for tracker_id, expected_bone in zip(tracker_ids, BODY_BONES):
        observed = summary['trackers'][str(tracker_id)]
        if observed['assigned_bones_observed'] != [expected_bone]:
            warnings.append(f'ID {tracker_id}: expected bone {expected_bone}, observed {observed["assigned_bones_observed"]}')
        if expected_transport and observed['connection_types_observed'] != [expected_transport]:
            warnings.append(f'ID {tracker_id}: declared {input_kind}, observed transports {observed["connection_types_observed"]}')
    return warnings


async def capture(uri, duration, interval, target):
    import websockets
    rows = []
    latest = None
    received_at = None
    error = None
    started = time.monotonic()
    async with websockets.connect(uri, max_size=4 * 1024 * 1024, open_timeout=5) as socket:
        started = time.monotonic()

        async def receive():
            nonlocal latest, received_at, error
            try:
                async for raw in socket:
                    message = json.loads(raw)
                    if message.get('type') == 'Snapshot':
                        latest = message['data']
                        received_at = time.monotonic() - started
            except Exception as exc:
                error = f'{type(exc).__name__}: {exc}'
            else:
                error = 'backend connection closed'

        task = asyncio.create_task(receive())
        try:
            with target.open('x', encoding='utf-8') as output:
                next_tick = started
                while time.monotonic() - started < duration:
                    elapsed = time.monotonic() - started
                    row = {'elapsed_s': elapsed, 'snapshot_received_s': received_at,
                           'connection_error': error,
                           'trackers': latest.get('trackers', {}) if latest else {},
                           'packet_count': latest.get('packet_count') if latest else None,
                           'ble_status': latest.get('ble_status') if latest else None}
                    output.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
                    output.flush()
                    rows.append(row)
                    # Snapshot pushes can stop when trackers stop. This read-only
                    # request also exposes the increasing age in that case.
                    if error is None:
                        try:
                            await socket.send(json.dumps('RequestSnapshot'))
                        except Exception as exc:
                            error = f'{type(exc).__name__}: {exc}'
                    next_tick += interval
                    await asyncio.sleep(max(0, min(next_tick - time.monotonic(),
                                                   duration - (time.monotonic() - started))))
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    return rows, time.monotonic() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=600)
    parser.add_argument('--interval', type=float, default=0.1)
    parser.add_argument('--ids', type=int, nargs=6, required=True,
                        help='head chest left-forearm right-forearm left-shin right-shin')
    parser.add_argument('--input-kind', required=True,
                        choices=['physical-ble', 'physical-udp', 'simulated-udp', 'mixed'])
    parser.add_argument('--note', default='', help='anonymous participant, firmware and calibration notes')
    parser.add_argument('--uri', default='ws://127.0.0.1:9009/ws')
    parser.add_argument('--output', type=Path, help='new directory; existing paths are refused')
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 1 <= args.seconds <= 86400:
        parser.error('--seconds must be finite and between 1 and 86400')
    if not math.isfinite(args.interval) or not 0.02 <= args.interval <= 1:
        parser.error('--interval must be finite and between 0.02 and 1')
    if len(set(args.ids)) != 6 or any(not 0 <= value <= 255 for value in args.ids):
        parser.error('--ids requires six distinct IDs between 0 and 255')
    now = datetime.now(timezone.utc)
    target = args.output or ROOT / 'experiments' / now.strftime('%Y%m%dT%H%M%S.%fZ')
    target.mkdir(parents=True, exist_ok=False)
    metadata = {'schema_version': 1, 'started_utc': now.isoformat(),
                'declared_input_kind': args.input_kind,
                'physical_input_verified_by_tool': False,
                'tracker_ids_in_body_order': args.ids, 'note': args.note,
                'planned_duration_s': args.seconds, 'sample_interval_s': args.interval,
                'uri': args.uri, 'python': sys.version, 'platform': platform.platform(),
                'git_head': command_output(['git', 'rev-parse', 'HEAD']),
                'git_status': command_output(['git', 'status', '--short']),
                'git_diff': command_output(['git', 'diff', '--no-ext-diff']),
                'source_sha256': source_fingerprints(),
                'packages': command_output([sys.executable, '-m', 'pip', 'freeze']),
                'config': json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))}
    (target / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        rows, duration = asyncio.run(capture(args.uri, args.seconds, args.interval, target / 'samples.jsonl'))
        summary = summarize(rows, args.ids, duration)
        summary['capture_completed'] = True
        summary['source_or_assignment_warnings'] = source_warnings(summary, args.ids, args.input_kind)
        if not any(sample['snapshot_received_s'] is not None for sample in rows):
            summary['capture_completed'] = False
            summary['error'] = 'No backend snapshots received'
    except (Exception, KeyboardInterrupt) as exc:
        summary = {'capture_completed': False, 'automatic_hardware_acceptance': False,
                   'error': f'{type(exc).__name__}: {exc}',
                   'note': 'Partial samples, if present, are retained. Do not treat this run as complete.'}
    (target / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Evidence: {target}\nCapture completed: {summary['capture_completed']}")
    return 0 if summary['capture_completed'] else 1


if __name__ == '__main__':
    sys.exit(main())
