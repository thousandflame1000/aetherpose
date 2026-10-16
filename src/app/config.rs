use crate::app::types::{TrajectoryIntegrationMode, WsSettings};
use log::{error, info, warn};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufReader, Write};

// Missing fields take AppConfig::default(), not their type's zero: a config.json saved before
// the filter settings existed used to load min_cutoff 0 and beta 0, which freezes the filter.
#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(default)]
pub struct AppConfig {
    pub osc_ip: String,
    pub osc_port: u16,
    pub ik_smoothness: f32,
    pub prop_leg: f32,
    pub prop_arm: f32,
    pub prop_spine: f32,
    pub tracker_assignments: HashMap<u8, u8>,
    /// Trackers set to "未指派" on the page; they stay without a bone across restarts.
    pub unassigned_trackers: Vec<u8>,
    pub drift_correction: f32,
    pub smoothing_min_cutoff: f32,
    pub smoothing_beta: f32,
    pub trajectory_integration_mode: TrajectoryIntegrationMode,
    #[serde(default = "default_leg_ratio")]
    pub leg_ratio: f32,
    pub floor_offset: f32,
    #[serde(default = "default_zupt_window_size")]
    pub zupt_window_size: usize,
    #[serde(default = "default_zupt_enabled")]
    pub zupt_enabled: bool,
    #[serde(default = "default_zupt_accel_var_threshold")]
    pub zupt_accel_var_threshold: f32,
    #[serde(default = "default_zupt_gyro_threshold")]
    pub zupt_gyro_threshold: f32,
    pub serial_enabled: bool,
    pub serial_port: Option<String>,
    #[serde(default = "default_serial_baud")]
    pub serial_baud: u32,
    /// UDP port for Wi-Fi trackers (ImuDataPacket); separate from the OSC output port.
    #[serde(default = "default_udp_input_port")]
    pub udp_input_port: u16,
    /// Set when config.json could not be read: "<error>|<backup path>" (the
    /// backup path is empty if the copy failed). Not saved.
    #[serde(skip)]
    pub load_warning: Option<String>,
}

fn default_leg_ratio() -> f32 { 0.9 }
fn default_serial_baud() -> u32 { 115200 }
fn default_udp_input_port() -> u16 { 9003 }
fn default_zupt_window_size() -> usize { 8 }
fn default_zupt_enabled() -> bool { true }
fn default_zupt_accel_var_threshold() -> f32 { 0.0005 }
fn default_zupt_gyro_threshold() -> f32 { 0.02 }

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            osc_ip: "127.0.0.1".to_string(),
            osc_port: 9000,
            ik_smoothness: 0.5,
            prop_leg: 1.0,
            prop_arm: 1.0,
            prop_spine: 1.0,
            tracker_assignments: HashMap::new(),
            unassigned_trackers: Vec::new(),
            drift_correction: 0.0,
            smoothing_min_cutoff: 3.0,
            smoothing_beta: 3.0,
            trajectory_integration_mode: TrajectoryIntegrationMode::default(),
            leg_ratio: default_leg_ratio(),
            floor_offset: 0.0,
            serial_enabled: false,
            serial_port: None,
            serial_baud: default_serial_baud(),
            udp_input_port: default_udp_input_port(),
            load_warning: None,
            zupt_window_size: default_zupt_window_size(),
            zupt_enabled: default_zupt_enabled(),
            zupt_accel_var_threshold: default_zupt_accel_var_threshold(),
            zupt_gyro_threshold: default_zupt_gyro_threshold(),
        }
    }
}

