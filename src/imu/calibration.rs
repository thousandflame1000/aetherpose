use crate::imu::pose::{FilteredPose, SensorCalibratedPose};
use nalgebra::Vector3;

#[derive(Debug, Clone, Copy, serde::Serialize, serde::Deserialize)]
pub struct MagCalibration {
    pub offset: [f32; 3],
    pub scale: [f32; 3],
}

impl Default for MagCalibration {
    fn default() -> Self {
        Self {
            offset: [0.0; 3],
            scale: [1.0; 3],
        }
    }
}

impl MagCalibration {
    /// Simple Hard Iron (offset) and Soft Iron (scale) calibration.
    /// This is a naive implementation fitting an AABB.
    pub fn calibrate(points: &[Vector3<f32>]) -> Option<Self> {
        if points.len() < 10 {
            return None;
        }

        let mut min = Vector3::new(f32::MAX, f32::MAX, f32::MAX);
        let mut max = Vector3::new(f32::MIN, f32::MIN, f32::MIN);

        for p in points {
            if p.x < min.x {
                min.x = p.x;
            }
            if p.y < min.y {
                min.y = p.y;
            }
            if p.z < min.z {
                min.z = p.z;
            }

            if p.x > max.x {
                max.x = p.x;
            }
            if p.y > max.y {
                max.y = p.y;
            }
            if p.z > max.z {
                max.z = p.z;
            }
        }

        let offset = (min + max) / 2.0;
        let avg_dist = (max - min) / 2.0;

        // Avoid division by zero
        let avg_radius = (avg_dist.x + avg_dist.y + avg_dist.z) / 3.0;
        if avg_radius < 1e-6 {
            return None;
        }

        let scale = Vector3::new(
            avg_radius / avg_dist.x.max(1e-6),
            avg_radius / avg_dist.y.max(1e-6),
            avg_radius / avg_dist.z.max(1e-6),
        );

        Some(Self {
            offset: [offset.x, offset.y, offset.z],
            scale: [scale.x, scale.y, scale.z],
        })
    }
}

/// Applies the magnetometer calibration to the filtered pose.
pub fn apply_sensor_calibration(
    pose: FilteredPose,
    calib: &MagCalibration,
) -> SensorCalibratedPose {
    let mag = pose.magnetic_field;
    let offset = Vector3::from(calib.offset);
    let scale = Vector3::from(calib.scale);

    let calibrated_mag = Vector3::new(
        (mag.x - offset.x) * scale.x,
        (mag.y - offset.y) * scale.y,
        (mag.z - offset.z) * scale.z,
    );

    SensorCalibratedPose {
        rotation: pose.rotation,
        angular_velocity: pose.angular_velocity,
        acceleration: pose.acceleration,
        magnetic_field: calibrated_mag,
    }
}
