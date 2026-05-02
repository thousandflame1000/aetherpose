use crate::i18n::I18n;
use eframe::egui;
use log::error;
use std::process::Command;

const S_RECORDER_TITLE: &str = "recorder.title";
const S_START_REC: &str = "recorder.start";
const S_STOP_REC: &str = "recorder.stop";

pub fn ui_system(
    app: &mut crate::AetherposeApp,
    ui: &mut egui::Ui,
    _ctx: &egui::Context,
    theme: &crate::theme::Theme,
) {
    ui.heading(app.i18n.t("system_output"));
    ui.separator();

    ui.group(|ui| {
        ui.label(egui::RichText::new(app.i18n.t("network_settings")).strong());
        ui.add_space(crate::GAP_XS);
        egui::Grid::new("settings_net_grid")
            .spacing(egui::vec2(crate::GAP_SM, crate::GAP_SM))
            .show(ui, |ui| {
                ui.label(app.i18n.t("network.udp_port"));
                ui.label(app.i18n.t("system.default_udp_port"));
                ui.end_row();

                ui.label(app.i18n.t("system.osc_target"));
                ui.horizontal(|ui| {
                    ui.text_edit_singleline(&mut app.osc_ip);
                    ui.label(app.i18n.t("separator.colon"));
                    ui.text_edit_singleline(&mut app.osc_port);
                });
                ui.end_row();
            });

        if crate::ui_icons::icon_button(
            ui,
            crate::ui_icons::ICON_APPLY,
            &app.i18n.t("apply_network"),
        )
        .clicked()
        {
            if let Ok(port) = app.osc_port.parse::<u16>() {
                let _ = app
                    .cmd_tx
                    .send(crate::BackendCommand::SetOscTarget(app.osc_ip.clone(), port));
                app.config.osc_ip = app.osc_ip.clone();
                app.config.osc_port = port;
            }
        }

        ui.add_space(crate::GAP_SM);
        ui.label(egui::RichText::new(app.i18n.t("serial.section")).strong());
        ui.add_space(crate::GAP_XS);
        egui::Grid::new("settings_serial_grid")
            .spacing(egui::vec2(crate::GAP_SM, crate::GAP_SM))
            .show(ui, |ui| {
                ui.label(app.i18n.t("serial.enabled"));
                ui.checkbox(&mut app.serial_enabled_edit, "");
                ui.end_row();

                ui.label(app.i18n.t("serial.port"));
                ui.horizontal(|ui| {
                    let _ = ui.add(
                        egui::TextEdit::singleline(&mut app.serial_port_edit)
                            .desired_width(theme.input_w_large),
                    );
                });
                ui.end_row();

                ui.label(app.i18n.t("serial.baud"));
                ui.horizontal(|ui| {
                    let _ = ui.add(
                        egui::TextEdit::singleline(&mut app.serial_baud_edit)
                            .desired_width(theme.input_w_med),
                    );
                });
                ui.end_row();
            });

        if crate::ui_icons::icon_button(
            ui,
            crate::ui_icons::ICON_APPLY,
            &app.i18n.t("apply_serial"),
        )
        .clicked()
        {
            let baud_opt = app.serial_baud_edit.trim().parse::<u32>().ok();
            let _ = app.cmd_tx.send(crate::BackendCommand::SetSerialConfig {
                enabled: Some(app.serial_enabled_edit),
                port: if app.serial_port_edit.trim().is_empty() {
                    None
                } else {
                    Some(app.serial_port_edit.clone())
                },
                baud: baud_opt,
            });

            app.config.serial_enabled = app.serial_enabled_edit;
            app.config.serial_port = if app.serial_port_edit.trim().is_empty() {
                None
            } else {
                Some(app.serial_port_edit.clone())
            };
            if let Some(baud) = baud_opt {
                app.config.serial_baud = baud;
            }
            app.config.save();
        }

        ui.horizontal(|ui| {
            let status_text = if app.is_serial_running {
                app.i18n.t("serial.status_running")
            } else if app.config.serial_enabled {
                app.i18n.t("serial.status_starting")
            } else {
                app.i18n.t("serial.status_disabled")
            };
            let color = if app.is_serial_running {
                crate::UI_STATUS_ACTIVE
            } else {
                crate::UI_STATUS_TIMEOUT
            };

            ui.label(egui::RichText::new(status_text).color(color));
            if let Some(msg) = &app.serial_status_msg {
                ui.label(
                    egui::RichText::new(format!(" ({})", msg)).color(egui::Color32::LIGHT_GRAY),
                );
            }
        });

        ui.add_space(crate::GAP_XS);
        ui.horizontal(|ui| {
            if crate::ui_icons::icon_button(
                ui,
                crate::ui_icons::ICON_PLAY,
                &app.i18n.t("serial.start"),
            )
            .clicked()
            {
                let baud_opt = app.serial_baud_edit.trim().parse::<u32>().ok();
                let _ = app.cmd_tx.send(crate::BackendCommand::SetSerialConfig {
                    enabled: Some(true),
                    port: if app.serial_port_edit.trim().is_empty() {
                        None
                    } else {
                        Some(app.serial_port_edit.clone())
                    },
                    baud: baud_opt,
                });
            }

            if crate::ui_icons::icon_button(
                ui,
                crate::ui_icons::ICON_STOP,
                &app.i18n.t("serial.stop"),
            )
            .clicked()
            {
                let _ = app.cmd_tx.send(crate::BackendCommand::SetSerialConfig {
                    enabled: Some(false),
                    port: None,
                    baud: None,
                });
            }
        });

        ui.add_space(crate::GAP_SM);
        ui.label(egui::RichText::new(app.i18n.t("serial.log_title")).strong());
        ui.horizontal(|ui| {
            ui.label(app.i18n.t("serial.filter_label"));
            egui::ComboBox::from_label("")
                .selected_text(match app.serial_log_filter {
                    0 => app.i18n.t("serial.filter_all"),
                    1 => app.i18n.t("serial.filter_errors"),
                    2 => app.i18n.t("serial.filter_info"),
                    _ => app.i18n.t("serial.filter_all"),
                })
                .show_ui(ui, |ui| {
                    if ui
                        .selectable_label(app.serial_log_filter == 0, app.i18n.t("serial.filter_all"))
                        .clicked()
                    {
                        app.serial_log_filter = 0;
                    }
                    if ui
                        .selectable_label(
                            app.serial_log_filter == 1,
                            app.i18n.t("serial.filter_errors"),
                        )
                        .clicked()
                    {
                        app.serial_log_filter = 1;
                    }
                    if ui
                        .selectable_label(
                            app.serial_log_filter == 2,
                            app.i18n.t("serial.filter_info"),
                        )
                        .clicked()
                    {
                        app.serial_log_filter = 2;
                    }
                });

            if crate::ui_icons::icon_button(
                ui,
                crate::ui_icons::ICON_CLEAR,
                &app.i18n.t("serial.clear_log"),
            )
            .clicked()
            {
                app.serial_log.clear();
            }
        });

        egui::ScrollArea::vertical()
            .max_height(theme.scroll_max_h)
            .show(ui, |ui| {
                let is_error = |line: &str| {
                    let line = line.to_lowercase();
                    line.contains("error")
                        || line.contains("failed")
                        || line.contains("disconnect")
                        || line.contains("err")
                };

                for line in app.serial_log.iter().rev().filter(|line| match app.serial_log_filter {
                    0 => true,
                    1 => is_error(line),
                    2 => !is_error(line),
                    _ => true,
                }) {
                    ui.label(egui::RichText::new(line).monospace().size(theme.font_reg));
                }
            });

        ui.horizontal(|ui| {
            if crate::ui_icons::icon_button(
                ui,
                crate::ui_icons::ICON_EXPORT,
                &app.i18n.t("serial.export_serial_log"),
            )
            .clicked()
            {
                export_log_file(
                    "status_serial.log",
                    "serial_export",
                    &app.i18n,
                    &mut app.status,
                );
            }

            if crate::ui_icons::icon_button(
                ui,
                crate::ui_icons::ICON_CLEAR,
                &app.i18n.t("serial.clear_log"),
            )
            .clicked()
            {
                app.serial_log.clear();
            }

            if crate::ui_icons::icon_button(
                ui,
                crate::ui_icons::ICON_EXPORT,
                &app.i18n.t("serial.export_serial_log"),
            )
            .clicked()
            {
                if let Err(e) = std::fs::write("serial_log.txt", app.serial_log.join("\n")) {
                    error!("failed to export serial_log.txt: {}", e);
                } else {
                    let _ = Command::new("explorer")
                        .arg("/select,serial_log.txt")
                        .spawn();
                }
            }

            if crate::ui_icons::icon_button(
                ui,
                crate::ui_icons::ICON_EXPORT,
                &app.i18n.t("serial.export_ble_log"),
            )
            .clicked()
            {
                export_log_file(
                    "status_ble.log",
                    "ble_export",
                    &app.i18n,
                    &mut app.status,
                );
            }

            if crate::ui_icons::icon_button(
                ui,
                crate::ui_icons::ICON_TRUNCATE,
                &app.i18n.t("serial.truncate_serial_log"),
            )
            .clicked()
            {
                truncate_log_file("status_serial.log");
            }

            if crate::ui_icons::icon_button(
                ui,
                crate::ui_icons::ICON_TRUNCATE,
                &app.i18n.t("serial.truncate_ble_log"),
            )
            .clicked()
            {
                truncate_log_file("status_ble.log");
            }
        });
    });

    ui.add_space(crate::GAP_SM);

    ui.group(|ui| {
        ui.label(egui::RichText::new(app.i18n.t("zupt.section")).strong());
        ui.add_space(crate::GAP_XS);

        ui.horizontal(|ui| {
            if ui.checkbox(&mut app.zupt_enabled, "Enable ZUPT").changed() {
                app.config.zupt_enabled = app.zupt_enabled;
                let _ = app
                    .cmd_tx
                    .send(crate::BackendCommand::SetZuptEnabled(app.zupt_enabled));
                app.config.save();
            }
        });

        ui.add_space(crate::GAP_XS);

        egui::Grid::new("settings_zupt_grid")
            .spacing(egui::vec2(crate::GAP_SM, crate::GAP_SM))
            .show(ui, |ui| {
                ui.label(app.i18n.t("zupt.window_size"));
                ui.horizontal(|ui| {
                    let _ = ui.add(
                        egui::TextEdit::singleline(&mut app.zupt_window_edit)
                            .desired_width(theme.input_w_med),
                    );
                });
                ui.end_row();

                ui.label(app.i18n.t("zupt.accel_var"));
                ui.horizontal(|ui| {
                    let _ = ui.add(
                        egui::TextEdit::singleline(&mut app.zupt_accel_var_edit)
                            .desired_width(theme.input_w_med),
                    );
                });
                ui.end_row();

                ui.label(app.i18n.t("zupt.gyro_thresh"));
                ui.horizontal(|ui| {
                    let _ = ui.add(
                        egui::TextEdit::singleline(&mut app.zupt_gyro_edit)
                            .desired_width(theme.input_w_med),
                    );
                });
                ui.end_row();
            });

        ui.add_space(crate::GAP_XS);
        if crate::ui_icons::icon_button(
            ui,
            crate::ui_icons::ICON_CHECK,
            &app.i18n.t("zupt.apply"),
        )
        .clicked()
        {
            let win_opt = app.zupt_window_edit.trim().parse::<usize>().ok();
            let accel_opt = app.zupt_accel_var_edit.trim().parse::<f32>().ok();
            let gyro_opt = app.zupt_gyro_edit.trim().parse::<f32>().ok();

            let _ = app.cmd_tx.send(crate::BackendCommand::SetZuptParams {
                window_size: win_opt,
                accel_var_threshold: accel_opt,
                gyro_threshold: gyro_opt,
            });

            if let Some(window) = win_opt {
                app.config.zupt_window_size = window;
            }
            if let Some(accel) = accel_opt {
                app.config.zupt_accel_var_threshold = accel;
            }
            if let Some(gyro) = gyro_opt {
                app.config.zupt_gyro_threshold = gyro;
            }
            app.config.save();
        }
    });

    ui.group(|ui| {
        ui.label(egui::RichText::new(app.i18n.t("recorder.section")).strong());
        ui.horizontal(|ui| {
            if ui
                .add_enabled(
                    !app.is_recording,
                    egui::Button::new(crate::ui_icons::ICON_PLAY).fill(theme.btn_primary),
                )
                .on_hover_text(app.i18n.t(S_START_REC))
                .clicked()
            {
                let _ = app.cmd_tx.send(crate::BackendCommand::StartRecording);
            }

            if ui
                .add_enabled(
                    app.is_recording,
                    egui::Button::new(crate::ui_icons::ICON_STOP).fill(theme.btn_danger),
                )
                .on_hover_text(app.i18n.t(S_STOP_REC))
                .clicked()
            {
                let _ = app.cmd_tx.send(crate::BackendCommand::StopRecording);
            }

            if app.is_recording {
                ui.add(
                    egui::Label::new(
                        egui::RichText::new(app.i18n.t("recorder.recording_indicator"))
                            .color(crate::UI_STATUS_ERROR),
                    )
                    .sense(egui::Sense::hover()),
                );
            }
        });

        ui.label(
            egui::RichText::new(app.i18n.t("recorder.file_hint"))
                .size(theme.font_reg)
                .weak(),
        );
        ui.add_space(crate::GAP_XS);

        egui::Frame::group(ui.style()).show(ui, |ui| {
            ui.vertical_centered(|ui| {
                ui.heading(app.i18n.t(S_RECORDER_TITLE));
            });

            ui.horizontal(|ui| {
                ui.label(app.i18n.t("system.language"));
                egui::ComboBox::from_label("")
                    .selected_text(app.lang.clone())
                    .show_ui(ui, |ui| {
                        for (code, display) in app.i18n.available_langs_with_display() {
                            if ui.selectable_label(app.lang == code, &display).clicked()
                                && app.i18n.set_lang(&code)
                            {
                                app.lang = code.clone();
                                app.config.ui_lang = app.lang.clone();
                                app.config.save();
                            }
                        }
                    });

                if crate::ui_icons::icon_button(
                    ui,
                    crate::ui_icons::ICON_EXPORT,
                    &app.i18n.t("i18n.export"),
                )
                .clicked()
                {
                    let out = format!("i18n/export_{}.json", app.lang);
                    match app.i18n.export_lang(&app.lang, &out) {
                        Ok(()) => {
                            app.status = format!("{}: {}", app.i18n.t("i18n.exported"), out)
                        }
                        Err(e) => app.status = format!("Export failed: {}", e),
                    }
                }
            });

            ui.add_space(crate::GAP_XS);
            ui.horizontal(|ui| {
                if crate::ui_icons::icon_button(
                    ui,
                    crate::ui_icons::ICON_RELOAD,
                    &app.i18n.t("i18n.reload"),
                )
                .clicked()
                {
                    let mut i18n = I18n::load_dir("i18n", &app.lang);
                    let _ = i18n.set_lang(&app.lang);
                    app.i18n = i18n;
                    app.status = format!("{}: {}", app.i18n.t("i18n.reloaded"), app.lang);
                }
            });

            ui.add_space(crate::GAP_XS);
            ui.horizontal(|ui| {
                ui.label(format!(
                    "{} {}",
                    app.i18n.t("recorder.dropped_frames"),
                    app.recorder_dropped_count
                ));
                ui.separator();
                ui.label(format!(
                    "{} {}",
                    app.i18n.t("recorder.write_errors"),
                    app.recorder_write_errors
                ));
                ui.separator();
                ui.label(
                    egui::RichText::new(
                        app.recorder_filename
                            .clone()
                            .unwrap_or_else(|| app.i18n.t("recorder.file_not_created")),
                    )
                    .monospace()
                    .weak(),
                );
            });

            ui.add_space(crate::GAP_XS);
            ui.horizontal(|ui| {
                ui.label(app.i18n.t("recorder.filename_label"));
                let filename_response = ui.add(
                    egui::TextEdit::singleline(&mut app.recorder_filename_edit)
                        .hint_text(app.i18n.t("recorder.filename_hint"))
                        .desired_width(theme.input_w_xl),
                );
                filename_response.on_hover_text(app.i18n.t("recorder.filename_hint"));
            });

            ui.add_space(crate::GAP_XS);
            ui.label(
                egui::RichText::new(app.i18n.t("recorder.tip_empty_name"))
                    .size(theme.font_small)
                    .weak(),
            );

            ui.horizontal(|ui| {
                ui.label(app.i18n.t("recorder.batch_label"));
                let batch_response = ui.add(
                    egui::TextEdit::singleline(&mut app.recorder_batch_size_edit)
                        .desired_width(theme.input_w_small),
                );
                ui.label(app.i18n.t("recorder.flush_label"));
                let flush_response = ui.add(
                    egui::TextEdit::singleline(&mut app.recorder_flush_interval_ms_edit)
                        .desired_width(theme.input_w_small),
                );

                app.recorder_batch_valid = app.recorder_batch_size_edit.trim().is_empty()
                    || app.recorder_batch_size_edit.trim().parse::<usize>().is_ok();
                app.recorder_flush_valid =
                    app.recorder_flush_interval_ms_edit.trim().is_empty()
                        || app.recorder_flush_interval_ms_edit
                            .trim()
                            .parse::<u64>()
                            .is_ok();

                batch_response.on_hover_text(app.i18n.t("recorder.batch_hover"));
                flush_response.on_hover_text(app.i18n.t("recorder.flush_hover"));

                if !app.recorder_batch_valid {
                    ui.colored_label(
                        crate::UI_STATUS_ERROR,
                        app.i18n.t("recorder.batch_error"),
                    );
                }
                if !app.recorder_flush_valid {
                    ui.colored_label(
                        crate::UI_STATUS_ERROR,
                        app.i18n.t("recorder.flush_error"),
                    );
                }
            });

            ui.add_space(crate::GAP_XS);
            ui.horizontal(|ui| {
                let apply_enabled = app.recorder_batch_valid && app.recorder_flush_valid;

                if ui
                    .add_enabled(
                        apply_enabled,
                        egui::Button::new(crate::ui_icons::ICON_CHECK).small(),
                    )
                    .on_hover_text(app.i18n.t("recorder.apply"))
                    .clicked()
                {
                    let filename = optional_trimmed(&app.recorder_filename_edit);
                    let batch_size = optional_parse::<usize>(&app.recorder_batch_size_edit);
                    let flush_interval =
                        optional_parse::<u64>(&app.recorder_flush_interval_ms_edit);
                    let _ = app.cmd_tx.send(crate::BackendCommand::SetRecorderConfig {
                        enabled: None,
                        filename,
                        batch_size,
                        flush_interval_ms: flush_interval,
                    });

                    if app.recorder_auto_save {
                        persist_recorder_config(app, false);
                    }
                }

                if ui
                    .add_enabled(
                        apply_enabled,
                        egui::Button::new(crate::ui_icons::ICON_PLAY).small(),
                    )
                    .on_hover_text(app.i18n.t("recorder.apply_start"))
                    .clicked()
                {
                    let filename = optional_trimmed(&app.recorder_filename_edit);
                    let batch_size = optional_parse::<usize>(&app.recorder_batch_size_edit);
                    let flush_interval =
                        optional_parse::<u64>(&app.recorder_flush_interval_ms_edit);
                    let _ = app.cmd_tx.send(crate::BackendCommand::SetRecorderConfig {
                        enabled: Some(true),
                        filename,
                        batch_size,
                        flush_interval_ms: flush_interval,
                    });

                    if app.recorder_auto_save {
                        persist_recorder_config(app, true);
                    }
                }
            });

            ui.add_space(crate::GAP_XS);
            ui.horizontal(|ui| {
                if ui
                    .checkbox(&mut app.recorder_auto_save, app.i18n.t("recorder.auto_save"))
                    .changed()
                {
                    app.config.recorder_auto_save = app.recorder_auto_save;
                    if app.recorder_auto_save {
                        app.config.save();
                    }
                }
            });
        });
    });

    ui.add_space(crate::GAP_MD);
    ui.separator();
    ui.horizontal(|ui| {
        if crate::ui_icons::icon_button(
            ui,
            crate::ui_icons::ICON_CHECK,
            &app.i18n.t("save_config"),
        )
        .clicked()
        {
            app.config.mag_calibrations = app.mag_calibrations.clone();
            app.config.recorder_enabled = app.is_recording;
            app.config.recorder_filename = optional_trimmed(&app.recorder_filename_edit);
            if let Ok(batch_size) = app.recorder_batch_size_edit.trim().parse::<usize>() {
                app.config.recorder_batch_size = batch_size;
            }
            if let Ok(flush_interval) = app
                .recorder_flush_interval_ms_edit
                .trim()
                .parse::<u64>()
            {
                app.config.recorder_flush_interval_ms = flush_interval;
            }
            app.config.sidebar_width = app.sidebar_width;
            app.config.save();
        }

        if ui
            .add(egui::Button::new(crate::ui_icons::ICON_CANCEL).small())
            .on_hover_text(app.i18n.t("clear_cal"))
            .clicked()
        {
            let _ = app.cmd_tx.send(crate::BackendCommand::ClearAllCalibration);
        }
    });
}

