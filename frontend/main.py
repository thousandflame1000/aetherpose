"""
Aetherpose — Open3D GUI frontend (single window, no browser dependency)
  Left  : Open3D SceneWidget — SMPL mesh + IK skeleton + TP joints
  Right : control panel — Calibration / Monitor / Body / System tabs
"""

import os, time, threading, json, math, subprocess
import numpy as np
import open3d as o3d
import open3d.visualization.gui      as gui
import open3d.visualization.rendering as rendering
from ws_client import WsClient
from transpose_runner import (
    TransPoseRunner, SMPL_BONES, SMPL_LEFT, SMPL_RIGHT,
    _SMPL_NPZ,
)


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

# Keep line skeletons readable by drawing them beside the body mesh.
IK_SKELETON_OFFSET = np.array([-1.35, 0.0, 0.0], dtype=np.float64)
TP_SKELETON_OFFSET = np.array([ 1.35, 0.0, 0.0], dtype=np.float64)


# ── Reach-target mini-game ──────────────────────────────────────────────────
# Pure-IMU interaction: no mouse/keyboard. Floating targets pop when a
# tracked hand (driven by the live or demo-playback pose) reaches them.
SMPL_L_HAND = 22
SMPL_R_HAND = 23

class TargetGame:
    N_TARGETS  = 3
    HIT_RADIUS = 0.16
    _CENTER    = TP_SKELETON_OFFSET + np.array([0.0, 1.25, 0.0])
    _SPAN      = np.array([0.45, 0.30, 0.35])

    def __init__(self):
        self.score = 0
        self.hit_flash = 0.0   # seconds remaining on the last-hit visual pulse
        self.targets = [self._spawn_pos() for _ in range(self.N_TARGETS)]

    def _spawn_pos(self) -> np.ndarray:
        return self._CENTER + np.random.uniform(-1.0, 1.0, 3) * self._SPAN

    def update(self, joints: np.ndarray | None, dt: float) -> list[int]:
        """Check tracked hands against targets; respawn on hit.
        Returns indices of targets that were just hit (for a visual pulse)."""
        self.hit_flash = max(0.0, self.hit_flash - dt)
        if joints is None or len(joints) <= SMPL_R_HAND:
            return []
        hands = [joints[SMPL_L_HAND] + TP_SKELETON_OFFSET,
                 joints[SMPL_R_HAND] + TP_SKELETON_OFFSET]
        hit_idx = []
        for i, t in enumerate(self.targets):
            if any(np.linalg.norm(h - t) < self.HIT_RADIUS for h in hands):
                self.targets[i] = self._spawn_pos()
                self.score += 1
                self.hit_flash = 0.25
                hit_idx.append(i)
        return hit_idx


# ── App ───────────────────────────────────────────────────────────────────────

