"""TransPoseRunner without the model: tracker input checks, timing, and handing out poses.

Run with the project Python environment (numpy/scipy required).
"""
import importlib.util
from pathlib import Path
import threading
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location('transpose_mesh_test',
    Path(__file__).resolve().parents[1] / 'frontend/transpose_runner.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RunnerTests(unittest.TestCase):
    def test_update_rate_uses_smoothed_intervals(self):
        runner = module.TransPoseRunner.__new__(module.TransPoseRunner)
        runner._lock = threading.Lock()
        runner._device = 'cpu'
        with runner._lock:
            runner._update_runtime_timing(.95, 1.0)
            runner._update_runtime_timing(1.05, 1.1)
            runner._update_runtime_timing(1.1, 2.0)
        stats = runner.get_runtime_stats()
        self.assertAlmostEqual(stats['pose_fps'], 3.8)
        self.assertEqual(stats['frame_ms'], 900.0)
        self.assertEqual(stats['device'], 'cpu')
    def make_input_runner(self):
        runner = module.TransPoseRunner.__new__(module.TransPoseRunner)
        runner._lock = threading.Lock()
        runner._ready = True
        runner._mask_acc = np.zeros((2,6,3),dtype=np.float32)
        runner._mask_ori = np.tile(np.eye(3,dtype=np.float32),(2,6,1,1))
        runner._mask_idx = 0
        runner._pending = module.deque(maxlen=module.MAX_FRAMES_PER_PASS)
        runner._input_frames = runner._dropped_input_frames = 0
        runner._origin_t = np.array([1.,2.,3.],dtype=np.float32)
        runner.body = module.body_calibration.BodyCalibration()
        runner._calib_lock = threading.Lock()
        return runner

    def test_long_inference_is_not_mistaken_for_an_idle_pause(self):
        runner = module.TransPoseRunner.__new__(module.TransPoseRunner)
        runner._lock = threading.Lock()
        runner._update_runtime_timing(.95, 1.0)
        runner._update_runtime_timing(1.05, 1.1)
        runner._update_runtime_timing(1.11, 3.11)
        self.assertLess(runner.get_runtime_stats()['pose_fps'], 3)
        # A real input pause still restarts the interval average on resume.
        runner._update_runtime_timing(5.0, 5.1)
        runner._update_runtime_timing(5.15, 5.2)
        self.assertAlmostEqual(runner.get_runtime_stats()['pose_fps'], 10)

    def test_slow_model_queue_overflow_is_visible_in_runtime_stats(self):
        runner = self.make_input_runner()
        for _ in range(module.MAX_FRAMES_PER_PASS + 3):
            runner.push_frame({})
        stats = runner.get_runtime_stats()
        self.assertEqual(stats['input_frames'], module.MAX_FRAMES_PER_PASS + 3)
        self.assertEqual(stats['pending_frames'], module.MAX_FRAMES_PER_PASS)
        self.assertEqual(stats['dropped_input_frames'], 3)
        self.assertEqual(stats['batch_frames'], 0)

    def tracker(self,bone,**values):
        return {'assigned_bone':bone,'accel':[0,0,9.81],'rotation':[0,0,0,1],'last_update_ms':0,**values}

    def test_expired_and_invalid_trackers_do_not_count_as_live(self):
        runner = self.make_input_runner()
        records = {i:self.tracker(bone) for i,bone in enumerate(runner.BONE_TO_SLOT)}
        records[0]['last_update_ms'] = 501
        records[1]['rotation'] = [0,0,0,0]
        records[2]['accel'] = [float('nan'),0,0]
        records[3]['assigned_bone'] = [4]
        runner.push_frame(records)
        self.assertEqual(len(runner._last_live_slots),2)
        self.assertTrue(np.isfinite(runner._pending[-1][0]).all())
        self.assertTrue(np.isfinite(runner._pending[-1][1]).all())
        records = {i:self.tracker(bone) for i,bone in enumerate(runner.BONE_TO_SLOT)}
        runner.push_frame(records)
        self.assertEqual(len(runner._last_live_slots),6)
        np.testing.assert_allclose(runner._pending[-1][0],0,atol=1e-6)
        self.assertEqual(len(runner._pending),2,'every frame waits for the model, not just the newest')

    def test_live_frames_use_the_body_calibration_once_available(self):
        runner = self.make_input_runner()
        records = {i:self.tracker(bone,id=10+i) for i,bone in enumerate(runner.BONE_TO_SLOT)}
        runner.push_frame(records)
        self.assertEqual(runner._pending[-1][3],6,'all live trackers uncalibrated')
        self.assertIn('6 uncalibrated',runner._format_stream_status(1,6,'tpose',runner._pending[-1][3]))
        # Inertial frame Z up -> SMPL Y up, facing the inertial +X axis.
        runner.body.smpl2imu = np.array([[0,1,0],[0,0,1],[1,0,0]],dtype=float)
        # As calibrated from a T-pose in which every raw orientation was identity.
        runner.body.device2bone = {10+i:runner.body.smpl2imu.T for i in range(6)}
        runner.body.offsets = {10+i:np.zeros(3) for i in range(6)}
        records = {i:self.tracker(bone,id=10+i,rotation=[0,0,np.sin(np.pi/4),np.cos(np.pi/4)])
                   for i,bone in enumerate(runner.BONE_TO_SLOT)}
        runner.push_frame(records)
        self.assertEqual(runner._pending[-1][3],0)
        # 90 degrees about inertial Z (up) becomes 90 degrees about SMPL Y.
        np.testing.assert_allclose(runner._pending[-1][1][0],[[0,0,1],[0,1,0],[-1,0,0]],atol=1e-6)
        self.assertNotIn('uncalibrated',runner._format_stream_status(2,6,'tpose',0))

    def test_demo_loop_does_not_recenter_complete_live_tracking(self):
        runner = self.make_input_runner()
        runner._mask_idx = 2
        records = {i:self.tracker(bone) for i,bone in enumerate(runner.BONE_TO_SLOT)}
        runner.push_frame(records)
        np.testing.assert_equal(runner._origin_t,[1,2,3])
        runner._mask_idx = 4
        runner.push_frame({})
        self.assertIsNone(runner._origin_t)

    def test_each_pose_is_handed_out_once(self):
        runner = module.TransPoseRunner.__new__(module.TransPoseRunner)
        runner._lock = threading.Lock()
        runner._pose, runner._joints_version = None, 0
        self.assertEqual(runner.get_pose_if_new(-1), (None, -1))
        pose = module.Pose(np.zeros((24, 3), np.float32), [0.0] * 216, [0.0] * 3)
        runner._pose, runner._joints_version = pose, 1
        self.assertEqual(runner.get_pose_if_new(0), (pose, 1))
        self.assertEqual(runner.get_pose_if_new(1), (None, 1))
        self.assertEqual(runner.get_pose_if_new(-1), (pose, 1), 'a new page gets the current pose')


if __name__ == '__main__': unittest.main()
