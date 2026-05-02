use crate::imu::pose::FilteredPose;
use nalgebra::{UnitQuaternion, Vector3};

/// Applies drift compensation to an IMU pose, primarily correcting roll and pitch
/// using accelerometer data as a gravity reference.
///
/// # Arguments
/// * `pose` - The filtered pose data, which must include acceleration.
/// * `correction_strength` - A value from 0.0 to 1.0 controlling how strongly
///   the correction is applied. 0 means no correction.
///
/// This function does not correct for Yaw drift, as that is not directly
/// observable from accelerometer data alone.
pub fn compensate_drift(pose: FilteredPose, correction_strength: f32) -> FilteredPose {
    let mut corrected_rotation = pose.rotation;

    // 僅在補償強度 > 0 且加速度計數據有效時 (例如不是在自由落體狀態) 才進行修正
    if correction_strength > 0.0 && pose.acceleration.magnitude_squared() > 24.1 {
        // 24.1 = (0.5 * 9.81)^2 m/s²，低於此表示接近自由落體，跳過補償
        // 1. 從加速度計獲取 "up" 方向。此向量在 Tracker 的局部座標系中指向上方。
        let measured_up = pose.acceleration.normalize();

        // 2. 透過當前姿態，計算出 Tracker 認為的 "up" 在世界座標系中的方向。
        let current_world_up = pose.rotation * measured_up;

        // 3. 世界座標系中「真正」的向上方向。
        // Firmware 的 Madgwick 使用 Z-up 慣例（重力參考向量 [0,0,1]），因此用 Z 軸。
        let world_up = Vector3::z();

        // 4. 找到一個能將 "Tracker 認為的 up" 對齊到 "世界真實的 up" 的旋轉。
        if let Some(correction_quat) =
            UnitQuaternion::rotation_between(&current_world_up, &world_up)
        {
            // 4. 使用 SLERP 平滑地套用一小部分修正，以避免加速度計雜訊造成的抖動。
            // `correction_strength` 越大，修正速度越快。
            let slerp_factor = (correction_strength * 0.01).clamp(0.0, 0.1);
            corrected_rotation = correction_quat
                .slerp(&UnitQuaternion::identity(), 1.0 - slerp_factor)
                * pose.rotation;
        }
    }

    FilteredPose {
        rotation: corrected_rotation,
        magnetic_field: pose.magnetic_field,
        ..pose // 將 angular_velocity 和 acceleration 等其他欄位傳遞下去
    }
}

/// Simple ZUPT (zero-velocity) / stationary detector.
/// Maintains a short sliding window of recent acceleration magnitudes and
/// angular velocity to decide whether the sensor is stationary.
pub struct ZuptDetector {
    window: std::collections::VecDeque<f32>,
    window_size: usize,
    accel_var_threshold: f32,
    gyro_threshold: f32,
}

impl ZuptDetector {
    pub fn new(window_size: usize, accel_var_threshold: f32, gyro_threshold: f32) -> Self {
        Self {
            window: std::collections::VecDeque::with_capacity(window_size),
            window_size,
            accel_var_threshold,
            gyro_threshold,
        }
    }

    /// Update detector with latest filtered pose. Returns true if considered stationary.
    pub fn update(&mut self, pose: &FilteredPose) -> bool {
        // Use acceleration magnitude (including gravity) as primary cue.
        let mag = pose.acceleration.norm();

        if self.window.len() == self.window_size {
            self.window.pop_front();
        }
        self.window.push_back(mag);

        if self.window.len() < self.window_size {
            return false; // need more samples
        }

        // compute variance of the window
        let mean: f32 = self.window.iter().sum::<f32>() / (self.window.len() as f32);
        let var: f32 = self
            .window
            .iter()
            .map(|v| {
                let d = v - mean;
                d * d
            })
            .sum::<f32>()
            / (self.window.len() as f32);

        // angular velocity magnitude
        let gyro = pose.angular_velocity.norm();

        // Stationary if accel variance low AND gyro below threshold
        var <= self.accel_var_threshold && gyro <= self.gyro_threshold
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use nalgebra::UnitQuaternion;

    fn make_pose(accel: Vector3<f32>, angvel: Vector3<f32>) -> FilteredPose {
        FilteredPose {
            rotation: UnitQuaternion::identity(),
            angular_velocity: angvel,
            acceleration: accel,
            magnetic_field: Vector3::zeros(),
        }
    }

    #[test]
    fn test_zupt_detects_stationary() {
        let mut d = ZuptDetector::new(8, 0.0005, 0.02);
        // simulate steady gravity ~1.0 with small noise
        for i in 0..12 {
            let noise = if i % 2 == 0 { 0.001 } else { -0.001 };
            let pose = make_pose(Vector3::new(0.0, 1.0 + noise, 0.0), Vector3::new(0.0, 0.0, 0.0));
            let stationary = d.update(&pose);
            if i < 7 {
                assert!(!stationary, "need warmup samples");
            } else {
                assert!(stationary, "should detect stationary after window filled");
            }
        }
    }

    #[test]
    fn test_zupt_detects_motion() {
        let mut d = ZuptDetector::new(8, 0.0005, 0.02);
        // simulate motion: varying accel and non-zero gyro
        for i in 0..12 {
            let a = if i < 6 { 1.0 } else { 1.5 }; // big change
            let ang = if i < 6 { 0.0 } else { 0.5 };
            let pose = make_pose(Vector3::new(0.0, a, 0.0), Vector3::new(ang, 0.0, 0.0));
            let stationary = d.update(&pose);
            if i < 7 {
                assert!(!stationary);
            } else {
                assert!(!stationary, "should not be stationary when motion present");
            }
        }
    }
}
