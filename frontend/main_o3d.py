"""
Aetherpose — Open3D GUI frontend (single window)
  Left  : Open3D SceneWidget — SMPL mesh + IK skeleton + TP joints
  Right : control panel — Calibration / Monitor / Body / System tabs
"""

import os, sys, time, threading, json, math
import numpy as np
import open3d as o3d
import open3d.visualization.gui      as gui
import open3d.visualization.rendering as rendering
from scipy.spatial.transform import Rotation as _Rot
from ws_client import WsClient


# ── FPS camera (yaw/pitch only, roll = 0) ─────────────────────────────────────

class FPSCamera:
    """Game-style free camera: mouse drag = look, WASD = move, QE = up/down."""

    def __init__(self, scene_widget: 'gui.SceneWidget'):
        self._widget = scene_widget
        self.pos   = np.array([0.0, 1.2, 3.5])
        self.yaw   = math.pi        # face -Z (towards origin)
        self.pitch = -0.15
        self.speed = 2.0
        self._keys: set  = set()
        self._drag: tuple | None = None

    # ── derived vectors ──────────────────────────────────────────────────────
    @property
    def forward(self) -> np.ndarray:
        cy, sy = math.cos(self.yaw),   math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        return np.array([sy * cp, sp, -cy * cp])

    @property
    def right(self) -> np.ndarray:
        r = np.cross(self.forward, [0, 1, 0])
        n = np.linalg.norm(r)
        return r / n if n > 1e-6 else np.array([1, 0, 0])

    # ── apply to SceneWidget ─────────────────────────────────────────────────
    def apply(self, scene_widget: 'gui.SceneWidget | None' = None):
        w = scene_widget or self._widget
        target = self.pos + self.forward
        up     = np.cross(self.right, self.forward)
        w.look_at(target, self.pos, up)

    # ── events ───────────────────────────────────────────────────────────────
    def on_mouse(self, ev) -> gui.SceneWidget.EventCallbackResult:
        CONSUMED = gui.SceneWidget.EventCallbackResult.CONSUMED
        IGNORED  = gui.SceneWidget.EventCallbackResult.IGNORED

        if ev.type == gui.MouseEvent.BUTTON_DOWN:
            if ev.is_button_down(gui.MouseButton.LEFT):
                self._drag = (ev.x, ev.y)
            return CONSUMED

        if ev.type == gui.MouseEvent.BUTTON_UP:
            self._drag = None
            return CONSUMED

        if ev.type == gui.MouseEvent.DRAG:
            if self._drag and ev.is_button_down(gui.MouseButton.LEFT):
                dx = ev.x - self._drag[0]
                dy = ev.y - self._drag[1]
                self.yaw   += dx * 0.005
                self.pitch -= dy * 0.005
                self.pitch  = max(-1.4, min(1.4, self.pitch))
                self._drag  = (ev.x, ev.y)
                self.apply()   # 立即更新，不等 refresh
            return CONSUMED

        if ev.type == gui.MouseEvent.WHEEL:
            self.speed = max(0.2, min(20.0, self.speed * (1.15 if ev.wheel_dy > 0 else 0.87)))
            return CONSUMED

        return IGNORED

    def reset_to_origin(self):
        self.pos   = np.array([0.0, 1.2, 3.5])
        self.yaw   = math.pi
        self.pitch = -0.15
        self.apply()

    def on_key(self, ev) -> gui.SceneWidget.EventCallbackResult:
        k = ev.key
        if ev.type == gui.KeyEvent.DOWN:
            self._keys.add(k)
            if k in (ord('r'), ord('R')):
                self.reset_to_origin()
        elif ev.type == gui.KeyEvent.UP:
            self._keys.discard(k)
        return gui.SceneWidget.EventCallbackResult.IGNORED

    def tick(self, dt: float) -> bool:
        """Move camera, apply immediately. Returns True if moved."""
        moved = False
        spd   = self.speed * dt
        ks    = self._keys
        if any(k in ks for k in (ord('w'), ord('W'))): self.pos += self.forward * spd; moved = True
        if any(k in ks for k in (ord('s'), ord('S'))): self.pos -= self.forward * spd; moved = True
        if any(k in ks for k in (ord('a'), ord('A'))): self.pos -= self.right   * spd; moved = True
        if any(k in ks for k in (ord('d'), ord('D'))): self.pos += self.right   * spd; moved = True
        if any(k in ks for k in (ord('e'), ord('E'))): self.pos[1] += spd;             moved = True
        if any(k in ks for k in (ord('q'), ord('Q'))): self.pos[1] -= spd;             moved = True
        if moved:
            self.apply()
        return moved

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

