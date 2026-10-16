"""Project integration guards: external file locations, the in-project SMPL
kinematics, generated scene props, page file references, script encodings and
machine-specific paths in source files.

Run with the project Python environment (numpy required).
"""
import contextlib
import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'frontend'))
import external_paths  # noqa: E402
import smpl_fk  # noqa: E402


class ExternalPathTests(unittest.TestCase):
    def write_config(self, folder, data):
        path = Path(folder) / 'external_paths.json'
        path.write_text(data if isinstance(data, str) else json.dumps(data), encoding='utf-8')
        return path

    def test_environment_overrides_config_and_relative_paths_start_at_project(self):
        with tempfile.TemporaryDirectory() as folder:
            config = self.write_config(folder, {'smpl_npz': 'models/smpl.npz', 'weights': 'C:/w/weights.pt'})
            paths, problems = external_paths.resolve({'AETHER_TRANSPOSE_WEIGHTS': 'D:/env/weights.pt'}, config)
        self.assertEqual(problems, [])
        self.assertEqual(paths['smpl_npz'], external_paths.PROJECT_DIR / 'models/smpl.npz')
        self.assertEqual(paths['weights'], Path('D:/env/weights.pt'))
        self.assertEqual(paths['transpose_dir'], external_paths.DEFAULT_DIR / 'TransPose')

    def test_broken_config_is_reported_and_defaults_still_resolve(self):
        with tempfile.TemporaryDirectory() as folder:
            config = self.write_config(folder, '{not json')
            paths, problems = external_paths.resolve({}, config)
        self.assertEqual(len(problems), 1)
        self.assertIn('ignored', problems[0])
        self.assertEqual(paths['smpl_pkl'], external_paths.DEFAULT_DIR / 'SMPL_MALE.pkl')

    def test_unknown_keys_and_non_string_values_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            config = self.write_config(folder, {'_note': 'ok', 'smpl': 'x', 'weights': 3})
            paths, problems = external_paths.resolve({}, config)
        self.assertEqual(len(problems), 2)
        self.assertEqual(paths['weights'], external_paths.DEFAULT_DIR / 'weights.pt')

    def test_directory_items_need_their_marker_and_optional_items_can_be_absent(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'tp').mkdir()
            for name in ('smpl.npz', 'smpl.pkl', 'weights.pt'):
                (base / name).write_bytes(b'')
            paths = {'transpose_dir': base / 'tp', 'smpl_npz': base / 'smpl.npz', 'smpl_pkl': base / 'smpl.pkl',
                     'weights': base / 'weights.pt', 'dip_root': base / 'missing'}
            self.assertEqual([i.key for i in external_paths.missing(paths)], ['transpose_dir'])
            (base / 'tp' / 'net.py').write_text('', encoding='utf-8')
            self.assertEqual(external_paths.missing(paths), [])
            self.assertEqual([i.key for i in external_paths.missing(paths, required_only=False)], ['dip_root'])


class SmplKinematicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A 24-joint chain with one vertex per joint, each bound fully to its joint.
        rng = np.random.default_rng(3)
        cls.verts = rng.normal(size=(24, 3)).astype(np.float32)
        parents = np.array([-1] + list(range(23)))
        cls.folder = tempfile.TemporaryDirectory()
        cls.path = Path(cls.folder.name) / 'tiny_smpl.npz'
        np.savez(cls.path, v_template=cls.verts, J_regressor=np.eye(24, dtype=np.float32),
                 shapedirs=np.zeros((24, 3, 10), np.float32), posedirs=np.zeros((24, 3, 207), np.float32),
                 weights=np.eye(24, dtype=np.float32), f=np.zeros((1, 3), np.int32),
                 kintree_table=np.stack([parents, np.arange(24)]))
        cls.fk = smpl_fk.SMPLForwardKinematics(str(cls.path))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_rest_pose_reproduces_template_and_rest_joints(self):
        identity = np.tile(np.eye(3, dtype=np.float32), (24, 1, 1))
        np.testing.assert_allclose(self.fk.lbs_frame(identity), self.verts, atol=1e-5)
        np.testing.assert_allclose(self.fk.forward(np.zeros((2, 72)))[1], self.fk.J_rest, atol=1e-5)

    def test_root_rotation_turns_the_whole_body_about_the_pelvis(self):
        pose = np.zeros((1, 72))
        pose[0, 1] = np.pi / 2  # 90 degrees about Y at the root
        R = smpl_fk.axis_angle_to_matrix(pose[0, :3])
        pelvis = self.fk.J_rest[0]
        expected = (self.fk.J_rest - pelvis) @ R.T + pelvis
        np.testing.assert_allclose(self.fk.forward(pose)[0], expected, atol=1e-5)
        rotations = smpl_fk.batch_axis_angle_to_matrix(pose)[0].astype(np.float32)
        np.testing.assert_allclose(self.fk.lbs_frame(rotations), (self.verts - pelvis) @ R.T + pelvis, atol=1e-5)


