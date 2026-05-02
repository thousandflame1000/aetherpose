use eframe::egui;

pub fn ui_monitor(
    app: &mut crate::AetherposeApp,
    ui: &mut egui::Ui,
    _ctx: &egui::Context,
    theme: &crate::theme::Theme,
) {
    ui.heading(app.i18n.t("connected_trackers"));
    ui.separator();

    if crate::ui_icons::icon_button(
        ui,
        crate::ui_icons::ICON_APPLY,
        &app.i18n.t("monitor.auto_assign"),
    )
    .clicked()
    {
        let _ = app.cmd_tx.send(crate::BackendCommand::AutoAssign);
    }

    ui.label(
        egui::RichText::new(app.i18n.t("monitor.scroll_hint"))
            .size(theme.font_small)
            .weak(),
    );

    egui::ScrollArea::both().show(ui, |ui| {
        egui::Grid::new("trackers_grid")
            .striped(true)
            .spacing(egui::vec2(theme.gap_md, theme.gap_sm))
            .min_col_width(theme.table_min_col_width)
            .show(ui, |ui| {
                ui.style_mut().override_text_style = Some(egui::TextStyle::Heading);
                ui.strong(app.i18n.t("monitor.header.id"));
                ui.strong(app.i18n.t("monitor.header.bone"));
                ui.strong(app.i18n.t("monitor.header.status"));
                ui.strong(app.i18n.t("monitor.header.connection"));
                ui.strong(app.i18n.t("monitor.header.battery"));
                ui.strong(app.i18n.t("monitor.header.stationary"));
                ui.strong(app.i18n.t("monitor.header.tps"));
                ui.strong(app.i18n.t("monitor.header.loss"));
                ui.strong(app.i18n.t("monitor.header.signal"));
                ui.strong(app.i18n.t("monitor.header.accel"));
                ui.strong(app.i18n.t("monitor.header.assign"));
                ui.end_row();
                ui.reset_style();

                let mut tracker_list: Vec<_> = app.trackers.values().collect();
                tracker_list.sort_by_key(|t| t.id);

                for tracker in tracker_list {
                    ui.label(egui::RichText::new(format!("#{}", tracker.id)).strong());

                    let assigned_text = match tracker.assigned_bone {
                        Some(bone_id) => crate::bone_name(&app.i18n, bone_id),
                        None => app.i18n.t("tracker.unassigned"),
                    };
                    ui.label(assigned_text);

                    let is_active = tracker.last_update.elapsed().as_secs() < 2;
                    let status = if is_active {
                        (
                            app.i18n.t("tracker.status.active"),
                            crate::UI_STATUS_ACTIVE,
                        )
                    } else {
                        (
                            app.i18n.t("tracker.status.timeout"),
                            crate::UI_STATUS_TIMEOUT,
                        )
                    };
                    ui.label(egui::RichText::new(status.0).color(status.1));

                    let (conn_text, conn_color) = match tracker.connection_type {
                        crate::connection_type::ConnectionType::Serial => (
                            app.i18n.t("tracker.connection.serial"),
                            egui::Color32::from_rgb(0, 122, 204),
                        ),
                        crate::connection_type::ConnectionType::Ble => (
                            app.i18n.t("tracker.connection.ble"),
                            egui::Color32::from_rgb(0, 180, 0),
                        ),
                        crate::connection_type::ConnectionType::Udp => (
                            app.i18n.t("tracker.connection.udp"),
                            egui::Color32::from_rgb(255, 140, 0),
                        ),
                        crate::connection_type::ConnectionType::Unknown => (
                            "Unknown".to_string(),
                            egui::Color32::from_gray(150),
                        ),
                    };
                    ui.label(egui::RichText::new(conn_text).color(conn_color));

                    crate::ui_battery_bar(ui, tracker.battery, theme);

                    let movement = if tracker.stationary {
                        (app.i18n.t("status.stationary"), crate::UI_STATUS_ACTIVE)
                    } else {
                        (
                            app.i18n.t("status.moving"),
                            egui::Color32::from_rgb(220, 180, 0),
                        )
                    };
                    ui.label(egui::RichText::new(movement.0).color(movement.1));

                    ui.label(format!("{} Hz", tracker.tps));

                    let total_packets = tracker.received_packets + tracker.lost_packets;
                    let loss_rate = if total_packets > 0 {
                        tracker.lost_packets as f32 / total_packets as f32 * 100.0
                    } else {
                        0.0
                    };
                    let loss_color = if loss_rate > 2.0 {
                        crate::UI_LOSS_HIGH
                    } else if loss_rate > 0.5 {
                        crate::UI_LOSS_MED
                    } else {
                        crate::UI_LOSS_LOW
                    };
                    ui.label(
                        egui::RichText::new(format!("{:.1}%", loss_rate)).color(loss_color),
                    );

                    ui.label(format!("{} dBm", tracker.rssi));

                    if let Some(accel) = tracker.accel {
                        ui.label(
                            egui::RichText::new(format!(
                                "[{:.1}, {:.1}, {:.1}]",
                                accel[0], accel[1], accel[2]
                            ))
                            .size(theme.font_small),
                        );
                    } else {
                        ui.label(app.i18n.t("monitor.empty"));
                    }

                    egui::ComboBox::from_id_salt(tracker.id)
                        .selected_text(match tracker.assigned_bone {
                            None => app.i18n.t("tracker.unassigned"),
                            Some(bone_id) => crate::bone_name(&app.i18n, bone_id),
                        })
                        .show_ui(ui, |ui| {
                            let unassigned_sentinel: u8 = 255;
                            let mut combo_val =
                                tracker.assigned_bone.unwrap_or(unassigned_sentinel);
                            let prev_val = combo_val;

                            let options: &[(u8, &str)] = &[
                                (unassigned_sentinel, "tracker.unassigned"),
                                (0u8, "bone.hip"),
                                (2u8, "bone.chest"),
                                (4u8, "bone.head"),
                                (10u8, "bone.l_up_leg"),
                                (11u8, "bone.l_leg"),
                                (12u8, "bone.l_foot"),
                                (20u8, "bone.r_up_leg"),
                                (21u8, "bone.r_leg"),
                                (22u8, "bone.r_foot"),
                                (31u8, "bone.l_up_arm"),
                                (32u8, "bone.l_forearm"),
                                (41u8, "bone.r_up_arm"),
                                (42u8, "bone.r_forearm"),
                            ];

                            for &(bone_id, name_key) in options {
                                ui.selectable_value(&mut combo_val, bone_id, app.i18n.t(name_key));
                            }

                            if combo_val != prev_val {
                                if combo_val == unassigned_sentinel {
                                    app.config.tracker_assignments.remove(&tracker.id);
                                } else {
                                    let _ = app.cmd_tx.send(crate::BackendCommand::AssignTracker(
                                        tracker.id,
                                        combo_val,
                                    ));
                                    app.config
                                        .tracker_assignments
                                        .insert(tracker.id, combo_val);
                                }
                            }
                        });

                    ui.end_row();
                }

                if app.trackers.is_empty() {
                    ui.label(app.i18n.t("monitor.empty"));
                    ui.label(app.i18n.t("monitor.empty"));
                    ui.label(app.i18n.t("monitor.waiting_connection"));
                    ui.label(app.i18n.t("monitor.empty"));
                    ui.label(app.i18n.t("monitor.empty"));
                    ui.label(app.i18n.t("monitor.empty"));
                    ui.label(app.i18n.t("monitor.empty"));
                    ui.label(app.i18n.t("monitor.empty"));
                    ui.label(app.i18n.t("monitor.empty"));
                    ui.label(app.i18n.t("monitor.empty"));
                    ui.label(app.i18n.t("monitor.empty"));
                    ui.end_row();
                }
            });
    });

    ui.add_space(theme.gap_md);
    ui.heading(app.i18n.t("shake_assign"));
    ui.label(app.i18n.t("shake_assign.instruction"));
    ui.separator();

    egui::Grid::new("shake_assign_grid")
        .spacing(egui::vec2(theme.gap_sm, theme.gap_sm))
        .show(ui, |ui| {
            let assign_targets = [12u8, 22, 2, 0, 11, 21, 32, 42];

            for (index, bone_id) in assign_targets.iter().enumerate() {
                ui.label(crate::bone_name(&app.i18n, *bone_id));

                let is_waiting = app.pending_shake_bone == Some(*bone_id);
                let button_label = if is_waiting {
                    app.i18n.t("shake_assign.waiting")
                } else {
                    app.i18n.t("shake_assign.assign_button")
                };
                let button_icon = if is_waiting {
                    crate::ui_icons::ICON_STOP
                } else {
                    crate::ui_icons::ICON_PLAY
                };

                if crate::ui_icons::icon_button(ui, button_icon, &button_label).clicked() {
                    if is_waiting {
                        let _ = app.cmd_tx.send(crate::BackendCommand::CancelShakeAssign);
                    } else {
                        let _ = app
                            .cmd_tx
                            .send(crate::BackendCommand::StartShakeAssign(*bone_id));
                    }
                }

                if (index + 1) % 2 == 0 {
                    ui.end_row();
                }
            }
        });
}
