"""Body calibration for TransPose input, on synthetic trackers with unknown
mountings and an unknown facing direction.

Run with the project Python environment (numpy/scipy required).
"""
import sys
import unittest
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'frontend'))
import body_calibration as bc  # noqa: E402

TORSO, ARM, LEG = 76, 31, 43


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class Body:
    """Trackers worn with random mountings by a person facing a random direction."""

    def __init__(self, seed):
        rng = np.random.default_rng(seed)
        yaw = rng.uniform(-np.pi, np.pi)
        forward = np.array([np.cos(yaw), np.sin(yaw), 0.0])
        self.smpl2imu = np.stack([np.cross(bc.UP, forward), bc.UP, forward])
        self.mounting = {i: Rotation.random(random_state=rng.integers(1 << 30)).as_matrix() for i in (TORSO, ARM, LEG)}
        self.rng = rng

    def raw(self, bones, noise_deg=0.0):
        """Raw tracker frames for SMPL-frame bone orientations {id: R_bone}."""
        frames = {}
        for i, bone in bones.items():
            jitter = Rotation.from_rotvec(self.rng.normal(size=3) * np.radians(noise_deg) / np.sqrt(3)).as_matrix()
            r_raw = self.smpl2imu.T @ bone @ self.mounting[i].T @ jitter
            frames[i] = (r_raw, self.smpl2imu.T @ np.array([0.0, 0.0, 0.0]))
        return frames


def run(calibration, clock, body, bow_deg=40.0, noise_deg=0.5, wobble_phase=None, torso=TORSO):
    """Feed frames at 50 Hz through every phase."""
    calibration.start()
    rest = {i: np.eye(3) for i in (TORSO, ARM, LEG)}
    bow = {**rest, TORSO: Rotation.from_rotvec([np.radians(bow_deg), 0, 0]).as_matrix()}
    while calibration.phase in bc.PHASES:
        phase = calibration.phase
        pose = bow if phase in ('bow_ready', 'bow') else rest
        noise = 20.0 if phase == wobble_phase else noise_deg
        calibration.observe(body.raw(pose, noise), torso)
        clock.now += 0.02


class SolveTests(unittest.TestCase):
    def test_recovers_bone_orientations_for_any_facing_and_mounting(self):
        for seed in range(5):
            clock, body = Clock(), Body(seed)
            calibration = bc.BodyCalibration(clock)
            run(calibration, clock, body)
            self.assertEqual(calibration.phase, 'done', calibration.message)
            np.testing.assert_allclose(calibration.smpl2imu, body.smpl2imu, atol=0.02)
            for _ in range(5):
                bones = {i: Rotation.random(random_state=body.rng.integers(1 << 30)).as_matrix() for i in (TORSO, ARM, LEG)}
                for i, (r_raw, a_raw) in body.raw(bones).items():
                    r, _ = calibration.apply(i, r_raw, a_raw)
                    np.testing.assert_allclose(r, bones[i], atol=0.03)

    def test_acceleration_moves_into_the_smpl_frame_without_its_t_pose_bias(self):
        clock, body = Clock(), Body(7)
        calibration = bc.BodyCalibration(clock)
        run(calibration, clock, body)
        forward_push = body.smpl2imu.T @ np.array([0.0, 0.0, 2.0])  # 2 m/s² toward the person's front
        _, a = calibration.apply(ARM, np.eye(3), forward_push)
        np.testing.assert_allclose(a, [0.0, 0.0, 2.0], atol=0.05)

    def test_a_shallow_bow_is_refused(self):
        clock = Clock()
        calibration = bc.BodyCalibration(clock)
        run(calibration, clock, Body(1), bow_deg=8.0)
        self.assertEqual(calibration.phase, 'failed')
        self.assertIn('鞠躬再深一點', calibration.message)
        self.assertFalse(calibration.is_calibrated(TORSO))

    def test_moving_during_a_hold_is_refused(self):
        for phase in ('tpose', 'bow'):
            clock = Clock()
            calibration = bc.BodyCalibration(clock)
            run(calibration, clock, Body(2), wobble_phase=phase)
            self.assertEqual(calibration.phase, 'failed', phase)
            self.assertIn('請保持不動', calibration.message)

    def test_needs_a_torso_tracker(self):
        clock = Clock()
        calibration = bc.BodyCalibration(clock)
        run(calibration, clock, Body(3), torso=None)
        self.assertEqual(calibration.phase, 'failed')
        self.assertIn('胸口或頭部', calibration.message)

    def test_a_failed_retry_keeps_the_previous_calibration(self):
        clock, body = Clock(), Body(4)
        calibration = bc.BodyCalibration(clock)
        run(calibration, clock, body)
        previous = calibration.smpl2imu.copy()
        run(calibration, clock, body, bow_deg=5.0)
        self.assertEqual(calibration.phase, 'failed')
        np.testing.assert_array_equal(calibration.smpl2imu, previous)

    def test_state_reports_the_countdown(self):
        clock = Clock()
        calibration = bc.BodyCalibration(clock)
        calibration.start()
        clock.now += 1.0
        state = calibration.state()
        self.assertEqual((state['phase'], state['seconds_left']), ('tpose_ready', 2.0))
        calibration.cancel()
        self.assertEqual(calibration.state()['phase'], 'idle')
        self.assertEqual(calibration.state()['message'], '已取消。')
        clock.now += bc.CANCEL_NOTICE_SECONDS + 1
        self.assertEqual(calibration.state()['message'], '尚未校正。', 'the notice does not outlive its moment')

    def test_cancel_keeps_an_earlier_calibration(self):
        clock, body = Clock(), Body(5)
        calibration = bc.BodyCalibration(clock)
        run(calibration, clock, body)
        calibration.start()
        calibration.cancel()
        self.assertEqual(calibration.phase, 'done')
        self.assertTrue(calibration.is_calibrated(ARM))


if __name__ == '__main__':
    unittest.main()
