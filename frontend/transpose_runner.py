"""
TransPoseRunner — the neural-net (TransPose) full-body pose/mesh estimator.

Shared by:
  main.py       — the native Open3D app (imports it directly)
  mesh_bridge.py — a headless service with no window at all, for the web UI
"""

import os, sys, time, threading
_TORCH_THREADS = int(os.environ.get("AETHER_TORCH_THREADS", "2"))
_PERF_LOG = os.environ.get("AETHER_PERF_LOG", "0") == "1"
_PERF_LOG_EVERY = max(1, int(os.environ.get("AETHER_PERF_LOG_EVERY", "30")))
for _thread_var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_thread_var, str(_TORCH_THREADS))

import numpy as np
from scipy.spatial.transform import Rotation as _Rot

# ── Paths ─────────────────────────────────────────────────────────────────────
_BONE_DATA_DIR = r'C:\Users\20050\OneDrive\桌面\bone_data_anylasis'
_TRANSPOSE_DIR = r'D:\Download\TransPose\TransPose-main'
_SMPL_NPZ      = r'D:\Download\SMPL_MALE.npz'
_SMPL_PKL      = r'D:\Download\SMPL_MALE.pkl'
_TP_WEIGHTS    = r'D:\Download\weights.pt'
_DIP_ROOT      = r'D:\Download\DIPIMUandOthers\DIP_IMU_and_Others\DIP_IMU\DIP_IMU'

