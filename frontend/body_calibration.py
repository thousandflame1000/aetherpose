"""
Sensor-to-body calibration for TransPose input from live trackers.

TransPose expects orientations and accelerations in the SMPL frame (x left,
y up, z forward) with each sensor's mounting removed. Its live demo first
holds one IMU aligned with the body to find the frame, which needs the
sensor's axes; here the facing direction comes from a forward bow instead:

  1. T-pose, still: every tracker's raw orientation R0 and acceleration a0.
  2. Bow forward, still: the torso tracker's up axis tilts toward the front;
     the horizontal part of that tilt is the body's forward direction.

  smpl2imu        = rows [left, up, forward] of the inertial frame (Z up)
  device2bone[id] = (smpl2imu @ R0[id])^T      (bones are identity in a T-pose)
  per frame:  R = smpl2imu @ R_raw @ device2bone[id]
              a = smpl2imu @ a_raw - offset[id], offset = smpl2imu @ a0[id]
"""

import time

import numpy as np
from scipy.spatial.transform import Rotation

UP = np.array([0.0, 0.0, 1.0])  # inertial frame of the tracker firmware (NWU)
MIN_BOW_DEG = 15.0              # smaller tilts give an unreliable forward direction
MAX_WOBBLE_DEG = 8.0            # a hold that moves more than this is rejected

# phase: (seconds, message shown on the page)
PHASES = {
    'tpose_ready': (3.0, '站直做 T-pose：雙臂向兩側平舉，掌心朝下。'),
    'tpose': (2.0, '保持 T-pose 不動…'),
    'bow_ready': (3.0, '雙臂保持平舉，從髖部向前鞠躬約 45°。'),
    'bow': (1.5, '保持鞠躬不動…'),
}
ORDER = ['tpose_ready', 'tpose', 'bow_ready', 'bow']
CANCEL_NOTICE_SECONDS = 10.0    # afterwards the page shows the settled state again


class CalibrationError(ValueError):
    pass


def mean_rotation(matrices):
    """Mean rotation of a hold and its largest deviation in degrees."""
    rotations = Rotation.from_matrix(np.asarray(matrices, dtype=np.float64))
    mean = rotations.mean()
    wobble = np.degrees((mean.inv() * rotations).magnitude().max())
    return mean.as_matrix(), wobble


def facing_from_bow(r_stand, r_bow):
    """Unit horizontal forward direction in the inertial frame, from one torso
    tracker's raw orientation standing and bowed. Mounting cancels out: the
    change R_bow @ R_stand^T is the torso's own rotation in the inertial frame."""
    tilted_up = r_bow @ r_stand.T @ UP
    horizontal = tilted_up - UP * (tilted_up @ UP)
    if np.linalg.norm(horizontal) < np.sin(np.radians(MIN_BOW_DEG)):
        raise CalibrationError(f'鞠躬再深一點（至少 {MIN_BOW_DEG:.0f}°）')
    return horizontal / np.linalg.norm(horizontal)


def solve(tpose, bow_torso, torso_id):
    """tpose: {id: (R0, a0)}; bow_torso: the torso tracker's mean orientation in the bow."""
    forward = facing_from_bow(tpose[torso_id][0], bow_torso)
    smpl2imu = np.stack([np.cross(UP, forward), UP, forward])
    device2bone = {i: (smpl2imu @ r0).T for i, (r0, _) in tpose.items()}
    offsets = {i: smpl2imu @ a0 for i, (_, a0) in tpose.items()}
    return smpl2imu, device2bone, offsets


