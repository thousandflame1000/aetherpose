use crate::skeleton::SkeletonModel;

/// 簡易的地面約束，防止腳部穿過 Y=0 的平面
pub fn apply_ground_constraint(skeleton: &mut SkeletonModel) {
    // 遍歷左右腳
    for bone_id in [12, 22] { // 12: L_Foot, 22: R_Foot
        if let Some(bone) = skeleton.bones.get_mut(&bone_id) {
            // 直接修改 global_position 是一個比較粗糙的做法
            // 未來的版本應該透過調整膝蓋和髖關節的旋轉來達成
            if bone.global_position.y < 0.0 {
                bone.global_position.y = 0.0;
            }
        }
    }
}
