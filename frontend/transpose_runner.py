"""
TransPoseRunner — the neural-net (TransPose) full-body pose estimator.

Used by mesh_bridge.py, the headless pose service behind the web UI. Each pose carries the joint
positions (for the games) and the joint rotations the page skins the body mesh from.
"""

import os, sys, time, threading
from collections import deque
from typing import NamedTuple
# 2 threads: 4 were faster alone (~17 against ~21 ms a frame) but not with the browser
# rendering on the same machine (A/B runs 35/44 against 39/40 poses a second).
_TORCH_THREADS = int(os.environ.get("AETHER_TORCH_THREADS", "2"))
_PERF_LOG = os.environ.get("AETHER_PERF_LOG", "0") == "1"
_PERF_LOG_EVERY = max(1, int(os.environ.get("AETHER_PERF_LOG_EVERY", "30")))
for _thread_var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_thread_var, str(_TORCH_THREADS))

import numpy as np
from scipy.spatial.transform import Rotation as _Rot

# ── Paths (external files: see external_paths.py) ────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import external_paths
import body_calibration
from cpu_latency import configure_cpu_latency

_PATHS, _PATH_PROBLEMS = external_paths.resolve()
_TRANSPOSE_DIR = str(_PATHS['transpose_dir'])
_SMPL_NPZ      = str(_PATHS['smpl_npz'])
_SMPL_PKL      = str(_PATHS['smpl_pkl'])
_TP_WEIGHTS    = str(_PATHS['weights'])
_DIP_ROOT      = str(_PATHS['dip_root'])

if _TRANSPOSE_DIR not in sys.path:
    sys.path.insert(0, _TRANSPOSE_DIR)

SMPL_BONES = [
    (0,1),(0,2),(0,3),(1,4),(2,5),(3,6),(4,7),(5,8),(6,9),
    (7,10),(8,11),(9,12),(9,13),(9,14),(12,15),(13,16),(14,17),
    (16,18),(17,19),(18,20),(19,21),(20,22),(21,23),
]
SMPL_LEFT  = {1,4,7,10,13,16,18,20,22}
SMPL_RIGHT = {2,5,8,11,14,17,19,21,23}


# Frames waiting for the model: at 60 a second, up to about 0.13 s of catching up per pass.
MAX_FRAMES_PER_PASS = 8


def forward_online_frames(net, xs):
    """Evaluate each input's original fixed window, batching independent pose RNNs.

    Bidirectional RNN windows remain separate along the batch dimension. The
    unidirectional translation RNN sees those windows concatenated in chronological
    order, preserving the original online recurrent-state updates. Return the last
    pose and integrate all k translations; never lengthen the model's context.
    """
    import torch
    tp = sys.modules[type(net).__module__]
    art, joint_set = tp.art, tp.joint_set
    k, past, total = len(xs), net.num_past_frame, net.num_total_frame
    window = xs[0].repeat(total, 1) if net.imu is None else net.imu
    windows = []
    for sample in xs:
        window = torch.cat((window[1:], sample.unsqueeze(0)))
        windows.append(window)
    imu = torch.stack(windows, dim=1)  # [original window time, independent window, input]

    def rnn(module, values, state=None):
        hidden = torch.relu(module.linear1(module.dropout(values)))
        hidden, state = module.rnn(hidden, state)
        return module.linear2(hidden), state

    leaf = rnn(net.pose_s1, imu)[0]
    full = rnn(net.pose_s2, torch.cat((leaf, imu), dim=-1))[0]
    reduced = rnn(net.pose_s3, torch.cat((full, imu), dim=-1))[0]
    contact = rnn(net.tran_b1, torch.cat((leaf, imu), dim=-1))[0]
    chronological = torch.cat((full, imu), dim=-1).permute(1, 0, 2)
    velocity, net.rnn_state = rnn(net.tran_b2, chronological.reshape(k * total, 1, -1), net.rnn_state)
    velocity = velocity.reshape(k, total, -1)[:, past]
    root = imu[past, :, -9:].reshape(k, 3, 3).cpu()
    pose = net._reduced_glb_6d_to_full_local_mat(root, reduced[past].cpu())
    feet = art.math.forward_kinematics(pose[:, joint_set.lower_body], net.lower_body_bone.expand(k, -1, -1),
                                       joint_set.lower_body_parent)[1][:, 7:9]
    contact = contact[past].sigmoid().cpu()
    tran_b2 = root.bmm(velocity.cpu().reshape(k, 3, 1)).view(k, 3) / 60 * tp.vel_scale
    for i in range(k):
        lfoot, rfoot = feet[i]
        if contact[i, 0] > contact[i, 1]:
            tran_b1 = net.last_lfoot_pos - lfoot + net.gravity_velocity
        else:
            tran_b1 = net.last_rfoot_pos - rfoot + net.gravity_velocity
        step = art.math.lerp(tran_b2[i], tran_b1, net._prob_to_weight(contact[i].max()))
        # Keep the feet above the floor.
        foot_y = net.current_root_y + min(lfoot[1].item(), rfoot[1].item())
        if foot_y + step[1].item() <= net.floor_y:
            step[1] = net.floor_y - foot_y
        net.current_root_y += step[1].item()
        net.last_lfoot_pos, net.last_rfoot_pos = lfoot, rfoot
        net.last_root_pos += step
    net.imu = window
    return pose[-1], net.last_root_pos.clone()


