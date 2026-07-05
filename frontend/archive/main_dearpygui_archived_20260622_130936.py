"""
Aetherpose — Python frontend (Dear PyGui)
  Calibration → left: aetherpose IK skeleton (real-time)
                right: TransPose DIP-IMU skeleton (background inference)
  Monitor     → tracker table
  Body        → motion settings groups
  System      → OSC / serial / recording
"""

import math
import multiprocessing as mp
import os
import sys
import time
import threading
import numpy as np
import dearpygui.dearpygui as dpg
from PIL import Image, ImageDraw
from ws_client import WsClient
import live_o3d

# ── TransPose / DIP paths ──────────────────────────────────────────────────────
_BONE_DATA_DIR = r'C:\Users\20050\OneDrive\桌面\bone_data_anylasis'
_TRANSPOSE_DIR = r'D:\Download\TransPose\TransPose-main'
_SMPL_NPZ      = r'D:\Download\SMPL_MALE.npz'
_SMPL_PKL      = r'D:\Download\SMPL_MALE.pkl'
_TP_WEIGHTS    = r'D:\Download\weights.pt'
_DIP_ROOT      = r'D:\Download\DIPIMUandOthers\DIP_IMU_and_Others\DIP_IMU\DIP_IMU'

for _p in (_BONE_DATA_DIR, _TRANSPOSE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scipy.spatial.transform import Rotation as _Rot

# ── Open3D viewer (separate process, starts with T-pose) ──────────────────────

class Open3DViewer:
    def __init__(self):
        self._queue: mp.Queue | None = None
        self._proc:  mp.Process | None = None

    def start(self, v_template: np.ndarray, faces: np.ndarray) -> None:
        self._queue = mp.Queue(maxsize=2)
        self._proc  = mp.Process(
            target=live_o3d.run,
            args=(self._queue, v_template.copy(), faces.copy()),
            daemon=True)
        self._proc.start()

    def send(self, verts: np.ndarray, faces: np.ndarray) -> None:
        if self._queue is None:
            return
        try:
            self._queue.put_nowait((verts.copy(), faces.copy()))
        except Exception:
            pass

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.is_alive()


# ── Software SMPL mesh renderer (PIL, no OpenGL needed) ───────────────────────
# Pre-sampled face indices: every 17th face of SMPL (800 faces → ~5ms vs 80ms)
_RENDER_STRIDE = 17

def _smpl_render_pil(verts: np.ndarray, faces: np.ndarray,
                     W: int, H: int, yaw: float, pitch: float) -> np.ndarray:
    """Depth-sorted painter render using pre-sampled faces. ~5ms for SMPL."""
    img  = Image.new('RGB', (W, H), (18, 24, 33))
    draw = ImageDraw.Draw(img)
    cx, cy = W / 2, H / 2
    scale  = min(W, H) * 0.52

    sy_, cy_ = np.sin(yaw),   np.cos(yaw)
    sp,  cp  = np.sin(pitch), np.cos(pitch)
    x    =  verts[:,0]*cy_ - verts[:,2]*sy_
    z    =  verts[:,0]*sy_ + verts[:,2]*cy_
    yrot =  verts[:,1]*cp  - z*sp
    zrot =  verts[:,1]*sp  + z*cp
    sx   = cx + x    * scale
    sy   = cy - yrot * scale

    fd    = zrot[faces].mean(axis=1)
    order = np.argsort(fd)

    v0 = verts[faces[:,0]]; v1 = verts[faces[:,1]]; v2 = verts[faces[:,2]]
    n  = np.cross(v1-v0, v2-v0)
    nl = np.linalg.norm(n, axis=1, keepdims=True)
    n /= np.where(nl < 1e-8, 1e-8, nl)
    light = np.array([0.3, 1.0, 0.5], np.float32); light /= np.linalg.norm(light)
    shade = np.clip(n @ light, 0.15, 1.0)
    BASE  = np.array([200, 155, 110], np.float32)

    fsx = sx[faces]; fsy = sy[faces]
    for i in order:
        c = (shade[i] * BASE).astype(np.uint8)
        pts = list(zip(fsx[i].tolist(), fsy[i].tolist()))
        draw.polygon(pts, fill=(int(c[0]), int(c[1]), int(c[2])))

    return np.array(img)

WS_URL = "ws://127.0.0.1:9009/ws"

BONE_NAMES: dict[int, str] = {
    0: "Hip", 1: "Waist", 2: "Chest", 3: "Neck", 4: "Head",
    10: "L_UpLeg", 11: "L_Leg", 12: "L_Foot",
    20: "R_UpLeg", 21: "R_Leg", 22: "R_Foot",
    30: "L_Shoulder", 31: "L_UpperArm", 32: "L_ForeArm", 33: "L_Hand",
    40: "R_Shoulder", 41: "R_UpperArm", 42: "R_ForeArm", 43: "R_Hand",
}
BONE_ITEMS = [f"{k}: {v}" for k, v in BONE_NAMES.items()]

LEFT_BONE_IDS  = {10, 11, 12, 30, 31, 32, 33}
RIGHT_BONE_IDS = {20, 21, 22, 40, 41, 42, 43}

# SMPL (24 joints)
SMPL_BONES = [
    (0,1),(0,2),(0,3),(1,4),(2,5),(3,6),(4,7),(5,8),(6,9),
    (7,10),(8,11),(9,12),(9,13),(9,14),(12,15),(13,16),(14,17),
    (16,18),(17,19),(18,20),(19,21),(20,22),(21,23),
]
SMPL_LEFT  = {1,4,7,10,13,16,18,20,22}
SMPL_RIGHT = {2,5,8,11,14,17,19,21,23}

SMPL_LABELS = {0:"Pelvis", 4:"Head", 7:"L.Ankle", 8:"R.Ankle"}

DARK = {
    "window_bg":    (18,  24,  33),
    "child_bg":     (24,  30,  40),
    "btn":          (64, 160, 255),
    "btn_hov":      (90, 180, 255),
    "btn_act":      (40, 120, 200),
    "header":       (64, 160, 255, 100),
    "header_hov":   (64, 160, 255, 160),
    "tab":          (24,  30,  40),
    "tab_active":   (64, 160, 255),
    "title":        (18,  24,  33),
    "title_active": (24,  30,  40),
    "text":         (220, 225, 235),
    "text_weak":    (130, 135, 145),
    "separator":    (60,  68,  85),
    "frame_bg":     (40,  44,  52),
    "frame_hov":    (50,  55,  65),
    "frame_act":    (60,  65,  75),
    "accent":       (64, 160, 255),
    "tp_accent":    (255, 175, 90),
    "col_spine":    (200, 210, 220, 255),
    "col_left":     (0,   200, 200, 255),
    "col_right":    (255, 175, 90,  255),
    "col_joint":    (64,  160, 255, 255),
    "col_tracked":  (90,  220, 100, 255),
    "col_tp_joint": (255, 175, 90,  255),
}


# ── 3-D projection ─────────────────────────────────────────────────────────────

def project_bone(pos, yaw, pitch, cx, cy, scale):
    x, y, z = pos
    c, s = math.cos(yaw), math.sin(yaw)
    x, z = x*c + z*s, -x*s + z*c
    c, s = math.cos(pitch), math.sin(pitch)
    y, z = y*c - z*s, y*s + z*c
    return cx + x * scale, cy - y * scale


# ── TransPose background runner ────────────────────────────────────────────────

class TransPoseRunner:
    """
    Loads TransPose model + DIP mask data in a background thread.
    Every STEP new frames, runs forward_offline on a rolling WIN-frame window
    and stores the latest (24, 3) SMPL joint positions.
    """
    _IMU_MASK  = [7, 8, 11, 12, 0, 2]
    MESH_EVERY = 20   # render mesh every N inference steps (~2fps at 40Hz inference)
    BONE_TO_SLOT: dict[int, int] = {32: 0, 42: 1, 11: 2, 21: 3, 4: 4, 2: 5}

    def __init__(self, dip_subj: str = 's_01', dip_clip: int = 0):
        self._lock       = threading.Lock()
        self._status     = "Loading…"
        self._joints    = None
        self._mesh_img: np.ndarray | None = None
        self._o3d_viewer: Open3DViewer | None = None
        self._mask_acc   = None
        self._mask_ori   = None
        self._mask_idx   = 0
        self._online_cnt = 0
        self._mesh_busy  = False
        self._ready      = False
        self._net        = None
        self._fk         = None
        self._nac        = None
        threading.Thread(target=self._init,
                         args=(dip_subj, dip_clip),
                         daemon=True, name='tp-init').start()

    # ── public ────────────────────────────────────────────────────────────────

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    def get_joints(self):
        with self._lock:
            return self._joints.copy() if self._joints is not None else None


    def push_frame(self, trackers: dict):
        """
        Called every frame from main thread — maps all connected trackers to their
        TransPose slots via BONE_TO_SLOT, then enqueues for inference.
        Non-blocking: inference runs in its own background thread.
        """
        if not self._ready or self._mask_acc is None:
            return

        N  = len(self._mask_acc)
        mi = self._mask_idx % N
        acc_f = self._mask_acc[mi].copy()
        ori_f = self._mask_ori[mi].copy()
        self._mask_idx += 1

        live_slots = []
        for t in trackers.values():
            bone = t.get('assigned_bone')
            slot = self.BONE_TO_SLOT.get(bone)
            if slot is None:
                continue
            accel = t.get('accel')
            quat  = t.get('rotation')
            if accel and quat:
                R = _Rot.from_quat(np.array(quat, dtype=np.float64)).as_matrix().astype('float32')
                a_local  = np.array(accel, dtype=np.float32)
                a_global = R @ a_local - np.array([0.0, 0.0, 9.81], np.float32)
                acc_f[slot] = a_global
                ori_f[slot] = R
                live_slots.append(slot)

        if self._mask_idx % 60 == 1:
            ids   = [t.get('id') for t in trackers.values()]
            bones = [t.get('assigned_bone') for t in trackers.values()]
            print(f"[tp] trackers={ids} bones={bones} live_slots={live_slots}")

        with self._lock:
            # Keep only latest frame — inference thread drains this
            self._pending = (acc_f, ori_f)

    def _inference_loop(self):
        """Background thread: continuously drains _pending and runs forward_online."""
        import torch
        while True:
            with self._lock:
                pending  = getattr(self, '_pending', None)
                self._pending = None
                net, fk, nac = self._net, self._fk, self._nac

            if pending is None or not self._ready:
                time.sleep(0.005)
                continue

            acc_f, ori_f = pending
            try:
                x = nac(torch.from_numpy(acc_f[None]),
                        torch.from_numpy(ori_f[None]))[0]   # (72,)

                pose, tran = net.forward_online(x)   # (24,3,3), (3,)

                R_np = pose.numpy()
                t_np = tran.numpy()

                aa     = _Rot.from_matrix(R_np).as_rotvec().reshape(1, 72).astype('float32')
                joints = fk.forward(aa)[0]
                joints -= joints[0:1]
                joints += t_np

                self._online_cnt += 1
                do_mesh = False
                with self._lock:
                    self._joints = joints
                    if (self._online_cnt % self.MESH_EVERY == 0
                            and not self._mesh_busy):
                        self._mesh_busy = True
                        do_mesh = True

                if do_mesh and self._ready:
                    threading.Thread(target=self._send_mesh_async,
                                     args=(R_np.copy(), t_np.copy()),
                                     daemon=True, name='tp-mesh').start()

                self._set_status(f"Streaming #{self._online_cnt}")

            except Exception as e:
                self._set_status(f"Infer err: {e}")

    # ── private ───────────────────────────────────────────────────────────────

    def _set_status(self, s: str):
        with self._lock:
            self._status = s

    def _init(self, subj: str, clip_idx: int):
        try:
            import pickle, torch
            self._set_status("Loading DIP mask…")
            subj_dir  = os.path.join(_DIP_ROOT, subj)
            pkl_files = sorted(f for f in os.listdir(subj_dir) if f.endswith('.pkl'))
            path      = os.path.join(subj_dir, pkl_files[clip_idx])
            data      = pickle.load(open(path, 'rb'), encoding='latin1')

            acc = data['imu_acc'][:, self._IMU_MASK].astype('float32')
            ori = data['imu_ori'][:, self._IMU_MASK].astype('float32')
            at, ot = torch.from_numpy(acc), torch.from_numpy(ori)
            for _ in range(4):
                at[1:].masked_scatter_(torch.isnan(at[1:]),   at[:-1][torch.isnan(at[1:])])
                ot[1:].masked_scatter_(torch.isnan(ot[1:]),   ot[:-1][torch.isnan(ot[1:])])
                at[:-1].masked_scatter_(torch.isnan(at[:-1]), at[1:][torch.isnan(at[:-1])])
                ot[:-1].masked_scatter_(torch.isnan(ot[:-1]), ot[1:][torch.isnan(ot[:-1])])
            with self._lock:
                self._mask_acc = at.numpy()
                self._mask_ori = ot.numpy()

            self._set_status("Loading TransPose model…")
            import config as tp_cfg
            tp_cfg.paths.smpl_file    = _SMPL_PKL
            tp_cfg.paths.weights_file = _TP_WEIGHTS
            from net import TransPoseNet
            from utils import normalize_and_concat
            from dip_loader import SMPLForwardKinematics

            net = TransPoseNet()
            net.reset()
            fk = SMPLForwardKinematics(_SMPL_NPZ)
            with self._lock:
                self._net     = net
                self._fk      = fk
                self._nac     = normalize_and_concat
                self._pending = None
                self._ready   = True

            self._set_status("Ready — streaming starts now")

            # Start inference loop in its own thread
            threading.Thread(target=self._inference_loop,
                             daemon=True, name='tp-online').start()

        except Exception as e:
            self._set_status(f"Error: {e}")

    def get_mesh_img(self) -> 'np.ndarray | None':
        with self._lock:
            return self._mesh_img

    def _send_mesh_async(self, R_24x3x3: np.ndarray, tran: np.ndarray):
        """Compute LBS vertices and send to Open3D viewer process."""
        try:
            with self._lock:
                fk     = self._fk
                viewer = self._o3d_viewer

            verts = fk.lbs_frame(R_24x3x3).astype(np.float32)
            verts -= verts[0:1]
            verts += tran.astype(np.float32)

            if viewer is not None and viewer.running:
                viewer.send(verts, fk.faces.astype(np.int32))

            with self._lock:
                self._mesh_busy = False
        except Exception as e:
            with self._lock:
                self._mesh_busy = False
            self._set_status(f"Mesh err: {e}")



# ── App ───────────────────────────────────────────────────────────────────────

class App:
    def __init__(self):
        self.ws = WsClient(WS_URL)
        self.snapshot: dict = {}

        # Camera (shared between both canvases)
        self._yaw:         float = 0.436
        self._pitch:       float = 0.175
        self._zoom:        float = 1.0
        self._scroll_delta: float = 0.0
        self._drag_last    = None

        self._mon_rows: set[int] = set()
        self._tp: TransPoseRunner | None = None


    # ── command ───────────────────────────────────────────────────────────────

    def _cmd(self, cmd) -> None:
        self.ws.send_command(cmd)

    # ── message ───────────────────────────────────────────────────────────────

    def _apply_message(self, msg: dict) -> None:
        t = msg.get("type")
        data = msg.get("data", {})
        if t == "Snapshot":
            self.snapshot = data
        elif t == "Status":
            self.snapshot["serial_running"]    = data.get("serial_running", False)
            self.snapshot["serial_status_msg"] = data.get("serial_status_msg")

    # ── UI: Calibration tab ───────────────────────────────────────────────────

    def _build_calibration_tab(self) -> None:
        with dpg.group(horizontal=True):
            dpg.add_text("Skeleton Preview", color=DARK["accent"])
            dpg.add_spacer(width=12)
            dpg.add_button(label="Reset Yaw",
                           callback=lambda: self._cmd("ResetYaw"))
            dpg.add_button(label="Reset Mounting",
                           callback=lambda: self._cmd("ResetMounting"))
            dpg.add_button(label="Auto Assign",
                           callback=lambda: self._cmd("AutoAssign"))
            dpg.add_button(label="Reset View",
                           callback=self._reset_camera)
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_text("← Aetherpose IK  |  TransPose DIP-IMU →",
                         color=DARK["text_weak"])
        dpg.add_spacer(height=2)

        # ── Two side-by-side canvases (PIL texture approach) ─────────────────
        with dpg.group(horizontal=True):
            # Left: aetherpose IK  (explicit width, fill height)
            with dpg.child_window(tag="cal_left_win", border=True,
                                   width=680, height=-1, no_scrollbar=True):
                dpg.add_text("Aetherpose IK", color=DARK["accent"])
                dpg.add_drawlist(tag="skel_canvas", width=670, height=480)

            # Right: TransPose DIP  (fill remaining width and height)
            with dpg.child_window(tag="cal_right_win", border=True,
                                   height=-1, no_scrollbar=True):
                with dpg.group(horizontal=True):
                    dpg.add_text("TransPose", color=DARK["tp_accent"])
                    dpg.add_spacer(width=8)
                    dpg.add_text("Loading…", tag="tp_status",
                                 color=DARK["text_weak"])
                dpg.add_drawlist(tag="tp_canvas", width=500, height=480)

    # ── UI: Monitor tab ───────────────────────────────────────────────────────

    def _build_monitor_tab(self) -> None:
        with dpg.group(horizontal=True):
            dpg.add_text("Packets: 0", tag="mon_header", color=DARK["text_weak"])
            dpg.add_spacer(width=16)
            dpg.add_button(label="Auto Assign",
                           callback=lambda: self._cmd("AutoAssign"))
        dpg.add_separator()
        with dpg.table(
            tag="mon_table", header_row=True,
            resizable=True, policy=dpg.mvTable_SizingStretchProp,
            borders_outerH=True, borders_innerV=True,
            borders_innerH=True, borders_outerV=True,
            scrollY=True, height=-1,
            row_background=True,
        ):
            dpg.add_table_column(label="ID",     width_fixed=True, init_width_or_weight=44)
            dpg.add_table_column(label="Bone")
            dpg.add_table_column(label="Status", width_fixed=True, init_width_or_weight=110)
            dpg.add_table_column(label="Type",   width_fixed=True, init_width_or_weight=64)
            dpg.add_table_column(label="Batt",   width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(label="TPS",    width_fixed=True, init_width_or_weight=52)
            dpg.add_table_column(label="Loss%",  width_fixed=True, init_width_or_weight=62)
            dpg.add_table_column(label="RSSI",   width_fixed=True, init_width_or_weight=80)
            dpg.add_table_column(label="Assign")

    # ── UI: Body tab ──────────────────────────────────────────────────────────

    def _build_body_tab(self) -> None:
        def _section(title: str, height: int):
            dpg.add_spacer(height=6)
            return dpg.child_window(border=True, height=height, no_scrollbar=True)

        dpg.add_text("Body Motion", color=DARK["accent"])
        dpg.add_separator()

        with dpg.child_window(border=True, height=162, no_scrollbar=True):
            dpg.add_text("Body Proportions", color=DARK["accent"])
            dpg.add_text("Scale limb lengths relative to default rig.", color=DARK["text_weak"])
            dpg.add_spacer(height=2)
            dpg.add_slider_float(label="IK Smoothness", tag="prop_ik",
                                 min_value=0.0, max_value=1.0, default_value=0.5, width=-1,
                                 callback=lambda s, a: self._cmd({"SetIkSmoothness": a}))
            dpg.add_slider_float(label="Legs",  tag="prop_leg",
                                 min_value=0.5, max_value=1.5, default_value=1.0, width=-1,
                                 callback=self._on_proportions_change)
            dpg.add_slider_float(label="Arms",  tag="prop_arm",
                                 min_value=0.5, max_value=1.5, default_value=1.0, width=-1,
                                 callback=self._on_proportions_change)
            dpg.add_slider_float(label="Spine", tag="prop_spine",
                                 min_value=0.5, max_value=1.5, default_value=1.0, width=-1,
                                 callback=self._on_proportions_change)

        with _section("One Euro Filter", 106):
            dpg.add_text("One Euro Filter", color=DARK["accent"])
            dpg.add_slider_float(label="Min Cutoff", tag="smooth_cutoff",
                                 min_value=0.01, max_value=5.0, default_value=1.0, width=-1,
                                 callback=self._on_smoothing_change)
            dpg.add_text("Lower = smoother, more lag.", color=DARK["text_weak"])
            dpg.add_slider_float(label="Beta", tag="smooth_beta",
                                 min_value=0.0, max_value=2.0, default_value=0.01, width=-1,
                                 callback=self._on_smoothing_change)

        with _section("Trajectory", 72):
            dpg.add_text("Trajectory Integrator", color=DARK["accent"])
            dpg.add_spacer(height=4)
            with dpg.group(horizontal=True):
                dpg.add_button(label="EKF + RK4",
                               callback=lambda: self._cmd({"SetTrajectoryIntegrationMode": "rk4"}))
                dpg.add_button(label="EKF + Euler",
                               callback=lambda: self._cmd({"SetTrajectoryIntegrationMode": "euler"}))

        with _section("Auto Skeleton", 82):
            dpg.add_text("Auto Skeleton", color=DARK["accent"])
            dpg.add_text("Leg ratio: —", tag="leg_ratio_label", color=DARK["text_weak"])
            with dpg.group(horizontal=True):
                dpg.add_button(label="Start Leg Cal",
                               callback=lambda: self._cmd("StartLegCalibration"))
                dpg.add_button(label="Stop Leg Cal",
                               callback=lambda: self._cmd("StopLegCalibration"))

        with _section("Virtual Floor", 72):
            dpg.add_text("Virtual Floor", color=DARK["accent"])
            with dpg.group(horizontal=True):
                dpg.add_slider_float(label="Offset", tag="floor_offset",
                                     min_value=-2.0, max_value=2.0, default_value=0.0,
                                     width=-50,
                                     callback=lambda s, a: self._cmd({"SetFloorOffset": a}))
                dpg.add_button(label="Auto", callback=lambda: self._cmd("AutoFloor"))

        with _section("Drift", 58):
            dpg.add_text("Drift Compensation", color=DARK["accent"])
            dpg.add_slider_float(label="Strength", tag="drift_str",
                                 min_value=0.0, max_value=1.0, default_value=0.0, width=-1,
                                 callback=lambda s, a: self._cmd({"SetDriftCorrection": a}))

    # ── UI: System tab ────────────────────────────────────────────────────────

    def _build_system_tab(self) -> None:
        W_INPUT = 180  # consistent input field width

        with dpg.child_window(border=True, height=112, no_scrollbar=True):
            dpg.add_text("OSC Output", color=DARK["accent"])
            dpg.add_separator()
            dpg.add_spacer(height=2)
            dpg.add_input_text(label="IP",   tag="osc_ip",
                               default_value="127.0.0.1", width=W_INPUT)
            dpg.add_input_text(label="Port", tag="osc_port",
                               default_value="9000",       width=W_INPUT)
            dpg.add_button(label="Apply OSC", callback=self._on_osc_apply)

        dpg.add_spacer(height=6)
        with dpg.child_window(border=True, height=158, no_scrollbar=True):
            dpg.add_text("ZUPT  (Zero Velocity Update)", color=DARK["accent"])
            dpg.add_separator()
            dpg.add_spacer(height=2)
            dpg.add_checkbox(label="Enabled", tag="zupt_en", default_value=True,
                             callback=lambda s, a: self._cmd({"SetZuptEnabled": a}))
            dpg.add_input_text(label="Window",    tag="zupt_win",   default_value="8",    width=W_INPUT)
            dpg.add_input_text(label="Accel Var", tag="zupt_accel", default_value="0.05", width=W_INPUT)
            dpg.add_input_text(label="Gyro Thr.", tag="zupt_gyro",  default_value="0.1",  width=W_INPUT)
            dpg.add_button(label="Apply ZUPT", callback=self._on_zupt_apply)

        dpg.add_spacer(height=6)
        with dpg.child_window(border=True, height=180, no_scrollbar=True):
            dpg.add_text("Recording", color=DARK["accent"])
            dpg.add_separator()
            dpg.add_spacer(height=2)
            dpg.add_input_text(label="Filename", tag="rec_file",
                               default_value="recording.bin", width=W_INPUT + 60)
            with dpg.group(horizontal=True):
                dpg.add_input_text(label="Batch",    tag="rec_batch",
                                   default_value="128", width=80)
                dpg.add_spacer(width=8)
                dpg.add_input_text(label="Flush ms", tag="rec_flush",
                                   default_value="500", width=80)
            dpg.add_button(label="Apply Config", callback=self._on_rec_config)
            dpg.add_spacer(height=4)
            with dpg.group(horizontal=True):
                dpg.add_button(label="▶  Record",
                               callback=lambda: self._cmd("StartRecording"))
                dpg.add_spacer(width=4)
                dpg.add_button(label="■  Stop",
                               callback=lambda: self._cmd("StopRecording"))
            dpg.add_text("Idle", tag="rec_status", color=DARK["text_weak"])

        dpg.add_spacer(height=6)
        with dpg.child_window(border=True, height=136, no_scrollbar=True):
            dpg.add_text("Serial", color=DARK["accent"])
            dpg.add_separator()
            dpg.add_spacer(height=2)
            dpg.add_input_text(label="Port", tag="serial_port",
                               default_value="COM3",   width=W_INPUT)
            dpg.add_input_text(label="Baud", tag="serial_baud",
                               default_value="115200", width=W_INPUT)
            dpg.add_checkbox(label="Enabled", tag="serial_en", default_value=False)
            dpg.add_button(label="Apply Serial", callback=self._on_serial_apply)
            dpg.add_text("", tag="serial_status", color=DARK["text_weak"])

    # ── callbacks ─────────────────────────────────────────────────────────────

    def _reset_camera(self) -> None:
        self._yaw, self._pitch, self._zoom = 0.436, 0.175, 1.0

    def _on_proportions_change(self, sender, app_data) -> None:
        self._cmd({"SetProportions": {
            "leg":   dpg.get_value("prop_leg"),
            "arm":   dpg.get_value("prop_arm"),
            "spine": dpg.get_value("prop_spine"),
        }})

    def _on_smoothing_change(self, sender, app_data) -> None:
        self._cmd({"SetSmoothingParams": {
            "min_cutoff": dpg.get_value("smooth_cutoff"),
            "beta":       dpg.get_value("smooth_beta"),
        }})

    def _on_osc_apply(self) -> None:
        try:
            self._cmd({"SetOscTarget": [
                dpg.get_value("osc_ip"), int(dpg.get_value("osc_port"))
            ]})
        except ValueError:
            pass

    def _on_rec_config(self) -> None:
        def _int(t):
            try: return int(dpg.get_value(t))
            except ValueError: return None
        self._cmd({"SetRecorderConfig": {
            "enabled": None,
            "filename": dpg.get_value("rec_file") or None,
            "batch_size": _int("rec_batch"),
            "flush_interval_ms": _int("rec_flush"),
        }})

    def _on_serial_apply(self) -> None:
        try: baud = int(dpg.get_value("serial_baud"))
        except ValueError: baud = 115200
        self._cmd({"SetSerialConfig": {
            "enabled": dpg.get_value("serial_en"),
            "port": dpg.get_value("serial_port") or None,
            "baud": baud,
        }})

    def _on_zupt_apply(self) -> None:
        def _i(t):
            try: return int(dpg.get_value(t))
            except ValueError: return None
        def _f(t):
            try: return float(dpg.get_value(t))
            except ValueError: return None
        self._cmd({"SetZuptParams": {
            "window_size": _i("zupt_win"),
            "accel_var_threshold": _f("zupt_accel"),
            "gyro_threshold": _f("zupt_gyro"),
        }})

    def _on_bone_assign(self, sender, app_data, user_data: int) -> None:
        try:
            bone_id = int(app_data.split(":")[0])
            self._cmd({"AssignTracker": [user_data, bone_id]})
        except (ValueError, IndexError):
            pass

    # ── camera input ──────────────────────────────────────────────────────────

    def _on_scroll(self, sender, app_data) -> None:
        for tag in ("skel_canvas", "tp_canvas"):
            if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                self._scroll_delta += app_data

    def _update_camera_input(self) -> None:
        # Check both the drawlist and its parent window for hover (more reliable)
        hovered = any(
            dpg.does_item_exist(t) and dpg.is_item_hovered(t)
            for t in ("skel_canvas", "tp_canvas",
                      "cal_left_win", "cal_right_win")
        )

        if hovered and dpg.is_mouse_button_down(0):
            curr = dpg.get_mouse_pos(local=False)
            if self._drag_last is not None:
                dx = curr[0] - self._drag_last[0]
                dy = curr[1] - self._drag_last[1]
                self._yaw   += dx * 0.008
                self._pitch += dy * 0.008
                self._pitch  = max(-1.4, min(1.4, self._pitch))
            self._drag_last = curr
        else:
            self._drag_last = None

        if self._scroll_delta != 0:
            if hovered:
                self._zoom *= 1.12 if self._scroll_delta > 0 else 0.89
                self._zoom  = max(0.4, min(4.0, self._zoom))
            self._scroll_delta = 0.0

    # ── PIL skeleton rendering helpers (kept for non-skeleton use only) ──────────

    def _pil_to_tex(self, img_np: np.ndarray, tex_id,
                    reg_flag_attr: str, size_attr: str) -> None:
        """Upload a (H,W,3) uint8 numpy image to a DPG raw texture (integer ID)."""
        if tex_id is None:
            return
        H, W = img_np.shape[:2]
        rgba = np.empty((H, W, 4), dtype=np.float32)
        rgba[:, :, :3] = img_np.astype(np.float32) * (1.0 / 255.0)
        rgba[:, :,  3] = 1.0
        flat = rgba.flatten()

        registered = getattr(self, reg_flag_attr)
        cur_size   = getattr(self, size_attr)
        exists     = dpg.does_item_exist(tex_id)

        if not registered or cur_size != (W, H) or not exists:
            if exists:
                dpg.delete_item(tex_id)
            dpg.push_container_stack(self._tex_reg_id)
            dpg.add_raw_texture(W, H, flat, tag=tex_id,
                                format=dpg.mvFormat_Float_rgba)
            dpg.pop_container_stack()
            setattr(self, reg_flag_attr, True)
            setattr(self, size_attr, (W, H))
        else:
            dpg.set_value(tex_id, flat)

    @staticmethod
    def _render_skeleton_pil(W: int, H: int,
                              bones: list, by_id: dict, assigned: set,
                              left_ids: set, right_ids: set,
                              yaw: float, pitch: float, zoom: float) -> np.ndarray:
        img  = Image.new('RGB', (W, H), (18, 24, 33))
        draw = ImageDraw.Draw(img)
        cx, cy = W / 2, H / 2 + H * 0.08
        scale  = min(W, H) * 0.42 * zoom

        SPINE = (200, 210, 220)
        LEFT  = (0,   200, 200)
        RIGHT = (255, 175,  90)
        JOINT = (64,  160, 255)
        TRACK = (90,  220, 100)

        # Bones (lines)
        for b in bones:
            pid = b.get("parent_id")
            if pid is None or pid not in by_id:
                continue
            bid = b["id"]
            sx1, sy1 = project_bone(by_id[pid]["pos"], yaw, pitch, cx, cy, scale)
            sx2, sy2 = project_bone(b["pos"],          yaw, pitch, cx, cy, scale)
            col = LEFT if bid in left_ids else RIGHT if bid in right_ids else SPINE
            draw.line([(sx1, sy1), (sx2, sy2)], fill=col, width=3)

        # Joints (circles)
        for b in bones:
            bid = b["id"]
            sx, sy = project_bone(b["pos"], yaw, pitch, cx, cy, scale)
            r    = 8 if bid == 4 else 4
            fill = TRACK if bid in assigned else JOINT
            draw.ellipse([(sx-r, sy-r), (sx+r, sy+r)], fill=fill)

        # Labels
        for bid, lbl in ((0, "Hip"), (4, "Head")):
            if bid in by_id:
                sx, sy = project_bone(by_id[bid]["pos"], yaw, pitch, cx, cy, scale)
                draw.text((sx + 6, sy - 8), lbl, fill=(160, 170, 185))

        return np.array(img)

    @staticmethod
    def _render_smpl_pil(W: int, H: int, joints: np.ndarray,
                          yaw: float, pitch: float, zoom: float) -> np.ndarray:
        img  = Image.new('RGB', (W, H), (18, 24, 33))
        draw = ImageDraw.Draw(img)
        cx, cy = W / 2, H / 2 + H * 0.08
        scale  = min(W, H) * 0.42 * zoom

        SPINE = (200, 210, 220)
        LEFT  = (0,   200, 200)
        RIGHT = (255, 175,  90)
        JOINT = (255, 175,  90)

        for i, j in SMPL_BONES:
            sx1, sy1 = project_bone(joints[i], yaw, pitch, cx, cy, scale)
            sx2, sy2 = project_bone(joints[j], yaw, pitch, cx, cy, scale)
            col = LEFT if j in SMPL_LEFT else RIGHT if j in SMPL_RIGHT else SPINE
            draw.line([(sx1, sy1), (sx2, sy2)], fill=col, width=3)

        for i, pos in enumerate(joints):
            sx, sy = project_bone(pos, yaw, pitch, cx, cy, scale)
            r    = 8 if i == 15 else 4
            draw.ellipse([(sx-r, sy-r), (sx+r, sy+r)], fill=JOINT)

        return np.array(img)

    # ── skeleton draw helpers (native DPG draw — zero texture overhead) ─────────

    def _dpg_draw_skeleton(self, canvas: str, W: int, H: int,
                           bones: list, by_id: dict, assigned: set,
                           left_ids: set, right_ids: set) -> None:
        """Draw IK skeleton directly on a DPG drawlist — no PIL, no texture upload."""
        dpg.delete_item(canvas, children_only=True)
        if not bones:
            return
        cx, cy = W / 2, H / 2 + H * 0.08
        scale  = min(W, H) * 0.42 * self._zoom
        yaw, pitch = self._yaw, self._pitch

        COL_SPINE = (200, 210, 220, 220)
        COL_LEFT  = (0,   200, 200, 220)
        COL_RIGHT = (255, 175,  90, 220)
        COL_JOINT = (64,  160, 255, 255)
        COL_TRACK = (90,  220, 100, 255)

        for b in bones:
            pid = b.get("parent_id")
            if pid is None or pid not in by_id:
                continue
            bid = b["id"]
            x1, y1 = project_bone(by_id[pid]["pos"], yaw, pitch, cx, cy, scale)
            x2, y2 = project_bone(b["pos"],           yaw, pitch, cx, cy, scale)
            col = COL_LEFT if bid in left_ids else COL_RIGHT if bid in right_ids else COL_SPINE
            dpg.draw_line([x1, y1], [x2, y2], color=col, thickness=2.5, parent=canvas)

        for b in bones:
            bid = b["id"]
            sx, sy = project_bone(b["pos"], yaw, pitch, cx, cy, scale)
            r    = 7 if bid == 4 else 3.5
            fill = COL_TRACK if bid in assigned else COL_JOINT
            dpg.draw_circle([sx, sy], r, color=(0,0,0,0), fill=fill, parent=canvas)

        for bid, lbl in ((0, "Hip"), (4, "Head")):
            if bid in by_id:
                sx, sy = project_bone(by_id[bid]["pos"], yaw, pitch, cx, cy, scale)
                dpg.draw_text([sx + 6, sy - 8], lbl, color=(160, 170, 185, 200),
                              size=13, parent=canvas)

    def _dpg_draw_smpl(self, canvas: str, W: int, H: int,
                       joints: np.ndarray) -> None:
        """Draw TransPose SMPL joints directly on a DPG drawlist."""
        dpg.delete_item(canvas, children_only=True)
        cx, cy = W / 2, H / 2 + H * 0.08
        scale  = min(W, H) * 0.42 * self._zoom
        yaw, pitch = self._yaw, self._pitch

        COL_SPINE = (200, 210, 220, 220)
        COL_LEFT  = (0,   200, 200, 220)
        COL_RIGHT = (255, 175,  90, 220)
        COL_JOINT = (255, 175,  90, 255)

        for i, j in SMPL_BONES:
            x1, y1 = project_bone(joints[i], yaw, pitch, cx, cy, scale)
            x2, y2 = project_bone(joints[j], yaw, pitch, cx, cy, scale)
            col = COL_LEFT if j in SMPL_LEFT else COL_RIGHT if j in SMPL_RIGHT else COL_SPINE
            dpg.draw_line([x1, y1], [x2, y2], color=col, thickness=2.5, parent=canvas)

        for i, pos in enumerate(joints):
            sx, sy = project_bone(pos, yaw, pitch, cx, cy, scale)
            r = 7 if i == 15 else 3.5
            dpg.draw_circle([sx, sy], r, color=(0,0,0,0), fill=COL_JOINT, parent=canvas)

        for i, lbl in SMPL_LABELS.items():
            sx, sy = project_bone(joints[i], yaw, pitch, cx, cy, scale)
            dpg.draw_text([sx + 6, sy - 8], lbl, color=(160, 170, 185, 200),
                          size=13, parent=canvas)

    # ── skeleton draw: aetherpose IK ─────────────────────────────────────────

    def _draw_ik_skeleton(self) -> None:
        if not dpg.does_item_exist("skel_canvas"):
            return
        W = max(100, dpg.get_item_width("cal_left_win")  - 4)
        H = max(100, dpg.get_item_height("cal_left_win") - 30)
        dpg.configure_item("skel_canvas", width=W, height=H)

        bones    = self.snapshot.get("bones", [])
        by_id    = {b["id"]: b for b in bones}
        assigned = {t["assigned_bone"]
                    for t in self.snapshot.get("trackers", {}).values()
                    if t.get("assigned_bone") is not None}

        self._dpg_draw_skeleton("skel_canvas", W, H, bones, by_id, assigned,
                                LEFT_BONE_IDS, RIGHT_BONE_IDS)

    # ── skeleton draw: TransPose stick ───────────────────────────────────────

    def _draw_tp_skeleton(self) -> None:
        if not dpg.does_item_exist("tp_canvas"):
            return
        W = max(100, dpg.get_item_width("cal_right_win")  - 4)
        H = max(100, dpg.get_item_height("cal_right_win") - 30)
        dpg.configure_item("tp_canvas", width=W, height=H)

        if self._tp is not None and dpg.does_item_exist("tp_status"):
            dpg.set_value("tp_status", self._tp.status)

        joints = self._tp.get_joints() if self._tp else None
        if joints is None:
            return
        self._dpg_draw_smpl("tp_canvas", W, H, joints)

    # ── frame refresh ─────────────────────────────────────────────────────────

    def _resize_cal_panels(self) -> None:
        """Force the skeleton child-windows to fill the whole Calibration tab."""
        if not dpg.does_item_exist("cal_left_win"):
            return
        vw = dpg.get_viewport_client_width()
        vh = dpg.get_viewport_client_height()
        # Leave room for status bar / tab bar / toolbar  (~116 px vertical)
        h = max(200, vh - 116)
        # Split horizontally 50/50 with a 4 px gap
        half = max(200, vw // 2 - 4)
        dpg.set_item_width("cal_left_win",  half)
        dpg.set_item_width("cal_right_win", half)
        dpg.set_item_height("cal_left_win",  h)
        dpg.set_item_height("cal_right_win", h)

    def _refresh(self) -> None:
        self._resize_cal_panels()
        snap     = self.snapshot
        trackers = snap.get("trackers", {})

        # Status bar
        ok = self.ws.is_connected()
        dpg.set_value("status_bar",
                      "Connected" if ok else "Disconnected — waiting for backend…")
        dpg.configure_item("status_bar",
                           color=(80, 185, 120) if ok else (190, 90, 90))

        # Push all tracker frames to TransPose (non-blocking, maps by bone assignment)
        if self._tp is not None:
            self._tp.push_frame(trackers)

        # Calibration canvases
        self._draw_ik_skeleton()
        self._draw_tp_skeleton()

        # Monitor tab
        dpg.set_value("mon_header", f"Packets: {snap.get('packet_count', 0)}")
        self._refresh_monitor(trackers)

        # Body tab
        if dpg.does_item_exist("leg_ratio_label"):
            dpg.set_value("leg_ratio_label",
                          f"Leg ratio: {snap.get('leg_ratio', 0.0):.3f}")

        # System tab
        is_rec  = snap.get("is_recording", False)
        dropped = snap.get("recorder_dropped_count", 0)
        dpg.set_value("rec_status", f"{'● REC' if is_rec else 'Idle'}  dropped={dropped}")
        s_run = snap.get("serial_running", False)
        s_msg = snap.get("serial_status_msg") or ""
        dpg.set_value("serial_status",
                      f"{'Running' if s_run else 'Stopped'}  {s_msg}".strip())

    def _refresh_monitor(self, trackers: dict) -> None:
        for tid in list(self._mon_rows):
            if str(tid) not in trackers:
                tag = f"mon_row_{tid}"
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)
                self._mon_rows.discard(tid)

        for tid_s, t in sorted(trackers.items(), key=lambda x: int(x[0])):
            tid   = int(tid_s)
            lost  = t.get("lost_packets", 0)
            recv  = t.get("received_packets", 0)
            total = recv + lost
            loss  = f"{lost / total * 100:.1f}%" if total else "0%"
            batt  = f"{int(t.get('battery', 0) * 100)}%"
            bone  = t.get("assigned_bone")
            bname = BONE_NAMES.get(bone, str(bone)) if bone is not None else "(none)"
            ms    = t.get("last_update_ms", 0)
            alive = "OK" if ms < 2000 else f"Timeout {ms//1000}s"

            row_tag = f"mon_row_{tid}"
            if tid not in self._mon_rows:
                self._mon_rows.add(tid)
                with dpg.table_row(tag=row_tag, parent="mon_table"):
                    dpg.add_text(str(t.get("id", tid)))
                    dpg.add_text(bname,  tag=f"mon_{tid}_bone")
                    dpg.add_text(alive,  tag=f"mon_{tid}_alive")
                    dpg.add_text(t.get("connection_type", "?")[:6])
                    dpg.add_text(batt,   tag=f"mon_{tid}_batt")
                    dpg.add_text(str(t.get("tps", 0)), tag=f"mon_{tid}_tps")
                    dpg.add_text(loss,   tag=f"mon_{tid}_loss")
                    dpg.add_text(f"{t.get('rssi', 0)} dBm", tag=f"mon_{tid}_rssi")
                    dpg.add_combo(items=BONE_ITEMS, width=160,
                                  default_value=f"{bone}: {bname}" if bone is not None else BONE_ITEMS[0],
                                  callback=self._on_bone_assign, user_data=tid,
                                  tag=f"mon_{tid}_combo")
            else:
                dpg.set_value(f"mon_{tid}_bone",  bname)
                dpg.set_value(f"mon_{tid}_alive", alive)
                dpg.set_value(f"mon_{tid}_batt",  batt)
                dpg.set_value(f"mon_{tid}_tps",   str(t.get("tps", 0)))
                dpg.set_value(f"mon_{tid}_loss",  loss)
                dpg.set_value(f"mon_{tid}_rssi",  f"{t.get('rssi', 0)} dBm")

    # ── theme ─────────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        with dpg.theme() as t:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg,       DARK["window_bg"])
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg,        DARK["child_bg"])
                dpg.add_theme_color(dpg.mvThemeCol_PopupBg,        DARK["child_bg"])
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg,        DARK["frame_bg"])
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, DARK["frame_hov"])
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive,  DARK["frame_act"])
                dpg.add_theme_color(dpg.mvThemeCol_Button,         DARK["btn"])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered,  DARK["btn_hov"])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,   DARK["btn_act"])
                dpg.add_theme_color(dpg.mvThemeCol_Header,         DARK["header"])
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered,  DARK["header_hov"])
                dpg.add_theme_color(dpg.mvThemeCol_Tab,            DARK["tab"])
                dpg.add_theme_color(dpg.mvThemeCol_TabHovered,     DARK["btn_hov"])
                dpg.add_theme_color(dpg.mvThemeCol_TabActive,      DARK["tab_active"])
                dpg.add_theme_color(dpg.mvThemeCol_TitleBg,        DARK["title"])
                dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive,  DARK["title_active"])
                dpg.add_theme_color(dpg.mvThemeCol_Text,           DARK["text"])
                dpg.add_theme_color(dpg.mvThemeCol_Separator,      DARK["separator"])
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrab,     DARK["accent"])
                dpg.add_theme_color(dpg.mvThemeCol_CheckMark,      DARK["accent"])
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding,  6)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding,  8)
                dpg.add_theme_style(dpg.mvStyleVar_TabRounding,     6)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing,     8, 6)
        dpg.bind_theme(t)

    # ── run ───────────────────────────────────────────────────────────────────

    def run(self) -> None:
        self.ws.start()

        # Load SMPL T-pose and start Open3D BEFORE DearPyGui creates its GL context
        try:
            _smpl = np.load(_SMPL_NPZ, allow_pickle=True)
            _vt   = _smpl['v_template'].astype(np.float32)
            _fc   = _smpl['f'].astype(np.int32)
            _o3d  = Open3DViewer()
            _o3d.start(_vt, _fc)
        except Exception as e:
            _o3d = None

        self._tp = TransPoseRunner(dip_subj='s_03', dip_clip=3)
        self._tp._o3d_viewer = _o3d

        dpg.create_context()
        self._apply_theme()

        with dpg.handler_registry():
            dpg.add_mouse_wheel_handler(callback=self._on_scroll)

        with dpg.window(tag="main_win", no_title_bar=True,
                        no_move=True, no_resize=True):
            with dpg.group(horizontal=True):
                dpg.add_text("Aetherpose", color=DARK["accent"])
                dpg.add_spacer(width=12)
                dpg.add_text("—", tag="status_bar")
            dpg.add_separator()
            dpg.add_spacer(height=2)

            with dpg.tab_bar():
                with dpg.tab(label="Calibration"):
                    self._build_calibration_tab()
                with dpg.tab(label="Monitor"):
                    self._build_monitor_tab()
                with dpg.tab(label="Body"):
                    with dpg.child_window(border=False, no_scrollbar=False):
                        self._build_body_tab()
                with dpg.tab(label="System"):
                    with dpg.child_window(border=False, no_scrollbar=False):
                        self._build_system_tab()

        dpg.create_viewport(title="Aetherpose Control Panel",
                            width=1280, height=740, resizable=True)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_primary_window("main_win", True)

        def _on_resize():
            w = dpg.get_viewport_client_width()
            h = dpg.get_viewport_client_height()
            dpg.set_item_width("main_win", w)
            dpg.set_item_height("main_win", h)

        dpg.set_viewport_resize_callback(_on_resize)

        last_refresh = 0.0
        while dpg.is_dearpygui_running():
            msg = self.ws.get_update()
            while msg is not None:
                self._apply_message(msg)
                msg = self.ws.get_update()

            self._update_camera_input()

            now = time.monotonic()
            if now - last_refresh >= 1 / 30:
                self._refresh()
                last_refresh = now

            dpg.render_dearpygui_frame()

        dpg.destroy_context()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    App().run()
