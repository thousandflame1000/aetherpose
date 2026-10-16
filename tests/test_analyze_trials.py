"""Evidence integrity and denominators for manually annotated action trials."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools' / 'analyze_trials.py'
spec = importlib.util.spec_from_file_location('analyze_trials', TOOL)
analyzer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyzer)
HEADER = b'trial_id,expected,detected,action_at_s,detected_at_s\n'


class TrialEvidenceTests(unittest.TestCase):
    def test_known_confusion_and_signed_offsets(self):
        rows = analyzer.read_trials(HEADER + b'a,1,1,1,1.2\nb,1,1,3,2.9\nc,1,0,5,\nd,0,1,,6\ne,0,0,,\n')
        report = analyzer.summarize(rows, 'same-video')
        self.assertEqual(report['confusion'], {'tp': 2, 'fp': 1, 'fn': 1, 'tn': 1})
        self.assertAlmostEqual(report['precision'], 2 / 3)
        self.assertAlmostEqual(report['recall'], 2 / 3)
        self.assertAlmostEqual(report['f1'], 2 / 3)
        self.assertEqual(report['false_positive_rate'], .5)
        timing = report['observed_detection_offset_s']
        self.assertEqual(timing['negative_offsets'], 1)
        self.assertAlmostEqual(timing['median'], .05)
        self.assertAlmostEqual(timing['p95'], .185)
        self.assertFalse(report['automatic_hardware_acceptance'])

    def test_empty_denominators_and_missing_times_are_explicit(self):
        report = analyzer.summarize(analyzer.read_trials(HEADER + b'a,0,0,,\n'), 'unverified')
        self.assertIsNone(report['precision'])
        self.assertIsNone(report['recall'])
        self.assertIsNone(report['f1'])
        self.assertIsNone(report['observed_detection_offset_s']['median'])
        report = analyzer.summarize(analyzer.read_trials(HEADER + b'a,1,1,,\n'), 'unverified')
        self.assertEqual(report['observed_detection_offset_s']['true_positives_missing_paired_times'], 1)

    def test_duplicate_missing_and_ambiguous_rows_rejected(self):
        for raw in (HEADER, HEADER + b'a,1,1,,\na,0,0,,\n', HEADER + b'a,yes,1,,\n',
                    HEADER + b'a,1,1,\n', HEADER + b'a,1,1,,,extra\n',
                    b'trial_id,expected,detected\na,1,1\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                analyzer.read_trials(raw)

    def test_invalid_times_and_label_contradictions_rejected(self):
        for row in (b'a,1,1,nan,2\n', b'a,1,1,1,inf\n', b'a,1,1,-1,2\n',
                    b'a,0,1,1,2\n', b'a,1,0,1,2\n'):
            with self.subTest(row=row), self.assertRaises(ValueError):
                analyzer.read_trials(HEADER + row)

    def test_times_require_a_declared_common_clock(self):
        rows = analyzer.read_trials(HEADER + b'a,1,1,1,2\n')
        with self.assertRaisesRegex(ValueError, 'timebase'):
            analyzer.summarize(rows, 'unverified')

    def test_cli_retains_source_hash_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / 'trials.csv', Path(tmp) / 'result.json'
            source.write_bytes(HEADER + b'a,1,1,,\n')
            command = [sys.executable, str(TOOL), '--input', str(source), '--output', str(output),
                       '--run-id', 'TEST_ONLY', '--source', 'simulated-udp']
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            original = output.read_bytes()
            report = json.loads(original)
            self.assertEqual(report['declared_source'], 'simulated-udp')
            self.assertEqual(len(report['input_sha256']), 64)
            self.assertNotIn(str(source.parent), output.read_text())
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(output.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
