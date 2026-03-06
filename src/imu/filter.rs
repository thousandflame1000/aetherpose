use crate::imu::pose::FilteredPose;
use nalgebra::{Quaternion, UnitQuaternion, Vector3};

/// 將原始感測器數據轉換並套用一個簡單的重力校正濾波器。
///
/// # Arguments
/// * `quat` - 來自感測器的四元數 [x, y, z, w]
/// * `accel` - 來自感測器的加速度 [x, y, z]
///
/// # Returns
/// * `FilteredPose` - 經過濾波後的姿態
pub fn filter_raw_data(quat: [f32; 4], accel: [f32; 3], mag: [f32; 3]) -> FilteredPose {
    // 將原始數據轉換為 nalgebra 類型
    // 假設輸入是 [x, y, z, w]，nalgebra 建構子為 (w, x, y, z)
    let rotation =
        UnitQuaternion::from_quaternion(Quaternion::new(quat[3], quat[0], quat[1], quat[2]));
    let acceleration = Vector3::from(accel);
    let magnetic_field = Vector3::from(mag);

    // 直接回傳轉換後的姿態。
    // 漂移校正等複雜邏輯已移至 drift.rs 模組，由 FusionEngine 呼叫。
    FilteredPose {
        rotation,
        acceleration,
        magnetic_field,
        angular_velocity: Vector3::zeros(),
    }
}
