use crate::app::types::{CameraProjectionMode, TrackerState};
use crate::i18n::I18n;
use crate::imu::calibration::MagCalibration;
use crate::skeleton::model::SkeletonModel;
use crate::theme::{Theme, BATTERY_H, BATTERY_W, BTN_PAD_X, BTN_PAD_Y, UI_FOREGROUND};
use eframe::{
    egui,
    epaint::{Color32, Pos2, Stroke},
};
use nalgebra::{Matrix4, Rotation3, Vector3, Vector4};
use std::collections::HashMap;

pub struct DrawCtx<'a> {
    pub painter: &'a egui::Painter,
    pub rect: egui::Rect,
    pub yaw: f32,
    pub pitch: f32,
    pub zoom: f32,
    pub camera_projection: CameraProjectionMode,
    pub th: &'a Theme,
}

pub struct CameraTransform {
    pub view: Matrix4<f32>,
    pub projection: Matrix4<f32>,
    pub view_projection: Matrix4<f32>,
    screen_center: Pos2,
    screen_y_offset: f32,
}

impl CameraTransform {
    fn project(&self, point: Vector3<f32>) -> (Pos2, f32) {
        let world = Vector4::new(point.x, point.y, point.z, 1.0);
        let camera = self.view * world;
        let projected = self.projection * camera;
        let inv_w = if projected.w.abs() > 1e-5 {
            1.0 / projected.w
        } else {
            1.0
        };

        (
            Pos2::new(
                self.screen_center.x + projected.x * inv_w,
                self.screen_center.y + self.screen_y_offset + projected.y * inv_w,
            ),
            camera.z,
        )
    }
}

pub fn camera_transform(
    ctx: &DrawCtx,
    mirror_view: bool,
    base_scale: f32,
    screen_y_offset: f32,
) -> CameraTransform {
    const PERSPECTIVE_STRENGTH: f32 = 0.12;

    let pitch = Rotation3::from_axis_angle(&Vector3::x_axis(), ctx.pitch);
    let yaw = Rotation3::from_axis_angle(&Vector3::y_axis(), -ctx.yaw);
    let rotation = (yaw * pitch).to_homogeneous();
    let mirror = if mirror_view {
        Matrix4::new_nonuniform_scaling(&Vector3::new(-1.0, 1.0, 1.0))
    } else {
        Matrix4::identity()
    };

    let scale = base_scale * ctx.zoom;
    let projection = match ctx.camera_projection {
        CameraProjectionMode::Orthographic => Matrix4::new(
            scale, 0.0, 0.0, 0.0,
            0.0, -scale, 0.0, 0.0,
            0.0,  0.0,   1.0, 0.0,
            0.0,  0.0,   0.0, 1.0,
        ),
        CameraProjectionMode::Perspective => Matrix4::new(
            scale, 0.0,   0.0, 0.0,
            0.0, -scale,  0.0, 0.0,
            0.0,  0.0,    1.0, 0.0,
            0.0,  0.0,    PERSPECTIVE_STRENGTH, 1.0,
        ),
    };

    let view = mirror * rotation;
    let view_projection = projection * view;

    CameraTransform {
        view,
        projection,
        view_projection,
        screen_center: ctx.rect.center(),
        screen_y_offset,
    }
}

pub fn format_matrix4(matrix: &Matrix4<f32>) -> String {
    let mut rows = Vec::with_capacity(4);
    for row in 0..4 {
        rows.push(format!(
            "[{:>8.3}, {:>8.3}, {:>8.3}, {:>8.3}]",
            matrix[(row, 0)],
            matrix[(row, 1)],
            matrix[(row, 2)],
            matrix[(row, 3)],
        ));
    }
    rows.join("\n")
}

