mod i18n;
mod backpress;
mod ui_icons;
mod fusion;
mod ik;
mod imu;
mod net;
mod connection_type;
mod osc;
mod output;
mod skeleton;
mod recording;
mod app;
mod smoothing;
mod state;
mod theme;
// 宣告模組

use eframe::{
    egui,
    epaint::{Color32, Pos2, Stroke},
};
use log::{error, info};
use std::collections::HashMap;
use std::sync::{mpsc, Arc, RwLock};
use std::sync::atomic::Ordering;
use crossbeam_channel::bounded;
use tokio::{
    sync::watch,
    time::{interval, Duration},
}; // 新增 watch
// use std::io::Read; // [移除] 暫時未使用的引用
use crate::{
    fusion::{AuthoritativePose, FusionEngine}, // [更改] 使用新的 FusionEngine
    ik::{goals::Goal, IkSolver},
    imu::calibration::MagCalibration, // 引入校準結構
    net::packet::PacketData,          // [修改] 移除未使用的 FullDataPacket 引用
    osc::OscSender,                   // 引入 OscSender
    recording::Recorder,
    skeleton::model::SkeletonModel,
};
use crate::connection_type::ConnectionType;
use crate::backpress::BackpressStats;
use crate::i18n::I18n;
use crate::theme::*;
use nalgebra::{UnitQuaternion, Vector3}; // 新增 UnitQuaternion
use serde::{Deserialize, Serialize}; // 新增 Serialize
use std::fs::File; // 新增檔案操作
use std::io::Write;
use chrono::Local;
use std::io::BufReader;
use flate2::write::GzEncoder;
use flate2::Compression;
use std::process::Command;

// String keys (prepare for i18n extraction)
const S_RECORDER_TITLE: &str = "recorder.title";
const S_START_REC: &str = "recorder.start";
const S_STOP_REC: &str = "recorder.stop";

// --- [新增] 權威來源 (如 Quest) 的資料結構 ---
// 定義單一姿態數據
#[derive(Serialize, Deserialize, Debug, Clone)]
struct VrPoseData {
    pos: [f32; 3],
    rot: [f32; 4], // [x, y, z, w]
}

// 定義完整的 VR 封包 (包含頭與手)
#[derive(Serialize, Deserialize, Debug, Clone)]
struct VrBridgePacket {
    head: Option<VrPoseData>,
    left_hand: Option<VrPoseData>,
    right_hand: Option<VrPoseData>,
}

// 用於 Watch Channel 傳遞的結構
struct QuestInputData {
    head: Option<AuthoritativePose>,
    left_hand: Option<AuthoritativePose>,
    right_hand: Option<AuthoritativePose>,
}

// --- 設定檔結構 ---
#[derive(Serialize, Deserialize, Debug, Clone)]
struct AppConfig {
    osc_ip: String,
    osc_port: u16,
    ik_smoothness: f32,
    prop_leg: f32,
    prop_arm: f32,
    prop_spine: f32,
    tracker_assignments: HashMap<u8, u8>, // TrackerID -> BoneID
    #[serde(default)] // 若舊設定檔無此欄位，使用預設值
    mirror_view: bool,
    #[serde(default)]
    drift_correction: f32,
    #[serde(default)]
    mag_calibrations: HashMap<u8, MagCalibration>, // 儲存磁力計校準數據
    #[serde(default)]
    smoothing_min_cutoff: f32, // One Euro Filter Min Cutoff
    #[serde(default)]
    smoothing_beta: f32, // One Euro Filter Beta
    #[serde(default = "default_leg_ratio")]
    leg_ratio: f32, // 大腿長度 / 小腿長度 比例 (預設約 0.9)
    #[serde(default)]
    floor_offset: f32, // 虛擬地板高度偏移 (公尺)
    // Recorder settings
    #[serde(default)]
    recorder_enabled: bool,
    #[serde(default)]
    recorder_filename: Option<String>,
    #[serde(default)]
    recorder_batch_size: usize,
    #[serde(default)]
    recorder_flush_interval_ms: u64,
    #[serde(default)]
    recorder_auto_save: bool,
    #[serde(default = "default_ui_lang")]
    ui_lang: String,
    #[serde(default = "default_theme_variant")]
    theme_variant: crate::theme::ThemeVariant,
    #[serde(default = "default_sidebar_width")]
    sidebar_width: f32,
    // ZUPT parameters
    #[serde(default = "default_zupt_window_size")]
    zupt_window_size: usize,
    #[serde(default = "default_zupt_accel_var_threshold")]
    zupt_accel_var_threshold: f32,
    #[serde(default = "default_zupt_gyro_threshold")]
    zupt_gyro_threshold: f32,
    // Serial port bridge settings
    #[serde(default)]
    serial_enabled: bool,
    #[serde(default)]
    serial_port: Option<String>,
    #[serde(default = "default_serial_baud")]
    serial_baud: u32,
}

fn default_leg_ratio() -> f32 {
    0.9
}

fn default_ui_lang() -> String {
    "zh".to_string()
}

fn default_sidebar_width() -> f32 { 180.0 }

fn default_theme_variant() -> crate::theme::ThemeVariant {
    crate::theme::ThemeVariant::Dark
}

fn default_serial_baud() -> u32 {
    115200
}

fn default_zupt_window_size() -> usize { 8 }
fn default_zupt_accel_var_threshold() -> f32 { 0.0005 }
fn default_zupt_gyro_threshold() -> f32 { 0.02 }

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            osc_ip: "127.0.0.1".to_string(),
            osc_port: 9000,
            ik_smoothness: 0.5,
                prop_leg: 1.0, // Default leg proportion
                prop_arm: 1.0, // Default arm proportion
                prop_spine: 1.0, // Default spine proportion
            tracker_assignments: HashMap::new(),
            mirror_view: false,
            drift_correction: 0.0,
            mag_calibrations: HashMap::new(),
            smoothing_min_cutoff: 1.0,
            smoothing_beta: 1.5, // [修改] 提高預設速度係數，讓快速動作更靈敏 (增加動量感)
            leg_ratio: default_leg_ratio(),
            floor_offset: 0.0,
            recorder_enabled: false,
            recorder_filename: None,
            recorder_batch_size: 128,
            recorder_flush_interval_ms: 500,
            recorder_auto_save: false,
            ui_lang: default_ui_lang(),
            theme_variant: default_theme_variant(),
            sidebar_width: default_sidebar_width(),
            serial_enabled: false,
            serial_port: None,
            serial_baud: default_serial_baud(),
            zupt_window_size: default_zupt_window_size(),
            zupt_accel_var_threshold: default_zupt_accel_var_threshold(),
            zupt_gyro_threshold: default_zupt_gyro_threshold(),
        }
    }
}

impl AppConfig {
    fn load() -> Self {
        if let Ok(file) = File::open("config.json") {
            if let Ok(cfg) = serde_json::from_reader(file) {
                info!("已載入設定檔 config.json");
                return cfg;
            }
        }
        Self::default()
    }

    fn save(&self) {
        // 原子寫入：先寫入臨時檔，再以 rename 原子替換目標檔案
        let tmp_path = "config.json.tmp";
        match File::create(tmp_path) {
            Ok(mut file) => {
                if let Err(e) = serde_json::to_writer(&mut file, self) {
                    error!("寫入設定檔暫存檔失敗: {}", e);
                    let _ = std::fs::remove_file(tmp_path);
                    return;
                }
                if let Err(e) = file.flush() {
                    error!("Flush 設定檔暫存檔失敗: {}", e);
                }
                // 嘗試以原子方式替換
                if let Err(e) = std::fs::rename(tmp_path, "config.json") {
                    error!("以原子方式寫入設定檔失敗，嘗試以備援方式複製: {}", e);
                    // 備援：嘗試拷貝內容
                    if let Err(e2) = std::fs::copy(tmp_path, "config.json") {
                        error!("備援複製設定檔失敗: {}", e2);
                    } else {
                        let _ = std::fs::remove_file(tmp_path);
                        info!("設定檔已儲存至 config.json (備援方式)");
                    }
                } else {
                    info!("設定檔已原子性儲存至 config.json");
                }
            }
            Err(e) => {
                error!("建立設定檔暫存檔失敗: {}", e);
            }
        }
    }
}