class BodyCalibration:
    """Steps through the calibration by time while live frames come in.
    observe() collects raw frames; apply() maps a calibrated tracker's raw
    orientation/acceleration into the SMPL frame."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.phase = 'idle'
        self.message = '尚未校正。'
        self.phase_end = 0.0
        self.samples = {}
        self.tpose = {}
        self.torso_id = None
        self.smpl2imu = None
        self.device2bone = {}
        self.offsets = {}
        self.calibrated_at = None
        self.cancelled_at = None

    def start(self):
        self.cancelled_at = None
        self._enter('tpose_ready')
        self.samples, self.tpose, self.torso_id = {}, {}, None

    def cancel(self):
        """Stop a running calibration; an earlier calibration stays in use."""
        if self.phase not in PHASES:
            return
        self.samples = {}
        self.cancelled_at = self.clock()
        if self.smpl2imu is not None:
            self.phase, self.message = 'done', '已取消，繼續使用先前的校正。'
        else:
            self.phase, self.message = 'idle', '已取消。'

    def _enter(self, phase):
        self.phase = phase
        self.message = PHASES[phase][1]
        self.phase_end = self.clock() + PHASES[phase][0]
        self.samples = {}

    def _fail(self, message):
        self.phase, self.message, self.samples = 'failed', message, {}

    def observe(self, frames, torso_id):
        """frames: {tracker id: (R_raw 3x3, a_raw 3)} of the live trackers;
        torso_id: the chest (or head) tracker id, or None."""
        if self.phase not in PHASES:
            return
        if self.phase in ('tpose', 'bow'):
            for tracker_id, (r, a) in frames.items():
                self.samples.setdefault(tracker_id, []).append((np.asarray(r, float), np.asarray(a, float)))
        if self.clock() < self.phase_end:
            return
        try:
            if self.phase == 'tpose':
                if torso_id is None or torso_id not in self.samples:
                    raise CalibrationError('沒有即時的胸口或頭部追蹤器，請指派一顆後重試')
                for tracker_id, rows in self.samples.items():
                    r0, wobble = mean_rotation([r for r, _ in rows])
                    if wobble > MAX_WOBBLE_DEG:
                        raise CalibrationError(f'追蹤器 {tracker_id} 在 T-pose 時移動了，請保持不動後重試')
                    self.tpose[tracker_id] = (r0, np.mean([a for _, a in rows], axis=0))
                self.torso_id = torso_id
            elif self.phase == 'bow':
                rows = self.samples.get(self.torso_id)
                if not rows:
                    raise CalibrationError(f'追蹤器 {self.torso_id} 在鞠躬時停止傳送資料')
                bow, wobble = mean_rotation([r for r, _ in rows])
                if wobble > MAX_WOBBLE_DEG:
                    raise CalibrationError('鞠躬時軀幹移動了，請保持不動後重試')
                self.smpl2imu, self.device2bone, self.offsets = solve(self.tpose, bow, self.torso_id)
                self.calibrated_at = time.time()
                self.phase, self.message, self.samples = 'done', f'已校正 {len(self.device2bone)} 顆追蹤器。', {}
                return
        except CalibrationError as exc:
            self._fail(f'校正失敗：{exc}。')
            return
        self._enter(ORDER[ORDER.index(self.phase) + 1])

    def is_calibrated(self, tracker_id):
        return self.smpl2imu is not None and tracker_id in self.device2bone

    def apply(self, tracker_id, r_raw, a_raw):
        r = self.smpl2imu @ r_raw @ self.device2bone[tracker_id]
        a = self.smpl2imu @ a_raw - self.offsets[tracker_id]
        return r.astype(np.float32), a.astype(np.float32)

    def state(self):
        left = max(0.0, self.phase_end - self.clock()) if self.phase in PHASES else 0.0
        message = self.message
        if self.cancelled_at is not None and self.clock() - self.cancelled_at > CANCEL_NOTICE_SECONDS:
            if self.phase == 'idle':
                message = '尚未校正。'
            elif self.phase == 'done':
                message = f'已校正 {len(self.device2bone)} 顆追蹤器。'
        return {'phase': self.phase, 'message': message, 'seconds_left': round(left, 1),
                'trackers': sorted(self.device2bone), 'calibrated_at': self.calibrated_at}