pub fn draw_magnetometer_points(
    ctx: &DrawCtx,
    all_mag_points: &HashMap<u8, Vec<Vector3<f32>>>,
    active_tracker_id: Option<u8>,
    calibration: Option<&MagCalibration>,
) {
    let camera = camera_transform(ctx, false, 50.0, 0.0);

    enum DrawCmd {
        Point {
            pos: Pos2,
            radius: f32,
            fill: Color32,
            depth: f32,
        },
        Line {
            start: Pos2,
            end: Pos2,
            stroke: Stroke,
            depth: f32,
        },
    }
    impl DrawCmd {
        fn depth(&self) -> f32 {
            match self {
                DrawCmd::Point { depth, .. } => *depth,
                DrawCmd::Line { depth, .. } => *depth,
            }
        }
    }

    let mut cmds = Vec::new();
    let (origin_screen, origin_depth) = camera.project(Vector3::new(0.0, 0.0, 0.0));
    cmds.push(DrawCmd::Point {
        pos: origin_screen,
        radius: 3.0,
        fill: ctx.th.foreground,
        depth: origin_depth,
    });

    let axis_len = 0.5;
    cmds.push(DrawCmd::Line {
        start: origin_screen,
        end: camera.project(Vector3::new(axis_len, 0.0, 0.0)).0,
        stroke: Stroke::new(2.0, ctx.th.axis_x),
        depth: origin_depth,
    });
    cmds.push(DrawCmd::Line {
        start: origin_screen,
        end: camera.project(Vector3::new(0.0, axis_len, 0.0)).0,
        stroke: Stroke::new(2.0, ctx.th.axis_y),
        depth: origin_depth,
    });
    cmds.push(DrawCmd::Line {
        start: origin_screen,
        end: camera.project(Vector3::new(0.0, 0.0, axis_len)).0,
        stroke: Stroke::new(2.0, ctx.th.axis_z),
        depth: origin_depth,
    });

    if let Some(tid) = active_tracker_id {
        if let Some(points) = all_mag_points.get(&tid) {
            for point in points {
                let (screen_pos, depth) = camera.project(*point);
                cmds.push(DrawCmd::Point {
                    pos: screen_pos,
                    radius: 2.0,
                    fill: ctx.th.mag_point,
                    depth,
                });
            }
        }
    }

    if let Some(calib) = calibration {
        let offset = Vector3::from(calib.offset);
        let s = calib.scale;
        let avg_radius = 40.0;
        let rx = avg_radius / s[0];
        let ry = avg_radius / s[1];
        let rz = avg_radius / s[2];
        let steps = 32;
        let ellipse_stroke = Stroke::new(1.0, ctx.th.mag_color);

        let mut xy_points = Vec::with_capacity(steps + 1);
        let mut xz_points = Vec::with_capacity(steps + 1);
        let mut yz_points = Vec::with_capacity(steps + 1);
        let mut total_depth = 0.0;

        for i in 0..=steps {
            let angle = (i as f32 / steps as f32) * std::f32::consts::TAU;
            let (sin_a, cos_a) = angle.sin_cos();

            let p_xy = offset + Vector3::new(rx * cos_a, ry * sin_a, 0.0);
            let (s_xy, d_xy) = camera.project(p_xy);
            xy_points.push(s_xy);
            total_depth += d_xy;

            let p_xz = offset + Vector3::new(rx * cos_a, 0.0, rz * sin_a);
            let (s_xz, d_xz) = camera.project(p_xz);
            xz_points.push(s_xz);
            total_depth += d_xz;

            let p_yz = offset + Vector3::new(0.0, ry * cos_a, rz * sin_a);
            let (s_yz, d_yz) = camera.project(p_yz);
            yz_points.push(s_yz);
            total_depth += d_yz;
        }
        let avg_depth = total_depth / (3.0 * (steps + 1) as f32);

        for i in 0..steps {
            cmds.push(DrawCmd::Line {
                start: xy_points[i],
                end: xy_points[i + 1],
                stroke: ellipse_stroke,
                depth: avg_depth,
            });
            cmds.push(DrawCmd::Line {
                start: xz_points[i],
                end: xz_points[i + 1],
                stroke: ellipse_stroke,
                depth: avg_depth,
            });
            cmds.push(DrawCmd::Line {
                start: yz_points[i],
                end: yz_points[i + 1],
                stroke: ellipse_stroke,
                depth: avg_depth,
            });
        }
    }

    cmds.sort_by(|a, b| {
        a.depth()
            .partial_cmp(&b.depth())
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    for cmd in cmds {
        match cmd {
            DrawCmd::Point {
                pos, radius, fill, ..
            } => ctx.painter.circle_filled(pos, radius, fill),
            DrawCmd::Line {
                start, end, stroke, ..
            } => ctx.painter.line_segment([start, end], stroke),
        };
    }
}

pub fn draw_skeleton(
    ctx: &DrawCtx,
    skeleton: &SkeletonModel,
    show_grid: bool,
    mirror_view: bool,
    trackers: &HashMap<u8, TrackerState>,
    debug_axes: bool,
) {
    let camera = camera_transform(ctx, mirror_view, 100.0, 60.0);

    enum DrawCmd {
        Line {
            start: Pos2,
            end: Pos2,
            stroke: Stroke,
            depth: f32,
        },
        Circle {
            pos: Pos2,
            radius: f32,
            fill: Color32,
            stroke: Stroke,
            depth: f32,
        },
    }
    impl DrawCmd {
        fn depth(&self) -> f32 {
            match self {
                DrawCmd::Line { depth, .. } => *depth,
                DrawCmd::Circle { depth, .. } => *depth,
            }
        }
    }

    let mut cmds = Vec::new();

    if show_grid {
        let grid_stroke = Stroke::new(1.0, ctx.th.grid);
        for i in -4..=4 {
            let off = i as f32;
            let (s1, z1) = camera.project(Vector3::new(-4.0, 0.0, off));
            let (e1, z2) = camera.project(Vector3::new(4.0, 0.0, off));
            cmds.push(DrawCmd::Line {
                start: s1,
                end: e1,
                stroke: grid_stroke,
                depth: (z1 + z2) / 2.0,
            });

            let (s2, z3) = camera.project(Vector3::new(off, 0.0, -4.0));
            let (e2, z4) = camera.project(Vector3::new(off, 0.0, 4.0));
            cmds.push(DrawCmd::Line {
                start: s2,
                end: e2,
                stroke: grid_stroke,
                depth: (z3 + z4) / 2.0,
            });
        }
    }

    let (origin, z_origin) = camera.project(Vector3::new(0.0, 0.0, 0.0));
    let (forward, z_forward) = camera.project(Vector3::new(0.0, 0.0, 1.0));
    cmds.push(DrawCmd::Line {
        start: origin,
        end: forward,
        stroke: Stroke::new(3.0, ctx.th.dir),
        depth: (z_origin + z_forward) / 2.0,
    });

    let c_center = ctx.th.foreground;
    let c_left = ctx.th.left_limb;
    let c_right = ctx.th.right_limb;
    let tracker_color = ctx.th.tracker;
    let border_stroke = Stroke::new(2.0, ctx.th.border);

    // Depth range for shading: collect all z_camera values to normalise.
    // We use a fixed expected range [−1.5, +1.5] world-units (body half-depth ~0.15m,
    // skeleton scale ~1.8m tall). Clamp prevents division edge cases.
    const DEPTH_HALF: f32 = 1.5;

    // dim(t) → multiply each RGB channel by t ∈ [0,1]
    let shade = |c: Color32, z_cam: f32| -> Color32 {
        // z_cam < 0  = closer to camera (front) → brighter
        // z_cam > 0  = farther from camera (back) → darker
        // t ∈ [0.45 .. 1.0]
        let t = 1.0 - 0.55 * ((z_cam / DEPTH_HALF).clamp(-1.0, 1.0) * 0.5 + 0.5);
        Color32::from_rgba_unmultiplied(
            (c.r() as f32 * t) as u8,
            (c.g() as f32 * t) as u8,
            (c.b() as f32 * t) as u8,
            c.a(),
        )
    };

    for bone in skeleton.bones.values() {
        let pos = bone.global_position;
        let (screen_pos, depth) = camera.project(pos);
        let base_color = if bone.id < 10 {
            c_center
        } else if (10..20).contains(&bone.id) || (30..40).contains(&bone.id) {
            c_left
        } else {
            c_right
        };
        let _color = shade(base_color, depth);

        if let Some(parent_id) = bone.parent_id {
            if let Some(parent) = skeleton.bones.get(&parent_id) {
                let p_pos = parent.global_position;
                let (p_screen_pos, p_depth) = camera.project(p_pos);
                let mid_depth = (depth + p_depth) / 2.0;
                let line_color = shade(base_color, mid_depth);
                // Line thickness: front bones slightly thicker for extra pop
                let thickness = if mid_depth < 0.0 { 6.0 } else { 4.0 };
                cmds.push(DrawCmd::Line {
                    start: p_screen_pos,
                    end: screen_pos,
                    stroke: Stroke::new(thickness, line_color),
                    depth: mid_depth,
                });
            }
        }

        cmds.push(DrawCmd::Circle {
            pos: screen_pos,
            radius: if bone.id == 4 { 12.0 } else { 7.0 },
            fill: shade(if bone.id < 10 { tracker_color } else { base_color }, depth),
            stroke: border_stroke,
            depth,
        });

        if bone.id == 4 {
            let forward = bone.global_rotation * Vector3::z();
            let face_pos = pos + forward * 0.15;
            let (f_screen_pos, f_depth) = camera.project(face_pos);
            cmds.push(DrawCmd::Circle {
                pos: f_screen_pos,
                radius: 4.0,
                fill: UI_FOREGROUND,
                stroke: Stroke::NONE,
                depth: f_depth,
            });
        }
    }

    if debug_axes {
        for tracker in trackers.values() {
            if let (Some(bone_id), Some(quat)) = (tracker.assigned_bone, tracker.rotation) {
                if let Some(bone) = skeleton.bones.get(&bone_id) {
                    let pos = bone.global_position;
                    let q = nalgebra::UnitQuaternion::new_normalize(nalgebra::Quaternion::new(
                        quat[3], quat[0], quat[1], quat[2],
                    ));
                    for (dir, color) in [
                        (Vector3::x(), ctx.th.axis_x),
                        (Vector3::y(), ctx.th.axis_y),
                        (Vector3::z(), ctx.th.axis_z),
                    ] {
                        let rotated_dir = q.transform_vector(&dir);
                        let end_pos = pos + rotated_dir * 0.15;
                        let (start_screen, s_depth) = camera.project(pos);
                        let (end_screen, e_depth) = camera.project(end_pos);
                        cmds.push(DrawCmd::Line {
                            start: start_screen,
                            end: end_screen,
                            stroke: Stroke::new(2.0, color),
                            depth: (s_depth + e_depth) / 2.0 - 0.5,
                        });
                    }
                }
            }
        }
    }

    cmds.sort_by(|a, b| {
        a.depth()
            .partial_cmp(&b.depth())
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    for cmd in cmds {
        let _ = match cmd {
            DrawCmd::Line {
                start, end, stroke, ..
            } => ctx.painter.line_segment([start, end], stroke),
            DrawCmd::Circle {
                pos,
                radius,
                fill,
                stroke,
                ..
            } => ctx.painter.circle(pos, radius, fill, stroke),
        };
    }

    let cross_len = 8.0 * ctx.zoom.max(1.0);
    let center = ctx.rect.center();
    ctx.painter.line_segment(
        [
            Pos2::new(center.x - cross_len, center.y),
            Pos2::new(center.x + cross_len, center.y),
        ],
        Stroke::new(1.6, ctx.th.selection),
    );
    ctx.painter.line_segment(
        [
            Pos2::new(center.x, center.y - cross_len),
            Pos2::new(center.x, center.y + cross_len),
        ],
        Stroke::new(1.6, ctx.th.selection),
    );
    ctx.painter.circle_filled(center, 3.0, ctx.th.accent);
}

/// Draw a large coloured 3D cube representing tracker orientation.
///
/// Face colours: +X=red  -X=darkred  +Y=green  -Y=darkgreen  +Z=blue  -Z=darkblue
/// The cube is rotated by `quat_xyzw` ([x,y,z,w]).  Camera yaw/pitch from `ctx`.
pub fn draw_tracker_cube(ctx: &DrawCtx, quat_xyzw: Option<[f32; 4]>) {
    use nalgebra::{Quaternion, UnitQuaternion};
    use std::cmp::Ordering;

    let q = quat_xyzw
        .map(|q| UnitQuaternion::new_normalize(Quaternion::new(q[3], q[0], q[1], q[2])))
        .unwrap_or_else(UnitQuaternion::identity);

    let canvas = ctx.rect.width().min(ctx.rect.height());
    let base_scale = canvas * 0.36;
    let camera = camera_transform(ctx, false, base_scale, 0.0);

    // 8 corners of the cube, local space (half-size = 1.0)
    let s = 1.0_f32;
    let lv: [Vector3<f32>; 8] = [
        Vector3::new(-s, -s, -s), // 0
        Vector3::new( s, -s, -s), // 1
        Vector3::new( s,  s, -s), // 2
        Vector3::new(-s,  s, -s), // 3
        Vector3::new(-s, -s,  s), // 4
        Vector3::new( s, -s,  s), // 5
        Vector3::new( s,  s,  s), // 6
        Vector3::new(-s,  s,  s), // 7
    ];

    // Rotate all corners by tracker quaternion into world space, then project
    let pv: Vec<(Pos2, f32)> = lv.iter().map(|v| camera.project(q * v)).collect();

    // 6 faces: corner indices (CCW when viewed from outside), fill colour, label
    let faces: [([usize; 4], Color32, &str); 6] = [
        ([1, 5, 6, 2], Color32::from_rgb(210,  55,  55), "+X"),
        ([0, 3, 7, 4], Color32::from_rgb(120,  25,  25), "-X"),
        ([3, 2, 6, 7], Color32::from_rgb( 50, 190,  70), "+Y"),
        ([0, 4, 5, 1], Color32::from_rgb( 20,  95,  35), "-Y"),
        ([4, 7, 6, 5], Color32::from_rgb( 55, 115, 240), "+Z"),
        ([0, 1, 2, 3], Color32::from_rgb( 15,  40, 140), "-Z"),
    ];

    // Collect draw commands with depth, sort back→front
    let mut cmds: Vec<(f32, Vec<Pos2>, Color32, Pos2, &str)> = faces
        .iter()
        .map(|(idx, col, lbl)| {
            let pts: Vec<Pos2>  = idx.iter().map(|&i| pv[i].0).collect();
            let depth: f32      = idx.iter().map(|&i| pv[i].1).sum::<f32>() / 4.0;
            let cx = pts.iter().map(|p| p.x).sum::<f32>() / 4.0;
            let cy = pts.iter().map(|p| p.y).sum::<f32>() / 4.0;
            (depth, pts, *col, Pos2::new(cx, cy), *lbl)
        })
        .collect();
    cmds.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(Ordering::Equal));

    // Draw faces
    let label_size = (canvas * 0.09).clamp(14.0, 42.0);
    for (_, pts, col, center, lbl) in &cmds {
        ctx.painter.add(egui::Shape::convex_polygon(
            pts.clone(),
            *col,
            egui::Stroke::new(2.5, Color32::BLACK),
        ));
        ctx.painter.text(
            *center,
            egui::Align2::CENTER_CENTER,
            *lbl,
            egui::FontId::proportional(label_size),
            Color32::WHITE,
        );
    }

    // XYZ axis arrows (in local/tracker space)
    let alen = s * 1.55;
    let origin = camera.project(q * Vector3::zeros()).0;
    for (axis, col, name) in [
        (Vector3::x() * alen, Color32::from_rgb(255, 110, 110), "X"),
        (Vector3::y() * alen, Color32::from_rgb(110, 255, 110), "Y"),
        (Vector3::z() * alen, Color32::from_rgb(110, 160, 255), "Z"),
    ] {
        let tip = camera.project(q * axis).0;
        ctx.painter.line_segment([origin, tip], egui::Stroke::new(3.5, col));
        ctx.painter.text(
            tip,
            egui::Align2::CENTER_CENTER,
            name,
            egui::FontId::proportional(16.0),
            col,
        );
    }

    // "No tracker" watermark when cube is identity because no data
    if quat_xyzw.is_none() {
        ctx.painter.text(
            ctx.rect.center_bottom() - egui::vec2(0.0, 20.0),
            egui::Align2::CENTER_BOTTOM,
            "No tracker data",
            egui::FontId::proportional(14.0),
            ctx.th.hint_text,
        );
    }
}

pub fn bone_name(i18n: &I18n, id: u8) -> String {
    match id {
        0 => i18n.t("bone.hip"),
        1 => i18n.t("bone.waist"),
        2 => i18n.t("bone.chest"),
        3 => i18n.t("bone.neck"),
        4 => i18n.t("bone.head"),
        10 => i18n.t("bone.l_up_leg"),
        11 => i18n.t("bone.l_leg"),
        12 => i18n.t("bone.l_foot"),
        20 => i18n.t("bone.r_up_leg"),
        21 => i18n.t("bone.r_leg"),
        22 => i18n.t("bone.r_foot"),
        30 => i18n.t("bone.l_shoulder"),
        31 => i18n.t("bone.l_up_arm"),
        32 => i18n.t("bone.l_forearm"),
        40 => i18n.t("bone.r_shoulder"),
        41 => i18n.t("bone.r_up_arm"),
        42 => i18n.t("bone.r_forearm"),
        _ => i18n.t("bone.unknown"),
    }
}

pub fn setup_custom_fonts(ctx: &egui::Context) {
    let mut fonts = egui::FontDefinitions::default();
    let try_fonts = [
        ("C:\\Windows\\Fonts\\msjh.ttc", "Microsoft JhengHei"),
        ("C:\\Windows\\Fonts\\msjh.ttf", "Microsoft JhengHei"),
        ("C:\\Windows\\Fonts\\segoeui.ttf", "Segoe UI"),
        ("C:\\Windows\\Fonts\\arial.ttf", "Arial"),
    ];

    let mut loaded = false;
    for (path, name) in &try_fonts {
        if let Ok(bytes) = std::fs::read(path) {
            let font_name = name.to_string();
            let font_data = egui::FontData::from_owned(bytes);
            fonts.font_data.insert(font_name.clone(), font_data);
            fonts
                .families
                .entry(egui::FontFamily::Proportional)
                .or_default()
                .insert(0, font_name.clone());
            fonts
                .families
                .entry(egui::FontFamily::Monospace)
                .or_default()
                .insert(0, font_name.clone());
            ctx.set_fonts(fonts.clone());
            log::info!("Loaded font {} ({})", name, path);
            loaded = true;
            break;
        }
    }

    if !loaded {
        log::info!("No custom Windows font loaded, using egui defaults");
    }
}

pub fn configure_style(ctx: &egui::Context, theme: &Theme) {
    let mut visuals = if theme.foreground == eframe::epaint::Color32::WHITE {
        egui::Visuals::dark()
    } else {
        egui::Visuals::light()
    };

    visuals.window_fill = theme.window_fill;
    visuals.panel_fill = theme.panel_fill;
    visuals.widgets.noninteractive.bg_fill = theme.window_fill;
    visuals.widgets.inactive.weak_bg_fill = theme.widget_inactive;
    visuals.widgets.hovered.weak_bg_fill = theme.widget_hover;
    visuals.widgets.active.weak_bg_fill = theme.widget_active;
    visuals.widgets.inactive.fg_stroke = egui::Stroke::new(0.5, theme.foreground);
    visuals.widgets.hovered.fg_stroke = egui::Stroke::new(1.0, theme.accent);
    visuals.widgets.active.fg_stroke = egui::Stroke::new(1.0, theme.foreground);
    visuals.widgets.active.bg_fill = theme.btn_primary;
    visuals.window_rounding = egui::Rounding::same(theme.corner_round_md);
    visuals.widgets.inactive.rounding = egui::Rounding::same(theme.corner_round_md);
    visuals.widgets.hovered.rounding = egui::Rounding::same(theme.corner_round_md);
    visuals.widgets.active.rounding = egui::Rounding::same(theme.corner_round_md);
    visuals.selection.bg_fill = theme.selection;
    visuals.selection.stroke = egui::Stroke::new(1.0, theme.accent);
    visuals.window_stroke = egui::Stroke::new(0.8, theme.stroke_gray);
    ctx.set_visuals(visuals);

    let mut style = (*ctx.style()).clone();
    style.spacing.item_spacing = egui::vec2(theme.gap_sm, theme.gap_sm);
    style.spacing.button_padding = egui::vec2(BTN_PAD_X, BTN_PAD_Y);
    style.spacing.window_margin = egui::Margin::same(14.0);
    style.text_styles.insert(
        egui::TextStyle::Heading,
        egui::FontId::new(22.0, egui::FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Body,
        egui::FontId::new(15.5, egui::FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Button,
        egui::FontId::new(15.5, egui::FontFamily::Proportional),
    );
    ctx.set_style(style);
}

pub fn ui_battery_bar(ui: &mut egui::Ui, battery: f32, theme: &Theme) {
    let (rect, _resp) =
        ui.allocate_at_least(egui::vec2(BATTERY_W, BATTERY_H), egui::Sense::hover());
    let rounding = 4.0;
    ui.painter().rect_filled(rect, rounding, theme.batt_bg);

    let fill_pct = (battery / 100.0).clamp(0.0, 1.0);
    let fill_width = rect.width() * fill_pct;
    let fill_rect = egui::Rect::from_min_size(rect.min, egui::vec2(fill_width, rect.height()));

    let color = if battery > 60.0 {
        theme.batt_high
    } else if battery > 20.0 {
        theme.batt_med
    } else {
        theme.batt_low
    };

    ui.painter().rect_filled(fill_rect, rounding, color);
    ui.painter().text(
        rect.center(),
        egui::Align2::CENTER_CENTER,
        format!("{:.0}%", battery),
        egui::FontId::proportional(theme.icon_size * 0.6),
        theme.foreground,
    );
}