for _p in (_BONE_DATA_DIR, _TRANSPOSE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SMPL_BONES = [
    (0,1),(0,2),(0,3),(1,4),(2,5),(3,6),(4,7),(5,8),(6,9),
    (7,10),(8,11),(9,12),(9,13),(9,14),(12,15),(13,16),(14,17),
    (16,18),(17,19),(18,20),(19,21),(20,22),(21,23),
]
SMPL_LEFT  = {1,4,7,10,13,16,18,20,22}
SMPL_RIGHT = {2,5,8,11,14,17,19,21,23}


class TransPoseRunner:
    _IMU_MASK  = [7, 8, 11, 12, 0, 2]
    MESH_EVERY = int(os.environ.get("AETHER_MESH_EVERY", "4"))
    BONE_TO_SLOT: dict[int, int] = {32:0, 42:1, 11:2, 21:3, 4:4, 2:5}

    def __init__(self, dip_subj='s_03', dip_clip=3):
        self._lock       = threading.Lock()
        self._status     = "Loading…"
        self._joints     = None
        self._joints_version = 0
        self._latest_verts: np.ndarray | None = None
        self._verts_version = 0
        self._faces: np.ndarray | None = None
        self._mask_acc   = None
        self._mask_ori   = None
        self._mask_idx   = 0
        self._mask_source = "none"
        self._last_live_slots = set()
        self._online_cnt = 0
        self._mesh_busy  = False
        self._ready      = False
        self._origin_t: np.ndarray | None = None  # first-frame translation, subtracted from every frame
        self._net = self._fk = self._nac = self._pending = self._device = None
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

    def _set_status(self, s):
        with self._lock:
            self._status = s

    def _format_stream_status(self, frame_no: int, live_count: int, mask_source: str) -> str:
        if live_count >= 6:
            return f"Streaming #{frame_no} LIVE 6/6"
        return f"Streaming #{frame_no} DEBUG mask={mask_source} live {live_count}/6"

    def get_joints_if_new(self, last_version: int):
        """Return (joints, version) only if changed since last_version, else (None, last_version).
        Avoids re-uploading identical geometry to the GPU/wire every frame."""
        with self._lock:
            if self._joints is None or self._joints_version == last_version:
                return None, last_version
            return self._joints.copy(), self._joints_version

    def reset_origin(self):
        """Re-center the player: the next inferred frame's translation becomes (0,0,0)."""
        with self._lock:
            self._origin_t = None

    def get_latest_verts_if_new(self, last_version: int):
        with self._lock:
            if self._latest_verts is None or self._verts_version == last_version:
                return None, last_version
            return self._latest_verts.copy(), self._verts_version

    def push_frame(self, trackers: dict):
        if not self._ready or self._mask_acc is None:
            return
        N  = len(self._mask_acc)
        mi = self._mask_idx % N
        if mi == 0 and self._mask_idx > 0:
            # The clip just looped back to its start — recapture the origin
            # on the next frame so a demo left running doesn't keep drifting
            # further from center every pass (real walking motion within one
            # pass is fine and expected; it's the repeat that would add up).
            with self._lock:
                self._origin_t = None
        acc_f = self._mask_acc[mi].copy()
        ori_f = self._mask_ori[mi].copy()
        self._mask_idx += 1

        # Madgwick world frame: gravity = +Z = 9.81 m/s²
        # DIP imu_acc = gravity-free linear acceleration in global frame
        # Our firmware = raw accel (includes gravity) in local sensor frame
        # Fix: a_global_linear = R @ a_local - gravity_world
        _GRAVITY_WORLD = np.array([0.0, 0.0, 9.81], dtype=np.float32)
        live_slots = set()

        for t in trackers.values():
            bone = t.get('assigned_bone')
            slot = self.BONE_TO_SLOT.get(bone)
            if slot is None: continue
            accel = t.get('accel')
            quat  = t.get('rotation')
            if accel and quat:
                R = _Rot.from_quat(
                    np.array(quat, dtype=np.float64)).as_matrix().astype('float32')
                a_local  = np.array(accel, dtype=np.float32)   # local frame, includes gravity
                a_global = R @ a_local - _GRAVITY_WORLD         # gravity-free global frame
                acc_f[slot] = a_global
                ori_f[slot] = R
                live_slots.add(slot)

        with self._lock:
            self._last_live_slots = live_slots
            self._pending = (acc_f, ori_f, live_slots)

    def _init(self, subj, clip_idx):
        try:
            import pickle, torch
            torch.set_num_threads(_TORCH_THREADS)
            try:
                torch.set_num_interop_threads(1)
            except RuntimeError:
                pass
            device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
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
            from dip_loader import SMPLForwardKinematics

            net = TransPoseNet().to(device); net.reset(); net.eval()
            fk  = SMPLForwardKinematics(_SMPL_NPZ)
            with self._lock:
                self._net  = net
                self._fk   = fk
                self._faces = fk.faces.astype(np.int32)
                self._nac  = normalize_and_concat
                self._device = device
                self._pending = None
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
                pending = getattr(self, '_pending', None)
                self._pending = None
                net, fk, nac = self._net, self._fk, self._nac
            if pending is None or not self._ready:
                time.sleep(0.005); continue
            acc_f, ori_f, live_slots = pending
            try:
                t0 = time.perf_counter()
                device = self._device or torch.device('cpu')
                acc_t = torch.from_numpy(acc_f[None]).to(device, non_blocking=True)
                ori_t = torch.from_numpy(ori_f[None]).to(device, non_blocking=True)
                x = nac(acc_t, ori_t)[0]
                t1 = time.perf_counter()
                with torch.inference_mode():
                    pose, tran = net.forward_online(x)
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
                t_np = t_np - self._origin_t
                aa     = _Rot.from_matrix(R_np).as_rotvec().reshape(1, 72).astype('float32')
                joints = fk.forward(aa)[0]
                joints -= joints[0:1]; joints += t_np
                t4 = time.perf_counter()

                self._online_cnt += 1
                do_mesh = False
                frame_no = self._online_cnt
                with self._lock:
                    self._joints = joints
                    self._joints_version += 1
                    if self._online_cnt % self.MESH_EVERY == 0 and not self._mesh_busy:
                        self._mesh_busy = True
                        do_mesh = True
                    mask_source = self._mask_source

                if do_mesh:
                    threading.Thread(target=self._compute_mesh,
                                     args=(R_np.copy(), t_np.copy(), frame_no),
                                     daemon=True, name='tp-mesh').start()
                self._set_status(self._format_stream_status(
                    self._online_cnt, len(live_slots), mask_source))
                if _PERF_LOG and frame_no % _PERF_LOG_EVERY == 0:
                    total_ms = (time.perf_counter() - t0) * 1000
                    print(
                        "[transpose_runner] perf "
                        f"#{frame_no}: prep={(t1 - t0) * 1000:.1f}ms "
                        f"model={(t2 - t1) * 1000:.1f}ms "
                        f"copy={(t3 - t2) * 1000:.1f}ms "
                        f"fk={(t4 - t3) * 1000:.1f}ms "
                        f"total={total_ms:.1f}ms mesh_every={self.MESH_EVERY}",
                        flush=True,
                    )
            except Exception as e:
                self._set_status(f"Infer err: {e}")

    def _compute_mesh(self, R_24x3x3, tran, frame_no):
        try:
            t0 = time.perf_counter()
            with self._lock:
                fk = self._fk
            verts = fk.lbs_frame(R_24x3x3).astype(np.float32)
            verts -= verts[0:1]
            verts += tran.astype(np.float32)
            mesh_ms = (time.perf_counter() - t0) * 1000
            with self._lock:
                self._latest_verts = verts
                self._verts_version += 1
                self._mesh_busy    = False
            if _PERF_LOG:
                print(
                    f"[transpose_runner] perf mesh #{frame_no}: "
                    f"lbs={mesh_ms:.1f}ms",
                    flush=True,
                )
        except Exception:
            with self._lock:
                self._mesh_busy = False