// Append `line` to `path`, rotating the file if it exceeds `MAX_BYTES`.
fn append_and_rotate_log(path: &str, line: &str) {
    const MAX_BYTES: u64 = 5 * 1024 * 1024; // 5 MB
    const KEEP_FILES: usize = 5; // 保留最近 N 個輪替檔案

    let pathp = std::path::Path::new(path);
    // rotate if needed
    if let Ok(md) = std::fs::metadata(path) {
        if md.len() > MAX_BYTES {
            let ts = Local::now().format("%Y%m%d%H%M%S").to_string();
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
                // compress rotated -> rotated.gz
                if let Ok(inf) = File::open(&rotated) {
                    let mut reader = BufReader::new(inf);
                    let gz_path = format!("{}.gz", rotated);
                    if let Ok(outf) = File::create(&gz_path) {
                        let mut encoder = GzEncoder::new(outf, Compression::default());
                        if std::io::copy(&mut reader, &mut encoder).is_ok() {
                            let _ = encoder.finish();
                            let _ = std::fs::remove_file(&rotated);
                        }
                    }
                }

                // retention: remove older rotated gz files, keep newest KEEP_FILES
                if let Some(dir) = pathp.parent() {
                    if let Ok(entries) = std::fs::read_dir(dir) {
                        let base = pathp.file_name().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
                        let mut rotated_files: Vec<(std::time::SystemTime, std::path::PathBuf)> = entries.filter_map(|e| e.ok()).map(|e| e.path()).filter_map(|p| {
                            if let Some(fname) = p.file_name().and_then(|n| n.to_str()) {
                                if fname.starts_with(&format!("{}.", base)) && fname.ends_with(".gz") {
                                    if let Ok(md) = std::fs::metadata(&p) {
                                        if let Ok(mtime) = md.modified() {
                                            return Some((mtime, p));
                                        }
                                    }
                                }
                            }
                            None
                        }).collect();
                        // sort by modified desc
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

// ConnectionType defined in src/connection_type.rs

// 定義 Tracker 狀態 (用於 GUI 顯示)
#[derive(Clone, Debug)]
struct TrackerState {
    id: u8,
    connection_type: ConnectionType, // 新增：連線方式
    battery: f32,
    rssi: i32,
    accel: Option<[f32; 3]>,
    last_update: std::time::Instant,
    assigned_bone: Option<u8>,  // 新增：目前分配到的骨骼 ID
    tps: u32,                   // 新增：每秒封包數 (Hz)
    rotation: Option<[f32; 4]>, // 新增：原始旋轉資料 [x, y, z, w]
    stationary: bool,           // 新增：靜止狀態
    last_sequence: u16,
    received_packets: u64,
    lost_packets: u64,
    mag: Option<[f32; 3]>,    // 新增：原始磁力計資料
    is_mag_calibrating: bool, // 新增：是否正在進行磁力計校準
}

// 定義後端傳給 GUI 的資料結構
struct GuiUpdate {
    packet_count: u64,
    trackers: HashMap<u8, TrackerState>,
    // skeleton moved to shared Arc<RwLock<SkeletonModel>> to avoid cloning
    mag_calibration_points: HashMap<u8, Vec<Vector3<f32>>>, // 磁力計校準點雲
    mag_calibrating_tracker_id: Option<u8>,                 // 當前正在校準的 Tracker ID
    is_recording: bool,
    recorder_dropped_count: u64,
    recorder_write_errors: u64,
    recorder_filename: Option<String>,
    recorder_batch_size: usize,
    recorder_flush_interval_ms: u64,
    mag_calibrations: HashMap<u8, MagCalibration>, // 回傳校準結果給 GUI
    leg_ratio: f32,                                // 回傳當前的腿部比例
    floor_offset: f32,                             // 回傳當前的地板偏移
    pending_shake_bone: Option<u8>,                // 新增：後端正在等待搖晃分配的骨骼
    serial_running: bool,
    serial_status_msg: Option<String>,
    // runtime serial messages (recent)
    // (moved to GUI-only `AetherposeApp::serial_log`)
}

// 定義從 GUI 傳送給後端的指令
enum BackendCommand {
    SetIkSmoothness(f32),
    ResetYaw,
    SetOscTarget(String, u16),
    AssignTracker(u8, u8), // TrackerID, BoneID
    SetProportions { leg: f32, arm: f32, spine: f32 },
    ResetMounting,
    ClearAllCalibration,
    SetDriftCorrection(f32),
    AutoAssign,              // 新增自動分配指令
    StartMagCalibration(u8), // 開始磁力計校準
    StopMagCalibration(u8),  // 停止磁力計校準
    StartRecording,
    StopRecording,
    SetRecorderConfig {
        enabled: Option<bool>,
        filename: Option<String>,
        batch_size: Option<usize>,
        flush_interval_ms: Option<u64>,
    },
    SetSerialConfig {
        enabled: Option<bool>,
        port: Option<String>,
        baud: Option<u32>,
    },
    SetSmoothingParams { min_cutoff: f32, beta: f32 },
    SetZuptParams { window_size: Option<usize>, accel_var_threshold: Option<f32>, gyro_threshold: Option<f32> },
    StartLegCalibration,  // 開始腿部比例校準
    StopLegCalibration,   // 停止並計算
    SetFloorOffset(f32),  // 設定地板偏移
    AutoFloor,            // 自動偵測地板高度
    StartShakeAssign(u8), // 開始搖晃分配 (BoneID)
    CancelShakeAssign,    // 取消搖晃分配
}

// 定義介面的分頁
#[derive(PartialEq, Clone, Copy)]
enum Tab {
    Calibration, // 校準與預覽
    Monitor,     // 追蹤器監控
    Body,        // 身體比例與參數
    System,      // 系統設定
}

fn main() -> eframe::Result<()> {
    // 1. 設定 Log
    if std::env::var("RUST_LOG").is_err() {
        std::env::set_var("RUST_LOG", "info");
    }
    env_logger::init();

    // 載入設定檔
    let config = AppConfig::load();
    let mut config_backend = config.clone(); // 複製一份給後端

    // 建立通道：tx (傳送端) 給後端, rx (接收端) 給 GUI
    let (tx, rx) = mpsc::channel::<GuiUpdate>();

    // 共享骨架：用 Arc<RwLock> 在 GUI 與後端之間共享，減少頻繁 clone
    let shared_skel = Arc::new(RwLock::new(skeleton::model::SkeletonModel::new_humanoid()));

    // 建立反向通道：cmd_tx (GUI) -> cmd_rx (後端)
    let (cmd_tx, cmd_rx) = mpsc::channel::<BackendCommand>();

    // 2. 啟動後端邏輯 (在獨立的 Thread 中執行 Tokio Runtime)
    let backend_shared_skel = shared_skel.clone();
    std::thread::spawn(move || {
        let rt = tokio::runtime::Runtime::new().unwrap();
        rt.block_on(async move {
            info!("Aetherpose 後端系統啟動中...");

            // --- [新增] 權威來源 (Quest) 資料通道 ---
            // watch channel 非常適合用於狀態更新，因為我們只關心最新值。
            let (quest_tx, quest_rx) = watch::channel::<QuestInputData>(QuestInputData {
                head: None,
                left_hand: None,
                right_hand: None,
            });

            // 初始化網路 (取得 Socket)
            let socket = match net::bind_udp_socket(config_backend.osc_port).await {
                Ok(s) => s,
                Err(e) => {
                    error!("Net 初始化失敗: {}", e);
                    return;
                }
            };

            // --- [新增] 權威來源 (Quest) UDP 監聽執行緒 ---
            tokio::spawn(async move {
                // 監聽一個不同的埠號 (例如 9002) 來接收頭戴顯示器的資料
                let quest_socket = match tokio::net::UdpSocket::bind("0.0.0.0:9002").await {
                    Ok(s) => {
                        info!("成功綁定 Quest 監聽埠於 0.0.0.0:9002");
                        s
                    }
                    Err(e) => {
                        error!("無法綁定 Quest 監聽埠 9002: {}", e);
                        return;
                    }
                };
                let mut buf = [0u8; 256];
                loop {
                    if let Ok((len, _addr)) = quest_socket.recv_from(&mut buf).await {
                        // 假設資料格式為 JSON
                        if let Ok(packet) = serde_json::from_slice::<VrBridgePacket>(&buf[..len]) {
                            // 輔助函式：將 VrPoseData 轉為 AuthoritativePose
                            let to_auth_pose = |p: VrPoseData| AuthoritativePose {
                                position: Vector3::new(p.pos[0], p.pos[1], p.pos[2]),
                                rotation: UnitQuaternion::new_normalize(nalgebra::Quaternion::new(
                                    p.rot[3], // w
                                    p.rot[0], // x
                                    p.rot[1], // y
                                    p.rot[2], // z
                                )),
                            };

                            let input_data = QuestInputData {
                                head: packet.head.map(to_auth_pose),
                                left_hand: packet.left_hand.map(to_auth_pose),
                                right_hand: packet.right_hand.map(to_auth_pose),
                            };

                            // 將最新姿態發送到主迴圈。如果接收端已關閉，則迴圈中斷。
                            if quest_tx.send(input_data).is_err() {
                                break;
                            }
                        } else {
                            // 嘗試解析舊格式 (僅為了相容性，可選)
                            // log::warn!("收到無法解析的 Quest 封包");
                        }
                    }
                }
            });

            // 初始化核心模組 (local mutable copy for fast updates)
            let mut skeleton = {
                let s = backend_shared_skel.read().unwrap();
                s.clone()
            };
            let t_pose = skeleton.clone(); // 作為姿態先驗 (Pose Prior)
            let mut fusion = FusionEngine::new();
            let mut ik_solver = IkSolver::new();

            let mut recorder: Option<Recorder> = None;
            // 初始化 OSC Sender
            let mut osc_sender: Option<OscSender> =
                match OscSender::new(&config_backend.osc_ip, config_backend.osc_port).await {
                    Ok(sender) => Some(sender),
                    Err(e) => {
                        error!("OSC 初始化失敗: {}", e);
                        None
                    }
                };
            info!("系統初始化完成，進入後端迴圈。");

            let mut packet_count = 0;
            let mut buf = [0u8; 1024];
            let mut trackers: HashMap<u8, TrackerState> = HashMap::new();
            let mut tick_rate = interval(Duration::from_millis(10));
            let mut tracker_packet_counts: HashMap<u8, u32> = HashMap::new();
            let mut last_tps_update = std::time::Instant::now();
            let _last_rotations: HashMap<u8, nalgebra::UnitQuaternion<f32>> = HashMap::new(); // 用於計算靜止狀態
            // serial manager stop signal (for graceful shutdown)
            let mut serial_stop_tx: Option<tokio::sync::watch::Sender<bool>> = None;
            // shared flag to indicate whether serial manager is running (avoid moving serial_stop_tx into tasks)
            let serial_running_flag = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));

            // 套用設定檔中的參數
            let mut ik_smoothness_weight = config_backend.ik_smoothness;
            let mut prop_leg = config_backend.prop_leg;
            let mut prop_arm = config_backend.prop_arm;
            let mut prop_spine = config_backend.prop_spine;
            let mut mag_calibrating_tracker_id: Option<u8> = None; // 後端追蹤哪個 Tracker 正在校準
            let mut leg_ratio = config_backend.leg_ratio;
            let mut floor_offset = config_backend.floor_offset;

            // [更改] 將設定檔中的參數載入到 FusionEngine
            fusion.drift_correction = config_backend.drift_correction;
            fusion.smoothing_min_cutoff = config_backend.smoothing_min_cutoff;
            fusion.smoothing_beta = config_backend.smoothing_beta;
            fusion.mag_calibrations = config_backend.mag_calibrations.clone();

            skeleton.adjust_proportions(prop_leg, prop_arm, prop_spine);

            // skeleton.set_leg_ratio(leg_ratio); // TODO: 應用初始腿部比例

            for (tid, bid) in &config_backend.tracker_assignments {
                fusion.assigner.set_assignment(*tid, *bid);
            }

            // --- 新增: Serial Port 讀取執行緒 ---
            // 使用 crossbeam bounded channel 提供更低延遲與可量測回壓
            let (serial_tx, serial_rx) = bounded::<(PacketData, ConnectionType)>(256);

            // Backpressure statistics (shared)
            let bp_stats = std::sync::Arc::new(BackpressStats::new());

            // Shared serial status message for UI
            let serial_status_shared = std::sync::Arc::new(std::sync::Mutex::new(None::<String>));

            // [新增] 啟動 BLE 掃描與連線任務（使用管理器 wrapper，自動重啟/背壓統計）
            // 使用與 Serial Port 相同的通道 (serial_tx) 來傳遞數據
            let ble_tx = serial_tx.clone();
            let ble_stats = bp_stats.clone();
            // BLE 狀態共享緩存與轉發到 GUI 的 channel
            let ble_status_shared = std::sync::Arc::new(std::sync::Mutex::new(None::<String>));
            let (ble_status_tx, mut ble_status_rx) = tokio::sync::mpsc::unbounded_channel::<String>();
            {
                let ble_status_shared_clone = ble_status_shared.clone();
                let tx_clone_for_update = tx.clone();
                let serial_running_flag_clone = serial_running_flag.clone();
                tokio::spawn(async move {
                    while let Some(msg) = ble_status_rx.recv().await {
                        if let Ok(mut lock) = ble_status_shared_clone.lock() {
                            *lock = Some(msg.clone());
                        }
                        // append to BLE-specific log with rotation
                        let line = format!("{} [BLE] {}\n", chrono::Local::now().format("%Y-%m-%d %H:%M:%S"), msg);
                        append_and_rotate_log("status_ble.log", &line);

                        let _ = tx_clone_for_update.send(GuiUpdate {
                            packet_count: 0,
                            trackers: HashMap::new(),
                            mag_calibration_points: HashMap::new(),
                            mag_calibrating_tracker_id: None,
                            is_recording: false,
                            recorder_dropped_count: 0,
                            recorder_write_errors: 0,
                            recorder_filename: None,
                            recorder_batch_size: 128,
                            recorder_flush_interval_ms: 500,
                            mag_calibrations: HashMap::new(),
                            leg_ratio: 0.0,
                            floor_offset: 0.0,
                            pending_shake_bone: None,
                            serial_running: serial_running_flag_clone.load(std::sync::atomic::Ordering::Relaxed),
                            serial_status_msg: Some(msg.clone()),
                            
                        });
                    }
                });
            }
            tokio::spawn(async move {
                crate::net::connection::run_ble_manager(ble_tx, ble_stats, Some(ble_status_tx)).await;
            });

            // 若設定啟用 Serial Bridge，則啟動 Serial 管理器（Reconnect/backoff）
            if config_backend.serial_enabled {
                if let Some(port_name) = config_backend.serial_port.clone() {
                    let serial_tx_clone = serial_tx.clone();
                    let serial_stats = bp_stats.clone();
                    let baud = config_backend.serial_baud;
                    // create stop channel for graceful shutdown
                    let (stop_tx, stop_rx) = tokio::sync::watch::channel(false);
                    serial_stop_tx = Some(stop_tx.clone());
                    // mark serial as running
                    serial_running_flag.store(true, std::sync::atomic::Ordering::Relaxed);
                    // create status channel and forward to shared cache
                    let (status_tx, mut status_rx) = tokio::sync::mpsc::unbounded_channel::<String>();
                    {
                        let serial_status_shared_clone = serial_status_shared.clone();
                        let tx_clone_for_update = tx.clone();
                        let serial_running_flag_clone = serial_running_flag.clone();
                        // task to forward status into shared cache
                        tokio::spawn(async move {
                            while let Some(msg) = status_rx.recv().await {
                                if let Ok(mut lock) = serial_status_shared_clone.lock() {
                                    *lock = Some(msg.clone());
                                }
                                        // append to SERIAL-specific log with rotation
                                        let line = format!("{} [SERIAL] {}\n", chrono::Local::now().format("%Y-%m-%d %H:%M:%S"), msg);
                                        append_and_rotate_log("status_serial.log", &line);

                                // also send an immediate lightweight GUI update so UI can refresh
                                let _ = tx_clone_for_update.send(GuiUpdate {
                                    packet_count: 0,
                                    trackers: HashMap::new(),
                                    mag_calibration_points: HashMap::new(),
                                    mag_calibrating_tracker_id: None,
                                    is_recording: false,
                                    recorder_dropped_count: 0,
                                    recorder_write_errors: 0,
                                    recorder_filename: None,
                                    recorder_batch_size: 128,
                                    recorder_flush_interval_ms: 500,
                                    mag_calibrations: HashMap::new(),
                                    leg_ratio: 0.0,
                                    floor_offset: 0.0,
                                    pending_shake_bone: None,
                                    serial_running: serial_running_flag_clone.load(std::sync::atomic::Ordering::Relaxed),
                                    serial_status_msg: Some(msg.clone()),
                                });
                            }
                        });
                    }
                    tokio::spawn(async move {
                        crate::net::connection::run_serial_manager(port_name, baud, serial_tx_clone, serial_stats, stop_rx, Some(status_tx)).await;
                    });
                } else {
                    log::warn!("serial_enabled is true but no serial_port configured");
                }
            }

            // 每秒輸出回壓統計
            let stats_reporter = bp_stats.clone();
            tokio::spawn(async move {
                let mut ticker = tokio::time::interval(Duration::from_secs(1));
                loop {
                    ticker.tick().await;
                    let (s, f, d, sum_ns, cnt) = stats_reporter.snapshot_and_reset();
                    let avg_ms = if cnt > 0 { (sum_ns as f64) / (cnt as f64) / 1_000_000.0 } else { 0.0 };
                    log::info!("Backpress stats (1s): sent={} dropped_full={} disconnected={} avg_try_send_ms={:.6}", s, f, d, avg_ms);
                }
            });

            let mut pending_shake_bone: Option<u8> = None; // 用於搖晃分配的狀態

            // --- [暫時停用] 為了專注於 BLE 無線連線，暫時關閉 Serial Port 自動掃描執行緒 ---
            // --- 這樣可以避免 USB 連線重置 Arduino，導致 BLE 無法穩定連線的問題 ---
            // std::thread::spawn(move || {
            //     loop {
            //         // ... Serial Port 邏輯 ...
            //     }
            // });
            // ------------------------------------

            // This is a placeholder for the real tracker data from the network
            let mut net_trackers: HashMap<u8, crate::net::tracker::Tracker> = HashMap::new();

            // [新增] 複製一份 quest_rx 給主迴圈使用
            let main_quest_rx = quest_rx.clone();

            loop {
                // 1. 嘗試接收 UDP 封包 (非阻塞式)
                let mut received_any = false;
                let mut loop_count = 0;

                // 定義封包處理邏輯 (Closure)，避免 UDP 和 Serial 重複寫兩遍
                let mut process_packet = |data: PacketData, source: ConnectionType| {
                    packet_count += 1;
                    received_any = true;

                    let tracker_state = trackers.entry(data.id).or_insert_with(|| {
                        // This is the first time we see this tracker. Initialize its state.
                        TrackerState {
                            id: data.id,
                            connection_type: source, // [新增]
                            battery: data.batt.unwrap_or(100.0),
                            rssi: -50, // Serial 沒有 RSSI，給個預設值
                            accel: data.accel,
                            last_update: std::time::Instant::now(),
                            assigned_bone: fusion.assigner.get_bone_id(data.id),
                            tps: 0,
                            rotation: data.quat,
                            stationary: false,
                            mag: data.mag,
                            // Initialize packet loss fields
                            last_sequence: data.sequence.unwrap_or(0),
                            received_packets: 0,
                            lost_packets: 0,
                            is_mag_calibrating: false,
                        }
                    });

                    // --- Packet Loss Calculation ---
                    if let Some(new_sequence) = data.sequence {
                        // Only calculate loss if we have a previous sequence number (i.e., not the first packet)
                        if tracker_state.received_packets > 0 {
                            // Handle wrapping (u16). A large difference in the "wrong" direction indicates a wrap-around.
                            let diff = if new_sequence > tracker_state.last_sequence {
                                new_sequence - tracker_state.last_sequence
                            } else if new_sequence < tracker_state.last_sequence
                                && (tracker_state.last_sequence - new_sequence) > (u16::MAX / 2)
                            {
                                // Wrapped around: e.g., from 65530 to 5
                                (u16::MAX - tracker_state.last_sequence) + new_sequence + 1
                            } else {
                                // Out-of-order packet or no change, treat as 1 packet received
                                1
                            };

                            if diff > 1 {
                                tracker_state.lost_packets += (diff - 1) as u64;
                            }
                        }
                        tracker_state.last_sequence = new_sequence;
                    }
                    tracker_state.received_packets += 1;

                    // --- Update rest of the state ---
                    *tracker_packet_counts.entry(data.id).or_insert(0) += 1;
                    tracker_state.connection_type = source; // [新增] 更新連線類型
                    tracker_state.last_update = std::time::Instant::now();
                    if let Some(b) = data.batt {
                        tracker_state.battery = b;
                    }
                    if let Some(a) = data.accel {
                        tracker_state.accel = Some(a);
                    }
                    tracker_state.assigned_bone = fusion.assigner.get_bone_id(data.id);
                    if let Some(m) = data.mag {
                        tracker_state.mag = Some(m);
                    }
                    if let Some(q) = data.quat {
                        tracker_state.rotation = Some(q);
                    }

                    // 計算靜止狀態 (用於 UI 顯示)。使用 FusionEngine 的 ZUPT 偵測器若可用。
                    if let Some(acc) = tracker_state.accel {
                        let is_stat = fusion.is_tracker_stationary(data.id, acc, tracker_state.rotation);
                        tracker_state.stationary = is_stat;
                    } else {
                        tracker_state.stationary = false;
                    }

                    if let Some(active) = fusion.mag_calibration_active.get(&data.id) {
                        tracker_state.is_mag_calibrating = *active;
                    }

                    // --- 搖晃分配偵測 (Shake-to-Assign) ---
                    if let Some(target_bone) = pending_shake_bone {
                        if let Some(acc) = data.accel {
                            let mag = (acc[0].powi(2) + acc[1].powi(2) + acc[2].powi(2)).sqrt();
                            // 閾值設為 25.0 m/s^2 (約 2.5G)，避免誤觸
                            if mag > 25.0 {
                                fusion.assigner.set_assignment(data.id, target_bone);
                                config_backend
                                    .tracker_assignments
                                    .insert(data.id, target_bone);
                                info!("搖晃分配成功: Tracker #{} -> Bone {}", data.id, target_bone);
                                pending_shake_bone = None; // 分配完成，重置狀態
                            }
                        }
                    }

                    let tracker_entry = net_trackers.entry(data.id);
                    tracker_entry
                        .and_modify(|tracker| {
                            tracker.update_data(&data);
                        })
                        .or_insert_with(|| {
                            let mut new_tracker = crate::net::tracker::Tracker::new(data.id);
                            new_tracker.update_data(&data);
                            new_tracker
                        });
                };

                // A. 處理 UDP 封包
                while let Ok((len, _addr)) = socket.try_recv_from(&mut buf) {
                    if loop_count > 50 {
                        break;
                    }
                    loop_count += 1;

                    // --- 從 JSON 協議升級為二進位協議 ---
                    // 舊的 JSON 解析方式 (註解備用):
                    // if let Ok(data) = serde_json::from_slice::<PacketData>(&buf[..len]) {
                    //     process_packet(data);
                    // }

                    // 新的二進位解析方式:
                    if let Some(packet) = net::protocol::FullDataPacket::from_bytes(&buf[..len]) {
                        // 為了重用現有邏輯，將二進位封包轉換為通用的 PacketData 結構
                        let data = PacketData {
                            id: packet.id,
                            sequence: Some(packet.sequence),
                            batt: Some(packet.batt as f32),
                            quat: Some(packet.quat),
                            mag: Some(packet.mag),
                            accel: Some(packet.accel),
                        };
                        process_packet(data, ConnectionType::Udp);
                    }
                }

                // B. 處理 Serial 封包 (新增)
                while let Ok((data, source)) = serial_rx.try_recv() {
                    process_packet(data, source);
                }

                // C. 處理來自 GUI 的指令
                while let Ok(cmd) = cmd_rx.try_recv() {
                    match cmd {
                        BackendCommand::SetIkSmoothness(v) => ik_smoothness_weight = v,
                        BackendCommand::ResetYaw => fusion.reset_yaw(&net_trackers),
                        BackendCommand::SetOscTarget(ip, port) => {
                            osc_sender = match OscSender::new(&ip, port).await {
                                Ok(sender) => Some(sender),
                                Err(e) => {
                                    error!("OSC 目標更新失敗: {}", e);
                                    None
                                }
                            };
                        }
                        BackendCommand::AssignTracker(tid, bid) => {
                            fusion.assigner.set_assignment(tid, bid);
                        }
                        BackendCommand::SetProportions { leg, arm, spine } => {
                            prop_leg = leg;
                            prop_arm = arm;
                            prop_spine = spine;
                            skeleton.adjust_proportions(prop_leg, prop_arm, prop_spine);
                            skeleton.set_leg_ratio(leg_ratio); // 調整整體比例後，需重新應用腿部比例
                        }
                        BackendCommand::ResetMounting => {
                            fusion.reset_mounting(&net_trackers);
                        }
                        BackendCommand::ClearAllCalibration => {
                            fusion.clear_all_calibration();
                        }
                        BackendCommand::SetDriftCorrection(val) => {
                            fusion.drift_correction = val;
                        }
                        BackendCommand::AutoAssign => {
                            fusion.auto_assign(&net_trackers);
                        }
                        BackendCommand::StartMagCalibration(tid) => {
                            fusion.start_mag_calibration(tid);
                            mag_calibrating_tracker_id = Some(tid);
                        }
                        BackendCommand::StopMagCalibration(tid) => fusion.stop_mag_calibration(tid),

                        BackendCommand::StartRecording => {
                            if recorder.is_none() {
                                match Recorder::new(&skeleton) {
                                    Ok(r) => recorder = Some(r), // Fix: Incomplete error handling
                                    Err(e) => {
                                        error!("錄製器初始化失敗: {}", e);
                                    }
                                }
                            }
                        }
                        BackendCommand::StopRecording => {
                            if let Some(_r) = recorder.take() {
                                // r 在這裡被銷毀，檔案會自動關閉
                                info!("已停止錄製");
                            }
                        }
                        BackendCommand::SetRecorderConfig { enabled, filename, batch_size, flush_interval_ms } => {
                            // enabled: Some(true) => start, Some(false) => stop, None => keep current enabled state
                            let want_enable = enabled.unwrap_or_else(|| recorder.is_some());
                            if want_enable {
                                // start or reconfigure
                                if recorder.is_none() {
                                    // create new recorder with provided options or defaults
                                    if filename.is_none() && batch_size.is_none() && flush_interval_ms.is_none() {
                                        match Recorder::new(&skeleton) {
                                            Ok(r) => recorder = Some(r),
                                            Err(e) => error!("錄製器初始化失敗: {}", e),
                                        }
                                    } else {
                                        let fname = filename.unwrap_or_else(|| {
                                            let ts = Local::now().format("%Y-%m-%d_%H-%M-%S").to_string();
                                            format!("recording_{}.csv", ts)
                                        });
                                        let bs = batch_size.unwrap_or(128usize);
                                        let fi = Duration::from_millis(flush_interval_ms.unwrap_or(500));
                                        match Recorder::new_with_options(&skeleton, fname, bs, fi) {
                                            Ok(r) => recorder = Some(r),
                                            Err(e) => error!("錄製器初始化失敗: {}", e),
                                        }
                                    }
                                } else if filename.is_some() || batch_size.is_some() || flush_interval_ms.is_some() {
                                    // reconfigure: recreate with new params
                                    if let Some(old) = recorder.take() {
                                        let old_fname = old.filename.clone();
                                        let fname = filename.unwrap_or(old_fname);
                                        let bs = batch_size.unwrap_or(old.batch_size);
                                        let fi_ms = flush_interval_ms.unwrap_or(old.flush_interval_ms);
                                        let fi = Duration::from_millis(fi_ms);
                                        match Recorder::new_with_options(&skeleton, fname, bs, fi) {
                                            Ok(r) => recorder = Some(r),
                                            Err(e) => {
                                                error!("重新配置錄製器失敗: {}", e);
                                                recorder = Some(old); // restore
                                            }
                                        }
                                    }
                                }
                            } else {
                                // disable recording if active
                                if let Some(_r) = recorder.take() {
                                    info!("已停止錄製 (由設定命令)");
                                }
                            }
                        }
                        BackendCommand::SetSerialConfig { enabled, port, baud } => {
                            if let Some(en) = enabled {
                                config_backend.serial_enabled = en;
                            }
                            if let Some(p) = port {
                                config_backend.serial_port = Some(p.clone());
                            }
                            if let Some(b) = baud {
                                config_backend.serial_baud = b;
                            }
                            config_backend.save();

                            if config_backend.serial_enabled {
                                if let Some(port_name) = config_backend.serial_port.clone() {
                                    let serial_tx_clone = serial_tx.clone();
                                    let serial_stats = bp_stats.clone();
                                    let baud = config_backend.serial_baud;
                                            // create a new stop channel and keep sender so we can stop later
                                            let (stop_tx, stop_rx) = tokio::sync::watch::channel(false);
                                            serial_stop_tx = Some(stop_tx.clone());
                                            // mark serial as running
                                            serial_running_flag.store(true, std::sync::atomic::Ordering::Relaxed);
                                    // create status channel and forward to shared cache
                                    let (status_tx, mut status_rx) = tokio::sync::mpsc::unbounded_channel::<String>();
                                    {
                                        let serial_status_shared_clone = serial_status_shared.clone();
                                        let tx_clone_for_update = tx.clone();
                                        let serial_running_flag_clone = serial_running_flag.clone();
                                        tokio::spawn(async move {
                                            while let Some(msg) = status_rx.recv().await {
                                                if let Ok(mut lock) = serial_status_shared_clone.lock() {
                                                    *lock = Some(msg.clone());
                                                }
                                                // append to debug log file
                                                let _ = std::fs::OpenOptions::new().create(true).append(true).open("status_debug.log").and_then(|mut f| {
                                                    let line = format!("{} [SERIAL] {}\n", chrono::Local::now().format("%Y-%m-%d %H:%M:%S"), msg);
                                                    use std::io::Write as _;
                                                    f.write_all(line.as_bytes())
                                                });

                                                let _ = tx_clone_for_update.send(GuiUpdate {
                                                    packet_count: 0,
                                                    trackers: HashMap::new(),
                                                    mag_calibration_points: HashMap::new(),
                                                    mag_calibrating_tracker_id: None,
                                                    is_recording: false,
                                                    recorder_dropped_count: 0,
                                                    recorder_write_errors: 0,
                                                    recorder_filename: None,
                                                    recorder_batch_size: 128,
                                                    recorder_flush_interval_ms: 500,
                                                    mag_calibrations: HashMap::new(),
                                                    leg_ratio: 0.0,
                                                    floor_offset: 0.0,
                                                    pending_shake_bone: None,
                                                    serial_running: serial_running_flag_clone.load(std::sync::atomic::Ordering::Relaxed),
                                                    serial_status_msg: Some(msg.clone()),
                                    
                                                });
                                            }
                                        });
                                    }
                                    tokio::spawn(async move {
                                        crate::net::connection::run_serial_manager(port_name, baud, serial_tx_clone, serial_stats, stop_rx, Some(status_tx)).await;
                                    });
                                } else {
                                    log::warn!("serial_enabled is true but no serial_port configured");
                                }
                                } else {
                                log::info!("Serial bridge disabled: signalling stop to running manager");
                                // mark serial as not running
                                serial_running_flag.store(false, std::sync::atomic::Ordering::Relaxed);
                                if let Some(stop) = serial_stop_tx.take() {
                                    let _ = stop.send(true);
                                }
                            }
                        }
                        BackendCommand::SetSmoothingParams { min_cutoff, beta } => {
                            fusion.smoothing_min_cutoff = min_cutoff;
                            fusion.smoothing_beta = beta;
                        }
                        BackendCommand::SetZuptParams { window_size, accel_var_threshold, gyro_threshold } => {
                            if let Some(w) = window_size {
                                config_backend.zupt_window_size = w;
                            }
                            if let Some(a) = accel_var_threshold {
                                config_backend.zupt_accel_var_threshold = a;
                            }
                            if let Some(g) = gyro_threshold {
                                config_backend.zupt_gyro_threshold = g;
                            }
                            // apply immediately to fusion engine
                            fusion.set_zupt_params(
                                config_backend.zupt_window_size,
                                config_backend.zupt_accel_var_threshold,
                                config_backend.zupt_gyro_threshold,
                            );
                            config_backend.save();
                        }
                        BackendCommand::StartLegCalibration => {
                            fusion.start_leg_calibration();
                        }
                        BackendCommand::StopLegCalibration => {
                            // 計算當前骨架的總腿長 (大腿 + 小腿)
                            // 10: L.UpLeg, 11: L.Leg, 12: L.Foot
                            // 長度 = (Leg - UpLeg).len + (Foot - Leg).len
                            let mut total_len = 0.9; // 預設值
                            if let (Some(b10), Some(b11), Some(b12)) = (
                                skeleton.bones.get(&10),
                                skeleton.bones.get(&11),
                                skeleton.bones.get(&12),
                            ) {
                                let len_thigh =
                                    (b11.global_position - b10.global_position).magnitude();
                                let len_shin =
                                    (b12.global_position - b11.global_position).magnitude();
                                total_len = len_thigh + len_shin;
                            }

                            if let Some(new_ratio) = fusion.stop_leg_calibration(total_len) {
                                info!("計算出的新腿部比例: {:.3}", new_ratio);
                                leg_ratio = new_ratio;
                                // 應用新比例
                                // 注意：請確保 src/skeleton/model.rs 中已實作 set_leg_ratio
                                skeleton.set_leg_ratio(leg_ratio);
                            }
                        }
                        BackendCommand::SetFloorOffset(val) => {
                            floor_offset = val;
                        }
                        BackendCommand::AutoFloor => {
                            // 自動地板校準：找到雙腳的最低點，將其對齊到 Y=0
                            let mut min_y = f32::MAX;
                            // 12: L.Foot, 22: R.Foot
                            if let Some(bone) = skeleton.bones.get(&12) {
                                min_y = min_y.min(bone.global_position.y);
                            }
                            if let Some(bone) = skeleton.bones.get(&22) {
                                min_y = min_y.min(bone.global_position.y);
                            }

                            if min_y != f32::MAX {
                                // 目標是讓 min_y 變成 0
                                // 目前高度 = 原始高度 + 舊offset
                                // 新offset = 舊offset - 目前最低高度
                                floor_offset -= min_y;
                            }
                        }
                        BackendCommand::StartShakeAssign(bid) => {
                            pending_shake_bone = Some(bid);
                        }
                        BackendCommand::CancelShakeAssign => {
                            pending_shake_bone = None;
                        }
                    }
                }

                // --- [更改] 2. Fusion, IK, 與骨架更新 ---

                // 取得最新的權威姿態 (如果有的話)
                // [修正] 移除 .changed().await，這會導致主迴圈在沒有 Quest 數據時卡死
                // 我們只需要直接 borrow() 取得當前最新值即可，不需要等待更新
                let quest_data = main_quest_rx.borrow();

                let mut ik_goals = fusion.process(
                    &skeleton,
                    &net_trackers,
                    quest_data.head.as_ref(),
                    quest_data.left_hand.as_ref(),
                    quest_data.right_hand.as_ref(),
                );
                ik_goals.push(Goal::PosePrior {
                    pose: t_pose.clone(),
                    weight: 0.02,
                });

                // Add Temporal Smoothness (動態調整權重)
                ik_goals.push(Goal::TemporalSmoothness {
                    weight: ik_smoothness_weight,
                });

                // Finally, run the solver.
                skeleton.update_fk(); // It's often better to run FK before IK
                ik_solver.solve(&mut skeleton, &ik_goals);

                // --- 應用虛擬地板偏移 (Virtual Floor) ---
                for bone in skeleton.bones.values_mut() {
                    bone.global_position.y += floor_offset;
                }

                // 如果正在錄製，則記錄當前幀
                let mut stop_recording_on_error = false;
                if let Some(rec) = &mut recorder {
                    if let Err(e) = rec.record_frame(&skeleton) {
                        error!("錄製幀時發生錯誤，停止錄製: {}", e);
                        stop_recording_on_error = true;
                    }
                }
                if stop_recording_on_error {
                    recorder = None; // 這會銷毀 recorder 並關閉檔案
                }

                // 3. 發送 OSC 數據到 VRChat
                if let Some(sender) = &osc_sender {
                    sender.send_skeleton(&skeleton).await;
                }

                // 3. 定期發送狀態給 GUI (例如每 10ms 發送一次)
                tick_rate.tick().await;

                // 計算 TPS (每秒更新一次)
                if last_tps_update.elapsed() >= Duration::from_secs(1) {
                    for (tid, count) in tracker_packet_counts.iter() {
                        if let Some(t) = trackers.get_mut(tid) {
                            t.tps = *count;
                        }
                    }
                    tracker_packet_counts.clear();
                    last_tps_update = std::time::Instant::now();
                }

                // 優化：只有在有收到新資料時才發送更新，並更新共享骨架，減少 Channel 複製
                if received_any {
                    // 更新共享骨架 (寫鎖)
                    if let Ok(mut shared) = backend_shared_skel.write() {
                        *shared = skeleton.clone();
                    }

                    let (rec_dropped, rec_write_err, rec_fname, rec_bs, rec_fi_ms) = if let Some(r) = &recorder {
                        (
                            r.dropped_count.load(Ordering::Relaxed),
                            r.write_error_count.load(Ordering::Relaxed),
                            Some(r.filename.clone()),
                            r.batch_size,
                            r.flush_interval_ms,
                        )
                    } else {
                        (0u64, 0u64, None, 128usize, 500u64)
                    };

                    let _ = tx.send(GuiUpdate {
                        packet_count,
                        trackers: trackers.clone(),
                        mag_calibration_points: fusion.mag_calibration_points.clone(),
                        mag_calibrating_tracker_id,
                        is_recording: recorder.is_some(),
                        recorder_dropped_count: rec_dropped,
                        recorder_write_errors: rec_write_err,
                        recorder_filename: rec_fname,
                        recorder_batch_size: rec_bs,
                        recorder_flush_interval_ms: rec_fi_ms,
                        mag_calibrations: fusion.mag_calibrations.clone(),
                        leg_ratio, // 回傳給 GUI 更新顯示與儲存
                        floor_offset,
                                pending_shake_bone,
                                serial_running: serial_stop_tx.is_some(),
                                serial_status_msg: serial_status_shared.lock().ok().and_then(|m| m.clone()),
                    });
                }
            }
        });
    });

    // 3. 啟動 GUI 視窗
    let options = eframe::NativeOptions::default();
    eframe::run_native(
        "Aetherpose Control Panel",
        options,
        Box::new(|cc| {
            setup_custom_fonts(&cc.egui_ctx);
            // apply initial style based on default theme variant from config
            let theme = crate::theme::Theme::from_variant(config.theme_variant);
            configure_style(&cc.egui_ctx, &theme);
            // 將接收端 rx 傳入 App
            // 傳入 shared_skel clone 給 GUI
            let gui_shared_skel = shared_skel.clone();
            Ok(Box::new(AetherposeApp::new(
                rx,
                cmd_tx,
                config,
                gui_shared_skel,
            )))
        }),
    )
}

struct AetherposeApp {
    status: String,
    rx: mpsc::Receiver<GuiUpdate>,
    cmd_tx: mpsc::Sender<BackendCommand>, // 新增指令傳送端
    packet_count: u64,
    rotation_yaw: f32,
    rotation_pitch: f32,
    zoom: f32,
    current_tab: Tab, // 新增：當前選中的分頁
    trackers: HashMap<u8, TrackerState>,
    skeleton_data: Option<SkeletonModel>,
    shared_skel: Arc<RwLock<SkeletonModel>>, // 共享骨架引用
    ik_smoothness: f32,                      // GUI 上的暫存值
    show_grid: bool,
    osc_ip: String,
    osc_port: String,
    // Serial UI editable fields
    serial_enabled_edit: bool,
    serial_port_edit: String,
    serial_baud_edit: String,
    prop_leg: f32,
    prop_arm: f32,
    prop_spine: f32,
    fps: f32,          // 新增 FPS 欄位
    config: AppConfig, // 儲存設定檔狀態
    mirror_view: bool,
    drift_correction: f32,
    debug_draw_axes: bool,
    mag_calibration_points: HashMap<u8, Vec<Vector3<f32>>>, // GUI 顯示的點雲
    mag_calibrating_tracker_id: Option<u8>,                 // GUI 顯示哪個 Tracker 正在校準
    is_recording: bool,
    mag_calibrations: HashMap<u8, MagCalibration>, // GUI 儲存的校準數據
    smoothing_min_cutoff: f32,
    smoothing_beta: f32,
    leg_ratio: f32,
    is_leg_calibrating: bool,
    floor_offset: f32,
    pending_shake_bone: Option<u8>, // GUI 顯示用
    // Recorder UI state
    recorder_dropped_count: u64,
    recorder_write_errors: u64,
    recorder_filename: Option<String>,
    recorder_batch_size: usize,
    recorder_flush_interval_ms: u64,
    // editable inputs
    recorder_filename_edit: String,
    recorder_batch_size_edit: String,
    recorder_flush_interval_ms_edit: String,
    // validation & auto-save
    recorder_batch_valid: bool,
    recorder_flush_valid: bool,
    recorder_auto_save: bool,
    // serial runtime state shown in UI
    is_serial_running: bool,
    serial_status_msg: Option<String>,
    // recent serial runtime messages for display
    serial_log: Vec<String>,
    // 0=All,1=Errors only,2=Info only
    serial_log_filter: u8,
    // i18n
    i18n: I18n,
    lang: String,
    // theme variant selection for runtime switching
    theme_variant: crate::theme::ThemeVariant,
    // 可調整側邊欄寬度
    sidebar_width: f32,
    // ZUPT editable inputs
    zupt_window_edit: String,
    zupt_accel_var_edit: String,
    zupt_gyro_edit: String,
}

impl AetherposeApp {
    fn new(
        rx: mpsc::Receiver<GuiUpdate>,
        cmd_tx: mpsc::Sender<BackendCommand>,
        config: AppConfig,
        shared_skel: Arc<RwLock<SkeletonModel>>,
    ) -> Self {
        let default_skel = {
            let s = shared_skel.read().unwrap();
            s.clone()
        };

        let mirror_view = config.mirror_view;

        Self {
            status: "系統運行中 (Backend Running)".to_owned(),
            rx,
            cmd_tx,
            packet_count: 0,
            rotation_yaw: 0.0,
            rotation_pitch: 0.0,
            zoom: 1.0,
            current_tab: Tab::Calibration, // 預設在校準頁面
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
            config: config.clone(), // Clone config to avoid move error
            mirror_view,
            drift_correction: config.drift_correction,
            debug_draw_axes: false,
            mag_calibration_points: HashMap::new(),
            mag_calibrating_tracker_id: None,
            is_recording: false,
            mag_calibrations: config.mag_calibrations.clone(),
            smoothing_min_cutoff: config.smoothing_min_cutoff,
            smoothing_beta: config.smoothing_beta,
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
            // i18n loader (load from ./i18n directory; default to config.ui_lang)
            i18n: {
                let mut t = I18n::load_dir("i18n", &config.ui_lang);
                let _ = t.set_lang(&config.ui_lang);
                t
            },
            lang: config.ui_lang.clone(),
            theme_variant: config.theme_variant,
            sidebar_width: config.sidebar_width,
            serial_status_msg: None,
            zupt_window_edit: config.zupt_window_size.to_string(),
            zupt_accel_var_edit: config.zupt_accel_var_threshold.to_string(),
            zupt_gyro_edit: config.zupt_gyro_threshold.to_string(),
            serial_log: Vec::new(),
            serial_log_filter: 0,
        }
    }
}

impl eframe::App for AetherposeApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // 1. 接收後端傳來的最新資料 (非阻塞)
        // try_iter() 會把通道中累積的所有訊息讀出來，我們只取最後一個或累加
        while let Ok(update) = self.rx.try_recv() {
            self.packet_count = update.packet_count; // 更新封包計數
            self.trackers = update.trackers;

            // 從共享骨架讀取最新值
            if let Ok(s) = self.shared_skel.read() {
                self.skeleton_data = Some(s.clone());
            }

            self.mag_calibration_points = update.mag_calibration_points;
            self.mag_calibrating_tracker_id = update.mag_calibrating_tracker_id;
            self.is_recording = update.is_recording;
            self.recorder_dropped_count = update.recorder_dropped_count;
            self.recorder_write_errors = update.recorder_write_errors;
            self.recorder_filename = update.recorder_filename.clone();
            self.recorder_batch_size = update.recorder_batch_size;
            self.recorder_flush_interval_ms = update.recorder_flush_interval_ms;
            self.mag_calibrations = update.mag_calibrations; // 更新校準數據
            self.leg_ratio = update.leg_ratio;
            self.config.leg_ratio = update.leg_ratio; // 同步到設定檔物件以便儲存
            self.floor_offset = update.floor_offset;
            self.config.floor_offset = update.floor_offset;
            self.pending_shake_bone = update.pending_shake_bone;
            // serial runtime state
            self.is_serial_running = update.serial_running;
            self.serial_status_msg = update.serial_status_msg.clone();
            // append runtime serial status to local log for UI (keep recent 200)
            if let Some(msg) = &self.serial_status_msg {
                let ts = chrono::Local::now().format("%H:%M:%S").to_string();
                self.serial_log.push(format!("{} - {}", ts, msg));
                if self.serial_log.len() > 200 {
                    let excess = self.serial_log.len() - 200;
                    self.serial_log.drain(0..excess);
                }
            }
            // update recorder status from backend
            self.recorder_dropped_count = update.recorder_dropped_count;
            self.recorder_write_errors = update.recorder_write_errors;
            self.recorder_filename = update.recorder_filename.clone();
            self.recorder_batch_size = update.recorder_batch_size;
            self.recorder_flush_interval_ms = update.recorder_flush_interval_ms;
            // keep editable fields in sync when backend provides values
            if self.recorder_filename_edit.is_empty() {
                if let Some(fname) = &self.recorder_filename {
                    self.recorder_filename_edit = fname.clone();
                }
            }
            self.recorder_batch_size_edit = self.recorder_batch_size.to_string();
            self.recorder_flush_interval_ms_edit = self.recorder_flush_interval_ms.to_string();
        }

        // 計算 FPS
        let dt = ctx.input(|i| i.stable_dt);
        if dt > 0.0 {
            self.fps = 1.0 / dt;
        }

        // current theme instance (for runtime switching)
        let theme = crate::theme::Theme::from_variant(self.theme_variant);
        // ensure egui visuals reflect selected theme
        configure_style(ctx, &theme);

        // 同步 Tracker 分配狀態到 config (為了儲存功能)
        for t in self.trackers.values() {
            if let Some(bid) = t.assigned_bone {
                self.config.tracker_assignments.insert(t.id, bid);
            }
        }

        // 讓 GUI 持續刷新 (因為我們需要顯示即時動畫/數據)
        ctx.request_repaint();

        // --- 1. 側邊欄 (導航選單) ---
        egui::SidePanel::left("sidebar_panel")
            .resizable(true)
            .min_width(140.0)
            .default_width(self.sidebar_width)
            .frame(egui::Frame::side_top_panel(&ctx.style()).fill(UI_PANEL_FILL))
            .show(ctx, |ui| {
                ui.add_space(GAP_SM);
                ui.vertical_centered(|ui| {
                    ui.heading(
                        egui::RichText::new(self.i18n.t("app.title"))
                            .strong()
                            .color(UI_ACCENT),
                    );
                    ui.label(
                        egui::RichText::new(self.i18n.t("app.subtitle"))
                            .size(12.0)
                            .weak(),
                    );
                });
                ui.add_space(GAP_SM);
                ui.separator();
                ui.add_space(6.0);
                // 導航按鈕：自定義樣式，以支援 hover 陰影與選中強調
                let mut tab_btn = |label: &str, tab: Tab| {
                    let selected = self.current_tab == tab;
                    let btn_h = BTN_H;
                    let fill = if selected { theme.selection } else { theme.widget_inactive };
                    let stroke = if selected { egui::Stroke::new(1.6, theme.btn_primary) } else { egui::Stroke::new(0.6, theme.stroke_gray) };
                    let resp = ui.add_sized([ui.available_width(), btn_h], egui::Button::new(egui::RichText::new(label).strong().color(if selected { theme.foreground } else { theme.hint_text })).fill(fill).stroke(stroke).rounding(egui::Rounding::same(CORNER_ROUND_MD)));
                    // hover visual: stronger drop shadow + subtle outer glow
                    if resp.hovered() {
                        let shadow_color = egui::Color32::from_rgba_unmultiplied(0, 0, 0, 80);
                        let shadow_rect = resp.rect.translate(egui::vec2(0.0, 4.0));
                        ui.painter().rect_filled(shadow_rect, egui::Rounding::same(CORNER_ROUND_MD), shadow_color);
                        let sel = theme.selection;
                        let glow = egui::Color32::from_rgba_unmultiplied(sel.r(), sel.g(), sel.b(), 28);
                        let glow_rect = resp.rect.expand(6.0);
                        ui.painter().rect_filled(glow_rect, egui::Rounding::same(CORNER_ROUND_MD + 2.0), glow);
                    }
                    if resp.clicked() {
                        self.current_tab = tab;
                    }
                };

                tab_btn(&self.i18n.t("menu.calibration"), Tab::Calibration);
                tab_btn(&self.i18n.t("menu.monitor"), Tab::Monitor);
                tab_btn(&self.i18n.t("menu.body"), Tab::Body);
                tab_btn(&self.i18n.t("menu.system"), Tab::System);

                ui.add_space(6.0);
                ui.separator();

                // 填滿剩餘空間，讓狀態列沉底
                ui.with_layout(egui::Layout::bottom_up(egui::Align::LEFT), |ui| {
                    ui.add_space(GAP_MD);
                    ui.horizontal(|ui| {
                        ui.label(self.i18n.t("status"));
                        ui.label(egui::RichText::new(&self.status).color(theme.status_active));
                    });
                    ui.label(format!("{} {:.1}", self.i18n.t("status.fps_label"), self.fps)); // 顯示 FPS
                    ui.label(format!("{} {}", self.i18n.t("packet_count"), self.packet_count));
                    ui.add_space(GAP_XS);
                    ui.horizontal(|ui| {
                        ui.label(self.i18n.t("theme.label").as_str());
                        ui.horizontal(|ui| {
                            let mut changed = false;
                            // segmented-style buttons (compact + icons)
                            let variants = [
                                (crate::theme::ThemeVariant::Dark, "🌙"),
                                (crate::theme::ThemeVariant::Light, "☀"),
                                (crate::theme::ThemeVariant::Solarized, "🌀"),
                            ];
                            for (v, icon) in variants.iter() {
                                let label = match *v {
                                    crate::theme::ThemeVariant::Dark => format!("{} {}", icon, self.i18n.t("theme.dark")),
                                    crate::theme::ThemeVariant::Light => format!("{} {}", icon, self.i18n.t("theme.light")),
                                    crate::theme::ThemeVariant::Solarized => format!("{} {}", icon, self.i18n.t("theme.solarized")),
                                };
                                let selected = *v == self.theme_variant;
                                let fill = if selected { theme.btn_primary } else { theme.widget_inactive };
                                let resp = ui.add_sized([48.0, BTN_H], egui::Button::new(*icon).fill(fill).rounding(egui::Rounding::same(CORNER_ROUND_MD))).on_hover_text(label);
                                if resp.clicked() {
                                    self.theme_variant = *v;
                                    changed = true;
                                }
                            }

                            ui.add_space(GAP_XS);

                            // preview panel: window / panel / canvas swatches
                            ui.vertical(|ui| {
                                ui.horizontal(|ui| {
                                    let _ = ui.add_sized([24.0, 12.0], egui::Button::new(" ").fill(theme.window_fill).stroke(egui::Stroke::new(STROKE_W, theme.border)));
                                    let _ = ui.add_sized([24.0, 12.0], egui::Button::new(" ").fill(theme.panel_fill).stroke(egui::Stroke::new(STROKE_W, theme.border)));
                                    let _ = ui.add_sized([24.0, 12.0], egui::Button::new(" ").fill(theme.canvas_fill).stroke(egui::Stroke::new(STROKE_W, theme.border)));
                                });
                                ui.label(egui::RichText::new(self.i18n.t("theme.preview_hint")).size(10.0).weak());
                            });

                            if changed {
                                self.config.theme_variant = self.theme_variant;
                                self.config.save();
                                configure_style(ctx, &crate::theme::Theme::from_variant(self.theme_variant));
                                ctx.request_repaint();
                            }
                            ui.add_space(GAP_SM);
                            // Theme actions: smaller icon buttons with hover tooltip
                            if ui.add(egui::Button::new(ui_icons::ICON_EXPORT).small()).on_hover_text(self.i18n.t("theme.export")).clicked() {
                                let theme_inst = crate::theme::Theme::from_variant(self.theme_variant);
                                if let Err(e) = theme_inst.export_to_file("theme_custom.json") {
                                    error!("匯出主題失敗: {}", e);
                                }
                            }
                            if ui.add(egui::Button::new(ui_icons::ICON_IMPORT).small()).on_hover_text(self.i18n.t("theme.import")).clicked() {
                                match crate::theme::Theme::import_from_file("theme_custom.json") {
                                    Ok(t) => {
                                        // apply imported theme
                                        configure_style(ctx, &t);
                                        // persist by assigning to Solarized as a marker
                                        self.theme_variant = crate::theme::ThemeVariant::Solarized;
                                        self.config.theme_variant = self.theme_variant;
                                        self.config.save();
                                    }
                                    Err(e) => {
                                        error!("匯入主題失敗: {}", e);
                                    }
                                }
                            }

                            if ui.add(egui::Button::new(ui_icons::ICON_RELOAD).small()).on_hover_text(self.i18n.t("theme.reset")).clicked() {
                                self.theme_variant = crate::theme::ThemeVariant::Dark;
                                self.config.theme_variant = self.theme_variant;
                                self.config.save();
                                configure_style(ctx, &crate::theme::Theme::from_variant(self.theme_variant));
                            }
                        });
                    });
                    ui.separator();

                    // 更新實際側欄寬度以保持使用者調整結果（避免每帧被重置）
                    let actual_w = ui.min_rect().width();
                    if (actual_w - self.sidebar_width).abs() > 0.5 {
                        self.sidebar_width = actual_w.clamp(140.0, 900.0);
                    }
                });
            });

        // --- 2. 主畫面 (根據分頁顯示內容) ---
        egui::CentralPanel::default().show(ctx, |ui| {
            // 統一標題樣式
            ui.add_space(GAP_SM);

            match self.current_tab {
                Tab::Calibration => {
                    ui.horizontal(|ui| {
                        ui.heading(self.i18n.t("skeleton.preview"));
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            // compact icon button for reset view
                            if ui.add(egui::Button::new(ui_icons::ICON_RELOAD).small()).on_hover_text(self.i18n.t("calibration.reset_view")).clicked() {
                                self.rotation_yaw = 0.0;
                                self.rotation_pitch = 0.0;
                                self.zoom = 1.0;
                            }
                            ui.checkbox(&mut self.show_grid, &self.i18n.t("calibration.show_grid"));
                            if ui.checkbox(&mut self.mirror_view, &self.i18n.t("calibration.mirror_mode")).changed() {
                                self.config.mirror_view = self.mirror_view;
                            }
                            ui.checkbox(&mut self.debug_draw_axes, &self.i18n.t("calibration.debug_axes"));
                        });
                    });
                    ui.separator();

                    // 校準按鈕區 (使用 Grid 排版更整齊)
                    ui.horizontal(|ui| {
                        let btn_size = egui::vec2(BTN_W, BTN_H);
                        if ui
                            .add_sized(btn_size, egui::Button::new(ui_icons::ICON_RELOAD))
                            .on_hover_text(self.i18n.t("calibration.reset_yaw"))
                            .clicked()
                        {
                            info!("Reset Yaw Clicked");
                            let _ = self.cmd_tx.send(BackendCommand::ResetYaw);
                        }
                        if ui
                            .add_sized(btn_size, egui::Button::new(ui_icons::ICON_APPLY))
                            .on_hover_text(self.i18n.t("calibration.full"))
                            .clicked()
                        {
                            info!("Full Calib Clicked");
                        }
                        if ui
                            .add_sized(btn_size, egui::Button::new(ui_icons::ICON_CANCEL))
                            .on_hover_text(self.i18n.t("calibration.reset_mount"))
                            .clicked()
                        {
                            info!("Reset Mounting Clicked");
                            let _ = self.cmd_tx.send(BackendCommand::ResetMounting);
                        }
                    });

                    ui.add_space(GAP_SM);

                    // 骨架預覽區 (加強視覺區隔)
                    egui::Frame::canvas(ui.style())
                        .fill(theme.canvas_fill)
                        .rounding(CORNER_ROUND_MD)
                        .stroke(egui::Stroke::new(STROKE_W, theme.stroke_gray))
                        .show(ui, |ui| {
                            let (response, painter) =
                                ui.allocate_painter(ui.available_size(), egui::Sense::drag());

                            // 繪製提示文字
                                painter.text(
                                response.rect.min + egui::vec2(GAP_SM, GAP_SM),
                                egui::Align2::LEFT_TOP,
                                &self.i18n.t("preview.controls_hint"),
                                egui::FontId::proportional(12.0),
                                theme.hint_text,
                            );

                            if response.dragged() {
                                self.rotation_yaw += response.drag_delta().x * 0.01;
                                self.rotation_pitch += response.drag_delta().y * 0.01;
                                self.rotation_pitch = self.rotation_pitch.clamp(-1.57, 1.57);
                            }

                            if response.hovered() {
                                ctx.input(|i| {
                                    let scroll = i.raw_scroll_delta.y;
                                    if scroll != 0.0 {
                                        let factor = if scroll > 0.0 { 1.1 } else { 0.9 };
                                        self.zoom = (self.zoom * factor).clamp(0.5, 3.0);
                                    }
                                });
                            }

                            if let Some(skel) = &self.skeleton_data {
                                let draw_ctx = DrawCtx {
                                    painter: &painter,
                                    rect: response.rect,
                                    yaw: self.rotation_yaw,
                                    pitch: self.rotation_pitch,
                                    zoom: self.zoom,
                                    th: &theme,
                                };

                                draw_skeleton(
                                    &draw_ctx,
                                    skel,
                                    self.show_grid,
                                    self.mirror_view,
                                    &self.trackers,
                                    self.debug_draw_axes,
                                );
                            }
                        });
                }
                Tab::Monitor => {
                    ui.heading(self.i18n.t("connected_trackers"));
                    ui.separator();

                    // 新增自動分配按鈕
                    if ui_icons::icon_button(ui, "⚡", &self.i18n.t("monitor.auto_assign")).clicked() {
                        let _ = self.cmd_tx.send(BackendCommand::AutoAssign);
                    }

                    egui::ScrollArea::vertical().show(ui, |ui| {
                        egui::Grid::new("trackers_grid")
                            .striped(true)
                            .spacing(egui::vec2(GAP_MD, GAP_SM))
                            .min_col_width(80.0)
                            .show(ui, |ui| {
                                // 表頭
                                ui.style_mut().override_text_style = Some(egui::TextStyle::Heading);
                                ui.strong(self.i18n.t("monitor.header.id"));
                                ui.strong(self.i18n.t("monitor.header.bone"));
                                ui.strong(self.i18n.t("monitor.header.status"));
                                ui.strong(self.i18n.t("monitor.header.connection")); // [新增]
                                ui.strong(self.i18n.t("monitor.header.battery"));
                                ui.strong(self.i18n.t("monitor.header.stationary")); // 新增欄位
                                ui.strong(self.i18n.t("monitor.header.tps"));
                                ui.strong(self.i18n.t("monitor.header.loss"));
                                ui.strong(self.i18n.t("monitor.header.signal"));
                                ui.strong(self.i18n.t("monitor.header.accel"));
                                ui.strong(self.i18n.t("monitor.header.assign"));
                                ui.end_row();
                                ui.reset_style();

                                let mut tracker_list: Vec<_> = self.trackers.values().collect();
                                tracker_list.sort_by_key(|t| t.id);

                                for t in tracker_list {
                                    ui.label(egui::RichText::new(format!("#{}", t.id)).strong());
                                    // ui.label("Generic"); // 移除舊的

                                    let is_active = t.last_update.elapsed().as_secs() < 2;
                                    if is_active {
                                        ui.add(egui::Label::new(
                                            egui::RichText::new(self.i18n.t("tracker.status.active")).color(UI_STATUS_ACTIVE),
                                        ));
                                    } else {
                                        ui.add(egui::Label::new(
                                            egui::RichText::new(self.i18n.t("tracker.status.timeout")).color(UI_STATUS_TIMEOUT),
                                        ));
                                    }

                                    // [新增] 連線方式：顯示彩色圓點與文字
                                    let (conn_text, conn_color) = match t.connection_type {
                                        ConnectionType::Serial => (self.i18n.t("tracker.connection.serial"), Color32::from_rgb(0, 122, 204)),
                                        ConnectionType::Ble => (self.i18n.t("tracker.connection.ble"), Color32::from_rgb(0, 180, 0)),
                                        ConnectionType::Udp => (self.i18n.t("tracker.connection.udp"), Color32::from_rgb(255, 140, 0)),
                                        ConnectionType::Unknown => ("❓".to_string(), Color32::from_gray(150)),
                                    };
                                    ui.label(egui::RichText::new(format!("● {}", conn_text)).color(conn_color));
                                    // 電量條
                                    ui_battery_bar(ui, t.battery, &theme);

                                    // 靜止/移動狀態指示：綠點=靜止，黃點=移動
                                    if t.stationary {
                                        ui.label(egui::RichText::new(format!("● {}", self.i18n.t("status.stationary"))).color(Color32::from_rgb(0, 200, 0)));
                                    } else {
                                        ui.label(egui::RichText::new(format!("● {}", self.i18n.t("status.moving"))).color(Color32::from_rgb(220, 180, 0)));
                                    }

                                    // TPS
                                    ui.label(format!("{} Hz", t.tps));

                                    // 掉包率
                                    let total_packets = t.received_packets + t.lost_packets;
                                    let loss_rate = if total_packets > 0 {
                                        t.lost_packets as f32 / total_packets as f32 * 100.0
                                    } else {
                                        0.0
                                    };
                                        let loss_color = if loss_rate > 2.0 {
                                        UI_LOSS_HIGH
                                    } else if loss_rate > 0.5 {
                                        UI_LOSS_MED
                                    } else {
                                        UI_LOSS_LOW
                                    };
                                    ui.label(
                                        egui::RichText::new(format!("{:.1}%", loss_rate))
                                            .color(loss_color),
                                    );

                                    ui.label(format!("{} dBm", t.rssi));

                                    if let Some(accel) = t.accel {
                                        ui.label(
                                            egui::RichText::new(format!(
                                                "[{:.1}, {:.1}, {:.1}]",
                                                accel[0], accel[1], accel[2]
                                            ))
                                            .size(10.0),
                                        );
                                    } else {
                                        ui.label(self.i18n.t("monitor.empty"));
                                    }

                                    // 下拉選單 (ComboBox) 選擇部位
                                    let current_bone = t.assigned_bone.unwrap_or(0);
                                    egui::ComboBox::from_id_salt(t.id)
                                            .selected_text(if current_bone == 0 {
                                                self.i18n.t("tracker.unassigned")
                                            } else {
                                                bone_name(&self.i18n, current_bone)
                                            })
                                        .show_ui(ui, |ui| {
                                            // 定義可選的部位列表
                                            let options = [
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

                                            for (bid, name_key) in options {
                                                let label = self.i18n.t(name_key);
                                                if ui
                                                    .selectable_value(
                                                        &mut (current_bone.clone()),
                                                        bid,
                                                        label,
                                                    )
                                                    .clicked()
                                                {
                                                    let _ = self.cmd_tx.send(
                                                        BackendCommand::AssignTracker(t.id, bid),
                                                    );
                                                    // 更新設定檔並儲存
                                                    self.config
                                                        .tracker_assignments
                                                        .insert(t.id, bid);
                                                }
                                            }
                                        });

                                    ui.end_row();
                                }

                                if self.trackers.is_empty() {
                                    ui.label(self.i18n.t("monitor.empty"));
                                    ui.label(self.i18n.t("monitor.empty"));
                                    ui.label(&self.i18n.t("monitor.waiting_connection"));
                                    ui.label(self.i18n.t("monitor.empty"));
                                    ui.label(self.i18n.t("monitor.empty"));
                                    ui.label(self.i18n.t("monitor.empty"));
                                    ui.label(self.i18n.t("monitor.empty"));
                                    ui.label(self.i18n.t("monitor.empty"));
                                    ui.label(self.i18n.t("monitor.empty"));
                                    ui.end_row();
                                    ui.label(self.i18n.t("monitor.empty"));
                                    ui.label(self.i18n.t("monitor.empty"));
                                    ui.end_row();
                                }
                            });
                    });

                    ui.add_space(GAP_MD);
                    ui.heading(self.i18n.t("shake_assign"));
                    ui.label(self.i18n.t("shake_assign.instruction"));
                    ui.separator();

                    egui::Grid::new("shake_assign_grid")
                        .spacing(egui::vec2(GAP_SM, GAP_SM))
                        .show(ui, |ui| {
                            let assign_targets = [
                                (12, "左腳 (L.Foot)"),
                                (22, "右腳 (R.Foot)"),
                                (2, "胸部 (Chest)"),
                                (0, "臀部 (Hip)"),
                                (11, "左膝 (L.Knee)"),
                                (21, "右膝 (R.Knee)"),
                                (32, "左肘 (L.Elbow)"),
                                (42, "右肘 (R.Elbow)"),
                            ];

                            for (i, (bid, name)) in assign_targets.iter().enumerate() {
                                ui.label(*name);

                                let is_waiting = self.pending_shake_bone == Some(*bid);
                                let btn_text = if is_waiting {
                                    &self.i18n.t("shake_assign.waiting")
                                } else {
                                    &self.i18n.t("shake_assign.assign_button")
                                };

                                let icon = if is_waiting { "⏳" } else { "🎯" };
                                if ui_icons::icon_button(ui, icon, btn_text).clicked() {
                                    if is_waiting {
                                        let _ = self.cmd_tx.send(BackendCommand::CancelShakeAssign);
                                    } else {
                                        let _ = self
                                            .cmd_tx
                                            .send(BackendCommand::StartShakeAssign(*bid));
                                    }
                                }

                                if (i + 1) % 2 == 0 {
                                    ui.end_row();
                                }
                            }
                        });
                }
                Tab::Body => {
                    ui.heading(self.i18n.t("body_motion"));
                    ui.separator();

                    ui.group(|ui| {
                        ui.label(egui::RichText::new(self.i18n.t("body.proportions.title")).strong());
                        ui.label(
                            egui::RichText::new(self.i18n.t("body.proportions.description"))
                                .size(12.0)
                                .weak(),
                        );
                        ui.add_space(GAP_XS);

                        if ui
                                .add(
                                egui::Slider::new(&mut self.ik_smoothness, 0.0..=1.0)
                                    .text(self.i18n.t("body.ik_smoothness")),
                            )
                            .changed()
                        {
                            let _ = self
                                .cmd_tx
                                .send(BackendCommand::SetIkSmoothness(self.ik_smoothness));
                        }

                        let mut changed = false;
                        changed |= ui
                            .add(
                                egui::Slider::new(&mut self.prop_leg, 0.5..=1.5)
                                    .text(self.i18n.t("body.prop.legs")),
                            )
                            .changed();
                        changed |= ui
                            .add(
                                egui::Slider::new(&mut self.prop_arm, 0.5..=1.5)
                                    .text(self.i18n.t("body.prop.arms")),
                            )
                            .changed();
                        changed |= ui
                            .add(
                                egui::Slider::new(&mut self.prop_spine, 0.5..=1.5)
                                    .text(self.i18n.t("body.prop.spine")),
                            )
                            .changed();

                        if changed {
                            self.config.prop_leg = self.prop_leg;
                            self.config.prop_arm = self.prop_arm;
                            self.config.prop_spine = self.prop_spine;

                            let _ = self.cmd_tx.send(BackendCommand::SetProportions {
                                leg: self.prop_leg,
                                arm: self.prop_arm,
                                spine: self.prop_spine,
                            });
                        }
                    });

                    ui.add_space(GAP_SM);

                    ui.group(|ui| {
                        ui.label(egui::RichText::new(self.i18n.t("one_euro")).strong());
                        let mut changed = false;
                        changed |= ui
                            .add(
                                egui::Slider::new(&mut self.smoothing_min_cutoff, 0.01..=5.0)
                                    .text(self.i18n.t("body.smoothing.min_cutoff")),
                            )
                            .changed();
                        ui.label(
                            egui::RichText::new(self.i18n.t("body.smoothing.min_cutoff_tip"))
                                .size(10.0)
                                .weak(),
                        );

                        changed |= ui
                            .add(
                                egui::Slider::new(&mut self.smoothing_beta, 0.0..=2.0)
                                    .text(self.i18n.t("body.smoothing.beta")),
                            )
                            .changed();
                        ui.label(
                            egui::RichText::new(self.i18n.t("body.smoothing.beta_tip"))
                                .size(10.0)
                                .weak(),
                        );

                        if changed {
                            self.config.smoothing_min_cutoff = self.smoothing_min_cutoff;
                            self.config.smoothing_beta = self.smoothing_beta;
                            let _ = self.cmd_tx.send(BackendCommand::SetSmoothingParams {
                                min_cutoff: self.smoothing_min_cutoff,
                                beta: self.smoothing_beta,
                            });
                        }
                    });

                    ui.add_space(GAP_SM);

                    ui.group(|ui| {
                        ui.label(egui::RichText::new(self.i18n.t("body.auto_skeleton.title")).strong());
                        ui.label(
                            egui::RichText::new(self.i18n.t("body.auto_skeleton.description"))
                                .size(12.0)
                                .weak(),
                        );

                        ui.horizontal(|ui| {
                            ui.label(format!("{} {:.3}", self.i18n.t("body.auto_skeleton.current_ratio_label"), self.leg_ratio));
                        });

                        if self.is_leg_calibrating {
                            ui.label(
                                    egui::RichText::new(self.i18n.t("body.auto_skeleton.calibrating")).color(UI_STATUS_STATIONARY),
                            );
                            if ui_icons::icon_button(ui, ui_icons::ICON_CHECK, &self.i18n.t("body.auto_skeleton.finish")).clicked() {
                                let _ = self.cmd_tx.send(BackendCommand::StopLegCalibration);
                                self.is_leg_calibrating = false;
                            }
                        } else if ui_icons::icon_button(ui, ui_icons::ICON_PLAY, &self.i18n.t("body.auto_skeleton.start")).clicked() {
                            let _ = self.cmd_tx.send(BackendCommand::StartLegCalibration);
                            self.is_leg_calibrating = true;
                        }
                    });

                    ui.add_space(GAP_SM);

                    ui.group(|ui| {
                        ui.label(egui::RichText::new(self.i18n.t("virtual_floor")).strong());
                        ui.label(
                            egui::RichText::new(self.i18n.t("body.virtual_floor.description"))
                                .size(12.0)
                                .weak(),
                        );

                        ui.horizontal(|ui| {
                            if ui
                                .add(
                                    egui::Slider::new(&mut self.floor_offset, -2.0..=2.0)
                                        .text(self.i18n.t("body.virtual_floor.offset")),
                                )
                                .changed()
                            {
                                let _ = self
                                    .cmd_tx
                                    .send(BackendCommand::SetFloorOffset(self.floor_offset));
                            }
                            if ui_icons::icon_button(ui, ui_icons::ICON_CHECK, &self.i18n.t("body.virtual_floor.auto")).clicked() {
                                let _ = self.cmd_tx.send(BackendCommand::AutoFloor);
                            }
                        });
                    });

                    ui.add_space(GAP_SM);

                    ui.group(|ui| {
                        ui.label(egui::RichText::new(self.i18n.t("drift_comp")).strong());
                        if ui
                            .add(
                                egui::Slider::new(&mut self.drift_correction, 0.0..=1.0)
                                    .text(self.i18n.t("body.drift_comp.strength")),
                            )
                            .changed()
                        {
                            self.config.drift_correction = self.drift_correction;
                            let _ = self
                                .cmd_tx
                                .send(BackendCommand::SetDriftCorrection(self.drift_correction));
                        }
                    });

                    ui.add_space(GAP_SM);
                    ui.group(|ui| {
                            ui.label(
                                egui::RichText::new(self.i18n.t("mag_calib")).strong(),
                            );
                            ui.label(
                                egui::RichText::new(self.i18n.t("body.mag_calib.description"))
                                .size(12.0)
                                .weak(),
                            );
                        ui.add_space(GAP_XS);

                        let mut selected_tracker_id = self.mag_calibrating_tracker_id.unwrap_or(0);
                        let mut tracker_options: Vec<u8> = self.trackers.keys().copied().collect();
                        tracker_options.sort();

                        ui.horizontal(|ui| {
                            ui.label(self.i18n.t("body.mag_calib.select_tracker"));
                            egui::ComboBox::from_id_salt("mag_calib_tracker_select")
                                .selected_text(format!("#{}", selected_tracker_id))
                                .show_ui(ui, |ui| {
                                    for &tid in &tracker_options {
                                        ui.selectable_value(
                                            &mut selected_tracker_id,
                                            tid,
                                            format!("#{}", tid),
                                        );
                                    }
                                });

                            let is_calibrating_this_tracker =
                                self.mag_calibrating_tracker_id == Some(selected_tracker_id);

                            if ui.add_enabled(!is_calibrating_this_tracker, egui::Button::new(ui_icons::ICON_PLAY)).on_hover_text(self.i18n.t("body.mag_calib.start")).clicked() {
                                let _ = self.cmd_tx.send(BackendCommand::StartMagCalibration(selected_tracker_id));
                            }
                            if ui.add_enabled(is_calibrating_this_tracker, egui::Button::new(ui_icons::ICON_STOP)).on_hover_text(self.i18n.t("body.mag_calib.stop")).clicked() {
                                let _ = self.cmd_tx.send(BackendCommand::StopMagCalibration(selected_tracker_id));
                            }

                            // 顯示目前校準參數
                            if let Some(_calib) = self.mag_calibrations.get(&selected_tracker_id) {
                                ui.label(egui::RichText::new(self.i18n.t("body.mag_calib.calibrated")).color(UI_STATUS_ACTIVE));
                            }
                        });

                        if let Some(tid) = self.mag_calibrating_tracker_id {
                            if let Some(points) = self.mag_calibration_points.get(&tid) {
                                ui.label(format!("{} {}", self.i18n.t("body.mag_calib.points_collected_label"), points.len()));
                            }
                        }

                        // 磁力計點雲視覺化區域
                        egui::Frame::canvas(ui.style())
                            .fill(theme.canvas_fill)
                            .rounding(CORNER_ROUND_MD)
                            .stroke(egui::Stroke::new(STROKE_W, theme.stroke_gray))
                            .show(ui, |ui| {
                                let (response, painter) =
                                    ui.allocate_painter(ui.available_size(), egui::Sense::drag());

                                // 繪製提示文字
                                painter.text(
                                    response.rect.min + egui::vec2(GAP_SM, GAP_SM),
                                    egui::Align2::LEFT_TOP,
                                    &self.i18n.t("preview.controls_hint"),
                                    egui::FontId::proportional(12.0),
                                    UI_HINT_TEXT,
                                );

                                // 這裡可以重用 draw_skeleton 的視角控制
                                // 但為了簡潔，我們為磁力計點雲使用獨立的視角控制
                                // 或者直接使用 draw_skeleton 的視角參數
                                let draw_ctx = DrawCtx {
                                    painter: &painter,
                                    rect: response.rect,
                                    yaw: self.rotation_yaw,
                                    pitch: self.rotation_pitch,
                                    zoom: self.zoom,
                                    th: &theme,
                                };

                                draw_magnetometer_points(
                                    &draw_ctx,
                                    &self.mag_calibration_points,
                                    self.mag_calibrating_tracker_id,
                                    self.mag_calibrations.get(&selected_tracker_id),
                                );
                            });
                    });
                }
                Tab::System => {
                    ui.heading(self.i18n.t("system_output"));
                    ui.separator();

                    ui.group(|ui| {
                        ui.label(egui::RichText::new(self.i18n.t("network_settings")).strong());
                        ui.add_space(GAP_XS);
                        egui::Grid::new("settings_net_grid")
                            .spacing(egui::vec2(GAP_SM, GAP_SM))
                            .show(ui, |ui| {
                                ui.label(self.i18n.t("network.udp_port"));
                                ui.label(self.i18n.t("system.default_udp_port"));
                                ui.end_row();

                                ui.label(self.i18n.t("system.osc_target"));
                                ui.horizontal(|ui| {
                                    ui.text_edit_singleline(&mut self.osc_ip);
                                    ui.label(self.i18n.t("separator.colon"));
                                    ui.text_edit_singleline(&mut self.osc_port);
                                });
                                ui.end_row();
                            });
                        if ui_icons::icon_button(ui, ui_icons::ICON_APPLY, &self.i18n.t("apply_network")).clicked() {
                            if let Ok(port) = self.osc_port.parse::<u16>() {
                                let _ = self
                                    .cmd_tx
                                    .send(BackendCommand::SetOscTarget(self.osc_ip.clone(), port));
                                self.config.osc_ip = self.osc_ip.clone();
                                self.config.osc_port = port;
                            }
                        }
                        // Serial bridge settings (UI only; apply sends command to backend)
                        ui.add_space(GAP_SM);
                        ui.label(egui::RichText::new(self.i18n.t("serial.section")).strong());
                        ui.add_space(GAP_XS);
                        egui::Grid::new("settings_serial_grid").spacing(egui::vec2(GAP_SM, GAP_SM)).show(ui, |ui| {
                            ui.label(self.i18n.t("serial.enabled"));
                            ui.checkbox(&mut self.serial_enabled_edit, "");
                            ui.end_row();

                            ui.label(self.i18n.t("serial.port"));
                            ui.horizontal(|ui| {
                                let _ = ui.add(egui::TextEdit::singleline(&mut self.serial_port_edit).desired_width(260.0));
                            });
                            ui.end_row();

                            ui.label(self.i18n.t("serial.baud"));
                            ui.horizontal(|ui| {
                                let _ = ui.add(egui::TextEdit::singleline(&mut self.serial_baud_edit).desired_width(120.0));
                            });
                            ui.end_row();
                        });
                        if ui_icons::icon_button(ui, ui_icons::ICON_APPLY, &self.i18n.t("apply_serial")).clicked() {
                            let baud_opt = self.serial_baud_edit.trim().parse::<u32>().ok();
                            let _ = self.cmd_tx.send(BackendCommand::SetSerialConfig {
                                enabled: Some(self.serial_enabled_edit),
                                port: if self.serial_port_edit.trim().is_empty() { None } else { Some(self.serial_port_edit.clone()) },
                                baud: baud_opt,
                            });
                            // persist locally
                            self.config.serial_enabled = self.serial_enabled_edit;
                            self.config.serial_port = if self.serial_port_edit.trim().is_empty() { None } else { Some(self.serial_port_edit.clone()) };
                            if let Some(b) = baud_opt { self.config.serial_baud = b; }
                            self.config.save();
                        }
                        // show serial runtime status
                        ui.horizontal(|ui| {
                            let status_text = if self.is_serial_running {
                                self.i18n.t("serial.status_running")
                            } else if self.config.serial_enabled {
                                self.i18n.t("serial.status_starting")
                            } else {
                                self.i18n.t("serial.status_disabled")
                            };
                            let color = if self.is_serial_running { UI_STATUS_ACTIVE } else { UI_STATUS_TIMEOUT };
                            ui.label(egui::RichText::new(status_text).color(color));
                            if let Some(msg) = &self.serial_status_msg {
                                ui.label(egui::RichText::new(format!(" ({})", msg)).color(Color32::LIGHT_GRAY));
                            }
                        });
                        ui.add_space(GAP_XS);
                        ui.horizontal(|ui| {
                            if ui_icons::icon_button(ui, ui_icons::ICON_PLAY, &self.i18n.t("serial.start")).clicked() {
                                let baud_opt = self.serial_baud_edit.trim().parse::<u32>().ok();
                                let _ = self.cmd_tx.send(BackendCommand::SetSerialConfig {
                                    enabled: Some(true),
                                    port: if self.serial_port_edit.trim().is_empty() { None } else { Some(self.serial_port_edit.clone()) },
                                    baud: baud_opt,
                                });
                            }
                            if ui_icons::icon_button(ui, ui_icons::ICON_STOP, &self.i18n.t("serial.stop")).clicked() {
                                let _ = self.cmd_tx.send(BackendCommand::SetSerialConfig { enabled: Some(false), port: None, baud: None });
                            }
                        });

                        ui.add_space(GAP_SM);
                        ui.label(egui::RichText::new(self.i18n.t("serial.log_title")).strong());
                        ui.horizontal(|ui| {
                            ui.label(self.i18n.t("serial.filter_label"));
                            egui::ComboBox::from_label("")
                                .selected_text(match self.serial_log_filter {
                                    0 => self.i18n.t("serial.filter_all"),
                                    1 => self.i18n.t("serial.filter_errors"),
                                    2 => self.i18n.t("serial.filter_info"),
                                    _ => self.i18n.t("serial.filter_all"),
                                })
                                .show_ui(ui, |ui| {
                                    if ui.selectable_label(self.serial_log_filter == 0, self.i18n.t("serial.filter_all")).clicked() { self.serial_log_filter = 0; }
                                    if ui.selectable_label(self.serial_log_filter == 1, self.i18n.t("serial.filter_errors")).clicked() { self.serial_log_filter = 1; }
                                    if ui.selectable_label(self.serial_log_filter == 2, self.i18n.t("serial.filter_info")).clicked() { self.serial_log_filter = 2; }
                                });
                            if ui_icons::icon_button(ui, ui_icons::ICON_CLEAR, &self.i18n.t("serial.clear_log")).clicked() {
                                self.serial_log.clear();
                            }
                        });
                        egui::ScrollArea::vertical().max_height(160.0).show(ui, |ui| {
                            let is_err = |s: &str| {
                                let sl = s.to_lowercase();
                                sl.contains("error") || sl.contains("failed") || sl.contains("disconnect") || sl.contains("err")
                            };
                            for line in self.serial_log.iter().rev().filter(|l| match self.serial_log_filter {
                                0 => true,
                                1 => is_err(l),
                                2 => !is_err(l),
                                _ => true,
                            }) {
                                ui.label(egui::RichText::new(line).monospace().size(12.0));
                            }
                        });
                        ui.horizontal(|ui| {
                            if ui_icons::icon_button(ui, ui_icons::ICON_EXPORT, &self.i18n.t("serial.export_serial_log")).clicked() {
                                let src = "status_serial.log";
                                if let Ok(data) = std::fs::read(src) {
                                    let fname = format!("serial_export_{}.log", chrono::Local::now().format("%Y%m%d_%H%M%S"));
                                    if let Ok(_) = std::fs::write(&fname, data) {
                                        let _ = std::fs::canonicalize(&fname).map(|p| {
                                            let pstr = p.to_string_lossy().to_string();
                                            let _ = Command::new("explorer").arg("/select,").arg(&pstr).spawn();
                                            pstr
                                        }).unwrap_or_else(|_| fname.clone());
                                        self.status = format!("{}: {}", self.i18n.t("serial.exported"), fname);
                                    } else {
                                        self.status = self.i18n.t("serial.export_failed").to_string();
                                    }
                                } else {
                                    self.status = self.i18n.t("serial.no_debug_log").to_string();
                                }
                            }
                            if ui_icons::icon_button(ui, ui_icons::ICON_CLEAR, &self.i18n.t("serial.clear_log")).clicked() {
                                self.serial_log.clear();
                            }
                            if ui_icons::icon_button(ui, ui_icons::ICON_EXPORT, &self.i18n.t("serial.export_serial_log")).clicked() {
                                // export serial log
                                if let Err(e) = std::fs::write("serial_log.txt", self.serial_log.join("\n")) {
                                    error!("寫出 serial log 失敗: {}", e);
                                } else {
                                    // 選取檔案
                                    let _ = Command::new("explorer").arg("/select,serial_log.txt").spawn();
                                }
                            }
                            if ui_icons::icon_button(ui, ui_icons::ICON_EXPORT, &self.i18n.t("serial.export_ble_log")).clicked() {
                                let src = "status_ble.log";
                                if let Ok(data) = std::fs::read(src) {
                                    let fname = format!("ble_export_{}.log", chrono::Local::now().format("%Y%m%d_%H%M%S"));
                                    if let Ok(_) = std::fs::write(&fname, data) {
                                        let _ = std::fs::canonicalize(&fname).map(|p| {
                                            let pstr = p.to_string_lossy().to_string();
                                            let _ = Command::new("explorer").arg("/select,").arg(&pstr).spawn();
                                            pstr
                                        }).unwrap_or_else(|_| fname.clone());
                                        self.status = format!("{}: {}", self.i18n.t("serial.exported"), fname);
                                    } else {
                                        self.status = self.i18n.t("serial.export_failed").to_string();
                                    }
                                } else {
                                    self.status = self.i18n.t("serial.no_debug_log").to_string();
                                }
                            }
                            if ui_icons::icon_button(ui, ui_icons::ICON_TRUNCATE, &self.i18n.t("serial.truncate_serial_log")).clicked() {
                                if let Err(e) = std::fs::OpenOptions::new().write(true).truncate(true).open("status_serial.log") {
                                    error!("截斷 serial log 失敗: {}", e);
                                }
                            }
                            if ui_icons::icon_button(ui, ui_icons::ICON_TRUNCATE, &self.i18n.t("serial.truncate_ble_log")).clicked() {
                                if let Err(e) = std::fs::OpenOptions::new().write(true).truncate(true).open("status_ble.log") {
                                    error!("截斷 ble log 失敗: {}", e);
                                }
                            }
                        });
                    });
                    ui.add_space(GAP_SM);
                    // ZUPT parameter controls
                    ui.group(|ui| {
                        ui.label(egui::RichText::new(self.i18n.t("zupt.section")).strong());
                        ui.add_space(GAP_XS);
                        egui::Grid::new("settings_zupt_grid").spacing(egui::vec2(GAP_SM, GAP_SM)).show(ui, |ui| {
                            ui.label(self.i18n.t("zupt.window_size"));
                            ui.horizontal(|ui| {
                                let _ = ui.add(egui::TextEdit::singleline(&mut self.zupt_window_edit).desired_width(120.0));
                            });
                            ui.end_row();

                            ui.label(self.i18n.t("zupt.accel_var"));
                            ui.horizontal(|ui| {
                                let _ = ui.add(egui::TextEdit::singleline(&mut self.zupt_accel_var_edit).desired_width(120.0));
                            });
                            ui.end_row();

                            ui.label(self.i18n.t("zupt.gyro_thresh"));
                            ui.horizontal(|ui| {
                                let _ = ui.add(egui::TextEdit::singleline(&mut self.zupt_gyro_edit).desired_width(120.0));
                            });
                            ui.end_row();
                        });

                        ui.add_space(GAP_XS);
                        if ui_icons::icon_button(ui, ui_icons::ICON_CHECK, &self.i18n.t("zupt.apply")).clicked() {
                            let win_opt = self.zupt_window_edit.trim().parse::<usize>().ok();
                            let accel_opt = self.zupt_accel_var_edit.trim().parse::<f32>().ok();
                            let gyro_opt = self.zupt_gyro_edit.trim().parse::<f32>().ok();
                            let _ = self.cmd_tx.send(BackendCommand::SetZuptParams { window_size: win_opt, accel_var_threshold: accel_opt, gyro_threshold: gyro_opt });
                            // persist to config when parse succeeded
                            if let Some(w) = win_opt { self.config.zupt_window_size = w; }
                            if let Some(a) = accel_opt { self.config.zupt_accel_var_threshold = a; }
                            if let Some(g) = gyro_opt { self.config.zupt_gyro_threshold = g; }
                            self.config.save();
                        }
                    });
                    ui.group(|ui| {
                        ui.label(egui::RichText::new(self.i18n.t("recorder.section")).strong());
                        ui.horizontal(|ui| {
                            if ui.add_enabled(!self.is_recording, egui::Button::new(ui_icons::ICON_PLAY).fill(theme.btn_primary)).on_hover_text(self.i18n.t(S_START_REC)).clicked() {
                                let _ = self.cmd_tx.send(BackendCommand::StartRecording);
                            }
                            if ui.add_enabled(self.is_recording, egui::Button::new(ui_icons::ICON_STOP).fill(theme.btn_danger)).on_hover_text(self.i18n.t(S_STOP_REC)).clicked() {
                                let _ = self.cmd_tx.send(BackendCommand::StopRecording);
                            }
                            if self.is_recording {
                                ui.add(
                                    egui::Label::new(
                                        egui::RichText::new(self.i18n.t("recorder.recording_indicator")).color(UI_STATUS_ERROR),
                                    )
                                    .sense(egui::Sense::hover()),
                                );
                            }
                        });
                            ui.label(
                                egui::RichText::new(self.i18n.t("recorder.file_hint"))
                                    .size(12.0)
                                    .weak(),
                            );

                            ui.add_space(GAP_XS);
                            // Prominent recorder card
                            egui::Frame::group(ui.style()).show(ui, |ui| {
                                ui.vertical_centered(|ui| {
                                    ui.heading(self.i18n.t(S_RECORDER_TITLE));
                                });
                                ui.horizontal(|ui| {
                                    ui.label(self.i18n.t("system.language"));
                                    egui::ComboBox::from_label("")
                                        .selected_text(self.lang.clone())
                                        .show_ui(ui, |ui| {
                                            for (code, disp) in self.i18n.available_langs_with_display() {
                                                if ui.selectable_label(self.lang == code, &disp).clicked() {
                                                    if self.i18n.set_lang(&code) {
                                                        self.lang = code.clone();
                                                        self.config.ui_lang = self.lang.clone();
                                                        self.config.save();
                                                    }
                                                }
                                            }
                                        });
                                    if ui_icons::icon_button(ui, ui_icons::ICON_EXPORT, &self.i18n.t("i18n.export")).clicked() {
                                        let out = format!("i18n/export_{}.json", self.lang);
                                        match self.i18n.export_lang(&self.lang, &out) {
                                            Ok(()) => self.status = format!("{}: {}", self.i18n.t("i18n.exported"), out),
                                            Err(e) => self.status = format!("Export failed: {}", e),
                                        }
                                    }
                                });
                                ui.add_space(GAP_XS);
                                ui.horizontal(|ui| {
                                    if ui_icons::icon_button(ui, ui_icons::ICON_RELOAD, &self.i18n.t("i18n.reload")).clicked() {
                                            let mut t = I18n::load_dir("i18n", &self.lang);
                                            let _ = t.set_lang(&self.lang);
                                            self.i18n = t;
                                            self.status = format!("{}: {}", self.i18n.t("i18n.reloaded"), self.lang);
                                        }
                                });
                                ui.add_space(GAP_XS);
                                ui.horizontal(|ui| {
                                    ui.label(format!("{} {}", self.i18n.t("recorder.dropped_frames"), self.recorder_dropped_count));
                                    ui.separator();
                                    ui.label(format!("{} {}", self.i18n.t("recorder.write_errors"), self.recorder_write_errors));
                                    ui.separator();
                                    ui.label(
                                        egui::RichText::new(self.recorder_filename.clone().unwrap_or_else(|| self.i18n.t("recorder.file_not_created")))
                                            .monospace()
                                            .weak(),
                                    );
                                });

                                ui.add_space(GAP_XS);
                                ui.horizontal(|ui| {
                                    ui.label(self.i18n.t("recorder.filename_label"));
                                    let fname_resp = ui.add(
                                        egui::TextEdit::singleline(&mut self.recorder_filename_edit)
                                            .hint_text(self.i18n.t("recorder.filename_hint"))
                                            .desired_width(300.0),
                                    );
                                    fname_resp.on_hover_text(self.i18n.t("recorder.filename_hint"));
                                });
                                ui.add_space(GAP_XS);
                                ui.label(egui::RichText::new(self.i18n.t("recorder.tip_empty_name")).size(11.0).weak());

                                ui.horizontal(|ui| {
                                    ui.label(self.i18n.t("recorder.batch_label"));
                                    let bs_resp = ui.add(egui::TextEdit::singleline(&mut self.recorder_batch_size_edit).desired_width(100.0));
                                    ui.label(self.i18n.t("recorder.flush_label"));
                                    let fi_resp = ui.add(egui::TextEdit::singleline(&mut self.recorder_flush_interval_ms_edit).desired_width(100.0));
                                    // validation: update flags
                                    self.recorder_batch_valid = if self.recorder_batch_size_edit.trim().is_empty() { true } else { self.recorder_batch_size_edit.trim().parse::<usize>().is_ok() };
                                    self.recorder_flush_valid = if self.recorder_flush_interval_ms_edit.trim().is_empty() { true } else { self.recorder_flush_interval_ms_edit.trim().parse::<u64>().is_ok() };
                                    bs_resp.on_hover_text(self.i18n.t("recorder.batch_hover"));
                                    fi_resp.on_hover_text(self.i18n.t("recorder.flush_hover"));
                                    if !self.recorder_batch_valid {
                                        ui.colored_label(UI_STATUS_ERROR, self.i18n.t("recorder.batch_error"));
                                    }
                                    if !self.recorder_flush_valid {
                                        ui.colored_label(UI_STATUS_ERROR, self.i18n.t("recorder.flush_error"));
                                    }
                                });

                                ui.add_space(GAP_XS);
                                ui.horizontal(|ui| {
                                    let apply_enabled = self.recorder_batch_valid && self.recorder_flush_valid;
                                    if ui.add_enabled(apply_enabled, egui::Button::new(ui_icons::ICON_CHECK).small()).on_hover_text(self.i18n.t("recorder.apply")).clicked() {
                                        let fname = if self.recorder_filename_edit.trim().is_empty() { None } else { Some(self.recorder_filename_edit.trim().to_string()) };
                                        let bs = if self.recorder_batch_size_edit.trim().is_empty() { None } else { self.recorder_batch_size_edit.trim().parse::<usize>().ok() };
                                        let fi = if self.recorder_flush_interval_ms_edit.trim().is_empty() { None } else { self.recorder_flush_interval_ms_edit.trim().parse::<u64>().ok() };
                                        let _ = self.cmd_tx.send(BackendCommand::SetRecorderConfig { enabled: None, filename: fname, batch_size: bs, flush_interval_ms: fi });
                                        // auto-save is persisted only when user enabled auto-save and pressed Apply
                                        if self.recorder_auto_save {
                                            self.config.recorder_filename = if self.recorder_filename_edit.trim().is_empty() { None } else { Some(self.recorder_filename_edit.trim().to_string()) };
                                            if let Ok(bs_v) = self.recorder_batch_size_edit.trim().parse::<usize>() { self.config.recorder_batch_size = bs_v; }
                                            if let Ok(fi_v) = self.recorder_flush_interval_ms_edit.trim().parse::<u64>() { self.config.recorder_flush_interval_ms = fi_v; }
                                            self.config.save();
                                        }

                                    }
                                    if ui.add_enabled(apply_enabled, egui::Button::new(ui_icons::ICON_PLAY).small()).on_hover_text(self.i18n.t("recorder.apply_start")).clicked() {
                                        let fname = if self.recorder_filename_edit.trim().is_empty() { None } else { Some(self.recorder_filename_edit.trim().to_string()) };
                                        let bs = if self.recorder_batch_size_edit.trim().is_empty() { None } else { self.recorder_batch_size_edit.trim().parse::<usize>().ok() };
                                        let fi = if self.recorder_flush_interval_ms_edit.trim().is_empty() { None } else { self.recorder_flush_interval_ms_edit.trim().parse::<u64>().ok() };
                                        let _ = self.cmd_tx.send(BackendCommand::SetRecorderConfig { enabled: Some(true), filename: fname, batch_size: bs, flush_interval_ms: fi });
                                        if self.recorder_auto_save {
                                            self.config.recorder_enabled = true;
                                            self.config.recorder_filename = if self.recorder_filename_edit.trim().is_empty() { None } else { Some(self.recorder_filename_edit.trim().to_string()) };
                                            if let Ok(bs_v) = self.recorder_batch_size_edit.trim().parse::<usize>() { self.config.recorder_batch_size = bs_v; }
                                            if let Ok(fi_v) = self.recorder_flush_interval_ms_edit.trim().parse::<u64>() { self.config.recorder_flush_interval_ms = fi_v; }
                                            self.config.save();
                                        }
                                    }
                                });

                                ui.add_space(GAP_XS);
                                ui.horizontal(|ui| {
                                    if ui.checkbox(&mut self.recorder_auto_save, &self.i18n.t("recorder.auto_save")).changed() {
                                        self.config.recorder_auto_save = self.recorder_auto_save;
                                        // persist immediately when toggled on
                                        if self.recorder_auto_save {
                                            self.config.save();
                                        }
                                    }
                                });
                            });
                    });

                    ui.add_space(GAP_MD);
                    ui.separator();
                                ui.horizontal(|ui| {
                                    if ui_icons::icon_button(ui, ui_icons::ICON_CHECK, &self.i18n.t("save_config")).clicked() {
                            self.config.mag_calibrations = self.mag_calibrations.clone(); // 更新 config 中的校準數據
                            // 更新 Recorder 設定到 config
                            self.config.recorder_enabled = self.is_recording;
                            self.config.recorder_filename = if self.recorder_filename_edit.trim().is_empty() {
                                None
                            } else {
                                Some(self.recorder_filename_edit.trim().to_string())
                            };
                            if let Ok(bs) = self.recorder_batch_size_edit.trim().parse::<usize>() {
                                self.config.recorder_batch_size = bs;
                            }
                            if let Ok(fi) = self.recorder_flush_interval_ms_edit.trim().parse::<u64>() {
                                self.config.recorder_flush_interval_ms = fi;
                            }
                            self.config.save();
                        }
                        if ui
                            .add(
                                egui::Button::new(ui_icons::ICON_CANCEL).small(),
                            )
                            .on_hover_text(self.i18n.t("clear_cal"))
                            .clicked()
                        {
                            let _ = self.cmd_tx.send(BackendCommand::ClearAllCalibration);
                        }
                    });
                }
            }
        });
    }
}

