"""The page skins the body mesh itself (webui/skinning.js) from the skin the pose service exports
(smpl_fk.page_skin) and each pose's rotations: run in node, it must give the vertices that
smpl_fk.lbs_frame gives, with the pelvis as origin plus the translation. Also checks that the
page refuses malformed skins and poses. Needs node (skipped without it)."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'frontend'))
import smpl_fk  # noqa: E402

SMPL_PARENTS = [-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19, 20, 21]
NODE = shutil.which('node')
HARNESS = r"""
const fs = require('node:fs'), vm = require('node:vm');
const page = vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8') + '\n;smplSkinning;');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const skin = page.load(input.skin);
const verts = page.pose(skin, input.rotations, input.translation);
process.stdout.write(JSON.stringify({
  verts: verts && Array.from(verts),
  refusedSkins: input.badSkins.map(bad => page.load(bad) === null),
  refusedPoses: input.badPoses.map(([rotations, translation]) => page.pose(skin, rotations, translation) === null),
}));
"""


def rotation(axis, angle):
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(angle) * k + (1 - np.cos(angle)) * k @ k


@unittest.skipUnless(NODE, 'node is not installed')
class PageSkinningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # SMPL's joint tree, 300 vertices each bound to four random joints.
        rng = np.random.default_rng(7)
        count = 300
        weights = np.zeros((count, 24), np.float32)
        for row in weights:
            row[rng.choice(24, 4, replace=False)] = rng.random(4) + .05
        weights /= weights.sum(1, keepdims=True)
        regressor = rng.random((24, count)).astype(np.float32)
        regressor /= regressor.sum(1, keepdims=True)
        cls.folder = tempfile.TemporaryDirectory()
        path = Path(cls.folder.name) / 'smpl_like.npz'
        np.savez(path, v_template=rng.normal(size=(count, 3)).astype(np.float32), J_regressor=regressor,
                 shapedirs=np.zeros((count, 3, 10), np.float32), posedirs=np.zeros((count, 3, 207), np.float32),
                 weights=weights, f=np.zeros((1, 3), np.int32),
                 kintree_table=np.stack([SMPL_PARENTS, np.arange(24)]))
        cls.fk = smpl_fk.SMPLForwardKinematics(str(path))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_page(self, skin, rotations, translation, bad_skins=(), bad_poses=()):
        payload = json.dumps({'skin': skin, 'rotations': rotations, 'translation': translation,
                              'badSkins': list(bad_skins), 'badPoses': list(bad_poses)})
        done = subprocess.run([NODE, '-e', HARNESS, str(ROOT / 'webui' / 'skinning.js')], input=payload,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_the_page_skins_like_the_pose_service(self):
        rng = np.random.default_rng(11)
        skin = self.fk.page_skin()
        for _ in range(3):
            rotations = np.stack([rotation(rng.normal(size=3), rng.uniform(-1.2, 1.2)) for _ in range(24)]).astype(np.float32)
            translation = rng.normal(scale=.5, size=3).astype(np.float32)
            expected = self.fk.lbs_frame(rotations) - self.fk.J_rest[0] + translation
            # Sent the way transpose_runner sends a pose.
            page = self.run_page(skin, np.round(rotations.astype(float), 5).ravel().tolist(),
                                 np.round(translation.astype(float), 5).ravel().tolist())
            np.testing.assert_allclose(np.reshape(page['verts'], (-1, 3)), expected, atol=2e-4)

    def test_malformed_skins_and_poses_are_refused(self):
        skin = self.fk.page_skin()
        bad_skins = [
            {**skin, 'joints': skin['joints'][:-3]},
            {**skin, 'parents': [-1, 2] + skin['parents'][2:]},   # a parent after its child
            {**skin, 'bones': [24] + skin['bones'][1:]},          # no joint 24
            {**skin, 'template': skin['template'][:-1]},
            {**skin, 'weights': skin['weights'][:-4]},
            {key: value for key, value in skin.items() if key != 'bones'},
            None,
        ]
        bad_skins[3]['template'] = list(bad_skins[3]['template'])
        identity = np.tile(np.eye(3), (24, 1)).ravel().tolist()
        bad_poses = [(identity[:-9], [0, 0, 0]), (identity, [0, 0]), ([None] + identity[1:], [0, 0, 0])]
        page = self.run_page(skin, identity, [0, 0, 0], bad_skins[:-1] + [None], bad_poses)
        self.assertEqual(page['refusedSkins'], [True] * len(bad_skins))
        self.assertEqual(page['refusedPoses'], [True] * len(bad_poses))
        np.testing.assert_allclose(np.reshape(page['verts'], (-1, 3)), self.fk.v_template - self.fk.J_rest[0], atol=2e-4)

    def test_the_export_keeps_four_weights_per_vertex(self):
        skin = self.fk.page_skin()
        weights = np.reshape(skin['weights'], (-1, 4))
        self.assertEqual(len(weights), len(self.fk.v_template))
        np.testing.assert_allclose(weights.sum(1), 1, atol=1e-5)
        self.assertEqual(skin['parents'], SMPL_PARENTS)


if __name__ == '__main__':
    unittest.main()
