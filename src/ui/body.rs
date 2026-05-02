use eframe::egui;

pub fn ui_body(app: &mut crate::AetherposeApp, ui: &mut egui::Ui, _ctx: &egui::Context, theme: &crate::theme::Theme) {
    use crate::DrawCtx;

    ui.heading(app.i18n.t("body_motion"));
    ui.separator();

    ui.group(|ui| {
        ui.label(egui::RichText::new(app.i18n.t("body.proportions.title")).strong());
        ui.label(egui::RichText::new(app.i18n.t("body.proportions.description")).size(theme.font_reg).weak());
        ui.add_space(theme.gap_xs);

        if ui.add(egui::Slider::new(&mut app.ik_smoothness, 0.0..=1.0).text(app.i18n.t("body.ik_smoothness"))).changed() {
            let _ = app.cmd_tx.send(crate::BackendCommand::SetIkSmoothness(app.ik_smoothness));
        }

        let mut changed = false;
        changed |= ui.add(egui::Slider::new(&mut app.prop_leg, 0.5..=1.5).text(app.i18n.t("body.prop.legs"))).changed();
        changed |= ui.add(egui::Slider::new(&mut app.prop_arm, 0.5..=1.5).text(app.i18n.t("body.prop.arms"))).changed();
        changed |= ui.add(egui::Slider::new(&mut app.prop_spine, 0.5..=1.5).text(app.i18n.t("body.prop.spine"))).changed();

        if changed {
            app.config.prop_leg = app.prop_leg; app.config.prop_arm = app.prop_arm; app.config.prop_spine = app.prop_spine;
            let _ = app.cmd_tx.send(crate::BackendCommand::SetProportions { leg: app.prop_leg, arm: app.prop_arm, spine: app.prop_spine });
        }
    });

    ui.add_space(theme.gap_sm);

    ui.group(|ui| {
        ui.label(egui::RichText::new(app.i18n.t("one_euro")).strong());
        let mut changed = false;
        changed |= ui.add(egui::Slider::new(&mut app.smoothing_min_cutoff, 0.01..=5.0).text(app.i18n.t("body.smoothing.min_cutoff"))).changed();
        ui.label(egui::RichText::new(app.i18n.t("body.smoothing.min_cutoff_tip")).size(theme.font_small).weak());
        changed |= ui.add(egui::Slider::new(&mut app.smoothing_beta, 0.0..=2.0).text(app.i18n.t("body.smoothing.beta"))).changed();
        ui.label(egui::RichText::new(app.i18n.t("body.smoothing.beta_tip")).size(theme.font_small).weak());
        if changed { app.config.smoothing_min_cutoff = app.smoothing_min_cutoff; app.config.smoothing_beta = app.smoothing_beta; let _ = app.cmd_tx.send(crate::BackendCommand::SetSmoothingParams { min_cutoff: app.smoothing_min_cutoff, beta: app.smoothing_beta }); }
    });

    ui.add_space(theme.gap_sm);

    ui.group(|ui| {
        ui.label(egui::RichText::new("Trajectory Integrator").strong());
        ui.label(
            egui::RichText::new("Switch IMU path integration mode for testing.")
                .size(theme.font_reg)
                .weak(),
        );
        ui.add_space(theme.gap_xs);

        ui.horizontal(|ui| {
            let rk4_selected =
                app.trajectory_integration_mode == crate::TrajectoryIntegrationMode::Rk4;
            if ui.selectable_label(rk4_selected, "EKF + RK4").clicked() && !rk4_selected {
                app.trajectory_integration_mode = crate::TrajectoryIntegrationMode::Rk4;
                app.config.trajectory_integration_mode = app.trajectory_integration_mode;
                let _ = app.cmd_tx.send(crate::BackendCommand::SetTrajectoryIntegrationMode(
                    app.trajectory_integration_mode,
                ));
                app.status = "Trajectory mode: EKF + RK4".to_string();
            }

            let euler_selected =
                app.trajectory_integration_mode == crate::TrajectoryIntegrationMode::Euler;
            if ui.selectable_label(euler_selected, "EKF + Euler").clicked() && !euler_selected {
                app.trajectory_integration_mode = crate::TrajectoryIntegrationMode::Euler;
                app.config.trajectory_integration_mode = app.trajectory_integration_mode;
                let _ = app.cmd_tx.send(crate::BackendCommand::SetTrajectoryIntegrationMode(
                    app.trajectory_integration_mode,
                ));
                app.status = "Trajectory mode: EKF + Euler".to_string();
            }
        });
    });

    ui.add_space(theme.gap_sm);

    ui.group(|ui| {
        ui.label(egui::RichText::new(app.i18n.t("body.auto_skeleton.title")).strong());
        ui.label(egui::RichText::new(app.i18n.t("body.auto_skeleton.description")).size(theme.font_reg).weak());

        ui.horizontal(|ui| { ui.label(format!("{} {:.3}", app.i18n.t("body.auto_skeleton.current_ratio_label"), app.leg_ratio)); });

        if app.is_leg_calibrating {
            ui.label(egui::RichText::new(app.i18n.t("body.auto_skeleton.calibrating")).color(crate::UI_STATUS_STATIONARY));
            if crate::ui_icons::icon_button(ui, crate::ui_icons::ICON_CHECK, &app.i18n.t("body.auto_skeleton.finish")).clicked() {
                let _ = app.cmd_tx.send(crate::BackendCommand::StopLegCalibration);
                app.is_leg_calibrating = false;
            }
        } else if crate::ui_icons::icon_button(ui, crate::ui_icons::ICON_PLAY, &app.i18n.t("body.auto_skeleton.start")).clicked() {
            let _ = app.cmd_tx.send(crate::BackendCommand::StartLegCalibration);
            app.is_leg_calibrating = true;
        }
    });

    ui.add_space(theme.gap_sm);

    ui.group(|ui| {
        ui.label(egui::RichText::new(app.i18n.t("virtual_floor")).strong());
        ui.label(egui::RichText::new(app.i18n.t("body.virtual_floor.description")).size(theme.font_reg).weak());

        ui.horizontal(|ui| {
            if ui.add(egui::Slider::new(&mut app.floor_offset, -2.0..=2.0).text(app.i18n.t("body.virtual_floor.offset"))).changed() {
                let _ = app.cmd_tx.send(crate::BackendCommand::SetFloorOffset(app.floor_offset));
            }
            if crate::ui_icons::icon_button(ui, crate::ui_icons::ICON_CHECK, &app.i18n.t("body.virtual_floor.auto")).clicked() {
                let _ = app.cmd_tx.send(crate::BackendCommand::AutoFloor);
            }
        });
    });

    ui.add_space(theme.gap_sm);

    ui.group(|ui| {
        ui.label(egui::RichText::new(app.i18n.t("drift_comp")).strong());
        if ui.add(egui::Slider::new(&mut app.drift_correction, 0.0..=1.0).text(app.i18n.t("body.drift_comp.strength"))).changed() {
            app.config.drift_correction = app.drift_correction;
            let _ = app.cmd_tx.send(crate::BackendCommand::SetDriftCorrection(app.drift_correction));
        }
    });

    ui.add_space(theme.gap_sm);
    ui.group(|ui| {
        ui.label(egui::RichText::new(app.i18n.t("mag_calib")).strong());
        ui.label(egui::RichText::new(app.i18n.t("body.mag_calib.description")).size(theme.font_reg).weak());
        ui.add_space(theme.gap_xs);

        let mut selected_tracker_id = app.mag_calibrating_tracker_id.unwrap_or(0);
        let mut tracker_options: Vec<u8> = app.trackers.keys().copied().collect();
        tracker_options.sort();

        ui.horizontal(|ui| {
            ui.label(app.i18n.t("body.mag_calib.select_tracker"));
            egui::ComboBox::from_id_salt("mag_calib_tracker_select").selected_text(format!("#{}", selected_tracker_id)).show_ui(ui, |ui| {
                for &tid in &tracker_options { ui.selectable_value(&mut selected_tracker_id, tid, format!("#{}", tid)); }
            });

            let is_calibrating_this_tracker = app.mag_calibrating_tracker_id == Some(selected_tracker_id);
            if ui.add_enabled(!is_calibrating_this_tracker, egui::Button::new(crate::ui_icons::ICON_PLAY)).on_hover_text(app.i18n.t("body.mag_calib.start")).clicked() {
                let _ = app.cmd_tx.send(crate::BackendCommand::StartMagCalibration(selected_tracker_id));
            }
            if ui.add_enabled(is_calibrating_this_tracker, egui::Button::new(crate::ui_icons::ICON_STOP)).on_hover_text(app.i18n.t("body.mag_calib.stop")).clicked() {
                let _ = app.cmd_tx.send(crate::BackendCommand::StopMagCalibration(selected_tracker_id));
            }

            if let Some(_calib) = app.mag_calibrations.get(&selected_tracker_id) { ui.label(egui::RichText::new(app.i18n.t("body.mag_calib.calibrated")).color(crate::UI_STATUS_ACTIVE)); }
        });

        if let Some(tid) = app.mag_calibrating_tracker_id {
            if let Some(points) = app.mag_calibration_points.get(&tid) { ui.label(format!("{} {}", app.i18n.t("body.mag_calib.points_collected_label"), points.len())); }
        }

        egui::Frame::canvas(ui.style()).fill(theme.canvas_fill).rounding(theme.corner_round_md).stroke(egui::Stroke::new(theme.stroke_w, theme.stroke_gray)).show(ui, |ui| {
            let (response, painter) = ui.allocate_painter(ui.available_size(), egui::Sense::drag());
            painter.text(response.rect.min + egui::vec2(theme.gap_sm, theme.gap_sm), egui::Align2::LEFT_TOP, &app.i18n.t("preview.controls_hint"), egui::FontId::proportional(theme.font_reg), theme.hint_text);

            let draw_ctx = DrawCtx { painter: &painter, rect: response.rect, yaw: app.rotation_yaw, pitch: app.rotation_pitch, zoom: app.zoom, camera_projection: app.camera_projection, th: &theme };

            crate::draw_magnetometer_points(&draw_ctx, &app.mag_calibration_points, app.mag_calibrating_tracker_id, app.mag_calibrations.get(&selected_tracker_id));
        });
    });
}