// 繪圖上下文，封裝常用繪圖參數以減少函式參數數量
struct DrawCtx<'a> {
    painter: &'a egui::Painter,
    rect: egui::Rect,
    yaw: f32,
    pitch: f32,
    zoom: f32,
    th: &'a crate::theme::Theme,
}

// 繪製磁力計點雲的輔助函式
fn draw_magnetometer_points(
    ctx: &DrawCtx,
    all_mag_points: &HashMap<u8, Vec<Vector3<f32>>>,
    active_tracker_id: Option<u8>,
    calibration: Option<&MagCalibration>,
) {
    let center = ctx.rect.center();
    let scale = 50.0 * ctx.zoom; // 調整縮放以適應磁力計數據範圍

    let (sin_y, cos_y) = ctx.yaw.sin_cos();
    let (sin_p, cos_p) = ctx.pitch.sin_cos();

    let transform = |x: f32, y: f32, z: f32| -> (Pos2, f32) {
        // 先繞 X 軸 (Pitch)
        let y1 = y * cos_p - z * sin_p;
        let z1 = y * sin_p + z * cos_p;
        // 再繞 Y 軸 (Yaw)
        let x2 = x * cos_y - z1 * sin_y;
        let z2 = x * sin_y + z1 * cos_y;
        (
            Pos2::new(center.x + x2 * scale, center.y - y1 * scale),
            z2, // 回傳深度 (Z) 用於排序
        )
    };

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

    // 繪製中心點
        let (origin_screen, origin_depth) = transform(0.0, 0.0, 0.0);
    cmds.push(DrawCmd::Point {
        pos: origin_screen,
        radius: 3.0,
        fill: ctx.th.foreground,
        depth: origin_depth,
    });

    // 繪製 X, Y, Z 軸
    let axis_len = 0.5; // 軸長度
    cmds.push(DrawCmd::Line {
        start: origin_screen,
        end: transform(axis_len, 0.0, 0.0).0,
        stroke: Stroke::new(2.0, ctx.th.axis_x),
        depth: origin_depth,
    });
    cmds.push(DrawCmd::Line {
        start: origin_screen,
        end: transform(0.0, axis_len, 0.0).0,
        stroke: Stroke::new(2.0, ctx.th.axis_y),
        depth: origin_depth,
    });
    cmds.push(DrawCmd::Line {
        start: origin_screen,
        end: transform(0.0, 0.0, axis_len).0,
        stroke: Stroke::new(2.0, ctx.th.axis_z),
        depth: origin_depth,
    });

    if let Some(tid) = active_tracker_id {
        if let Some(points) = all_mag_points.get(&tid) {
            for point in points {
                let (screen_pos, depth) = transform(point.x, point.y, point.z);
                cmds.push(DrawCmd::Point {
                    pos: screen_pos,
                    radius: 2.0,
                    fill: ctx.th.mag_point,
                    depth,
                });
            }
        }
    }

    // 繪製擬合的橢球體 (如果已有校準數據)
    if let Some(calib) = calibration {
        let offset = Vector3::from(calib.offset);
        let s = calib.scale;
        // 假設目標半徑為 1.0 (歸一化後)，還原回原始空間的半徑
        // Scale = Target_Radius / Raw_Radius  => Raw_Radius = Target_Radius / Scale
        // 這裡我們畫一個代表 "理想球體" 在原始空間中的樣子 (即橢球)
        // 橢球中心 = offset, 半徑 = 1.0 / scale (假設目標半徑約為 40uT 左右，這裡 scale 已經包含了歸一化)
        // 為了視覺化，我們畫出校準後的球體邊界 (應該是正球體)
        // 或者畫出擬合的橢球體。這裡畫擬合的橢球體比較直觀：
        // 橢球半徑 Rx = Avg_Radius / Scale.x

        // 簡單起見，我們畫 3 個圓環代表橢球
        let avg_radius = 40.0; // 假設平均磁場強度約 40uT
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

            // XY plane
            let p_xy = offset + Vector3::new(rx * cos_a, ry * sin_a, 0.0);
            let (s_xy, d_xy) = transform(p_xy.x, p_xy.y, p_xy.z);
            xy_points.push(s_xy);
            total_depth += d_xy;

            // XZ plane
            let p_xz = offset + Vector3::new(rx * cos_a, 0.0, rz * sin_a);
            let (s_xz, d_xz) = transform(p_xz.x, p_xz.y, p_xz.z);
            xz_points.push(s_xz);
            total_depth += d_xz;

            // YZ plane
            let p_yz = offset + Vector3::new(0.0, ry * cos_a, rz * sin_a);
            let (s_yz, d_yz) = transform(p_yz.x, p_yz.y, p_yz.z);
            yz_points.push(s_yz);
            total_depth += d_yz;
        }
        let avg_depth = total_depth / (3.0 * (steps + 1) as f32);

        // Draw as lines for now, as DrawCmd::Wireframe is removed
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
        let _ = match cmd {
            DrawCmd::Point {
                pos, radius, fill, ..
            } => ctx.painter.circle_filled(pos, radius, fill),
            DrawCmd::Line {
                start, end, stroke, ..
            } => ctx.painter.line_segment([start, end], stroke),
        };
    }
}

