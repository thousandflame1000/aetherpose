"""Review packages must preserve source and refuse private data or tampering."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

spec = importlib.util.spec_from_file_location('package_submission', Path(__file__).resolve().parents[1] / 'tools/package_submission.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'source'
        for name in package.REQUIRED:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('source for ' + name, encoding='utf-8')
        self.archive = self.base / 'review.zip'

    def rewrite(self, transform):
        with ZipFile(self.archive) as original:
            entries = {i.filename: original.read(i) for i in original.infolist()}
        transform(entries)
        output = self.base / 'modified.zip'
        with ZipFile(output, 'w') as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        return output

    def test_build_excludes_private_and_model_files_but_keeps_untracked_source(self):
        forbidden = ['config.json', 'external_paths.json', 'frontend/weights.pt', 'frontend/body.npz',
                     'webui/config.json', 'webui/assets/uploads/private.glb', 'docs/participant.png',
                     'docs/raw.csv', 'logs/private.log', '.cargo/config.toml',
                     'tools/__pycache__/code.pyc', 'experiments/subject.json']
        for name in forbidden + ['tools/new_untracked_tool.py']:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('test', encoding='utf-8')
        result = package.build(self.root, self.archive)
        self.assertTrue(result['verified'])
        self.assertFalse(result['hardware_acceptance'])
        with ZipFile(self.archive) as archive:
            names = set(archive.namelist())
        self.assertIn(package.PREFIX + 'tools/new_untracked_tool.py', names)
        self.assertTrue(all(package.PREFIX + name not in names for name in forbidden))
        with self.assertRaises(FileExistsError):
            package.build(self.root, self.archive)

    def test_missing_notice_prevents_build(self):
        (self.root / 'webui/vendor/three/LICENSE').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing required'):
            package.build(self.root, self.archive)
        self.assertFalse(self.archive.exists())

    def test_modified_payload_is_detected_even_when_zip_crc_is_valid(self):
        package.build(self.root, self.archive)
        def tamper(entries):
            key = package.PREFIX + 'README.md'
            entries[key] = b'!' * len(entries[key])
        with self.assertRaisesRegex(ValueError, 'Hash mismatch'):
            package.verify(self.rewrite(tamper))

    def test_extra_file_and_path_traversal_are_refused(self):
        package.build(self.root, self.archive)
        for name in ['aetherpose/unlisted.py', 'aetherpose/../escape.py', 'other/source.py',
                     'aetherpose/docs/CON.md', 'aetherpose/docs/back\\slash.md']:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    package.verify(self.rewrite(lambda entries: entries.update({name: b'x'})))

    def test_a_forged_manifest_cannot_allow_private_config(self):
        package.build(self.root, self.archive)
        def add_private(entries):
            manifest_key = package.PREFIX + package.MANIFEST
            manifest = json.loads(entries[manifest_key])
            data = b'private settings'
            manifest['files']['config.json'] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            entries[manifest_key] = json.dumps(manifest).encode()
            entries[package.PREFIX + 'config.json'] = data
        with self.assertRaisesRegex(ValueError, 'source policy'):
            package.verify(self.rewrite(add_private))

    def test_symbolic_links_do_not_copy_outside_files(self):
        outside = self.base / 'private.py'
        outside.write_text('private', encoding='utf-8')
        target = self.root / 'tools/outside.py'
        try:
            os.symlink(outside, target)
        except OSError as exc:
            self.skipTest(f'Cannot create symlink in this environment: {exc}')
        with self.assertRaisesRegex(ValueError, 'Link'):
            package.build(self.root, self.archive)


if __name__ == '__main__':
    unittest.main()