class ScenePropTests(unittest.TestCase):
    def test_bundled_props_match_their_generator(self):
        # webui/assets/props/*.glb come from tools/make_scene_props.py; a generator change
        # without a rebuild (or a hand-edited file) would ship props that no longer match it.
        spec = importlib.util.spec_from_file_location('make_scene_props', ROOT / 'tools' / 'make_scene_props.py')
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        bundled = ROOT / 'webui' / 'assets' / 'props'
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            generator.OUT = Path(tmp)
            generator.main()
            built = sorted(Path(tmp).glob('*.glb'))
            self.assertEqual([path.name for path in built], sorted(path.name for path in bundled.glob('*.glb')))
            for path in built:
                self.assertEqual(path.read_bytes(), (bundled / path.name).read_bytes(), path.name)


class SourceHygieneTests(unittest.TestCase):
    SKIP = {'target', 'target_test', '.git', '.venv', 'vendor', '__pycache__', 'external'}
    ROOT_OUTPUTS = {'releases', 'logs', 'experiments', 'recordings'}

    def files(self, *suffixes):
        for path in ROOT.rglob('*'):
            parts = path.relative_to(ROOT).parts
            if path.suffix in suffixes and path.is_file() and not (self.SKIP & set(parts)) \
                    and not parts[0].startswith('.') and parts[0] not in self.ROOT_OUTPUTS:
                yield path

    def test_generated_snapshots_are_excluded_but_active_nested_source_is_not(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            expected = {'src/main.py', 'src/experiments/active.py'}
            for name in expected | {f'{directory}/archived.py' for directory in self.ROOT_OUTPUTS}:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('source', encoding='utf-8')
            with patch.object(sys.modules[__name__], 'ROOT', root):
                self.assertEqual({path.relative_to(root).as_posix() for path in self.files('.py')}, expected)

    def test_powershell_scripts_with_non_ascii_text_have_a_utf8_bom(self):
        # Windows PowerShell 5.1 reads BOM-less files in the ANSI code page.
        for path in self.files('.ps1'):
            data = path.read_bytes()
            if any(byte > 127 for byte in data):
                self.assertTrue(data.startswith(b'\xef\xbb\xbf'), f'{path.relative_to(ROOT)} needs a UTF-8 BOM')

    def test_pages_load_only_files_that_exist(self):
        # The page is split into script and style files; a renamed one would fail only in the browser.
        for page in ('webui/index.html', 'webui/imu_axes.html'):
            text = (ROOT / page).read_text(encoding='utf-8')
            refs = re.findall(r'<(?:script|link)\b[^>]*?\b(?:src|href)="([^"]+)"', text)
            self.assertTrue(refs or page.endswith('imu_axes.html'), page)
            for ref in refs:
                if ref.startswith(('data:', 'http:', 'https:', '#')):
                    continue
                self.assertTrue(((ROOT / page).parent / ref.split('?')[0]).is_file(), f'{page}: {ref}')

    def test_source_files_do_not_reference_one_machine(self):
        pattern = re.compile(r'[A-Za-z]:[\\/]+(Users|Download)[\\/]|OneDrive', re.IGNORECASE)
        this_file = Path(__file__).resolve()
        for path in self.files('.py', '.ps1', '.js', '.rs', '.html', '.ino'):
            if path.resolve() == this_file:
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                self.assertIsNone(pattern.search(line), f'{path.relative_to(ROOT)}:{number}: {line.strip()}')


if __name__ == '__main__':
    unittest.main()