// 簡單的骨架繪圖函式
fn draw_skeleton(
    ctx: &DrawCtx,
    skeleton: &SkeletonModel,
    show_grid: bool,
    mirror_view: bool,
    trackers: &HashMap<u8, TrackerState>,
    debug_axes: bool,
) {
    // 1. 定義畫布中心與縮放
    let center = ctx.rect.center();
    let scale = 100.0 * ctx.zoom;

    // 2. 3D 旋轉矩陣 (Yaw + Pitch)
    let (sin_y, cos_y) = ctx.yaw.sin_cos();
    let (sin_p, cos_p) = ctx.pitch.sin_cos();

    let transform = |x: f32, y: f32, z: f32| -> (Pos2, f32) {
        // 先繞 X 軸 (Pitch)
        let y1 = y * cos_p - z * sin_p;
        let z1 = y * sin_p + z * cos_p;
        // 再繞 Y 軸 (Yaw)
        let x2 = x * cos_y - z1 * sin_y;
        let z2 = x * sin_y + z1 * cos_y;

        // 處理鏡像 (反轉螢幕空間的 X 軸)
        let screen_x_offset = if mirror_view { -x2 } else { x2 };

        (
            Pos2::new(
                center.x + screen_x_offset * scale,
                center.y - y1 * scale + 60.0,
            ),
            z2, // 回傳深度 (Z) 用於排序
        )
    };

    // 4. 建立繪圖指令 (Z-Sort 優化)
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

    // --- 0. 繪製地板網格 (SlimeVR 風格) ---
    if show_grid {
        let grid_stroke = Stroke::new(1.0, ctx.th.grid);
        let grid_range = 4; // 範圍 +/- 4米

        for i in -grid_range..=grid_range {
            let off = i as f32;
            // X 軸平行線
            let (s1, z1) = transform(-4.0, 0.0, off);
            let (e1, z2) = transform(4.0, 0.0, off);
            cmds.push(DrawCmd::Line {
                start: s1,
                end: e1,
                stroke: grid_stroke,
                depth: (z1 + z2) / 2.0,
            });

            // Z 軸平行線
            let (s2, z3) = transform(off, 0.0, -4.0);
            let (e2, z4) = transform(off, 0.0, 4.0);
            cmds.push(DrawCmd::Line {
                start: s2,
                end: e2,
                stroke: grid_stroke,
                depth: (z3 + z4) / 2.0,
            });
        }
    }

    // 繪製前方指示箭頭 (Z+)
    let (origin, z_origin) = transform(0.0, 0.0, 0.0);
    let (forward, z_forward) = transform(0.0, 0.0, 1.0); // 1米處
    let dir_stroke = Stroke::new(3.0, ctx.th.dir);
    cmds.push(DrawCmd::Line {
        start: origin,
        end: forward,
        stroke: dir_stroke,
        depth: (z_origin + z_forward) / 2.0,
    });

    // 定義顏色 (左: 青色, 右: 橘色, 中: 白色)
    let c_center = ctx.th.foreground;
    let c_left = ctx.th.left_limb;
    let c_right = ctx.th.right_limb;
    let tracker_color = ctx.th.tracker; // Slime 紫色
    let border_color = ctx.th.border;
    let border_stroke = Stroke::new(2.0, border_color);

    // 遍歷所有骨頭進行繪製
    for bone in skeleton.bones.values() {
        let pos = bone.global_position;
        let (screen_pos, depth) = transform(pos.x, pos.y, pos.z);

        // 決定顏色
        let color = if bone.id < 10 {
                c_center
            } else if (10..20).contains(&bone.id) || (30..40).contains(&bone.id) {
                c_left
            } else {
                c_right
            };

        // 1. 繪製骨頭連線 (如果有父骨頭)
        if let Some(parent_id) = bone.parent_id {
            if let Some(parent) = skeleton.bones.get(&parent_id) {
                let p_pos = parent.global_position;
                let (p_screen_pos, p_depth) = transform(p_pos.x, p_pos.y, p_pos.z);

                cmds.push(DrawCmd::Line {
                    start: p_screen_pos,
                    end: screen_pos,
                    stroke: Stroke::new(5.0, color),
                    depth: (depth + p_depth) / 2.0,
                });
            }
        }

        // 2. 繪製關節點
        cmds.push(DrawCmd::Circle {
            pos: screen_pos,
            radius: if bone.id == 4 { 12.0 } else { 7.0 }, // 頭部畫大一點
            fill: if bone.id < 10 { tracker_color } else { color }, // 軀幹用紫色，四肢用分色
            stroke: border_stroke,
            depth,
        });

        // 3. 如果是頭部，繪製面部方向
        if bone.id == 4 {
            let forward = bone.global_rotation * Vector3::z();
            let face_pos = pos + forward * 0.15;
            let (f_screen_pos, f_depth) = transform(face_pos.x, face_pos.y, face_pos.z);

            cmds.push(DrawCmd::Circle {
                pos: f_screen_pos,
                radius: 4.0,
                fill: UI_FOREGROUND,
                stroke: Stroke::NONE,
                depth: f_depth,
            });
        }
    }

    // 4. (新增) Debug: 繪製 Tracker 原始軸向
    if debug_axes {
        for tracker in trackers.values() {
            if let (Some(bone_id), Some(quat)) = (tracker.assigned_bone, tracker.rotation) {
                if let Some(bone) = skeleton.bones.get(&bone_id) {
                    let pos = bone.global_position;
                    // 轉換 Quaternion (x,y,z,w) -> Rotation Matrix
                    let q = nalgebra::UnitQuaternion::new_normalize(nalgebra::Quaternion::new(
                        quat[3], quat[0], quat[1], quat[2],
                    ));

                    let axis_len = 0.15; // 15cm 長度
                    let axes = [
                        (Vector3::x(), ctx.th.axis_x),
                        (Vector3::y(), ctx.th.axis_y),
                        (Vector3::z(), ctx.th.axis_z),
                    ];

                    for (dir, color) in axes {
                        let rotated_dir = q.transform_vector(&dir);
                        let end_pos = pos + rotated_dir * axis_len;

                        let (start_screen, s_depth) = transform(pos.x, pos.y, pos.z);
                        let (end_screen, e_depth) = transform(end_pos.x, end_pos.y, end_pos.z);

                        cmds.push(DrawCmd::Line {
                            start: start_screen,
                            end: end_screen,
                            stroke: Stroke::new(2.0, color),
                            depth: (s_depth + e_depth) / 2.0 - 0.5, // 稍微往前拉一點，避免被骨頭蓋住
                        });
                    }
                }
            }
        }
    }

    // 5. 排序並繪製 (由遠到近)
    cmds.sort_by(|a, b| {
        a.depth()
            .partial_cmp(&b.depth())
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    for cmd in cmds {
        match cmd {
            DrawCmd::Line {
                start, end, stroke, ..
            } => {
                ctx.painter.line_segment([start, end], stroke);
            }
            DrawCmd::Circle {
                pos,
                radius,
                fill,
                stroke,
                ..
            } => {
                ctx.painter.circle(pos, radius, fill, stroke);
            }
        }
    }
    // Draw subtle center crosshair + focus dot for preview clarity
    let cross_len = 8.0 * ctx.zoom.max(1.0);
    let center = ctx.rect.center();
    ctx.painter.line_segment([
        Pos2::new(center.x - cross_len, center.y),
        Pos2::new(center.x + cross_len, center.y),
    ], Stroke::new(1.6, ctx.th.selection));
    ctx.painter.line_segment([
        Pos2::new(center.x, center.y - cross_len),
        Pos2::new(center.x, center.y + cross_len),
    ], Stroke::new(1.6, ctx.th.selection));
    ctx.painter.circle_filled(center, 3.0, ctx.th.accent);
}

// 輔助函式：將 BoneId 轉為顯示名稱（使用 i18n）
fn bone_name(i18n: &crate::i18n::I18n, id: u8) -> String {
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

// 設定中文字型
fn setup_custom_fonts(ctx: &egui::Context) {
    let mut fonts = egui::FontDefinitions::default();

    // Try a list of common Windows fonts (prefer Chinese-capable first)
    let try_fonts = [
        ("C:\\Windows\\Fonts\\msjh.ttc", "Microsoft JhengHei"),
        ("C:\\Windows\\Fonts\\msjh.ttf", "Microsoft JhengHei"),
        ("C:\\Windows\\Fonts\\segoeui.ttf", "Segoe UI"),
        ("C:\\Windows\\Fonts\\arial.ttf", "Arial"),
    ];

    let mut loaded = false;
    for (path, name) in try_fonts.iter() {
        if let Ok(bytes) = std::fs::read(path) {
            let font_name = name.to_string();
            let font_data = egui::FontData::from_owned(bytes);
            fonts.font_data.insert(font_name.clone(), font_data);
            // set as priority for both proportional and monospace (fallback)
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
            log::info!("已載入字型: {} ({})", name, path);
            loaded = true;
            break;
        }
    }

    if !loaded {
        // fallback: use default egui fonts (do nothing)
        log::info!("未找到可用系統字型，使用預設字型。");
    }
}

// 設定全域樣式 (Dark Theme)
fn configure_style(ctx: &egui::Context, theme: &crate::theme::Theme) {
    // choose base visuals from dark or light depending on foreground brightness
    // Simple heuristic: if foreground is white -> dark visuals, else light visuals
    let mut visuals = if theme.foreground == eframe::epaint::Color32::WHITE {
        egui::Visuals::dark()
    } else {
        egui::Visuals::light()
    };

    // map theme colors into egui visuals
    visuals.window_fill = theme.window_fill;
    visuals.panel_fill = theme.panel_fill;

    visuals.widgets.noninteractive.bg_fill = theme.window_fill;
    visuals.widgets.inactive.weak_bg_fill = theme.widget_inactive;
    visuals.widgets.hovered.weak_bg_fill = theme.widget_hover;
    visuals.widgets.active.weak_bg_fill = theme.widget_active;

    // Button/Widget visuals: clearer fg stroke and active bg
    visuals.widgets.inactive.fg_stroke = egui::Stroke::new(0.5, theme.foreground);
    visuals.widgets.hovered.fg_stroke = egui::Stroke::new(1.0, theme.accent);
    visuals.widgets.active.fg_stroke = egui::Stroke::new(1.0, theme.foreground);
    visuals.widgets.active.bg_fill = theme.btn_primary; // active buttons use primary color

    // rounding for modern look
    visuals.window_rounding = egui::Rounding::same(CORNER_ROUND_MD);
    visuals.widgets.inactive.rounding = egui::Rounding::same(CORNER_ROUND_MD);
    visuals.widgets.hovered.rounding = egui::Rounding::same(CORNER_ROUND_MD);
    visuals.widgets.active.rounding = egui::Rounding::same(CORNER_ROUND_MD);

    visuals.selection.bg_fill = theme.selection;
    visuals.selection.stroke = egui::Stroke::new(1.0, theme.accent);

    // subtle window stroke
    visuals.window_stroke = egui::Stroke::new(0.8, theme.stroke_gray);

    ctx.set_visuals(visuals);

    let mut style = (*ctx.style()).clone();
    // adjust spacing and paddings from tokens
    style.spacing.item_spacing = egui::vec2(GAP_SM, GAP_SM);
    style.spacing.button_padding = egui::vec2(BTN_PAD_X, BTN_PAD_Y);
    style.spacing.window_margin = egui::Margin::same(14.0);

    // font sizes
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

    // Button visual tweaks are applied earlier when we set `visuals`.

    ctx.set_style(style);
}

// 繪製電量條 Widget
fn ui_battery_bar(ui: &mut egui::Ui, battery: f32, theme: &crate::theme::Theme) {
    let (rect, _resp) = ui.allocate_at_least(egui::vec2(BATTERY_W, BATTERY_H), egui::Sense::hover());
    let rounding = 4.0;

    // 背景
    ui.painter()
        .rect_filled(rect, rounding, theme.batt_bg);

    // 填充
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

    // 文字
    ui.painter().text(
        rect.center(),
        egui::Align2::CENTER_CENTER,
        format!("{:.0}%", battery),
        egui::FontId::proportional((ICON_SIZE * 0.6) as f32),
        theme.foreground,
    );
}
