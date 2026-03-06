use nalgebra::{Vector3, UnitQuaternion};
use crate::skeleton::{SkeletonModel, bone::BoneId};

/// 使用解析式 IK (analytical IK) 解算單條腿
///
/// # Arguments
/// * `skeleton` - 可變的骨架模型
/// * `hip_id` - 髖關節的 BoneId
/// * `knee_id` - 膝關節的 BoneId
/// * `ankle_id` - 踝關節的 BoneId
/// * `target` - 腳踝要到達的目標世界座標
///
/// # Returns
/// * `Result<(), &str>` - 成功或失敗
pub fn solve_leg_ik(
    skeleton: &mut SkeletonModel,
    hip_id: BoneId,
    knee_id: BoneId,
    ankle_id: BoneId,
    target: Vector3<f32>,
) -> Result<(), &'static str> {

    // --- 1. 取得骨骼長度 ---
    // 假設骨骼長度在 solve 期間不變，從靜態模型中獲取
    let upper_leg_len = skeleton.get_bone_length(knee_id).ok_or("Knee not found")?;
    let lower_leg_len = skeleton.get_bone_length(ankle_id).ok_or("Ankle not found")?;

    // --- 2. 取得髖關節的世界座標 ---
    // FK 必須在 IK 之前被計算，以確保 global_position 是最新的
    let hip_pos = skeleton.bones.get(&hip_id).ok_or("Hip not found")?.global_position;

    // --- 3. 計算目標向量與距離 ---
    let target_vec = target - hip_pos;
    let target_dist = target_vec.norm();

    // 檢查目標是否可達
    if target_dist > upper_leg_len + lower_leg_len {
        // 如果目標太遠，完全伸展腿部
        // (此處暫時返回錯誤，未來可以實作伸展邏輯)
        return Err("Target is unreachable");
    }

    // --- 4. 使用餘弦定理計算膝關節彎曲角度 ---
    // 公式: c^2 = a^2 + b^2 - 2ab*cos(C) => cos(C) = (a^2 + b^2 - c^2) / 2ab
    let cos_angle_knee = (upper_leg_len.powi(2) + lower_leg_len.powi(2) - target_dist.powi(2)) 
                       / (2.0 * upper_leg_len * lower_leg_len);
    
    // 限制 cos 值在 [-1.0, 1.0] 範圍內避免 acos 產生 NaN
    let angle_knee = cos_angle_knee.clamp(-1.0, 1.0).acos();

    // --- 5. 計算髖關節角度 ---
    // 這裡需要計算兩個角度：
    // a) target_vec 與 "up" vector (通常是 Y 軸) 的夾角
    // b) 髖關節與膝關節連線形成的三角形的內角
    let angle_hip_base = (target_dist / (2.0 * upper_leg_len)).clamp(-1.0, 1.0).acos();
    let angle_hip_offset = ((upper_leg_len.powi(2) + target_dist.powi(2) - lower_leg_len.powi(2)) / (2.0 * upper_leg_len * target_dist)).clamp(-1.0, 1.0).acos();
    let angle_hip = angle_hip_base + angle_hip_offset;

    // --- 6. 套用旋轉 ---
    // 這部分是簡化的，實際應用中需要決定旋轉軸
    // 簡單起見，我們先假設在 YZ 平面上運動 (只繞 X 軸旋轉)
    
    // a. 旋轉膝關節
    // 膝關節只應在一個軸上彎曲 (例如 X 軸)
    // 注意：angle_knee 是內角，實際旋轉可能是 PI - angle_knee
    let knee_rot = UnitQuaternion::from_axis_angle(&Vector3::x_axis(), std::f32::consts::PI - angle_knee);
    if let Some(knee_bone) = skeleton.bones.get_mut(&knee_id) {
        // 為了避免覆蓋 IMU 資料，這裡的旋轉應該與 IMU 的旋轉融合，而不是直接設定
        // 暫時直接設定以觀察效果
        knee_bone.local_rotation = knee_rot;
    }

    // b. 旋轉髖關節
    // 髖關節需要先對準目標方向，然後再應用 IK 計算出的彎曲
    let target_dir = target_vec.normalize();
    let hip_up_vector = Vector3::y(); // 假設骨架的 "up" 是 Y 軸
    let initial_hip_rot = UnitQuaternion::face_towards(&target_dir, &hip_up_vector);
    
    let hip_bend_rot = UnitQuaternion::from_axis_angle(&Vector3::x_axis(), -angle_hip);
    
    if let Some(hip_bone) = skeleton.bones.get_mut(&hip_id) {
        hip_bone.local_rotation = initial_hip_rot * hip_bend_rot;
    }
    
    // --- 7. 更新 FK ---
    // 局部旋轉被修改後，需要重新計算全域座標
    skeleton.update_fk_from(hip_id);
    
    Ok(())
}
