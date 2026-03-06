#![allow(dead_code)]

use nalgebra::{UnitQuaternion, Vector3};

/// Represents the raw, un-processed data directly from an IMU sensor.
#[derive(Debug, Clone, Copy, Default)]
pub struct RawPose {
    pub rotation: UnitQuaternion<f32>,
    pub acceleration: Vector3<f32>,
    // Potentially add gyro_data, magnetic_field, etc.
}

/// Represents IMU data after initial filtering (e.g., Madgwick, Mahony)
/// to provide a stable orientation, but still in the sensor's local frame.
#[derive(Debug, Clone, Copy, Default)]
pub struct FilteredPose {
    pub rotation: UnitQuaternion<f32>,
    pub angular_velocity: Vector3<f32>, // Filtered angular velocity
    pub acceleration: Vector3<f32>,     // Pass acceleration through for drift correction
    pub magnetic_field: Vector3<f32>,   // Pass magnetic field through for calibration
                                        // Potentially add other filtered metrics
}

/// Represents IMU data after sensor-level calibration (e.g., zero-point correction)
/// applied to the filtered pose, but before any body-level calibration.
#[derive(Debug, Clone, Copy, Default)]
pub struct SensorCalibratedPose {
    pub rotation: UnitQuaternion<f32>,
    pub angular_velocity: Vector3<f32>,
    pub acceleration: Vector3<f32>, // Pass acceleration through for drift correction
    pub magnetic_field: Vector3<f32>, // Pass magnetic field through for calibration
                                    // Potentially add other calibrated metrics
}
