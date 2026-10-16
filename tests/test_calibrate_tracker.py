"""tools/calibrate_tracker.py edits the firmware source: check the ellipsoid fit, the quality
gate that refuses a poor recording, and that writing the table changes only one tracker's line.

Run with the project Python environment (numpy required). Works on a copy of the firmware.
"""
import contextlib
import importlib.util
import io
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('calibrate_tracker', ROOT / 'tools' / 'calibrate_tracker.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def sphere_samples(offset, scale, field=45.0, n=600, seed=1):
    """Raw readings of a field of `field` uT whose correction is (raw - offset) * scale."""
    directions = np.random.default_rng(seed).normal(size=(n, 3))
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    return np.asarray(offset) + directions * field / np.asarray(scale)


class FitTests(unittest.TestCase):
    def test_the_fit_recovers_offset_and_relative_scale(self):
        offset, scale = np.array([25.7, 22.1, 10.0]), np.array([0.92, 1.11, 0.99])
        fit = tool.fit_ellipsoid(sphere_samples(offset, scale))
        np.testing.assert_allclose(fit['offset'], offset, atol=0.05)
        np.testing.assert_allclose(fit['scale'] / fit['scale'].mean(), scale / scale.mean(), atol=0.01)
        self.assertEqual(tool.quality_problems(fit, 600), [])

    def test_a_partial_rotation_is_refused(self):
        samples = sphere_samples(np.zeros(3), np.ones(3))
        cap = samples[samples[:, 2] > 20]  # the tracker was only tilted, never turned over
        self.assertTrue(tool.quality_problems(tool.fit_ellipsoid(cap), len(cap)))

    def test_too_few_samples_or_an_odd_field_are_refused(self):
        fit = tool.fit_ellipsoid(sphere_samples(np.zeros(3), np.ones(3), field=120.0))
        problems = tool.quality_problems(fit, 100)
        self.assertTrue(any('100' in p for p in problems), problems)
        self.assertTrue(any('uT' in p for p in problems), problems)


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.copy = Path(self.tmp.name) / 'tracker_firmware.ino'
        shutil.copy(tool.FIRMWARE, self.copy)
        self.original = self.copy.read_text(encoding='utf-8')
        self.saved, tool.FIRMWARE = tool.FIRMWARE, self.copy

    def tearDown(self):
        tool.FIRMWARE = self.saved
        self.tmp.cleanup()

    @staticmethod
    def split(text):
        """(before the table, the table, after it)."""
        start = text.index('MAG_CALIBRATIONS[] = {')
        end = text.index('};', start)
        return text[:start], text[start:end], text[end:]

    @staticmethod
    def ids(table):
        return [int(m) for m in re.findall(r'^\s*\{(\d+),', table, re.M)]

    def write(self, tracker_id, field=46.0):
        fit = dict(offset=np.array([1.0, -2.0, 3.0]), scale=np.array([1.0, 0.9, 1.1]), field=field)
        with contextlib.redirect_stdout(io.StringIO()):
            tool.write_calibration(tracker_id, fit)
        return self.copy.read_text(encoding='utf-8')

    def test_new_trackers_are_added_in_id_order_and_nothing_else_changes(self):
        self.write(200)
        text = self.write(7)
        before, table, after = self.split(text)
        old_before, old_table, old_after = self.split(self.original)
        self.assertEqual((before, after), (old_before, old_after))
        ids = self.ids(table)
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(set(ids), set(self.ids(old_table)) | {7, 200})

    def test_recalibrating_a_tracker_replaces_its_line(self):
        existing = self.ids(self.split(self.original)[1]) or [9]
        tracker_id = existing[0]
        self.write(tracker_id, field=44.0)
        table = self.split(self.write(tracker_id, field=50.0))[1]
        lines = [line for line in table.splitlines() if re.match(rf'\s*\{{{tracker_id},', line)]
        self.assertEqual(len(lines), 1, lines)
        self.assertIn('field 50.0 uT', lines[0])


if __name__ == '__main__':
    unittest.main()