class Pose(NamedTuple):
    """One inferred pose."""
    joints: np.ndarray   # (24, 3) positions: pelvis origin plus the translation
    rotations: list      # 24 local rotations, row-major 3x3, rounded for sending
    translation: list    # 3 values, rounded for sending


class TransPoseRunner:
    _IMU_MASK  = [7, 8, 11, 12, 0, 2]
    BONE_TO_SLOT: dict[int, int] = {32:0, 42:1, 11:2, 21:3, 4:4, 2:5}

    def __init__(self, dip_subj='s_03', dip_clip=3):
        self._lock       = threading.Lock()
        self._status     = "Loading…"
        self._pose: Pose | None = None
        self._joints_version = 0
        self._faces: np.ndarray | None = None
        self._skin: dict | None = None  # SMPL skinning data for the page (smpl_fk.page_skin)
        self._mask_acc   = None
        self._mask_ori   = None
        self._mask_idx   = 0
        self._mask_source = "none"
        self._last_live_slots = set()
        # Live trackers are mapped into the SMPL frame once body calibration ran.
        self.body = body_calibration.BodyCalibration()
        self._calib_lock = threading.Lock()
        self._online_cnt = 0
        self._frame_ms = self._pose_fps = self._previous_frame_at = self._frame_interval = 0.0
        self._ready      = False
        self._origin_t: np.ndarray | None = None  # first-frame translation, subtracted from every frame
        self._net = self._fk = self._nac = self._device = None
        self._pending = deque(maxlen=MAX_FRAMES_PER_PASS)  # frames not yet given to the model
        self._input_frames = self._dropped_input_frames = self._batch_frames = 0
        self._stage_ms = {}
        self.on_new_frame = None  # called from the model's thread after each new pose
        threading.Thread(target=self._init, args=(dip_subj, dip_clip),
                         daemon=True, name='tp-init').start()

    @property
    def status(self):
        with self._lock:
            return self._status

    @property
    def faces(self):
        with self._lock:
            return self._faces

    @property
    def skin(self):
        with self._lock:
            return self._skin

    def _set_status(self, s):
        with self._lock:
            self._status = s

    def _format_stream_status(self, frame_no: int, live_count: int, mask_source: str,
                              uncalibrated: int = 0) -> str:
        suffix = f" · {uncalibrated} uncalibrated" if uncalibrated else ""
        if live_count >= 6:
            return f"Streaming #{frame_no} LIVE 6/6{suffix}"
        return f"Streaming #{frame_no} DEBUG mask={mask_source} live {live_count}/6{suffix}"

    def start_body_calibration(self):
        with self._calib_lock:
            self.body.start()

    def cancel_body_calibration(self):
        with self._calib_lock:
            self.body.cancel()

    def body_calibration_state(self):
        with self._calib_lock:
            return self.body.state()

    def get_pose_if_new(self, last_version: int):
        """Return (Pose, version) only if changed since last_version, else (None, last_version),
        so an unchanged pose is not sent again."""
        with self._lock:
            if self._pose is None or self._joints_version == last_version:
                return None, last_version
            return self._pose, self._joints_version

    def reset_origin(self):
        """Re-center the player: the next inferred frame's translation becomes (0,0,0)."""
        with self._lock:
            self._origin_t = None
    def get_runtime_stats(self):
        with self._lock:
            return self._runtime_stats_locked()

    def get_frame_if_new(self, last_version):
        """Capture pose, source status and diagnostics under the same lock."""
        with self._lock:
            fresh = self._pose is not None and self._joints_version != last_version
            return (self._pose if fresh else None,
                    self._joints_version if fresh else last_version,
                    self._status, self._runtime_stats_locked())

    def _runtime_stats_locked(self):
        device = getattr(self, '_device', None)
        return {'device': str(device) if device is not None else 'loading',
                    'pose_fps': round(getattr(self, '_pose_fps', 0.0), 1),
                    'frame_ms': round(getattr(self, '_frame_ms', 0.0), 1),
                    'torch_threads': _TORCH_THREADS,
                    'input_frames': getattr(self, '_input_frames', 0),
                    'dropped_input_frames': getattr(self, '_dropped_input_frames', 0),
                    'pending_frames': len(getattr(self, '_pending', ())),
                    'batch_frames': getattr(self, '_batch_frames', 0),
                    'model_process_cpu_ms': getattr(self, '_model_process_cpu_ms', 0.0),
                    'model_thread_cpu_ms': getattr(self, '_model_thread_cpu_ms', 0.0),
                    'cpu_latency_policy': dict(getattr(self, '_cpu_latency_policy', {})),
                    'stage_ms': dict(getattr(self, '_stage_ms', {}))}
    def _update_runtime_timing(self, started, completed):
        """Caller holds _lock. Smooth elapsed intervals before taking inverse;
        averaging instantaneous FPS overstates throughput for uneven frames.
        """
        self._frame_ms = max(0.0, (completed - started) * 1000)
        previous = getattr(self, '_previous_frame_at', 0.0)
        if previous and started - previous > 1.0:
            # Only time idle before this pass is a pause. A pass which itself
            # takes seconds must remain in the output-rate average.
            previous = self._frame_interval = 0.0
        if previous and completed > previous:
            interval = completed - previous
            smoothed = getattr(self, '_frame_interval', 0.0)
            self._frame_interval = interval if not smoothed else .8 * smoothed + .2 * interval
            self._pose_fps = 1 / self._frame_interval
        self._previous_frame_at = completed

    def push_frame(self, trackers: dict):
        if not self._ready or self._mask_acc is None:
            return
        N  = len(self._mask_acc)
        mi = self._mask_idx % N
        acc_f = self._mask_acc[mi].copy()
        ori_f = self._mask_ori[mi].copy()
        self._mask_idx += 1

        # Madgwick world frame: gravity = +Z = 9.81 m/s²
        # DIP imu_acc = gravity-free linear acceleration in global frame
        # Our firmware = raw accel (includes gravity) in local sensor frame
        # Fix: a_global_linear = R @ a_local - gravity_world
        _GRAVITY_WORLD = np.array([0.0, 0.0, 9.81], dtype=np.float32)
        live_slots, uncalibrated = set(), set()
        raw_frames, slot_ids = {}, {}

        for t in trackers.values():
            if not isinstance(t, dict): continue
            bone = t.get('assigned_bone')
            if not isinstance(bone, (int, np.integer)): continue
            slot = self.BONE_TO_SLOT.get(bone)
            if slot is None: continue
            accel = t.get('accel')
            quat  = t.get('rotation')
            try:
                age = float(t.get('last_update_ms', 0))
                a_local = np.asarray(accel, dtype=np.float32)
                q = np.asarray(quat, dtype=np.float64)
                norm = np.linalg.norm(q)
                if (not np.isfinite(age) or age < 0 or age > 500 or
                    a_local.shape != (3,) or q.shape != (4,) or
                    not np.isfinite(a_local).all() or not np.isfinite(q).all() or
                    not np.isfinite(norm) or norm < 1e-6): continue
                R = _Rot.from_quat(q).as_matrix().astype('float32')
                a_global = R @ a_local - _GRAVITY_WORLD
            except (TypeError, ValueError, OverflowError):
                continue
            tracker_id = t.get('id')
            if isinstance(tracker_id, (int, np.integer)):
                raw_frames[int(tracker_id)] = (R, a_global)
                slot_ids[slot] = int(tracker_id)
            # Raw frames are in the tracker's inertial frame (Z up) with the
            # sensor mounting included; TransPose needs the calibrated SMPL frame.
            with self._calib_lock:
                if isinstance(tracker_id, (int, np.integer)) and self.body.is_calibrated(int(tracker_id)):
                    R, a_global = self.body.apply(int(tracker_id), R, a_global)
                else:
                    uncalibrated.add(slot)
            acc_f[slot] = a_global
            ori_f[slot] = R
            live_slots.add(slot)
        with self._calib_lock:
            self.body.observe(raw_frames, slot_ids.get(5, slot_ids.get(4)))  # chest, else head

        # The recorded fallback can loop while real IMUs continue tracking.
        # Only demo/mixed input should recenter on that loop boundary.
        if mi == 0 and self._mask_idx > 1 and len(live_slots) < 6:
            with self._lock:
                self._origin_t = None

        with self._lock:
            self._last_live_slots = live_slots
            self._input_frames += 1
            if len(self._pending) == self._pending.maxlen:
                self._dropped_input_frames += 1
            self._pending.append((acc_f, ori_f, live_slots, len(uncalibrated)))

    def _init(self, subj, clip_idx):
        for problem in _PATH_PROBLEMS:
            print(f"[transpose_runner] {problem}")
        lacking = external_paths.missing(_PATHS)
        if lacking:
            # "Error:" marks the status as an error for the page; the rest is shown to people.
            self._set_status("Error: 缺少外部檔案：" + "；".join(f"{item.label}（{_PATHS[item.key]}）" for item in lacking) +
                             "。請在 external_paths.json 設定路徑（說明見 frontend/external_paths.py）。")
            return
        try:
            import pickle, torch
            torch.set_num_threads(_TORCH_THREADS)
            try:
                torch.set_num_interop_threads(1)
            except RuntimeError:
                pass
            device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
            latency_setting = os.environ.get('AETHER_WINDOWS_LATENCY', '1')
            policy = (configure_cpu_latency(enabled=latency_setting == '1') if device.type == 'cpu'
                      else {'applied': False, 'reason': 'cuda_device'})
            if latency_setting not in ('0', '1'):
                policy = {'applied': False, 'reason': 'AETHER_WINDOWS_LATENCY must be 0 or 1'}
            with self._lock:
                self._cpu_latency_policy = policy
            print(f'[transpose_runner] CPU latency policy: {policy}', flush=True)
            self._set_status("Loading mask…")

            # ── custom mask (.npz) ────────────────────────────────────────
            _npz_path = os.path.join(os.path.dirname(__file__), 'tpose_mask.npz')
            if os.path.exists(_npz_path):
                d = np.load(_npz_path)
                acc = d['imu_acc'].astype('float32')   # (N, 6, 3)
                ori = d['imu_ori'].astype('float32')   # (N, 6, 3, 3)
                with self._lock:
                    self._mask_acc = acc
                    self._mask_ori = ori
                    self._mask_source = "tpose"
                print(f"[mask] loaded custom: {_npz_path}  shape acc{acc.shape}")
            elif not os.path.isdir(os.path.join(_DIP_ROOT, subj)):
                # ── no DIP-IMU data: static T-pose (same as make_tpose_mask.py)
                acc = np.zeros((2000, 6, 3), dtype='float32')
                acc[:, :, 1] = 9.81
                ori = np.tile(np.eye(3, dtype='float32'), (2000, 6, 1, 1))
                with self._lock:
                    self._mask_acc = acc
                    self._mask_ori = ori
                    self._mask_source = "tpose"
                print(f"[mask] DIP-IMU data not found at {_DIP_ROOT}; using a static T-pose")
            else:
                # ── DIP dataset mask ──────────────────────────────────────
                subj_dir  = os.path.join(_DIP_ROOT, subj)
                pkl_files = sorted(f for f in os.listdir(subj_dir) if f.endswith('.pkl'))
                path      = os.path.join(subj_dir, pkl_files[clip_idx])
                import warnings; warnings.filterwarnings('ignore')
                data = pickle.load(open(path, 'rb'), encoding='latin1')
                acc  = data['imu_acc'][:, self._IMU_MASK].astype('float32')
                ori  = data['imu_ori'][:, self._IMU_MASK].astype('float32')
                at, ot = torch.from_numpy(acc), torch.from_numpy(ori)
                for _ in range(4):
                    at[1:].masked_scatter_(torch.isnan(at[1:]),   at[:-1][torch.isnan(at[1:])])
                    ot[1:].masked_scatter_(torch.isnan(ot[1:]),   ot[:-1][torch.isnan(ot[1:])])
                    at[:-1].masked_scatter_(torch.isnan(at[:-1]), at[1:][torch.isnan(at[:-1])])
                    ot[:-1].masked_scatter_(torch.isnan(ot[:-1]), ot[1:][torch.isnan(ot[:-1])])
                with self._lock:
                    self._mask_acc = at.numpy()
                    self._mask_ori = ot.numpy()
                    self._mask_source = "dip_imu"

            self._set_status("Loading TransPose model…")
            import config as tp_cfg
            tp_cfg.paths.smpl_file    = _SMPL_PKL
            tp_cfg.paths.weights_file = _TP_WEIGHTS
            from net import TransPoseNet
            from utils import normalize_and_concat
            from smpl_fk import SMPLForwardKinematics

            net = TransPoseNet().to(device); net.reset(); net.eval()
            fk  = SMPLForwardKinematics(_SMPL_NPZ)
            with self._lock:
                self._net  = net
                self._fk   = fk
                self._faces = fk.faces.astype(np.int32)
                self._skin = fk.page_skin()
                self._nac  = normalize_and_concat
                self._device = device
                self._pending.clear()
                self._ready = True
                mask_source = self._mask_source
            self._set_status(
                f"Ready ({device.type}; torch threads={torch.get_num_threads()}; "
                f"debug mask={mask_source}; validation needs LIVE 6/6)"
            )
            threading.Thread(target=self._inference_loop, daemon=True, name='tp-online').start()
        except Exception as e:
            self._set_status(f"Error: {e}")

    def _inference_loop(self):
        import torch
        while True:
            with self._lock:
                frames = list(self._pending)
                self._pending.clear()
                net, fk, nac = self._net, self._fk, self._nac
            if not frames or not self._ready:
                time.sleep(0.005); continue
            _, _, live_slots, uncalibrated = frames[-1]
            try:
                t0 = time.perf_counter()
                device = self._device or torch.device('cpu')
                acc_t = torch.from_numpy(np.stack([f[0] for f in frames])).to(device, non_blocking=True)
                ori_t = torch.from_numpy(np.stack([f[1] for f in frames])).to(device, non_blocking=True)
                xs = nac(acc_t, ori_t)
                t1 = time.perf_counter()
                process_cpu_start, thread_cpu_start = time.process_time(), time.thread_time()
                with torch.inference_mode():
                    pose, tran = forward_online_frames(net, xs)
                process_cpu_ms = (time.process_time()-process_cpu_start)*1000
                thread_cpu_ms = (time.thread_time()-thread_cpu_start)*1000
                t2 = time.perf_counter()
                R_np = pose.detach().cpu().numpy()
                t_np = tran.detach().cpu().numpy()
                t3 = time.perf_counter()
                # Recorded clips (e.g. the DIP dataset fallback) carry whatever
                # absolute position the subject happened to be at in the
                # original capture volume — often far from the origin. Lock
                # onto the first frame's position and subtract it from every
                # frame after, so playback starts near (0,0,0) and stays
                # in view while keeping the motion itself untouched.
                with self._lock:
                    if self._origin_t is None:
                        self._origin_t = t_np.copy()
                        print(f"[transpose_runner] origin_t captured: {self._origin_t}")
                    origin_t = self._origin_t.copy()
                t_np = t_np - origin_t
                aa     = _Rot.from_matrix(R_np).as_rotvec().reshape(1, 72).astype('float32')
                joints = fk.forward(aa)[0]
                joints -= joints[0:1]; joints += t_np
                # The page skins the mesh from these (webui/skinning.js); 1e-5 is far below a millimetre.
                # Rounded as float64: rounded float32 values still print with about 17 digits.
                pose = Pose(joints, np.round(R_np.astype(np.float64), 5).ravel().tolist(),
                            np.round(t_np.astype(np.float64), 5).ravel().tolist())
                t4 = time.perf_counter()

                self._online_cnt += 1
                frame_no = self._online_cnt
                with self._lock:
                    self._pose = pose
                    self._update_runtime_timing(t0, t4)
                    self._batch_frames = len(frames)
                    self._model_process_cpu_ms = round(process_cpu_ms, 2)
                    self._model_thread_cpu_ms = round(thread_cpu_ms, 2)
                    self._stage_ms = {'prepare': round((t1-t0)*1000, 2),
                                      'model': round((t2-t1)*1000, 2),
                                      'copy': round((t3-t2)*1000, 2),
                                      'kinematics': round((t4-t3)*1000, 2)}
                    self._joints_version += 1
                    mask_source = self._mask_source
                    # Publish matching source status before waking the sender;
                    # otherwise the first pose can still be labelled Ready.
                    self._status = self._format_stream_status(
                        self._online_cnt, len(live_slots), mask_source, uncalibrated)

                self._notify_new_frame()
                if _PERF_LOG and frame_no % _PERF_LOG_EVERY == 0:
                    total_ms = (time.perf_counter() - t0) * 1000
                    print(
                        "[transpose_runner] perf "
                        f"#{frame_no}: frames={len(frames)} prep={(t1 - t0) * 1000:.1f}ms "
                        f"model={(t2 - t1) * 1000:.1f}ms "
                        f"copy={(t3 - t2) * 1000:.1f}ms "
                        f"fk={(t4 - t3) * 1000:.1f}ms "
                        f"total={total_ms:.1f}ms",
                        flush=True,
                    )
            except Exception as e:
                self._set_status(f"Infer err: {e}")

    def _notify_new_frame(self):
        callback = self.on_new_frame
        if callback is not None:
            try:
                callback()
            except RuntimeError:  # the event loop has closed: the service is stopping
                pass