WS_URL = "ws://127.0.0.1:9009/ws"

BONE_NAMES: dict[int, str] = {
    0:"Hip", 1:"Waist", 2:"Chest", 3:"Neck", 4:"Head",
    10:"L_UpLeg", 11:"L_Leg", 12:"L_Foot",
    20:"R_UpLeg", 21:"R_Leg", 22:"R_Foot",
    30:"L_Shoulder", 31:"L_UpperArm", 32:"L_ForeArm", 33:"L_Hand",
    40:"R_Shoulder", 41:"R_UpperArm", 42:"R_ForeArm", 43:"R_Hand",
}
LEFT_BONE_IDS  = {10,11,12,30,31,32,33}
RIGHT_BONE_IDS = {20,21,22,40,41,42,43}

SMPL_BONES = [
    (0,1),(0,2),(0,3),(1,4),(2,5),(3,6),(4,7),(5,8),(6,9),
    (7,10),(8,11),(9,12),(9,13),(9,14),(12,15),(13,16),(14,17),
    (16,18),(17,19),(18,20),(19,21),(20,22),(21,23),
]
SMPL_LEFT  = {1,4,7,10,13,16,18,20,22}
SMPL_RIGHT = {2,5,8,11,14,17,19,21,23}

# Keep line skeletons readable by drawing them beside the body mesh.
IK_SKELETON_OFFSET = np.array([-1.35, 0.0, 0.0], dtype=np.float64)
TP_SKELETON_OFFSET = np.array([ 1.35, 0.0, 0.0], dtype=np.float64)


# ── TransPose runner ──────────────────────────────────────────────────────────

class TransPoseRunner:
    _IMU_MASK  = [7, 8, 11, 12, 0, 2]
    MESH_EVERY = 8
    BONE_TO_SLOT: dict[int, int] = {32:0, 42:1, 11:2, 21:3, 4:4, 2:5}

    def __init__(self, dip_subj='s_03', dip_clip=3):
        self._lock       = threading.Lock()
        self._status     = "Loading…"
        self._joints     = None
        self._latest_verts: np.ndarray | None = None
        self._faces: np.ndarray | None = None
        self._mask_acc   = None
        self._mask_ori   = None
        self._mask_idx   = 0
        self._mask_source = "none"
        self._last_live_slots = set()
        self._online_cnt = 0
        self._mesh_busy  = False
        self._ready      = False
        self._net = self._fk = self._nac = self._pending = None
        threading.Thread(target=self._init, args=(dip_subj, dip_clip),
                         daemon=True, name='tp-init').start()

    @property
    def status(self):
        with self._lock:
            return self._status

    def _set_status(self, s):
        with self._lock:
            self._status = s

    def _format_stream_status(self, frame_no: int, live_count: int, mask_source: str) -> str:
        if live_count >= 6:
            return f"Streaming #{frame_no} LIVE 6/6"
        return f"Streaming #{frame_no} DEBUG mask={mask_source} live {live_count}/6"

    def get_joints(self):
        with self._lock:
            return self._joints.copy() if self._joints is not None else None

    def get_latest_verts(self):
        with self._lock:
            return self._latest_verts.copy() if self._latest_verts is not None else None

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

            net = TransPoseNet(); net.reset()
            fk  = SMPLForwardKinematics(_SMPL_NPZ)
            with self._lock:
                self._net  = net
                self._fk   = fk
                self._faces = fk.faces.astype(np.int32)
                self._nac  = normalize_and_concat
                self._pending = None
                self._ready = True
                mask_source = self._mask_source
            self._set_status(f"Ready (debug mask={mask_source}; validation needs LIVE 6/6)")
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
                x = nac(torch.from_numpy(acc_f[None]),
                        torch.from_numpy(ori_f[None]))[0]
                pose, tran = net.forward_online(x)
                R_np = pose.numpy()
                t_np = tran.numpy()
                aa     = _Rot.from_matrix(R_np).as_rotvec().reshape(1, 72).astype('float32')
                joints = fk.forward(aa)[0]
                joints -= joints[0:1]; joints += t_np

                self._online_cnt += 1
                do_mesh = False
                with self._lock:
                    self._joints = joints
                    if self._online_cnt % self.MESH_EVERY == 0 and not self._mesh_busy:
                        self._mesh_busy = True
                        do_mesh = True
                    mask_source = self._mask_source

                if do_mesh:
                    threading.Thread(target=self._compute_mesh,
                                     args=(R_np.copy(), t_np.copy()),
                                     daemon=True, name='tp-mesh').start()
                self._set_status(self._format_stream_status(
                    self._online_cnt, len(live_slots), mask_source))
            except Exception as e:
                self._set_status(f"Infer err: {e}")

    def _compute_mesh(self, R_24x3x3, tran):
        try:
            with self._lock:
                fk = self._fk
            verts = fk.lbs_frame(R_24x3x3).astype(np.float32)
            verts -= verts[0:1]
            verts += tran.astype(np.float32)
            with self._lock:
                self._latest_verts = verts
                self._mesh_busy    = False
        except Exception:
            with self._lock:
                self._mesh_busy = False


