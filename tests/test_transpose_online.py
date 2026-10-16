"""transpose_runner.forward_online_frames against TransPose's own forward_online, with the real
model (skipped when the external TransPose files are missing). One frame at a time it must give
forward_online's poses and positions; several frames per pass (what happens when inference is
slower than 60 frames a second) it must stay close to them."""
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'frontend'))
import external_paths  # noqa: E402

PATHS, _ = external_paths.resolve()
MISSING = external_paths.missing(PATHS)


def motion(frames):
    """Six IMUs turning smoothly (each about its own axis, at its own pace) and accelerating gently."""
    from scipy.spatial.transform import Rotation
    t = np.arange(frames)[:, None] / 60
    axes = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [0, 1, 1], [1, 0, 1]], float)
    axes /= np.linalg.norm(axes, axis=1, keepdims=True)
    angles = 0.6 * np.sin(2 * np.pi * (0.4 + 0.15 * np.arange(6)) * t)               # (frames, 6)
    ori = Rotation.from_rotvec((angles[..., None] * axes).reshape(-1, 3)).as_matrix().reshape(frames, 6, 3, 3)
    acc = 0.8 * np.sin(2 * np.pi * 0.7 * t)[..., None] * np.ones((frames, 6, 3))
    return acc.astype(np.float32), ori.astype(np.float32)


def angle_between(a, b):
    """Rotation angle (degrees) between matching rotation matrices."""
    cos = (np.einsum('...ij,...ij->...', a, b) - 1) / 2
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


@unittest.skipIf(MISSING, 'the TransPose files are not available')
class OnlineFramesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        import transpose_runner  # puts the TransPose folder on the path
        import config as tp_config
        tp_config.paths.smpl_file = str(PATHS['smpl_pkl'])
        tp_config.paths.weights_file = str(PATHS['weights'])
        from net import TransPoseNet
        from utils import normalize_and_concat
        torch.set_num_threads(2)
        cls.torch, cls.runner, cls.Net = torch, transpose_runner, TransPoseNet
        acc, ori = motion(90)
        cls.xs = normalize_and_concat(torch.from_numpy(acc), torch.from_numpy(ori))
        cls.reference = cls.infer(lambda net, i: net.forward_online(cls.xs[i]), range(90))

    @classmethod
    def infer(cls, step, calls):
        """Poses and positions from a fresh model, one call per item of `calls`."""
        net = cls.Net().eval()
        results = {}
        with cls.torch.inference_mode():
            for call in calls:
                pose, position = step(net, call)
                last = call if isinstance(call, int) else call.stop - 1
                results[last] = (pose.numpy().copy(), position.numpy().copy())
        return results

    def test_one_frame_at_a_time_is_forward_online(self):
        frames = self.infer(lambda net, i: self.runner.forward_online_frames(net, self.xs[i:i + 1]), range(90))
        for i, (pose, position) in self.reference.items():
            np.testing.assert_allclose(frames[i][0], pose, atol=1e-5, err_msg=f'pose of frame {i}')
            np.testing.assert_allclose(frames[i][1], position, atol=1e-5, err_msg=f'position of frame {i}')

    def deviation(self, results):
        """Mean and worst joint angle (degrees) and worst root distance (m) from every-frame forward_online."""
        angles = [angle_between(results[i][0], self.reference[i][0]) for i in results]
        root = max(np.linalg.norm(results[i][1] - self.reference[i][1]) for i in results)
        return np.mean([a.mean() for a in angles]), max(a.max() for a in angles), root

    def test_several_frames_per_pass_stay_close(self):
        # What the service did before: hand the model only the newest of the three.
        newest_only = self.deviation(self.infer(lambda net, i: net.forward_online(self.xs[i]), range(2, 90, 3)))
        for batch in (2, 3, 4, self.runner.MAX_FRAMES_PER_PASS):
            with self.subTest(batch=batch):
                results = self.infer(lambda net, s: self.runner.forward_online_frames(net, self.xs[s]),
                                     [slice(i, min(i + batch, 90)) for i in range(0, 90, batch)])
                batched = self.deviation(results)
                mean, worst, root = batched
                print(f'batch {batch}: joints {mean:.2f} degrees on average, {worst:.1f} at worst; root within {root * 100:.0f} cm')
                self.assertLess(mean, 1.0)
                self.assertLess(worst, 10.0)
                self.assertLess(root, 0.2)
                self.assertLess(mean * 5, newest_only[0], 'far closer to the model fed every frame')
                for index, (pose, position) in results.items():
                    np.testing.assert_allclose(pose, self.reference[index][0], atol=1e-5)
                    np.testing.assert_allclose(position, self.reference[index][1], atol=1e-5)
        print(f'newest only: joints {newest_only[0]:.2f} degrees on average, {newest_only[1]:.1f} at worst; root within {newest_only[2] * 100:.0f} cm')

    def test_variable_batches_preserve_the_online_state(self):
        slices, start = [], 0
        pattern = (1, 8, 2, 5, 3, 4, 7, 6)
        while start < 90:
            size = pattern[len(slices) % len(pattern)]
            stop = min(start + size, 90)
            slices.append(slice(start, stop))
            start = stop
        results = self.infer(lambda net, s: self.runner.forward_online_frames(net, self.xs[s]), slices)
        for index, (pose, position) in results.items():
            np.testing.assert_allclose(pose, self.reference[index][0], atol=1e-5)
            np.testing.assert_allclose(position, self.reference[index][1], atol=1e-5)


if __name__ == '__main__':
    unittest.main()
