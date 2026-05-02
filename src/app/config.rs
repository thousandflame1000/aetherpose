use crate::imu::calibration::MagCalibration;
use crate::app::types::{CameraProjectionMode, TrajectoryIntegrationMode};
use crate::theme::{ThemeDef, ThemeVariant};
use log::{error, info};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufReader, Write};

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct AppConfig {
    pub osc_ip: String,
    pub osc_port: u16,
    pub ik_smoothness: f32,
    pub prop_leg: f32,
    pub prop_arm: f32,
    pub prop_spine: f32,
    pub tracker_assignments: HashMap<u8, u8>,
    #[serde(default)]
    pub mirror_view: bool,
    #[serde(default)]
    pub camera_projection: CameraProjectionMode,
    #[serde(default)]
    pub drift_correction: f32,
    #[serde(default)]
    pub mag_calibrations: HashMap<u8, MagCalibration>,
    #[serde(default)]
    pub smoothing_min_cutoff: f32,
    #[serde(default)]
    pub smoothing_beta: f32,
    #[serde(default)]
    pub trajectory_integration_mode: TrajectoryIntegrationMode,
    #[serde(default = "default_leg_ratio")]
    pub leg_ratio: f32,
    #[serde(default)]
    pub floor_offset: f32,
    #[serde(default)]
    pub recorder_enabled: bool,
    #[serde(default)]
    pub recorder_filename: Option<String>,
    #[serde(default)]
    pub recorder_batch_size: usize,
    #[serde(default)]
    pub recorder_flush_interval_ms: u64,
    #[serde(default)]
    pub recorder_auto_save: bool,
    #[serde(default = "default_ui_lang")]
    pub ui_lang: String,
    #[serde(default = "default_theme_variant")]
    pub theme_variant: ThemeVariant,
    #[serde(default)]
    pub theme_custom: Option<ThemeDef>,
    #[serde(default = "default_sidebar_width")]
    pub sidebar_width: f32,
    #[serde(default = "default_zupt_window_size")]
    pub zupt_window_size: usize,
    #[serde(default = "default_zupt_enabled")]
    pub zupt_enabled: bool,
    #[serde(default = "default_zupt_accel_var_threshold")]
    pub zupt_accel_var_threshold: f32,
    #[serde(default = "default_zupt_gyro_threshold")]
    pub zupt_gyro_threshold: f32,
    #[serde(default)]
    pub serial_enabled: bool,
    #[serde(default)]
    pub serial_port: Option<String>,
    #[serde(default = "default_serial_baud")]
    pub serial_baud: u32,
}

fn default_leg_ratio() -> f32 {
    0.9
}

fn default_ui_lang() -> String {
    "zh".to_string()
}

fn default_sidebar_width() -> f32 {
    180.0
}

fn default_theme_variant() -> ThemeVariant {
    ThemeVariant::Dark
}

fn default_theme_custom() -> Option<ThemeDef> {
    None
}

fn default_serial_baud() -> u32 {
    115200
}

fn default_zupt_window_size() -> usize {
    8
}

fn default_zupt_enabled() -> bool {
    true
}

fn default_zupt_accel_var_threshold() -> f32 {
    0.0005
}

fn default_zupt_gyro_threshold() -> f32 {
    0.02
}

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
            mirror_view: false,
            camera_projection: CameraProjectionMode::Orthographic,
            drift_correction: 0.0,
            mag_calibrations: HashMap::new(),
            smoothing_min_cutoff: 3.0,
            smoothing_beta: 3.0,
            trajectory_integration_mode: TrajectoryIntegrationMode::default(),
            leg_ratio: default_leg_ratio(),
            floor_offset: 0.0,
            recorder_enabled: false,
            recorder_filename: None,
            recorder_batch_size: 128,
            recorder_flush_interval_ms: 500,
            recorder_auto_save: false,
            ui_lang: default_ui_lang(),
            theme_variant: default_theme_variant(),
            theme_custom: default_theme_custom(),
            sidebar_width: default_sidebar_width(),
            serial_enabled: false,
            serial_port: None,
            serial_baud: default_serial_baud(),
            zupt_window_size: default_zupt_window_size(),
            zupt_enabled: default_zupt_enabled(),
            zupt_accel_var_threshold: default_zupt_accel_var_threshold(),
            zupt_gyro_threshold: default_zupt_gyro_threshold(),
        }
    }
}

impl AppConfig {
    pub fn load() -> Self {
        if let Ok(file) = File::open("config.json") {
            if let Ok(cfg) = serde_json::from_reader(file) {
                info!("Loaded config.json");
                return cfg;
            }
        }
        Self::default()
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
