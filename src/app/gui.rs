use crate::app::config::AppConfig;
use crate::app::render::configure_style;
use crate::app::types::{
    BackendCommand, CameraProjectionMode, GuiSnapshot, GuiUpdate, Tab, TrackerState,
    TrajectoryIntegrationMode,
};
use crate::i18n::I18n;
use crate::skeleton::model::SkeletonModel;
use crate::theme::{Theme, ThemeVariant, UI_ACCENT, UI_PANEL_FILL, UI_STATUS_ACTIVE};
use eframe::egui;
use log::error;
use nalgebra::Vector3;
use std::collections::HashMap;
use std::sync::{mpsc, Arc, RwLock};

pub struct AetherposeApp {
    pub(crate) status: String,
    pub(crate) rx: mpsc::Receiver<GuiUpdate>,
    pub(crate) cmd_tx: mpsc::Sender<BackendCommand>,
    pub(crate) packet_count: u64,
    pub(crate) rotation_yaw: f32,
    pub(crate) rotation_pitch: f32,
    pub(crate) zoom: f32,
    pub(crate) current_tab: Tab,
    pub(crate) trackers: HashMap<u8, TrackerState>,
    pub(crate) skeleton_data: Option<SkeletonModel>,
    pub(crate) shared_skel: Arc<RwLock<SkeletonModel>>,
    pub(crate) ik_smoothness: f32,
    pub(crate) show_grid: bool,
    pub(crate) osc_ip: String,
    pub(crate) osc_port: String,
    pub(crate) serial_enabled_edit: bool,
    pub(crate) serial_port_edit: String,
    pub(crate) serial_baud_edit: String,
    pub(crate) prop_leg: f32,
    pub(crate) prop_arm: f32,
    pub(crate) prop_spine: f32,
    pub(crate) fps: f32,
    pub(crate) config: AppConfig,
    pub(crate) mirror_view: bool,
    pub(crate) camera_projection: CameraProjectionMode,
    pub(crate) drift_correction: f32,
    pub(crate) debug_draw_axes: bool,
    pub(crate) mag_calibration_points: HashMap<u8, Vec<Vector3<f32>>>,
    pub(crate) mag_calibrating_tracker_id: Option<u8>,
    pub(crate) is_recording: bool,
    pub(crate) mag_calibrations: HashMap<u8, crate::imu::calibration::MagCalibration>,
    pub(crate) smoothing_min_cutoff: f32,
    pub(crate) smoothing_beta: f32,
    pub(crate) trajectory_integration_mode: TrajectoryIntegrationMode,
    pub(crate) leg_ratio: f32,
    pub(crate) is_leg_calibrating: bool,
    pub(crate) floor_offset: f32,
    pub(crate) pending_shake_bone: Option<u8>,
    pub(crate) recorder_dropped_count: u64,
    pub(crate) recorder_write_errors: u64,
    pub(crate) recorder_filename: Option<String>,
    pub(crate) recorder_batch_size: usize,
    pub(crate) recorder_flush_interval_ms: u64,
    pub(crate) recorder_filename_edit: String,
    pub(crate) recorder_batch_size_edit: String,
    pub(crate) recorder_flush_interval_ms_edit: String,
    pub(crate) recorder_batch_valid: bool,
    pub(crate) recorder_flush_valid: bool,
    pub(crate) recorder_auto_save: bool,
    pub(crate) is_serial_running: bool,
    pub(crate) serial_status_msg: Option<String>,
    pub(crate) serial_log: Vec<String>,
    pub(crate) serial_log_filter: u8,
    pub(crate) i18n: I18n,
    pub(crate) lang: String,
    pub(crate) theme_variant: ThemeVariant,
    pub(crate) sidebar_width: f32,
    pub(crate) zupt_window_edit: String,
    pub(crate) zupt_enabled: bool,
    pub(crate) zupt_accel_var_edit: String,
    pub(crate) zupt_gyro_edit: String,
    pub(crate) show_cube_mode: bool,
}

