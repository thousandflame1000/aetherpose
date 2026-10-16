use crate::connection_type::ConnectionType;
use crate::fusion::AuthoritativePose;
pub use crate::imu::trajectory::TrajectoryIntegrationMode;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct VrPoseData {
    pub pos: [f32; 3],
    pub rot: [f32; 4],
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct VrBridgePacket {
    pub head: Option<VrPoseData>,
    pub left_hand: Option<VrPoseData>,
    pub right_hand: Option<VrPoseData>,
}

pub struct QuestInputData {
    pub head: Option<AuthoritativePose>,
    pub left_hand: Option<AuthoritativePose>,
    pub right_hand: Option<AuthoritativePose>,
    /// When the packet arrived; None until the headset sends one.
    pub received_at: Option<std::time::Instant>,
}

#[derive(Clone, Debug)]
pub struct TrackerState {
    pub id: u8,
    pub connection_type: ConnectionType,
    pub battery: f32,
    pub rssi: i32,
    pub accel: Option<[f32; 3]>,
    pub last_update: std::time::Instant,
    pub assigned_bone: Option<u8>,
    pub tps: u32,
    pub rotation: Option<[f32; 4]>,
    pub stationary: bool,
    pub last_sequence: u16,
    pub received_packets: u64,
    pub lost_packets: u64,
    pub mag: Option<[f32; 3]>,
}

pub struct GuiSnapshot {
    pub packet_count: u64,
    pub trackers: HashMap<u8, TrackerState>,
    pub is_recording: bool,
    pub recorder_dropped_count: u64,
    pub recorder_write_errors: u64,
    pub recorder_filename: Option<String>,
    pub recorder_batch_size: usize,
    pub recorder_flush_interval_ms: u64,
    pub recorder_error: Option<String>,
    pub osc_active: bool,
    pub osc_error: Option<String>,
    pub config_warning: Option<String>,
    pub leg_ratio: f32,
    pub floor_offset: f32,
    pub pending_shake_bone: Option<u8>,
    pub serial_running: bool,
    pub serial_status_msg: Option<String>,
    pub ble_status: Option<String>,
    pub headset_age_ms: Option<u64>,
    pub leg_calibrating: bool,
    pub leg_calibration_samples: usize,
    pub leg_calibration_result: Option<String>,
    pub settings: WsSettings,
    /// Processed skeleton joint positions (world space) after IK.
    pub bones: Vec<WsBone>,
}

/// The saved settings, so a page shows the backend's values instead of its
/// own control defaults (and does not send those defaults back).
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct WsSettings {
    pub ik_smoothness: f32,
    pub prop_leg: f32,
    pub prop_arm: f32,
    pub prop_spine: f32,
    pub drift_correction: f32,
    pub smoothing_min_cutoff: f32,
    pub smoothing_beta: f32,
    pub trajectory_integration_mode: TrajectoryIntegrationMode,
    pub osc_ip: String,
    pub osc_port: u16,
    pub zupt_enabled: bool,
    pub zupt_window_size: usize,
    pub zupt_accel_var_threshold: f32,
    pub zupt_gyro_threshold: f32,
    pub serial_enabled: bool,
    pub serial_port: Option<String>,
    pub serial_baud: u32,
}

/// One skeleton joint — world-space position only (rotation sent separately if needed).
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct WsBone {
    pub id: u8,
    pub name: String,
    pub parent_id: Option<u8>,
    /// [x, y, z] in metres, world space (Y-up).
    pub pos: [f32; 3],
}

pub enum GuiUpdate {
    /// Boxed: snapshots go through a channel many times a second and are far larger than Status.
    Snapshot(Box<GuiSnapshot>),
    Status {
        serial_running: bool,
        serial_status_msg: Option<String>,
    },
}

impl GuiUpdate {
    pub fn status(serial_running: bool, serial_status_msg: Option<String>) -> Self {
        Self::Status {
            serial_running,
            serial_status_msg,
        }
    }
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub enum BackendCommand {
    RequestSnapshot,
    SetIkSmoothness(f32),
    ResetYaw,
    SetOscTarget(String, u16),
    AssignTracker(u8, u8),
    UnassignTracker(u8),
    /// Drops a tracker entirely: its assignment, its saved entry and its row (the simulator's cleanup).
    ForgetTracker(u8),
    SetProportions { leg: f32, arm: f32, spine: f32 },
    ResetMounting,
    ClearAllCalibration,
    SetDriftCorrection(f32),
    AutoAssign,
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
    SetSmoothingParams {
        min_cutoff: f32,
        beta: f32,
    },
    SetTrajectoryIntegrationMode(TrajectoryIntegrationMode),
    SetZuptEnabled(bool),
    SetZuptParams {
        window_size: Option<usize>,
        accel_var_threshold: Option<f32>,
        gyro_threshold: Option<f32>,
    },
    StartLegCalibration,
    StopLegCalibration,
    /// Sets the thigh/shin ratio a leg calibration finds (the page's reset sends the default).
    SetLegRatio(f32),
    SetFloorOffset(f32),
    AutoFloor,
    StartShakeAssign(u8),
    CancelShakeAssign,
}

// ── WebSocket wire types ──────────────────────────────────────────────────────

/// Tracker state serialisable over JSON (replaces `std::time::Instant` with
/// elapsed milliseconds).
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct WsTrackerState {
    pub id: u8,
    pub connection_type: String,
    pub battery: f32,
    pub rssi: i32,
    pub accel: Option<[f32; 3]>,
    /// Milliseconds since the last packet from this tracker.
    pub last_update_ms: u64,
    pub assigned_bone: Option<u8>,
    pub tps: u32,
    pub rotation: Option<[f32; 4]>,
    pub stationary: bool,
    pub last_sequence: u16,
    pub received_packets: u64,
    pub lost_packets: u64,
    pub mag: Option<[f32; 3]>,
}

/// Snapshot of backend state broadcast to every connected WebSocket client.
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct WsSnapshot {
    pub packet_count: u64,
    pub trackers: HashMap<u8, WsTrackerState>,
    pub is_recording: bool,
    pub recorder_dropped_count: u64,
    pub recorder_write_errors: u64,
    pub recorder_filename: Option<String>,
    pub recorder_batch_size: usize,
    pub recorder_flush_interval_ms: u64,
    /// Why recording could not start (open:<error>) or stopped by itself
    /// (write:<error>); cleared by the next successful start or a stop.
    #[serde(default)]
    pub recorder_error: Option<String>,
    /// Whether OSC output is running, and why the last target set (or the
    /// saved one at start) could not be used: "<ip>:<port> (<error>)".
    #[serde(default)]
    pub osc_active: bool,
    #[serde(default)]
    pub osc_error: Option<String>,
    /// config.json could not be read at start, so defaults are in use:
    /// "<error>|<backup file name>" (see AppConfig::load_warning).
    #[serde(default)]
    pub config_warning: Option<String>,
    pub leg_ratio: f32,
    pub floor_offset: f32,
    pub pending_shake_bone: Option<u8>,
    pub serial_running: bool,
    /// Latest serial event: opened:<port>, parse_error:<port>:<error>,
    /// non_utf8:<port>:<n> bytes, error:<port>:<error>, disconnected:<port>,
    /// reconnect_scheduled:<port>:<attempt>.
    pub serial_status_msg: Option<String>,
    /// Latest BLE event: ble_scanning, ble_unavailable:<reason>, ble_discovered:<id>:<rssi>,
    /// ble_connected:<id>, ble_connect_error:<id>:<error>, ble_disconnected:<id>, ...
    pub ble_status: Option<String>,
    /// Age of the latest headset head pose (Quest bridge, UDP 9002); None if
    /// none arrived. The backend ignores headset input older than 500 ms.
    #[serde(default)]
    pub headset_age_ms: Option<u64>,
    /// Leg calibration (needs the headset plus left thigh and shin trackers).
    #[serde(default)]
    pub leg_calibrating: bool,
    #[serde(default)]
    pub leg_calibration_samples: usize,
    /// Last result: done:<ratio>, no_samples, small_swing:<metres>,
    /// unsolvable or out_of_range:<ratio>.
    #[serde(default)]
    pub leg_calibration_result: Option<String>,
    pub settings: WsSettings,
    /// Processed skeleton joints after IK (world-space, Y-up, metres).
    pub bones: Vec<WsBone>,
}

impl WsSnapshot {
    pub fn from_snapshot(snap: GuiSnapshot) -> Self {
        let trackers = snap
            .trackers
            .into_iter()
            .map(|(k, v)| {
                let ws = WsTrackerState {
                    id: v.id,
                    connection_type: format!("{:?}", v.connection_type),
                    battery: v.battery,
                    rssi: v.rssi,
                    accel: v.accel,
                    last_update_ms: v.last_update.elapsed().as_millis() as u64,
                    assigned_bone: v.assigned_bone,
                    tps: v.tps,
                    rotation: v.rotation,
                    stationary: v.stationary,
                    last_sequence: v.last_sequence,
                    received_packets: v.received_packets,
                    lost_packets: v.lost_packets,
                    mag: v.mag,
                };
                (k, ws)
            })
            .collect();

        Self {
            packet_count: snap.packet_count,
            trackers,
            is_recording: snap.is_recording,
            recorder_dropped_count: snap.recorder_dropped_count,
            recorder_write_errors: snap.recorder_write_errors,
            recorder_filename: snap.recorder_filename,
            recorder_batch_size: snap.recorder_batch_size,
            recorder_flush_interval_ms: snap.recorder_flush_interval_ms,
            recorder_error: snap.recorder_error,
            osc_active: snap.osc_active,
            osc_error: snap.osc_error,
            config_warning: snap.config_warning,
            leg_ratio: snap.leg_ratio,
            floor_offset: snap.floor_offset,
            pending_shake_bone: snap.pending_shake_bone,
            serial_running: snap.serial_running,
            serial_status_msg: snap.serial_status_msg,
            ble_status: snap.ble_status,
            headset_age_ms: snap.headset_age_ms,
            leg_calibrating: snap.leg_calibrating,
            leg_calibration_samples: snap.leg_calibration_samples,
            leg_calibration_result: snap.leg_calibration_result,
            settings: snap.settings,
            bones: snap.bones,
        }
    }
}

/// Top-level envelope sent from Rust → Python.
#[derive(Serialize, Deserialize, Clone, Debug)]
#[serde(tag = "type", content = "data")]
#[allow(clippy::large_enum_variant)]  // built and serialised in place once per update, never moved around
pub enum WsServerMessage {
    Snapshot(WsSnapshot),
    Status {
        serial_running: bool,
        serial_status_msg: Option<String>,
    },
}
