"""Summarize manually annotated positive/negative action trials; never certify hardware.

CSV columns: trial_id,expected,detected,action_at_s,detected_at_s
Labels are 0/1. Optional times must share the declared video/synchronized clock.
One positive trial contains at most one intended action. Repeated detections
within a trial need a separate count audit; this binary analysis does not match events.
"""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re


COLUMNS = ['trial_id', 'expected', 'detected', 'action_at_s', 'detected_at_s']
SOURCES = ('physical-ble', 'physical-udp', 'simulated-udp', 'mixed')
TIMEBASES = ('unverified', 'same-video', 'synchronized')


def read_trials(raw):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
    if reader.fieldnames != COLUMNS:
        raise ValueError('CSV header must be: ' + ','.join(COLUMNS))
    rows, seen = [], set()
    for line, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f'Line {line}: wrong column count')
        row = {key: value.strip() for key, value in row.items()}
        trial_id = row['trial_id']
        if not trial_id or trial_id in seen:
            raise ValueError(f'Line {line}: empty or duplicate trial_id')
        seen.add(trial_id)
        if row['expected'] not in ('0', '1') or row['detected'] not in ('0', '1'):
            raise ValueError(f'Line {line}: expected/detected must be 0 or 1')
        expected, detected = int(row['expected']), int(row['detected'])
        trial = {'trial_id': trial_id, 'expected': expected, 'detected': detected}
        for name, present in (('action_at_s', expected), ('detected_at_s', detected)):
            value = row[name]
            if value and not present:
                raise ValueError(f'Line {line}: {name} contradicts its 0 label')
            try:
                number = float(value) if value else None
            except ValueError:
                raise ValueError(f'Line {line}: invalid {name}') from None
            if number is not None and (not math.isfinite(number) or number < 0):
                raise ValueError(f'Line {line}: {name} must be finite and nonnegative')
            trial[name] = number
        rows.append(trial)
    if not rows:
        raise ValueError('CSV has no trials')
    return rows


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def percentile(values, probability):
    """Linear interpolation at (n-1)*p, including the single-sample case."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize(rows, timebase):
    if timebase not in TIMEBASES:
        raise ValueError('Unknown timebase')
    tp = sum(row['expected'] == row['detected'] == 1 for row in rows)
    tn = sum(row['expected'] == row['detected'] == 0 for row in rows)
    fp = sum(row['expected'] == 0 and row['detected'] == 1 for row in rows)
    fn = sum(row['expected'] == 1 and row['detected'] == 0 for row in rows)
    timed = [row for row in rows if row['expected'] == row['detected'] == 1
             and row['action_at_s'] is not None and row['detected_at_s'] is not None]
    if timed and timebase == 'unverified':
        raise ValueError('Paired times require --timebase same-video or synchronized')
    delays = [row['detected_at_s'] - row['action_at_s'] for row in timed]
    return {
        'trials': len(rows), 'positive_trials': tp + fn, 'negative_trials': tn + fp,
        'confusion': {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn},
        'precision': ratio(tp, tp + fp), 'recall': ratio(tp, tp + fn),
        'f1': ratio(2 * tp, 2 * tp + fp + fn),
        'false_positive_rate': ratio(fp, fp + tn),
        'observed_detection_offset_s': {
            'timebase': timebase, 'paired_true_positives': len(timed),
            'true_positives_missing_paired_times': tp - len(timed),
            'median': percentile(delays, .5) if delays else None,
            'p95': percentile(delays, .95) if delays else None,
            'negative_offsets': sum(value < 0 for value in delays),
            'samples': [{'trial_id': row['trial_id'], 'offset_s': delay}
                        for row, delay in zip(timed, delays)],
            'percentile_method': 'linear interpolation at (n-1)*p',
        },
        'automatic_hardware_acceptance': False,
        'limitations': [
            'Labels, event matching and source are operator-declared, not independently verified.',
            'Results describe these annotated trials, not 3D pose accuracy or untested actions.',
            'Detection offsets include the action rule and observation method, not just inference latency.',
            'Negative offsets are retained for annotation/timing review, never clipped or discarded.',
            'Trial-level rates require a predeclared trial protocol; they are not continuous event recall.',
            'Repeated detections within a trial are not measured by binary labels; audit counts separately.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--source', choices=SOURCES, required=True)
    parser.add_argument('--timebase', choices=TIMEBASES, default='unverified')
    args = parser.parse_args()
    try:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', args.run_id):
            raise ValueError('run-id must be 1-80 letters/digits/underscore/dot/dash')
        raw = args.input.read_bytes()
        report = summarize(read_trials(raw), args.timebase)
        report.update({'schema_version': 1, 'run_id': args.run_id,
                       'declared_source': args.source, 'input_name': args.input.name,
                       'input_sha256': hashlib.sha256(raw).hexdigest(),
                       'analyzer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as out:
            json.dump(report, out, ensure_ascii=False, indent=2, allow_nan=False)
            out.write('\n')
        print(json.dumps({'output': str(args.output), 'trials': report['trials'],
                          'confusion': report['confusion'], 'automatic_hardware_acceptance': False}))
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        parser.exit(1, f'Trial analysis failed: {exc}\n')


if __name__ == '__main__':
    main()