impl AetherposeApp {
    #[allow(dead_code)]
    pub(crate) fn new(
        rx: mpsc::Receiver<GuiUpdate>,
        cmd_tx: mpsc::Sender<BackendCommand>,
        config: AppConfig,
        shared_skel: Arc<RwLock<SkeletonModel>>,
    ) -> Self {
        let default_skel = match shared_skel.read() {
            Ok(s) => s.clone(),
            Err(e) => {
                error!("shared_skel read poisoned: {}", e);
                SkeletonModel::new_humanoid()
            }
        };

        let mut i18n = I18n::load_dir("i18n", &config.ui_lang);
        let _ = i18n.set_lang(&config.ui_lang);

        Self {
            status: "Backend Running".to_owned(),
            rx,
            cmd_tx,
            packet_count: 0,
            rotation_yaw: 0.436,   // ~25° — 四分之三視角，左右差異明顯
            rotation_pitch: 0.175, // ~10° — 略俯視，前後深度感清楚
            zoom: 1.0,
            current_tab: Tab::Calibration,
            trackers: HashMap::new(),
            skeleton_data: Some(default_skel),
            shared_skel,
            ik_smoothness: config.ik_smoothness,
            show_grid: true,
            osc_ip: config.osc_ip.clone(),
            osc_port: config.osc_port.to_string(),
            serial_enabled_edit: config.serial_enabled,
            serial_port_edit: config.serial_port.clone().unwrap_or_default(),
            serial_baud_edit: config.serial_baud.to_string(),
            prop_leg: config.prop_leg,
            prop_arm: config.prop_arm,
            prop_spine: config.prop_spine,
            fps: 0.0,
            config: config.clone(),
            mirror_view: config.mirror_view,
            camera_projection: config.camera_projection,
            drift_correction: config.drift_correction,
            debug_draw_axes: false,
            mag_calibration_points: HashMap::new(),
            mag_calibrating_tracker_id: None,
            is_recording: false,
            mag_calibrations: config.mag_calibrations.clone(),
            smoothing_min_cutoff: config.smoothing_min_cutoff,
            smoothing_beta: config.smoothing_beta,
            trajectory_integration_mode: config.trajectory_integration_mode,
            leg_ratio: config.leg_ratio,
            is_leg_calibrating: false,
            floor_offset: config.floor_offset,
            pending_shake_bone: None,
            recorder_dropped_count: 0,
            recorder_write_errors: 0,
            recorder_filename: config.recorder_filename.clone(),
            recorder_batch_size: config.recorder_batch_size,
            recorder_flush_interval_ms: config.recorder_flush_interval_ms,
            recorder_filename_edit: config.recorder_filename.clone().unwrap_or_default(),
            recorder_batch_size_edit: config.recorder_batch_size.to_string(),
            recorder_flush_interval_ms_edit: config.recorder_flush_interval_ms.to_string(),
            recorder_batch_valid: true,
            recorder_flush_valid: true,
            recorder_auto_save: config.recorder_auto_save,
            is_serial_running: false,
            serial_status_msg: None,
            serial_log: Vec::new(),
            serial_log_filter: 0,
            i18n,
            lang: config.ui_lang.clone(),
            theme_variant: config.theme_variant,
            sidebar_width: config.sidebar_width,
            zupt_window_edit: config.zupt_window_size.to_string(),
            zupt_enabled: config.zupt_enabled,
            zupt_accel_var_edit: config.zupt_accel_var_threshold.to_string(),
            zupt_gyro_edit: config.zupt_gyro_threshold.to_string(),
            show_cube_mode: false,
        }
    }

    fn sync_updates(&mut self) {
        while let Ok(update) = self.rx.try_recv() {
            match update {
                GuiUpdate::Snapshot(snapshot) => self.apply_snapshot(snapshot),
                GuiUpdate::Status {
                    serial_running,
                    serial_status_msg,
                } => self.apply_status_update(serial_running, serial_status_msg),
            }
        }
    }