impl AppConfig {
    /// Keeps settings from a hand-edited or damaged config.json inside the ranges the page and
    /// the backend use (non-finite values, e.g. an f32 overflow, become the default). Returns
    /// the names of the settings it changed.
    pub fn sanitize(&mut self) -> Vec<&'static str> {
        let defaults = Self::default();
        let mut adjusted = Vec::new();
        let mut fix = |value: &mut f32, min: f32, max: f32, default: f32, name: &'static str| {
            let fixed = if value.is_finite() { value.clamp(min, max) } else { default };
            if fixed != *value {
                *value = fixed;
                adjusted.push(name);
            }
        };
        fix(&mut self.ik_smoothness, 0.0, 1.0, defaults.ik_smoothness, "ik_smoothness");
        fix(&mut self.prop_leg, 0.5, 1.5, defaults.prop_leg, "prop_leg");
        fix(&mut self.prop_arm, 0.5, 1.5, defaults.prop_arm, "prop_arm");
        fix(&mut self.prop_spine, 0.5, 1.5, defaults.prop_spine, "prop_spine");
        fix(&mut self.drift_correction, 0.0, 1.0, defaults.drift_correction, "drift_correction");
        fix(&mut self.smoothing_min_cutoff, 0.01, 5.0, defaults.smoothing_min_cutoff, "smoothing_min_cutoff");
        fix(&mut self.smoothing_beta, 0.0, 10.0, defaults.smoothing_beta, "smoothing_beta");
        fix(&mut self.floor_offset, -2.0, 2.0, defaults.floor_offset, "floor_offset");
        // The range leg calibration accepts.
        fix(&mut self.leg_ratio, 0.2, 3.0, defaults.leg_ratio, "leg_ratio");
        fix(&mut self.zupt_accel_var_threshold, f32::MIN_POSITIVE, f32::MAX, defaults.zupt_accel_var_threshold, "zupt_accel_var_threshold");
        fix(&mut self.zupt_gyro_threshold, f32::MIN_POSITIVE, f32::MAX, defaults.zupt_gyro_threshold, "zupt_gyro_threshold");
        let window = self.zupt_window_size.clamp(1, crate::imu::drift::MAX_ZUPT_WINDOW);
        if window != self.zupt_window_size {
            self.zupt_window_size = window;
            adjusted.push("zupt_window_size");
        }
        adjusted
    }

    pub fn ws_settings(&self) -> WsSettings {
        WsSettings {
            ik_smoothness: self.ik_smoothness,
            prop_leg: self.prop_leg,
            prop_arm: self.prop_arm,
            prop_spine: self.prop_spine,
            drift_correction: self.drift_correction,
            smoothing_min_cutoff: self.smoothing_min_cutoff,
            smoothing_beta: self.smoothing_beta,
            trajectory_integration_mode: self.trajectory_integration_mode,
            osc_ip: self.osc_ip.clone(),
            osc_port: self.osc_port,
            zupt_enabled: self.zupt_enabled,
            zupt_window_size: self.zupt_window_size,
            zupt_accel_var_threshold: self.zupt_accel_var_threshold,
            zupt_gyro_threshold: self.zupt_gyro_threshold,
            serial_enabled: self.serial_enabled,
            serial_port: self.serial_port.clone(),
            serial_baud: self.serial_baud,
        }
    }

    pub fn load() -> Self {
        Self::load_from(std::path::Path::new("config.json"))
    }

    /// Defaults when the file is missing. An unreadable file is copied to
    /// "<name>.bad" first, because the next save would overwrite it, and the
    /// problem is kept in `load_warning` for the page.
    pub fn load_from(path: &std::path::Path) -> Self {
        let text = match std::fs::read_to_string(path) {
            Ok(text) => text,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Self::default(),
            Err(e) => return Self::with_warning(path, e.to_string()),
        };
        match serde_json::from_str::<Self>(&text) {
            Ok(mut cfg) => {
                info!("Loaded {}", path.display());
                let adjusted = cfg.sanitize();
                if !adjusted.is_empty() {
                    warn!("{}: out-of-range settings replaced: {}", path.display(), adjusted.join(", "));
                }
                cfg
            }
            Err(e) => Self::with_warning(path, e.to_string()),
        }
    }

    fn with_warning(path: &std::path::Path, problem: String) -> Self {
        let backup = path.with_extension("json.bad");
        let kept = std::fs::copy(path, &backup).is_ok();
        error!("{} could not be read ({}); using defaults{}", path.display(), problem,
            if kept { format!(", the file was kept as {}", backup.display()) } else { String::new() });
        let mut cfg = Self::default();
        let backup_name = if kept { backup.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default() } else { String::new() };
        cfg.load_warning = Some(format!("{}|{}", problem, backup_name));
        cfg
    }

    pub fn save(&self) {
        let tmp_path = "config.json.tmp";
        match File::create(tmp_path) {
            Ok(mut file) => {
                if let Err(e) = serde_json::to_writer(&mut file, self) {
                    error!("Failed to serialize config: {}", e);
                    let _ = std::fs::remove_file(tmp_path);
                    return;
                }
                if let Err(e) = file.flush() {
                    error!("Failed to flush config: {}", e);
                }
                if let Err(e) = std::fs::rename(tmp_path, "config.json") {
                    error!("Failed to rename config temp file: {}", e);
                    if let Err(e2) = std::fs::copy(tmp_path, "config.json") {
                        error!("Failed to copy config temp file: {}", e2);
                    } else {
                        let _ = std::fs::remove_file(tmp_path);
                        info!("Saved config.json via copy fallback");
                    }
                } else {
                    info!("Saved config.json");
                }
            }
            Err(e) => {
                error!("Failed to create config temp file: {}", e);
            }
        }
    }
}