fn optional_trimmed(value: &str) -> Option<String> {
    let value = value.trim();
    if value.is_empty() {
        None
    } else {
        Some(value.to_string())
    }
}

fn optional_parse<T>(value: &str) -> Option<T>
where
    T: std::str::FromStr,
{
    let value = value.trim();
    if value.is_empty() {
        None
    } else {
        value.parse::<T>().ok()
    }
}

fn persist_recorder_config(app: &mut crate::AetherposeApp, enable_recording: bool) {
    app.config.recorder_enabled = enable_recording;
    app.config.recorder_filename = optional_trimmed(&app.recorder_filename_edit);
    if let Ok(batch_size) = app.recorder_batch_size_edit.trim().parse::<usize>() {
        app.config.recorder_batch_size = batch_size;
    }
    if let Ok(flush_interval) = app
        .recorder_flush_interval_ms_edit
        .trim()
        .parse::<u64>()
    {
        app.config.recorder_flush_interval_ms = flush_interval;
    }
    app.config.save();
}

fn export_log_file(path: &str, prefix: &str, i18n: &I18n, status: &mut String) {
    if let Ok(data) = std::fs::read(path) {
        let filename = format!(
            "{}_{}.log",
            prefix,
            chrono::Local::now().format("%Y%m%d_%H%M%S")
        );
        if std::fs::write(&filename, data).is_ok() {
            let _ = std::fs::canonicalize(&filename)
                .map(|path| {
                    let path = path.to_string_lossy().to_string();
                    let _ = Command::new("explorer").arg("/select,").arg(&path).spawn();
                })
                .ok();
            *status = format!("{}: {}", i18n.t("serial.exported"), filename);
        } else {
            *status = i18n.t("serial.export_failed").to_string();
        }
    } else {
        *status = i18n.t("serial.no_debug_log").to_string();
    }
}

fn truncate_log_file(path: &str) {
    if let Err(e) = std::fs::OpenOptions::new()
        .write(true)
        .truncate(true)
        .open(path)
    {
        error!("failed to truncate {}: {}", path, e);
    }
}