    fn apply_snapshot(&mut self, snapshot: GuiSnapshot) {
        self.packet_count = snapshot.packet_count;
        self.trackers = snapshot.trackers;

        if let Ok(s) = self.shared_skel.read() {
            self.skeleton_data = Some(s.clone());
        }

        self.mag_calibration_points = snapshot.mag_calibration_points;
        self.mag_calibrating_tracker_id = snapshot.mag_calibrating_tracker_id;
        self.is_recording = snapshot.is_recording;
        self.recorder_dropped_count = snapshot.recorder_dropped_count;
        self.recorder_write_errors = snapshot.recorder_write_errors;
        self.recorder_filename = snapshot.recorder_filename.clone();
        self.recorder_batch_size = snapshot.recorder_batch_size;
        self.recorder_flush_interval_ms = snapshot.recorder_flush_interval_ms;
        self.mag_calibrations = snapshot.mag_calibrations;
        self.leg_ratio = snapshot.leg_ratio;
        self.config.leg_ratio = snapshot.leg_ratio;
        self.floor_offset = snapshot.floor_offset;
        self.config.floor_offset = snapshot.floor_offset;
        self.pending_shake_bone = snapshot.pending_shake_bone;
        self.apply_status_update(snapshot.serial_running, snapshot.serial_status_msg);

        if self.recorder_filename_edit.is_empty() {
            if let Some(fname) = &self.recorder_filename {
                self.recorder_filename_edit = fname.clone();
            }
        }
        self.recorder_batch_size_edit = self.recorder_batch_size.to_string();
        self.recorder_flush_interval_ms_edit = self.recorder_flush_interval_ms.to_string();
    }

    fn apply_status_update(&mut self, serial_running: bool, serial_status_msg: Option<String>) {
        let changed =
            self.is_serial_running != serial_running || self.serial_status_msg != serial_status_msg;

        self.is_serial_running = serial_running;
        self.serial_status_msg = serial_status_msg;

        if changed {
            if let Some(msg) = self.serial_status_msg.clone() {
                self.push_serial_log(&msg);
            }
        }
    }

    fn push_serial_log(&mut self, msg: &str) {
        let ts = chrono::Local::now().format("%H:%M:%S").to_string();
        self.serial_log.push(format!("{} - {}", ts, msg));
        if self.serial_log.len() > 200 {
            let excess = self.serial_log.len() - 200;
            self.serial_log.drain(0..excess);
        }
    }

    fn active_theme(&self) -> Theme {
        if let Some(def) = &self.config.theme_custom {
            Theme::from_def(def)
        } else {
            Theme::from_variant(self.theme_variant)
        }
    }

    fn apply_builtin_theme(&mut self, ctx: &egui::Context, variant: ThemeVariant) {
        self.theme_variant = variant;
        self.config.theme_variant = variant;
        self.config.theme_custom = None;
        self.config.save();
        configure_style(ctx, &Theme::from_variant(variant));
    }

