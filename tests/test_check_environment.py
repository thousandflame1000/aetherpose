"""Preflight must expose missing or divergent dependencies, not silently pass."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_environment', ROOT / 'tools/check_environment.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class PreflightTests(unittest.TestCase):
    def test_lock_normalization_and_conflicting_aliases(self):
        self.assertEqual(preflight.locked_versions('# comment\n--extra-index-url https://example.invalid\nSome_Name==1.0+cpu\n'),
                         {'some-name': '1.0+cpu'})
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            preflight.locked_versions('some_name==1\nsome-name==2')

    def test_unpinned_or_empty_lock_cannot_report_success(self):
        for text in ('', '# only a comment', 'numpy>=2', '-r other.txt'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                preflight.locked_versions(text)

    def test_missing_fails_and_version_drift_is_explicit(self):
        def installed(name):
            if name == 'missing':
                raise preflight.metadata.PackageNotFoundError(name)
            return '2.0'
        pins = {'match': '2.0', 'drift': '1.0', 'missing': '1.0'}
        normal = {c['name']: c for c in preflight.package_checks(pins, installed)}
        self.assertEqual(normal['package:match']['status'], 'pass')
        self.assertEqual(normal['package:drift']['status'], 'warn')
        self.assertEqual(normal['package:missing']['status'], 'fail')
        self.assertIn('installed=2.0; locked=1.0', normal['package:drift']['detail'])
        strict = {c['name']: c for c in preflight.package_checks(pins, installed, strict=True)}
        self.assertEqual(strict['package:drift']['status'], 'fail')


if __name__ == '__main__':
    unittest.main()