# ── App ───────────────────────────────────────────────────────────────────────

class App:
    MAX_TRACKERS = 8

    def __init__(self):
        app = gui.Application.instance
        app.initialize()
        self._app = app

        self.window = app.create_window("Aetherpose", 1400, 820)
        em = self.window.theme.font_size
        self._em = em

        self.ws       = WsClient(WS_URL)
        self.snapshot = {}
        self._tp      = TransPoseRunner()
        self._faces: np.ndarray | None = None

        self._mat_mesh  = rendering.MaterialRecord()
        self._mat_mesh.shader = "defaultLit"
        self._mat_line  = rendering.MaterialRecord()
        self._mat_line.shader = "unlitLine"
        self._mat_line.line_width = 3.0
        # TP uses same material as IK
        self._mat_line2 = self._mat_line

        self._build_scene()
        self._build_panel(em)
        self.window.set_on_layout(self._on_layout)

    # ── scene ─────────────────────────────────────────────────────────────────

    def _build_scene(self):
        self._scene = gui.SceneWidget()
        sc = rendering.Open3DScene(self.window.renderer)
        self._scene.scene = sc
        sc.set_background([0.08, 0.10, 0.14, 1.0])
        sc.scene.enable_sun_light(True)
        sc.scene.set_sun_light([0.45, -1.0, -0.6], [1.0, 0.98, 0.95], 80000)
        sc.scene.set_indirect_light_intensity(25000)

        # Load SMPL T-pose
        try:
            smpl  = np.load(_SMPL_NPZ, allow_pickle=True)
            verts = smpl['v_template'].astype(np.float64)
            faces = smpl['f'].astype(np.int32)
            self._faces = faces
            mesh = o3d.geometry.TriangleMesh()
            mesh.vertices  = o3d.utility.Vector3dVector(verts)
            mesh.triangles = o3d.utility.Vector3iVector(faces)
            mesh.paint_uniform_color([0.80, 0.62, 0.46])
            mesh.compute_vertex_normals()
            sc.add_geometry("mesh", mesh, self._mat_mesh)
        except Exception as e:
            print(f"[SMPL] load error: {e}")

        # Floor grid
        self._add_floor(sc, y=-1.0)

        # Camera — custom FPS (roll locked to 0)
        self._cam = FPSCamera(self._scene)
        self._scene.set_view_controls(gui.SceneWidget.Controls.ROTATE_CAMERA)
        bounds = o3d.geometry.AxisAlignedBoundingBox(
            np.array([-2.8, -1.2, -1.2]), np.array([2.8, 2.2, 1.2]))
        self._scene.setup_camera(60.0, bounds, np.array([0.0, 0.8, 0.0]))
        self._cam.apply()
        self._scene.set_on_mouse(self._cam.on_mouse)
        self._scene.set_on_key(self._cam.on_key)
        self.window.add_child(self._scene)

    def _add_floor(self, sc, y=-1.0, size=1.5, step=0.25):
        pts, lines, i = [], [], 0
        for v in np.arange(-size, size + 1e-6, step):
            pts += [[v, y, -size], [v, y, size]]
            lines.append([i, i+1]); i += 2
            pts += [[-size, y, v], [size, y, v]]
            lines.append([i, i+1]); i += 2
        grid = o3d.geometry.LineSet()
        grid.points = o3d.utility.Vector3dVector(pts)
        grid.lines  = o3d.utility.Vector2iVector(lines)
        grid.paint_uniform_color([0.20, 0.20, 0.24])
        m = rendering.MaterialRecord(); m.shader = "unlitLine"; m.line_width = 1.0
        sc.add_geometry("floor", grid, m)

    # ── panel ─────────────────────────────────────────────────────────────────

    def _build_panel(self, em):
        p  = int(em * 0.4)   # padding
        sp = int(em * 0.25)  # spacing
        m  = gui.Margins(p)
        panel = gui.ScrollableVert(sp, m)

        # ── status bar ──────────────────────────────────────────────────────
        sr = gui.Horiz(int(em * 0.4))
        self._status_lbl = gui.Label("● Disconnected")
        self._status_lbl.text_color = gui.Color(0.96, 0.31, 0.31)
        self._pkt_lbl = gui.Label("0 pkts")
        self._pkt_lbl.text_color = gui.Color(0.50, 0.53, 0.58)
        sr.add_child(self._status_lbl)
        sr.add_stretch()
        sr.add_child(self._pkt_lbl)
        panel.add_child(sr)

        # ── TP status ───────────────────────────────────────────────────────
        self._tp_lbl = gui.Label("TP: Loading…")
        self._tp_lbl.text_color = gui.Color(1.0, 0.69, 0.35)
        panel.add_child(self._tp_lbl)

        tabs = gui.TabControl()

        # ────────────────────────────────────────────────────────────────────
        # TAB: Calibration
        # ────────────────────────────────────────────────────────────────────
        cal = gui.ScrollableVert(sp, gui.Margins(p, sp, p, sp))

        sec_actions = gui.CollapsableVert("Actions", sp, gui.Margins(0))
        r1 = gui.Horiz(sp)
        for lbl, c in [("Reset Yaw","ResetYaw"),("Reset Mount","ResetMounting")]:
            b = gui.Button(lbl); b.set_on_clicked(lambda x=c: self._cmd(x)); r1.add_child(b)
        sec_actions.add_child(r1)
        r2 = gui.Horiz(sp)
        b_aa = gui.Button("Auto Assign"); b_aa.set_on_clicked(lambda: self._cmd("AutoAssign"))
        b_cc = gui.Button("Clear Cal.");  b_cc.set_on_clicked(lambda: self._cmd("ClearAllCalibration"))
        r2.add_child(b_aa); r2.add_child(b_cc)
        sec_actions.add_child(r2)
        r3 = gui.Horiz(sp)
        b_tp = gui.Button("Reset T-Pose"); b_tp.set_on_clicked(self._reset_tpose)
        r3.add_child(b_tp)
        sec_actions.add_child(r3)
        cal.add_child(sec_actions)

        sec_tr = gui.CollapsableVert("Trackers", sp, gui.Margins(0))
        self._cal_rows: list = []
        for _ in range(self.MAX_TRACKERS):
            row = gui.Horiz(sp)
            lbl = gui.Label(""); lbl.text_color = gui.Color(0.35, 0.70, 1.0)
            combo = gui.Combobox()
            combo.add_item("—")
            for bn in BONE_NAMES.values(): combo.add_item(bn)
            row.add_fixed(int(em * 3)); row.add_child(lbl)
            row.add_stretch(); row.add_child(combo)
            sec_tr.add_child(row)
            self._cal_rows.append((row, lbl, combo))
        cal.add_child(sec_tr)
        tabs.add_tab("Calibration", cal)

        # ────────────────────────────────────────────────────────────────────
        # TAB: Monitor
        # ────────────────────────────────────────────────────────────────────
        mon = gui.ScrollableVert(sp, gui.Margins(p, sp, p, sp))
        self._mon_rows: list = []
        for _ in range(self.MAX_TRACKERS):
            st_l  = gui.Label(""); st_l.text_color = gui.Color(0.35, 0.70, 1.0)
            det_l = gui.Label(""); det_l.text_color = gui.Color(0.50, 0.53, 0.58)
            mon.add_child(st_l)
            mon.add_child(det_l)
            self._mon_rows.append((st_l, det_l))
        tabs.add_tab("Monitor", mon)

        # ────────────────────────────────────────────────────────────────────
        # TAB: Body
        # ────────────────────────────────────────────────────────────────────
        body = gui.ScrollableVert(sp, gui.Margins(p, sp, p, sp))

        sec_prop = gui.CollapsableVert("Proportions", sp, gui.Margins(0))
        self._ik_s    = self._isl(sec_prop, "IK Smooth", 0.0, 1.0,  0.5, em,
                                  lambda v: self._cmd({"SetIkSmoothness": v}))
        self._leg_s   = self._isl(sec_prop, "Legs",      0.5, 1.5,  1.0, em, lambda v: self._prop_changed())
        self._arm_s   = self._isl(sec_prop, "Arms",      0.5, 1.5,  1.0, em, lambda v: self._prop_changed())
        self._spine_s = self._isl(sec_prop, "Spine",     0.5, 1.5,  1.0, em, lambda v: self._prop_changed())
        body.add_child(sec_prop)

        sec_filt = gui.CollapsableVert("One Euro Filter", sp, gui.Margins(0))
        self._cutoff_s = self._isl(sec_filt, "Cutoff", 0.01, 5.0, 3.0, em, lambda v: self._smooth_changed())
        self._beta_s   = self._isl(sec_filt, "Beta",    0.0, 10.0, 3.0, em, lambda v: self._smooth_changed())
        body.add_child(sec_filt)

        sec_floor = gui.CollapsableVert("Virtual Floor", sp, gui.Margins(0))
        fr = gui.Horiz(sp)
        lf = gui.Label("Offset"); lf.text_color = gui.Color(0.50, 0.53, 0.58)
        fr.add_child(lf); fr.add_fixed(int(em * 0.3))
        self._floor_s = gui.Slider(gui.Slider.DOUBLE)
        self._floor_s.set_limits(-2.0, 2.0); self._floor_s.double_value = 0.0
        self._floor_s.set_on_value_changed(lambda v: self._cmd({"SetFloorOffset": v}))
        btn_af = gui.Button("Auto"); btn_af.set_on_clicked(lambda: self._cmd("AutoFloor"))
        fr.add_child(self._floor_s); fr.add_child(btn_af)
        sec_floor.add_child(fr)
        body.add_child(sec_floor)

        sec_misc = gui.CollapsableVert("Drift / Trajectory", sp, gui.Margins(0))
        self._drift_s = self._isl(sec_misc, "Drift", 0.0, 1.0, 0.0, em,
                                  lambda v: self._cmd({"SetDriftCorrection": v}))
        tr = gui.Horiz(sp)
        for lbl, mode in [("RK4","rk4"),("Euler","euler")]:
            b = gui.Button(lbl)
            b.set_on_clicked(lambda m=mode: self._cmd({"SetTrajectoryIntegrationMode": m}))
            tr.add_child(b)
        sec_misc.add_child(tr)
        body.add_child(sec_misc)
        tabs.add_tab("Body", body)

        # ────────────────────────────────────────────────────────────────────
        # TAB: System
        # ────────────────────────────────────────────────────────────────────
        sys_t = gui.ScrollableVert(sp, gui.Margins(p, sp, p, sp))

        sec_osc = gui.CollapsableVert("OSC Output", sp, gui.Margins(0))
        self._osc_ip   = gui.TextEdit(); self._osc_ip.text_value   = "127.0.0.1"
        self._osc_port = gui.TextEdit(); self._osc_port.text_value = "9000"
        sec_osc.add_child(self._fw("IP",   self._osc_ip,   em))
        sec_osc.add_child(self._fw("Port", self._osc_port, em))
        b_osc = gui.Button("Apply OSC"); b_osc.set_on_clicked(self._on_osc_apply)
        sec_osc.add_child(b_osc)
        sys_t.add_child(sec_osc)

        sec_rec = gui.CollapsableVert("Recording", sp, gui.Margins(0))
        self._rec_file  = gui.TextEdit(); self._rec_file.text_value  = "recording.bin"
        self._rec_batch = gui.TextEdit(); self._rec_batch.text_value = "128"
        self._rec_flush = gui.TextEdit(); self._rec_flush.text_value = "500"
        sec_rec.add_child(self._fw("File",    self._rec_file,  em))
        bf = gui.Horiz(sp)
        bf.add_child(self._fw("Batch",    self._rec_batch, em))
        bf.add_child(self._fw("Flush ms", self._rec_flush, em))
        sec_rec.add_child(bf)
        rc = gui.Horiz(sp)
        b_rcfg = gui.Button("Config"); b_rcfg.set_on_clicked(self._on_rec_config)
        b_rs   = gui.Button("▶ Rec");  b_rs.set_on_clicked(lambda: self._cmd("StartRecording"))
        b_rx   = gui.Button("■ Stop"); b_rx.set_on_clicked(lambda: self._cmd("StopRecording"))
        rc.add_child(b_rcfg); rc.add_child(b_rs); rc.add_child(b_rx)
        sec_rec.add_child(rc)
        self._rec_st_lbl = gui.Label("Idle"); self._rec_st_lbl.text_color = gui.Color(0.50,0.53,0.58)
        sec_rec.add_child(self._rec_st_lbl)
        sys_t.add_child(sec_rec)

        sec_ser = gui.CollapsableVert("Serial", sp, gui.Margins(0))
        self._ser_port = gui.TextEdit(); self._ser_port.text_value = "COM3"
        self._ser_baud = gui.TextEdit(); self._ser_baud.text_value = "115200"
        self._ser_en   = gui.Checkbox("Enabled")
        sec_ser.add_child(self._fw("Port", self._ser_port, em))
        sec_ser.add_child(self._fw("Baud", self._ser_baud, em))
        sec_ser.add_child(self._ser_en)
        b_ser = gui.Button("Apply Serial"); b_ser.set_on_clicked(self._on_serial_apply)
        sec_ser.add_child(b_ser)
        self._ser_st_lbl = gui.Label(""); self._ser_st_lbl.text_color = gui.Color(0.50,0.53,0.58)
        sec_ser.add_child(self._ser_st_lbl)
        sys_t.add_child(sec_ser)
        tabs.add_tab("System", sys_t)

        panel.add_child(tabs)
        self._panel = panel
        self.window.add_child(panel)

    # ── layout ────────────────────────────────────────────────────────────────

    def _on_layout(self, ctx):
        r = self.window.content_rect
        panel_w = int(ctx.theme.font_size * 18)
        self._scene.frame  = gui.Rect(r.x, r.y, r.width - panel_w, r.height)
        self._panel.frame  = gui.Rect(r.x + r.width - panel_w, r.y, panel_w, r.height)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _isl(self, parent, label, lo, hi, default, em, cb):
        """Inline slider: [label][slider] on one row."""
        row = gui.Horiz(int(em * 0.3))
        lbl = gui.Label(label); lbl.text_color = gui.Color(0.50, 0.53, 0.58)
        s   = gui.Slider(gui.Slider.DOUBLE)
        s.set_limits(lo, hi); s.double_value = default
        s.set_on_value_changed(cb)
        row.add_fixed(int(em * 4.5))
        row.add_child(lbl)
        row.add_stretch()
        row.add_child(s)
        parent.add_child(row)
        return s

    def _fw(self, label, widget, em):
        """Fixed-width label + widget row."""
        row = gui.Horiz(int(em * 0.3))
        lbl = gui.Label(label); lbl.text_color = gui.Color(0.50, 0.53, 0.58)
        row.add_fixed(int(em * 3.5))
        row.add_child(lbl)
        row.add_fixed(int(em * 0.4))
        row.add_child(widget)
        return row

    # ── commands ──────────────────────────────────────────────────────────────

    def _cmd(self, cmd):
        self.ws.send_command(cmd)

    def _reset_tpose(self):
        """Reset SMPL mesh and TransPose inference state to T-pose."""
        # Reset latest verts to T-pose template
        if self._tp is not None:
            with self._tp._lock:
                self._tp._latest_verts = None
                self._tp._joints       = None
                if self._tp._net is not None:
                    try:
                        self._tp._net.reset()
                    except Exception:
                        pass
        # Reset mesh to T-pose template vertices
        if self._faces is not None:
            try:
                smpl  = np.load(_SMPL_NPZ, allow_pickle=True)
                verts = smpl['v_template'].astype(np.float64)
                mesh  = o3d.geometry.TriangleMesh()
                mesh.vertices  = o3d.utility.Vector3dVector(verts)
                mesh.triangles = o3d.utility.Vector3iVector(self._faces)
                mesh.paint_uniform_color([0.80, 0.62, 0.46])
                mesh.compute_vertex_normals()
                sc = self._scene.scene
                sc.remove_geometry("mesh")
                sc.add_geometry("mesh", mesh, self._mat_mesh)
                sc.remove_geometry("tp_skel")
                sc.remove_geometry("ik_skel")
            except Exception as e:
                print(f"[reset_tpose] {e}")

    def _prop_changed(self):
        self._cmd({"SetProportions": {
            "leg":   self._leg_s.double_value,
            "arm":   self._arm_s.double_value,
            "spine": self._spine_s.double_value,
        }})

    def _smooth_changed(self):
        self._cmd({"SetSmoothingParams": {
            "min_cutoff": self._cutoff_s.double_value,
            "beta":       self._beta_s.double_value,
        }})

    def _on_osc_apply(self):
        try:
            self._cmd({"SetOscTarget": [self._osc_ip.text_value, int(self._osc_port.text_value)]})
        except: pass

    def _on_rec_config(self):
        try:
            self._cmd({"SetRecorderConfig": {
                "filename":         self._rec_file.text_value,
                "batch_size":       int(self._rec_batch.text_value),
                "flush_interval_ms":int(self._rec_flush.text_value),
            }})
        except: pass

    def _on_serial_apply(self):
        self._cmd({"SetSerialConfig": {
            "enabled": self._ser_en.checked,
            "port":    self._ser_port.text_value,
            "baud":    int(self._ser_baud.text_value) if self._ser_baud.text_value.isdigit() else 115200,
        }})

    def _apply_message(self, msg):
        try:
            data = json.loads(msg) if isinstance(msg, str) else msg
            if isinstance(data, dict):
                if data.get("type") == "Snapshot":
                    self.snapshot = data.get("data", {})
                elif data.get("type") == "Status":
                    pass
        except: pass

    # ── 3D scene update ───────────────────────────────────────────────────────

    def _update_mesh(self, verts: np.ndarray):
        if self._faces is None:
            return
        mesh = o3d.geometry.TriangleMesh()
        mesh.vertices  = o3d.utility.Vector3dVector(verts.astype(np.float64))
        mesh.triangles = o3d.utility.Vector3iVector(self._faces)
        mesh.paint_uniform_color([0.80, 0.62, 0.46])
        mesh.compute_vertex_normals()
        sc = self._scene.scene
        sc.remove_geometry("mesh")
        sc.add_geometry("mesh", mesh, self._mat_mesh)

    def _update_ik_skeleton(self, bones: list, trackers: dict):
        by_id = {b["id"]: b for b in bones}
        pts, lines, colors = [], [], []
        idx_map = {}

        for b in bones:
            bid = b["id"]
            if bid not in idx_map:
                idx_map[bid] = len(pts)
                pts.append(np.asarray(b["pos"], dtype=np.float64) + IK_SKELETON_OFFSET)

        for b in bones:
            pid = b.get("parent_id")
            if pid is None or pid not in idx_map or b["id"] not in idx_map:
                continue
            bid = b["id"]
            lines.append([idx_map[pid], idx_map[bid]])
            if bid in LEFT_BONE_IDS:
                colors.append([0.0,  0.78, 0.78])   # cyan — left
            elif bid in RIGHT_BONE_IDS:
                colors.append([1.0,  0.69, 0.35])   # orange — right
            else:
                colors.append([0.78, 0.82, 0.86])   # white — spine

        if not pts or not lines:
            return
        ls = o3d.geometry.LineSet()
        ls.points  = o3d.utility.Vector3dVector(np.array(pts, np.float64))
        ls.lines   = o3d.utility.Vector2iVector(np.array(lines, np.int32))
        ls.colors  = o3d.utility.Vector3dVector(np.array(colors, np.float64))
        sc = self._scene.scene
        sc.remove_geometry("ik_skel")
        sc.add_geometry("ik_skel", ls, self._mat_line)

    def _update_tp_joints(self, joints: np.ndarray):
        pts    = np.asarray(joints, dtype=np.float64) + TP_SKELETON_OFFSET
        lines  = list(SMPL_BONES)
        # Same color scheme as IK skeleton
        colors = [([0.0, 0.78, 0.78] if b in SMPL_LEFT else
                   [1.0, 0.69, 0.35] if b in SMPL_RIGHT else
                   [0.78, 0.82, 0.86]) for a, b in SMPL_BONES]
        ls = o3d.geometry.LineSet()
        ls.points  = o3d.utility.Vector3dVector(pts)
        ls.lines   = o3d.utility.Vector2iVector(np.array(lines, np.int32))
        ls.colors  = o3d.utility.Vector3dVector(np.array(colors, np.float64))
        sc = self._scene.scene
        sc.remove_geometry("tp_skel")
        sc.add_geometry("tp_skel", ls, self._mat_line2)

    # ── refresh ───────────────────────────────────────────────────────────────

    def _refresh(self, dt: float = 0.033):
        # Camera movement tick (apply() called inside tick)
        self._cam.tick(dt)

        msg = self.ws.get_update()
        while msg is not None:
            self._apply_message(msg)
            msg = self.ws.get_update()

        snap     = self.snapshot
        trackers = snap.get("trackers", {})

        # Status
        ok = self.ws.is_connected()
        self._status_lbl.text = "● Connected" if ok else "● Disconnected"
        self._status_lbl.text_color = (gui.Color(0.31, 0.73, 0.47) if ok
                                       else gui.Color(0.75, 0.35, 0.35))
        self._tp_lbl.text = f"TP: {self._tp.status}"

        # Packets
        self._pkt_lbl.text = f"Packets: {snap.get('packet_count', 0):,}"

        # TransPose
        if self._tp:
            self._tp.push_frame(trackers)

        # Monitor rows
        items = sorted(trackers.items())
        for i, (st_l, det_l) in enumerate(self._mon_rows):
            if i < len(items):
                _, t = items[i]
                tid      = t.get('id','?')
                conn     = t.get('connection_type','?')
                tps      = t.get('tps', 0)
                bone_id  = t.get('assigned_bone')
                bone_str = BONE_NAMES.get(bone_id, "—") if bone_id is not None else "—"
                st_l.text  = f"ID {tid}  {conn}  {tps}tps  → {bone_str}"
                batt = t.get('battery', 0)
                loss = t.get('lost_packets', 0)
                recv = max(t.get('received_packets', 1), 1)
                det_l.text = f"Batt {batt:.0f}%  Loss {100*loss/recv:.1f}%  RSSI {t.get('rssi',0)}dBm"
            else:
                st_l.text  = ""
                det_l.text = ""

        # Calibration tracker rows
        for i, (row, lbl, combo) in enumerate(self._cal_rows):
            if i < len(items):
                _, t = items[i]
                lbl.text = f"ID {t.get('id','?')}"
            else:
                lbl.text = ""

        # Recording status
        if snap.get('is_recording'):
            self._rec_st_lbl.text = f"● Recording — dropped:{snap.get('recorder_dropped_count',0)}"
            self._rec_st_lbl.text_color = gui.Color(0.9, 0.35, 0.35)
        else:
            self._rec_st_lbl.text = "Idle"
            self._rec_st_lbl.text_color = gui.Color(0.51, 0.53, 0.57)

        # Serial status
        msg_s = snap.get('serial_status_msg', '')
        if msg_s:
            self._ser_st_lbl.text = msg_s

        # 3D scene updates
        bones = snap.get("bones", [])
        if bones:
            self._update_ik_skeleton(bones, trackers)

        if self._tp:
            verts = self._tp.get_latest_verts()
            if verts is not None:
                self._update_mesh(verts)
                if self._faces is not None and self._tp._faces is None:
                    self._tp._faces = self._faces

            joints = self._tp.get_joints()
            if joints is not None:
                self._update_tp_joints(joints)

    def _refresh_loop(self):
        last = time.perf_counter()
        while True:
            time.sleep(1 / 60)
            now = time.perf_counter()
            dt  = now - last; last = now
            self._app.post_to_main_thread(self.window,
                                          lambda d=dt: self._refresh(d))

    def run(self):
        self.ws.start()
        threading.Thread(target=self._refresh_loop, daemon=True, name="refresh").start()
        # Open browser panel
        import webbrowser, pathlib
        html = pathlib.Path(__file__).parent / "panel.html"
        webbrowser.open(html.as_uri())
        self._app.run()


if __name__ == "__main__":
    App().run()