    fn draw_sidebar(&mut self, ctx: &egui::Context, theme: &Theme) {
        egui::SidePanel::left("sidebar_panel")
            .resizable(true)
            .min_width(140.0)
            .default_width(self.sidebar_width)
            .frame(egui::Frame::side_top_panel(&ctx.style()).fill(UI_PANEL_FILL))
            .show(ctx, |ui| {
                ui.add_space(theme.gap_sm);
                ui.vertical_centered(|ui| {
                    ui.heading(
                        egui::RichText::new(self.i18n.t("app.title"))
                            .strong()
                            .color(UI_ACCENT),
                    );
                    ui.label(
                        egui::RichText::new(self.i18n.t("app.subtitle"))
                            .size(theme.font_reg)
                            .weak(),
                    );
                });

                ui.add_space(theme.gap_sm);
                ui.separator();

                for (tab, key) in [
                    (Tab::Calibration, "menu.calibration"),
                    (Tab::Monitor, "menu.monitor"),
                    (Tab::Body, "menu.body"),
                    (Tab::System, "menu.system"),
                ] {
                    let selected = self.current_tab == tab;
                    if ui
                        .selectable_label(selected, self.i18n.t(key))
                        .clicked()
                    {
                        self.current_tab = tab;
                    }
                }

                ui.add_space(theme.gap_sm);
                ui.separator();
                ui.label(self.i18n.t("theme.label"));

                egui::ComboBox::from_id_salt("theme_variant_select")
                    .selected_text(match self.theme_variant {
                        ThemeVariant::Dark => self.i18n.t("theme.dark"),
                        ThemeVariant::Light => self.i18n.t("theme.light"),
                        ThemeVariant::Solarized => self.i18n.t("theme.solarized"),
                    })
                    .show_ui(ui, |ui| {
                        if ui
                            .selectable_label(self.theme_variant == ThemeVariant::Dark, self.i18n.t("theme.dark"))
                            .clicked()
                        {
                            self.apply_builtin_theme(ctx, ThemeVariant::Dark);
                        }
                        if ui
                            .selectable_label(self.theme_variant == ThemeVariant::Light, self.i18n.t("theme.light"))
                            .clicked()
                        {
                            self.apply_builtin_theme(ctx, ThemeVariant::Light);
                        }
                        if ui
                            .selectable_label(
                                self.theme_variant == ThemeVariant::Solarized,
                                self.i18n.t("theme.solarized"),
                            )
                            .clicked()
                        {
                            self.apply_builtin_theme(ctx, ThemeVariant::Solarized);
                        }
                    });

                ui.horizontal(|ui| {
                    if ui
                        .add(egui::Button::new(crate::ui_icons::ICON_EXPORT).small())
                        .on_hover_text(self.i18n.t("theme.export"))
                        .clicked()
                    {
                        let theme_inst = self.active_theme();
                        if let Err(e) = theme_inst.export_to_file("theme_custom.json") {
                            error!("failed to export theme: {}", e);
                        }
                    }

                    if ui
                        .add(egui::Button::new(crate::ui_icons::ICON_IMPORT).small())
                        .on_hover_text(self.i18n.t("theme.import"))
                        .clicked()
                    {
                        match Theme::import_from_file("theme_custom.json") {
                            Ok(t) => {
                                configure_style(ctx, &t);
                                self.config.theme_custom = Some(t.to_def());
                                self.config.save();
                            }
                            Err(e) => error!("failed to import theme: {}", e),
                        }
                    }

                    if ui
                        .add(egui::Button::new(crate::ui_icons::ICON_RELOAD).small())
                        .on_hover_text(self.i18n.t("theme.reset"))
                        .clicked()
                    {
                        self.apply_builtin_theme(ctx, ThemeVariant::Dark);
                    }
                });

                ui.add_space(theme.gap_sm);
                ui.separator();
                ui.label(format!("{} {}", self.i18n.t("packet_count"), self.packet_count));
                ui.label(format!("{} {:.1}", self.i18n.t("status.fps_label"), self.fps));

                ui.horizontal(|ui| {
                    ui.label(self.i18n.t("status"));
                    ui.label(egui::RichText::new(&self.status).color(UI_STATUS_ACTIVE));
                });

                let actual_w = ui.min_rect().width();
                if (actual_w - self.sidebar_width).abs() > 0.5 {
                    self.sidebar_width = actual_w.clamp(140.0, 900.0);
                    self.config.sidebar_width = self.sidebar_width;
                }
            });
    }

    fn draw_main_panel(&mut self, ctx: &egui::Context, theme: &Theme) {
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.add_space(theme.gap_sm);
            match self.current_tab {
                Tab::Calibration => crate::ui::calibration::ui_calibration(self, ui, ctx, theme),
                Tab::Monitor => crate::ui::monitor::ui_monitor(self, ui, ctx, theme),
                Tab::Body => crate::ui::body::ui_body(self, ui, ctx, theme),
                Tab::System => crate::ui::system::ui_system(self, ui, ctx, theme),
            }
        });
    }
}

impl eframe::App for AetherposeApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.sync_updates();

        let dt = ctx.input(|i| i.stable_dt);
        if dt > 0.0 {
            self.fps = 1.0 / dt;
        }

        let theme = self.active_theme();
        configure_style(ctx, &theme);

        for tracker in self.trackers.values() {
            if let Some(bone_id) = tracker.assigned_bone {
                self.config.tracker_assignments.insert(tracker.id, bone_id);
            }
        }

        ctx.request_repaint();
        self.draw_sidebar(ctx, &theme);
        self.draw_main_panel(ctx, &theme);
    }
}