class App:
    MAX_TRACKERS  = 8
    TARGET_RADIUS = 0.06

    def __init__(self):
        app = gui.Application.instance
        app.initialize()
        self._app = app

        win_w, win_h = 1400, 820
        try:
            import ctypes
            user32 = ctypes.windll.user32
            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)
            if screen_w > 0 and screen_h > 0:
                # Leave room for the taskbar/title bar so the window (and its
                # control panel, which lives at the far right edge) is never
                # clipped off a smaller demo-room display or projector.
                win_w = min(win_w, int(screen_w * 0.92))
                win_h = min(win_h, int(screen_h * 0.88))
        except Exception:
            pass
        self.window = app.create_window("Aetherpose", win_w, win_h)
        em = self.window.theme.font_size
        self._em = em

        self.ws       = WsClient(WS_URL)
        self.snapshot = {}
        self._tp      = TransPoseRunner()
        self._faces: np.ndarray | None = None
        self._verts_version  = 0
        self._joints_version = 0
        self._last_bones_key = None
        self._last_geo_update = 0.0
        self._geo_interval    = 1.0 / 20   # cap GPU geometry churn at ~20 Hz
        self._game = TargetGame()

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

        # Reach-target mini-game markers — repositioned via set_geometry_transform
        # each frame (cheap: no GPU realloc), driven purely by tracked hand joints.
        self._mat_target = rendering.MaterialRecord()
        self._mat_target.shader = "defaultUnlit"
        target_mesh = o3d.geometry.TriangleMesh.create_sphere(radius=self.TARGET_RADIUS)
        target_mesh.compute_vertex_normals()
        target_mesh.paint_uniform_color([1.0, 0.84, 0.30])
        for i, pos in enumerate(self._game.targets):
            name = f"target_{i}"
            sc.add_geometry(name, target_mesh, self._mat_target)
            sc.set_geometry_transform(name, self._translation(pos))

        # Camera — custom FPS (roll locked to 0). setup_camera() derives its
        # projection from the SceneWidget's current pixel size, which is
        # still 0x0 here (no layout pass has run yet) — calling it this early
        # produces an invalid projection and an all-black viewport. It gets
        # called for real on the first _on_layout() once the widget has a
        # real frame.
        self._cam = FPSCamera(self._scene)
        self._scene.set_view_controls(gui.SceneWidget.Controls.ROTATE_CAMERA)
        self._camera_bounds = o3d.geometry.AxisAlignedBoundingBox(
            np.array([-2.8, -1.2, -1.2]), np.array([2.8, 2.2, 1.2]))
        self._camera_ready = False
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

        # ── palette ────────────────────────────────────────────────────────
        # Every widget below takes its own background_color override — the
        # shared Theme object has no color knobs, so this is the only way to
        # get out of the default flat-gray look.
        pal = {
            "bg":      gui.Color(0.08, 0.10, 0.14),   # matches the 3D viewport
            "card":    gui.Color(0.13, 0.16, 0.21),
            "tabs":    gui.Color(0.10, 0.125, 0.16),
            "accent":  gui.Color(0.40, 0.65, 1.00),   # primary actions
            "danger":  gui.Color(0.90, 0.45, 0.45),   # destructive actions
            "neutral": gui.Color(0.24, 0.28, 0.35),   # secondary actions
        }
        self._pal = pal
        panel.background_color = pal["bg"]

        def card(title):
            c = gui.CollapsableVert(title, sp, gui.Margins(0))
            c.background_color = pal["card"]
            return c

        def btn(label, kind="neutral"):
            b = gui.Button(label)
            b.background_color = pal[kind]
            return b

        # ── status bar ──────────────────────────────────────────────────────
        # Stacked rather than squeezed onto one stretched row — a stretch-to-
        # the-edge layout clips the trailing label the moment the panel is
        # narrower than "status text + packet count" combined.
        self._status_lbl = gui.Label("Disconnected")
        self._status_lbl.text_color = gui.Color(0.96, 0.31, 0.31)
        self._pkt_lbl = gui.Label("0 pkts")
        self._pkt_lbl.text_color = gui.Color(0.50, 0.53, 0.58)
        panel.add_child(self._status_lbl)
        panel.add_child(self._pkt_lbl)

        # ── TP status ───────────────────────────────────────────────────────
        self._tp_lbl = gui.Label("Initializing...")
        self._tp_lbl.text_color = gui.Color(1.0, 0.69, 0.35)
        panel.add_child(self._tp_lbl)

        # ── reach-target mini-game score ───────────────────────────────────
        self._score_lbl = gui.Label("Reach targets: 0")
        self._score_lbl.text_color = gui.Color(1.0, 0.84, 0.30)
        panel.add_child(self._score_lbl)

        tabs = gui.TabControl()
        tabs.background_color = pal["tabs"]

        # ────────────────────────────────────────────────────────────────────
        # TAB: Calibration
        # ────────────────────────────────────────────────────────────────────
        cal = gui.ScrollableVert(sp, gui.Margins(p, sp, p, sp))
        cal.background_color = pal["bg"]

        sec_actions = card("Actions")
        r1 = gui.Horiz(sp)
        for lbl, c in [("Reset Yaw","ResetYaw"),("Reset Mount","ResetMounting")]:
            b = btn(lbl); b.set_on_clicked(lambda x=c: self._cmd(x)); r1.add_child(b)
        sec_actions.add_child(r1)
        r2 = gui.Horiz(sp)
        b_aa = btn("Auto Assign", "accent"); b_aa.set_on_clicked(lambda: self._cmd("AutoAssign"))
        b_cc = btn("Clear Cal.", "danger");  b_cc.set_on_clicked(lambda: self._cmd("ClearAllCalibration"))
        r2.add_child(b_aa); r2.add_child(b_cc)
        sec_actions.add_child(r2)
        r3 = gui.Horiz(sp)
        b_tp = btn("Reset T-Pose"); b_tp.set_on_clicked(self._reset_tpose)
        r3.add_child(b_tp)
        sec_actions.add_child(r3)
        cal.add_child(sec_actions)

        sec_tr = card("Trackers")
        self._cal_bone_ids = list(BONE_NAMES.keys())
        self._cal_rows: list = []
        for _ in range(self.MAX_TRACKERS):
            row = gui.Horiz(sp)
            lbl = gui.Label(""); lbl.text_color = gui.Color(0.35, 0.70, 1.0)
            combo = gui.Combobox()
            combo.add_item("Unassigned")
            for bn in BONE_NAMES.values(): combo.add_item(bn)
            tracker_id_box = [None]  # mutable cell holding this row's current tracker id
            combo.set_on_selection_changed(
                lambda text, idx, box=tracker_id_box: self._on_bone_assign(box[0], idx))
            row.add_fixed(int(em * 3)); row.add_child(lbl)
            row.add_stretch(); row.add_child(combo)
            row.add_fixed(int(em * 0.3))   # trailing gap so the dropdown never hugs the edge
            sec_tr.add_child(row)
            self._cal_rows.append((row, lbl, combo, tracker_id_box))
        cal.add_child(sec_tr)
        tabs.add_tab("Calibration", cal)

        # ────────────────────────────────────────────────────────────────────
        # TAB: Monitor
        # ────────────────────────────────────────────────────────────────────
        mon = gui.ScrollableVert(sp, gui.Margins(p, sp, p, sp))
        mon.background_color = pal["bg"]
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
        body.background_color = pal["bg"]

        sec_prop = card("Proportions")
        self._ik_s    = self._isl(sec_prop, "IK Smooth", 0.0, 1.0,  0.5, em,
                                  lambda v: self._cmd({"SetIkSmoothness": v}))
        self._leg_s   = self._isl(sec_prop, "Legs",      0.5, 1.5,  1.0, em, lambda v: self._prop_changed())
        self._arm_s   = self._isl(sec_prop, "Arms",      0.5, 1.5,  1.0, em, lambda v: self._prop_changed())
        self._spine_s = self._isl(sec_prop, "Spine",     0.5, 1.5,  1.0, em, lambda v: self._prop_changed())
        body.add_child(sec_prop)

        sec_filt = card("One Euro Filter")
        self._cutoff_s = self._isl(sec_filt, "Cutoff", 0.01, 5.0, 3.0, em, lambda v: self._smooth_changed())
        self._beta_s   = self._isl(sec_filt, "Beta",    0.0, 10.0, 3.0, em, lambda v: self._smooth_changed())
        body.add_child(sec_filt)

        sec_floor = card("Virtual Floor")
        fr = gui.Horiz(sp)
        lf = gui.Label("Offset"); lf.text_color = gui.Color(0.50, 0.53, 0.58)
        fr.add_child(lf); fr.add_fixed(int(em * 0.3))
        self._floor_s = gui.Slider(gui.Slider.DOUBLE)
        self._floor_s.set_limits(-2.0, 2.0); self._floor_s.double_value = 0.0
        self._floor_s.set_on_value_changed(lambda v: self._cmd({"SetFloorOffset": v}))
        btn_af = btn("Auto"); btn_af.set_on_clicked(lambda: self._cmd("AutoFloor"))
        fr.add_child(self._floor_s); fr.add_child(btn_af)
        sec_floor.add_child(fr)
        body.add_child(sec_floor)

        sec_misc = card("Drift / Trajectory")
        self._drift_s = self._isl(sec_misc, "Drift", 0.0, 1.0, 0.0, em,
                                  lambda v: self._cmd({"SetDriftCorrection": v}))
        tr = gui.Horiz(sp)
        for lbl, mode in [("RK4","rk4"),("Euler","euler")]:
            b = btn(lbl)
            b.set_on_clicked(lambda m=mode: self._cmd({"SetTrajectoryIntegrationMode": m}))
            tr.add_child(b)
        sec_misc.add_child(tr)
        body.add_child(sec_misc)

        sec_leg = card("Leg Calibration")
        lr = gui.Horiz(sp)
        b_lc0 = btn("Start Leg Cal", "accent"); b_lc0.set_on_clicked(lambda: self._cmd("StartLegCalibration"))
        b_lc1 = btn("Stop", "danger");          b_lc1.set_on_clicked(lambda: self._cmd("StopLegCalibration"))
        lr.add_child(b_lc0); lr.add_child(b_lc1)
        sec_leg.add_child(lr)
        self._leg_ratio_lbl = gui.Label("Leg ratio: -")
        self._leg_ratio_lbl.text_color = gui.Color(0.50, 0.53, 0.58)
        sec_leg.add_child(self._leg_ratio_lbl)
        body.add_child(sec_leg)
        tabs.add_tab("Body", body)

        # ────────────────────────────────────────────────────────────────────
        # TAB: System
        # ────────────────────────────────────────────────────────────────────
        sys_t = gui.ScrollableVert(sp, gui.Margins(p, sp, p, sp))
        sys_t.background_color = pal["bg"]

        sec_osc = card("OSC Output")
        self._osc_ip   = gui.TextEdit(); self._osc_ip.text_value   = "127.0.0.1"
        self._osc_port = gui.TextEdit(); self._osc_port.text_value = "9000"
        sec_osc.add_child(self._fw("IP",   self._osc_ip,   em))
        sec_osc.add_child(self._fw("Port", self._osc_port, em))
        b_osc = btn("Apply OSC", "accent"); b_osc.set_on_clicked(self._on_osc_apply)
        sec_osc.add_child(b_osc)
        sys_t.add_child(sec_osc)

        sec_zupt = card("ZUPT")
        self._zupt_en = gui.Checkbox("Enabled"); self._zupt_en.checked = True
        self._zupt_en.set_on_checked(lambda v: self._cmd({"SetZuptEnabled": v}))
        sec_zupt.add_child(self._zupt_en)
        self._zupt_win   = gui.TextEdit(); self._zupt_win.text_value   = "8"
        self._zupt_accel = gui.TextEdit(); self._zupt_accel.text_value = "0.0005"
        self._zupt_gyro  = gui.TextEdit(); self._zupt_gyro.text_value  = "0.02"
        sec_zupt.add_child(self._fw("Window",    self._zupt_win,   em))
        sec_zupt.add_child(self._fw("Accel Var", self._zupt_accel, em))
        sec_zupt.add_child(self._fw("Gyro Thr.", self._zupt_gyro,  em))
        b_zupt = btn("Apply ZUPT", "accent"); b_zupt.set_on_clicked(self._on_zupt_apply)
        sec_zupt.add_child(b_zupt)
        sys_t.add_child(sec_zupt)

        sec_rec = card("Recording")
        self._rec_file  = gui.TextEdit(); self._rec_file.text_value  = "recording.bin"
        self._rec_batch = gui.TextEdit(); self._rec_batch.text_value = "128"
        self._rec_flush = gui.TextEdit(); self._rec_flush.text_value = "500"
        sec_rec.add_child(self._fw("File",    self._rec_file,  em))
        bf = gui.Horiz(sp)
        bf.add_child(self._fw("Batch",    self._rec_batch, em))
        bf.add_child(self._fw("Flush ms", self._rec_flush, em))
        sec_rec.add_child(bf)
        rc = gui.Horiz(sp)
        b_rcfg = btn("Config");            b_rcfg.set_on_clicked(self._on_rec_config)
        b_rs   = btn("Start Rec", "accent"); b_rs.set_on_clicked(lambda: self._cmd("StartRecording"))
        b_rx   = btn("Stop Rec", "danger");  b_rx.set_on_clicked(lambda: self._cmd("StopRecording"))
        rc.add_child(b_rcfg); rc.add_child(b_rs); rc.add_child(b_rx)
        sec_rec.add_child(rc)
        self._rec_st_lbl = gui.Label("Idle"); self._rec_st_lbl.text_color = gui.Color(0.50,0.53,0.58)
        sec_rec.add_child(self._rec_st_lbl)
        sys_t.add_child(sec_rec)

        sec_ser = card("Serial")
        self._ser_port = gui.TextEdit(); self._ser_port.text_value = "COM3"
        self._ser_baud = gui.TextEdit(); self._ser_baud.text_value = "115200"
        self._ser_en   = gui.Checkbox("Enabled")
        sec_ser.add_child(self._fw("Port", self._ser_port, em))
        sec_ser.add_child(self._fw("Baud", self._ser_baud, em))
        sec_ser.add_child(self._ser_en)
        b_ser = btn("Apply Serial", "accent"); b_ser.set_on_clicked(self._on_serial_apply)
        sec_ser.add_child(b_ser)
        self._ser_st_lbl = gui.Label(""); self._ser_st_lbl.text_color = gui.Color(0.50,0.53,0.58)
        sec_ser.add_child(self._ser_st_lbl)
        sys_t.add_child(sec_ser)
        tabs.add_tab("System", sys_t)

        # ────────────────────────────────────────────────────────────────────
        # TAB: Apps — sub-projects that run on top of the same backend
        # ────────────────────────────────────────────────────────────────────
        apps = gui.ScrollableVert(sp, gui.Margins(p, sp, p, sp))
        apps.background_color = pal["bg"]
        sec_combat = card("Aether Combat")
        combat_info = gui.Label("Browser 3D body view (combat/)")
        combat_info.text_color = gui.Color(0.50, 0.53, 0.58)
        sec_combat.add_child(combat_info)
        b_combat = btn("Open Aether Combat", "accent"); b_combat.set_on_clicked(self._on_open_combat)
        sec_combat.add_child(b_combat)
        self._combat_st_lbl = gui.Label(""); self._combat_st_lbl.text_color = gui.Color(0.50,0.53,0.58)
        sec_combat.add_child(self._combat_st_lbl)
        apps.add_child(sec_combat)
        tabs.add_tab("Apps", apps)

        panel.add_child(tabs)
        self._panel = panel
        self.window.add_child(panel)

    # ── layout ────────────────────────────────────────────────────────────────

    def _on_layout(self, ctx):
        r = self.window.content_rect
        panel_w = int(ctx.theme.font_size * 21)
        self._scene.frame  = gui.Rect(r.x, r.y, r.width - panel_w, r.height)
        self._panel.frame  = gui.Rect(r.x + r.width - panel_w, r.y, panel_w, r.height)
        if not self._camera_ready and self._scene.frame.width > 0 and self._scene.frame.height > 0:
            self._camera_ready = True
            self._scene.setup_camera(60.0, self._camera_bounds, np.array([0.0, 0.8, 0.0]))
            self._cam.apply()

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

    @staticmethod
    def _tp_display(status: str) -> tuple[str, gui.Color]:
        """Collapse the internal TransPose status string into a short,
        presentation-friendly label (no debug jargon)."""
        if status.startswith("Error"):
            return "Error", gui.Color(0.90, 0.35, 0.35)
        if status.startswith(("Loading", "Ready")):
            return "Initializing...", gui.Color(0.90, 0.65, 0.30)
        if "LIVE 6/6" in status:
            return "Live Motion Capture", gui.Color(0.35, 0.85, 0.55)
        return "Demo Playback", gui.Color(0.55, 0.78, 1.0)

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
                self._tp._origin_t     = None
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

    def _on_bone_assign(self, tracker_id, combo_idx):
        if tracker_id is None or combo_idx <= 0:
            return
        bone_id = self._cal_bone_ids[combo_idx - 1]
        self._cmd({"AssignTracker": [tracker_id, bone_id]})

    def _on_zupt_apply(self):
        try:
            self._cmd({"SetZuptParams": {
                "window_size":         int(self._zupt_win.text_value),
                "accel_var_threshold": float(self._zupt_accel.text_value),
                "gyro_threshold":      float(self._zupt_gyro.text_value),
            }})
        except: pass

    def _on_rec_config(self):
        try:
            self._cmd({"SetRecorderConfig": {
                "filename":         self._rec_file.text_value,
                "batch_size":       int(self._rec_batch.text_value),
                "flush_interval_ms":int(self._rec_flush.text_value),
            }})
        except: pass

    def _on_open_combat(self):
        """Launch combat/run.ps1, which starts mesh_bridge and the page server
        if they are not running yet and opens the browser. It can take up to a
        minute while mesh_bridge loads TransPose, so it runs off the UI thread."""
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "combat", "run.ps1")
        self._combat_st_lbl.text = "Starting..."

        def launch():
            try:
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
                    capture_output=True, text=True, timeout=180,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                out = (res.stdout.strip() or res.stderr.strip()).splitlines()
                msg = "Opened in browser" if res.returncode == 0 else f"Failed: {out[-1] if out else res.returncode}"
            except Exception as e:
                msg = f"Failed: {e}"

            def show():
                self._combat_st_lbl.text = msg
            self._app.post_to_main_thread(self.window, show)

        threading.Thread(target=launch, daemon=True, name="combat-launch").start()

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

    @staticmethod
    def _translation(pos: np.ndarray) -> np.ndarray:
        t = np.eye(4)
        t[:3, 3] = pos
        return t

    def _update_targets(self, hit_idx: list[int]):
        """Reposition target markers via a transform update — no geometry
        realloc, so this is cheap enough to run every throttled tick."""
        sc = self._scene.scene
        for i, pos in enumerate(self._game.targets):
            scale = 1.35 if i in hit_idx else 1.0
            t = self._translation(pos)
            t[:3, :3] *= scale
            sc.set_geometry_transform(f"target_{i}", t)

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
        self._status_lbl.text = "Connected" if ok else "Disconnected"
        self._status_lbl.text_color = (gui.Color(0.31, 0.73, 0.47) if ok
                                       else gui.Color(0.75, 0.35, 0.35))
        tp_text, tp_color = self._tp_display(self._tp.status)
        self._tp_lbl.text = tp_text
        self._tp_lbl.text_color = tp_color

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
                bone_str = BONE_NAMES.get(bone_id, "-") if bone_id is not None else "-"
                st_l.text  = f"ID {tid}  {conn}  {tps}tps  -> {bone_str}"
                batt = t.get('battery', 0)
                loss = t.get('lost_packets', 0)
                recv = max(t.get('received_packets', 1), 1)
                det_l.text = f"Batt {batt:.0f}%  Loss {100*loss/recv:.1f}%  RSSI {t.get('rssi',0)}dBm"
            else:
                st_l.text  = ""
                det_l.text = ""

        # Calibration tracker rows
        for i, (row, lbl, combo, tracker_id_box) in enumerate(self._cal_rows):
            if i < len(items):
                _, t = items[i]
                tracker_id_box[0] = t.get('id')
                lbl.text = f"ID {t.get('id','?')}"
                bone_id = t.get('assigned_bone')
                idx = (self._cal_bone_ids.index(bone_id) + 1
                       if bone_id in self._cal_bone_ids else 0)
                if combo.selected_index != idx:
                    combo.selected_index = idx
            else:
                tracker_id_box[0] = None
                lbl.text = ""

        # Leg ratio
        leg_ratio = snap.get('leg_ratio')
        if leg_ratio is not None:
            self._leg_ratio_lbl.text = f"Leg ratio: {leg_ratio:.3f}"

        # Recording status
        if snap.get('is_recording'):
            self._rec_st_lbl.text = f"Recording (dropped: {snap.get('recorder_dropped_count',0)})"
            self._rec_st_lbl.text_color = gui.Color(0.9, 0.35, 0.35)
        else:
            self._rec_st_lbl.text = "Idle"
            self._rec_st_lbl.text_color = gui.Color(0.51, 0.53, 0.57)

        # Serial status
        msg_s = snap.get('serial_status_msg', '')
        if msg_s:
            self._ser_st_lbl.text = msg_s

        # 3D scene updates — capped rate. Filament (the renderer) has to
        # reallocate GPU buffers on every remove/add of a geometry, and the
        # skeleton/mesh here would otherwise churn that at a full 60 Hz even
        # when nothing moved; that's needless driver load a demo laptop's
        # GPU doesn't need to eat, so update at a perceptually-smooth ~20 Hz
        # and skip anything that hasn't actually changed since last time.
        now_t = time.perf_counter()
        if now_t - self._last_geo_update >= self._geo_interval:
            self._last_geo_update = now_t

            bones = snap.get("bones", [])
            if bones:
                bones_key = tuple(round(c, 3) for b in bones for c in b["pos"])
                if bones_key != self._last_bones_key:
                    self._last_bones_key = bones_key
                    self._update_ik_skeleton(bones, trackers)

            if self._tp:
                verts, self._verts_version = self._tp.get_latest_verts_if_new(self._verts_version)
                if verts is not None:
                    self._update_mesh(verts)
                    if self._faces is not None and self._tp._faces is None:
                        self._tp._faces = self._faces

                joints, self._joints_version = self._tp.get_joints_if_new(self._joints_version)
                if joints is not None:
                    self._update_tp_joints(joints)
                    hit_idx = self._game.update(joints, self._geo_interval)
                    self._update_targets(hit_idx)

        self._score_lbl.text = f"Reach targets: {self._game.score}"

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
        self._app.run()
        # Several daemon threads (WS client, TransPose inference/mesh) keep
        # touching Python/torch state after the window closes. Letting the
        # interpreter run its normal finalization races with them and
        # reliably crashes with "Fatal Python error: gilstate_tss_set" on
        # exit. Nothing here needs a graceful teardown, so skip it.
        os._exit(0)


if __name__ == "__main__":
    App().run()