pub fn append_and_rotate_log(path: &str, line: &str) {
    const MAX_BYTES: u64 = 5 * 1024 * 1024;
    const KEEP_FILES: usize = 5;

    let pathp = std::path::Path::new(path);
    if let Some(dir) = pathp.parent().filter(|dir| !dir.as_os_str().is_empty()) {
        let _ = std::fs::create_dir_all(dir);
    }
    if let Ok(md) = std::fs::metadata(path) {
        if md.len() > MAX_BYTES {
            let ts = chrono::Local::now().format("%Y%m%d%H%M%S").to_string();
            let rotated = format!("{}.{}", path, ts);
            if let Err(e) = std::fs::rename(path, &rotated) {
                let _ = std::fs::OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(path)
                    .and_then(|mut f| {
                        use std::io::Write as _;
                        f.write_all(format!("[log-rotation] rename failed: {}\n", e).as_bytes())
                    });
            } else {
                if let Ok(inf) = File::open(&rotated) {
                    let mut reader = BufReader::new(inf);
                    let gz_path = format!("{}.gz", rotated);
                    if let Ok(outf) = File::create(&gz_path) {
                        let mut encoder =
                            flate2::write::GzEncoder::new(outf, flate2::Compression::default());
                        if std::io::copy(&mut reader, &mut encoder).is_ok() {
                            let _ = encoder.finish();
                            let _ = std::fs::remove_file(&rotated);
                        }
                    }
                }

                if let Some(dir) = pathp.parent() {
                    if let Ok(entries) = std::fs::read_dir(dir) {
                        let base = pathp
                            .file_name()
                            .map(|s| s.to_string_lossy().into_owned())
                            .unwrap_or_default();
                        let mut rotated_files: Vec<(std::time::SystemTime, std::path::PathBuf)> =
                            entries
                                .filter_map(|e| e.ok())
                                .map(|e| e.path())
                                .filter_map(|p| {
                                    if let Some(fname) = p.file_name().and_then(|n| n.to_str()) {
                                        if fname.starts_with(&format!("{}.", base))
                                            && fname.ends_with(".gz")
                                        {
                                            if let Ok(md) = std::fs::metadata(&p) {
                                                if let Ok(mtime) = md.modified() {
                                                    return Some((mtime, p));
                                                }
                                            }
                                        }
                                    }
                                    None
                                })
                                .collect();
                        rotated_files.sort_by(|a, b| b.0.cmp(&a.0));
                        if rotated_files.len() > KEEP_FILES {
                            for (_t, p) in rotated_files.into_iter().skip(KEEP_FILES) {
                                let _ = std::fs::remove_file(p);
                            }
                        }
                    }
                }
            }
        }
    }

    let _ = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .and_then(|mut f| {
            use std::io::Write as _;
            f.write_all(line.as_bytes())
        });
}
