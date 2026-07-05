use crate::connection_type::ConnectionType;
use crate::fusion::AuthoritativePose;
use crate::imu::calibration::MagCalibration;
pub use crate::imu::trajectory::TrajectoryIntegrationMode;
use nalgebra::Vector3;
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
    pub is_mag_calibrating: bool,
}

pub struct GuiSnapshot {
    pub packet_count: u64,
    pub trackers: HashMap<u8, TrackerState>,
    pub mag_calibration_points: HashMap<u8, Vec<Vector3<f32>>>,
    pub mag_calibrating_tracker_id: Option<u8>,
    pub is_recording: bool,
    pub recorder_dropped_count: u64,
    pub recorder_write_errors: u64,
    pub recorder_filename: Option<String>,
    pub recorder_batch_size: usize,
    pub recorder_flush_interval_ms: u64,
    pub mag_calibrations: HashMap<u8, MagCalibration>,
    pub leg_ratio: f32,
    pub floor_offset: f32,
    pub pending_shake_bone: Option<u8>,
    pub serial_running: bool,
    pub serial_status_msg: Option<String>,
    /// Processed skeleton joint positions (world space) after IK.
    pub bones: Vec<WsBone>,
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
    Snapshot(GuiSnapshot),
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
    SetIkSmoothness(f32),
    ResetYaw,
    SetOscTarget(String, u16),
    AssignTracker(u8, u8),
    SetProportions { leg: f32, arm: f32, spine: f32 },
    ResetMounting,
    ClearAllCalibration,
    SetDriftCorrection(f32),
    AutoAssign,
    StartMagCalibration(u8),
    StopMagCalibration(u8),
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
    pub is_mag_calibrating: bool,
}

/// Snapshot of backend state broadcast to every connected WebSocket client.
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct WsSnapshot {
    pub packet_count: u64,
    pub trackers: HashMap<u8, WsTrackerState>,
    pub mag_calibrating_tracker_id: Option<u8>,
    pub is_recording: bool,
    pub recorder_dropped_count: u64,
    pub recorder_write_errors: u64,
    pub recorder_filename: Option<String>,
    pub recorder_batch_size: usize,
    pub recorder_flush_interval_ms: u64,
    pub leg_ratio: f32,
    pub floor_offset: f32,
    pub pending_shake_bone: Option<u8>,
    pub serial_running: bool,
    pub serial_status_msg: Option<String>,
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
                    is_mag_calibrating: v.is_mag_calibrating,
                };
                (k, ws)
            })
            .collect();

        Self {
            packet_count: snap.packet_count,
            trackers,
            mag_calibrating_tracker_id: snap.mag_calibrating_tracker_id,
            is_recording: snap.is_recording,
            recorder_dropped_count: snap.recorder_dropped_count,
            recorder_write_errors: snap.recorder_write_errors,
            recorder_filename: snap.recorder_filename,
            recorder_batch_size: snap.recorder_batch_size,
            recorder_flush_interval_ms: snap.recorder_flush_interval_ms,
            leg_ratio: snap.leg_ratio,
            floor_offset: snap.floor_offset,
            pending_shake_bone: snap.pending_shake_bone,
            serial_running: snap.serial_running,
            serial_status_msg: snap.serial_status_msg,
            bones: snap.bones,
        }
    }
}

/// Top-level envelope sent from Rust → Python.
#[derive(Serialize, Deserialize, Clone, Debug)]
#[serde(tag = "type", content = "data")]
pub enum WsServerMessage {
    Snapshot(WsSnapshot),
    Status {
        serial_running: bool,
        serial_status_msg: Option<String>,
    },
}
