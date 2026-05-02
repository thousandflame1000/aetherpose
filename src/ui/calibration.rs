use eframe::egui;

pub fn ui_calibration(app: &mut crate::AetherposeApp, ui: &mut egui::Ui, ctx: &egui::Context, theme: &crate::theme::Theme) {
    use crate::{CameraProjectionMode, DrawCtx, camera_transform, draw_skeleton, format_matrix4};
    use crate::app::render::draw_tracker_cube;
    let is_zh = app.lang.starts_with("zh");

    ui.horizontal(|ui| {
        ui.heading(app.i18n.t("skeleton.preview"));
        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
            // ── Cube mode toggle ─────────────────────────────────────────────
            let cube_label = if app.show_cube_mode {
                if is_zh { "骨架模式" } else { "Skeleton" }
            } else {
                if is_zh { "方塊模式" } else { "Cube" }
            };
            if ui
                .add(egui::Button::new(cube_label).small())
                .on_hover_text(if is_zh { "切換方塊/骨架顯示" } else { "Toggle cube / skeleton view" })
                .clicked()
            {
                app.show_cube_mode = !app.show_cube_mode;
            }

            let projection_button = match app.camera_projection {
                CameraProjectionMode::Orthographic => {
                    if is_zh { "切到透視".to_string() } else { "Use Perspective".to_string() }
                }
                CameraProjectionMode::Perspective => {
                    if is_zh { "切到正交".to_string() } else { "Use Orthographic".to_string() }
                }
            };
            if ui
                .add(egui::Button::new(projection_button).small())
                .on_hover_text(if is_zh { "切換投影模式" } else { "Toggle projection mode" })
                .clicked()
            {
                app.camera_projection = match app.camera_projection {
                    CameraProjectionMode::Orthographic => CameraProjectionMode::Perspective,
                    CameraProjectionMode::Perspective => CameraProjectionMode::Orthographic,
                };
                app.config.camera_projection = app.camera_projection;
                app.config.save();
            }
            if ui.add(egui::Button::new(crate::ui_icons::ICON_RELOAD).small()).on_hover_text(app.i18n.t("calibration.reset_view")).clicked() {
                app.rotation_yaw = 0.436;
                app.rotation_pitch = 0.175;
                app.zoom = 1.0;
            }
            if !app.show_cube_mode {
                ui.checkbox(&mut app.show_grid, &app.i18n.t("calibration.show_grid"));
                if ui.checkbox(&mut app.mirror_view, &app.i18n.t("calibration.mirror_mode")).changed() {
                    app.config.mirror_view = app.mirror_view;
                }
                ui.checkbox(&mut app.debug_draw_axes, &app.i18n.t("calibration.debug_axes"));
            }
        });
    });
    ui.separator();

    ui.horizontal(|ui| {
        let btn_size = egui::vec2(theme.btn_w, theme.btn_h);
        if ui
            .add_sized(btn_size, egui::Button::new(crate::ui_icons::ICON_RELOAD))
            .on_hover_text(app.i18n.t("calibration.reset_yaw"))
            .clicked()
        {
            log::info!("Reset Yaw Clicked");
            let _ = app.cmd_tx.send(crate::BackendCommand::ResetYaw);
        }
        if ui
            .add_sized(btn_size, egui::Button::new(crate::ui_icons::ICON_APPLY))
            .on_hover_text(app.i18n.t("calibration.full"))
            .clicked()
        {
            log::info!("Full Calib Clicked");
        }
        if ui
            .add_sized(btn_size, egui::Button::new(crate::ui_icons::ICON_CANCEL))
            .on_hover_text(app.i18n.t("calibration.reset_mount"))
            .clicked()
        {
            log::info!("Reset Mounting Clicked");
            let _ = app.cmd_tx.send(crate::BackendCommand::ResetMounting);
        }
    });

    ui.add_space(theme.gap_sm);

    egui::Frame::canvas(ui.style())
        .fill(theme.canvas_fill)
        .rounding(theme.corner_round_md)
        .stroke(egui::Stroke::new(theme.stroke_w, theme.stroke_gray))
        .show(ui, |ui| {
            let (response, painter) = ui.allocate_painter(ui.available_size(), egui::Sense::drag());

            painter.text(
                response.rect.min + egui::vec2(theme.gap_sm, theme.gap_sm),
                egui::Align2::LEFT_TOP,
                &app.i18n.t("preview.controls_hint"),
                egui::FontId::proportional(theme.font_reg),
                theme.hint_text,
            );

            if response.dragged() {
                app.rotation_yaw += response.drag_delta().x * 0.01;
                app.rotation_pitch += response.drag_delta().y * 0.01;
                app.rotation_pitch = app.rotation_pitch.clamp(-1.57, 1.57);
            }

            if response.hovered() {
                ctx.input(|i| {
                    let scroll = i.raw_scroll_delta.y;
                    if scroll != 0.0 {
                        let factor = if scroll > 0.0 { 1.1 } else { 0.9 };
                        app.zoom = (app.zoom * factor).clamp(0.5, 3.0);
                    }
                });
            }

            let draw_ctx = DrawCtx {
                painter: &painter,
                rect: response.rect,
                yaw: app.rotation_yaw,
                pitch: app.rotation_pitch,
                zoom: app.zoom,
                camera_projection: app.camera_projection,
                th: &theme,
            };

            if app.show_cube_mode {
                // ── Cube mode ────────────────────────────────────────────────
                // Pick the first active tracker's quaternion
                let mut sorted: Vec<_> = app.trackers.values()
                    .filter(|t| t.last_update.elapsed().as_secs() < 2 && t.rotation.is_some())
                    .collect();
                sorted.sort_by_key(|t| t.id);
                let quat = sorted.first().and_then(|t| t.rotation);

                draw_tracker_cube(&draw_ctx, quat);

                // Show which tracker / bone is driving the cube
                if let Some(t) = sorted.first() {
                    let bone_text = match t.assigned_bone {
                        Some(b) => crate::bone_name(&app.i18n, b),
                        None    => format!("#{}", t.id),
                    };
                    painter.text(
                        response.rect.left_bottom() + egui::vec2(theme.gap_sm, -theme.gap_sm),
                        egui::Align2::LEFT_BOTTOM,
                        format!("Tracker #{} — {}", t.id, bone_text),
                        egui::FontId::proportional(theme.font_reg),
                        theme.hint_text,
                    );
                }
            } else if let Some(skel) = &app.skeleton_data {
                // ── Skeleton mode ────────────────────────────────────────────
                let camera = camera_transform(&draw_ctx, app.mirror_view, 100.0, 60.0);
                let projection_label = match app.camera_projection {
                    CameraProjectionMode::Orthographic => {
                        if is_zh { "正交".to_string() } else { "Orthographic".to_string() }
                    }
                    CameraProjectionMode::Perspective => {
                        if is_zh { "透視".to_string() } else { "Perspective".to_string() }
                    }
                };
                let camera_text = format!(
                    "{}: {}\n{}:\n{}",
                    if is_zh { "投影" } else { "Projection" },
                    projection_label,
                    if is_zh { "相機矩陣" } else { "Camera Matrix" },
                    format_matrix4(&camera.view_projection),
                );
                painter.text(
                    response.rect.right_top() + egui::vec2(-220.0, theme.gap_sm),
                    egui::Align2::LEFT_TOP,
                    camera_text,
                    egui::FontId::monospace(theme.font_small.max(11.0)),
                    theme.hint_text,
                );

                draw_skeleton(
                    &draw_ctx,
                    skel,
                    app.show_grid,
                    app.mirror_view,
                    &app.trackers,
                    app.debug_draw_axes,
                );
            }
        });
}
