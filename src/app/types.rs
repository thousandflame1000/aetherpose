use crate::connection_type::ConnectionType;
use crate::fusion::AuthoritativePose;
use crate::imu::calibration::MagCalibration;
pub use crate::imu::trajectory::TrajectoryIntegrationMode;
use nalgebra::Vector3;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Serialize, Deserialize, Clone, Copy, Debug, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CameraProjectionMode {
    Orthographic,
    Perspective,
}

impl Default for CameraProjectionMode {
    fn default() -> Self {
        Self::Orthographic
    }
}

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

#[derive(PartialEq, Clone, Copy)]
pub enum Tab {
    Calibration,
    Monitor,
    Body,
    System,
}
