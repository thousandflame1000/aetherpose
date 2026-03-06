use crate::ik::goals::Goal;
use crate::skeleton::model::SkeletonModel;
use nalgebra::{UnitQuaternion, Vector3};

/// A simple IK solver that uses CCD for position goals and a geometric
/// approach for pole vector goals.
pub struct IkSolver {
    iterations: usize,
    threshold: f32, // 誤差閾值 (公尺)，低於此值則提前結束迭代
}

impl Default for IkSolver {
    fn default() -> Self {
        Self::new()
    }
}

impl IkSolver {
    pub fn new() -> Self {
        Self {
            iterations: 10,   // 10 次迭代在效能和精度之間取得了不錯的平衡
            threshold: 0.001, // 1mm 精度
        }
    }

    /// Solves the IK for the given skeleton based on a set of goals.
    pub fn solve(&mut self, skeleton: &mut SkeletonModel, goals: &[Goal]) {
        // 為了清晰起見，將目標分類。在追求極致效能的場景下，可以只遍歷一次。
        let position_goals: Vec<&Goal> = goals
            .iter()
            .filter(|g| matches!(g, Goal::Position { .. }))
            .collect();
        let pole_goals: Vec<&Goal> = goals
            .iter()
            .filter(|g| matches!(g, Goal::Pole { .. }))
            .collect();
        let rotation_goals: Vec<&Goal> = goals
            .iter()
            .filter(|g| matches!(g, Goal::Rotation { .. }))
            .collect();

        // --- 主要迭代迴圈 ---
        for _i in 0..self.iterations {
            let mut solved = true;

            // 1. 優先處理位置目標 (手、腳)
            for goal in &position_goals {
                if let Goal::Position {
                    bone_id,
                    target_position,
                    weight,
                } = goal
                {
                    if *weight > 0.0 {
                        // 這裡的權重暫時未使用，一個完整的實作會根據權重調整旋轉角度
                        self.solve_ccd_pass(skeleton, *bone_id, *target_position);

                        // 檢查誤差是否已滿足閾值
                        if let Some(current_pos) = skeleton.get_joint_position(*bone_id) {
                            if (target_position - current_pos).norm_squared()
                                > self.threshold * self.threshold
                            {
                                solved = false;
                            }
                        }
                    }
                }
            }

            // 2. 處理極向量目標 (膝蓋、手肘)
            for goal in &pole_goals {
                if let Goal::Pole {
                    middle_joint_id,
                    end_effector_id,
                    pole_target_position,
                    weight,
                } = goal
                {
                    if *weight > 0.0 {
                        self.solve_pole_vector_pass(
                            skeleton,
                            *middle_joint_id,
                            *end_effector_id,
                            *pole_target_position,
                        );
                    }
                }
            }

            // 3. [新增] 應用關節限制
            self.apply_joint_limits(skeleton);

            if solved {
                break;
            }
        }

        // --- 後處理步驟 ---
        // 3. 應用旋轉目標 (臀部、胸部等)
        // 這些目標在位置確定後應用，作為最終的姿態調整。
        for goal in &rotation_goals {
            if let Goal::Rotation {
                bone_id,
                target_rotation,
                weight,
            } = goal
            {
                if *weight > 0.0 {
                    // 先取得父骨骼的旋轉 (如果有的話)，避免同時借用 skeleton.bones
                    let parent_rotation = if let Some(bone) = skeleton.bones.get(bone_id) {
                        bone.parent_id
                            .and_then(|pid| skeleton.bones.get(&pid).map(|p| p.global_rotation))
                    } else {
                        None
                    };

                    if let Some(bone) = skeleton.bones.get_mut(bone_id) {
                        // 直接設定其 Local Rotation。這假設其父骨骼的姿態已經被 IK 或其他目標確定。
                        if let Some(p_rot) = parent_rotation {
                            bone.local_rotation = p_rot.inverse() * *target_rotation;
                        } else {
                            bone.local_rotation = *target_rotation;
                        }
                    }
                }
            }
        }

        // 4. 最終執行一次正向運動學，確保所有骨骼的 Global Transform 都是最新的。
        skeleton.update_fk();
    }

    /// 執行一次循環座標下降法 (CCD) 來將 `end_effector_id` 移向 `target_pos`。
    fn solve_ccd_pass(
        &self,
        skeleton: &mut SkeletonModel,
        end_effector_id: u8,
        target_pos: Vector3<f32>,
    ) {
        const CHAIN_LEN: usize = 5; // 限制鏈的長度，避免影響到全身

        let mut bones_to_update = Vec::new();
        let mut current_bone_id_opt = Some(end_effector_id);

        // 從末端開始，向上遍歷父骨骼，收集構成 IK 鏈的骨骼。
        for _ in 0..CHAIN_LEN {
            if let Some(current_bone_id) = current_bone_id_opt {
                if let Some(bone) = skeleton.bones.get(&current_bone_id) {
                    if let Some(parent_id) = bone.parent_id {
                        bones_to_update.push(parent_id);
                        current_bone_id_opt = Some(parent_id);
                    } else {
                        break;
                    } // 到達根部
                } else {
                    break;
                }
            } else {
                break;
            }
        }

        // 從最靠近根部的骨骼開始，依次旋轉，將末端對準目標。
        for bone_id in bones_to_update {
            let end_effector_pos = skeleton.get_joint_position(end_effector_id).unwrap();
            let current_joint_pos = skeleton.get_joint_position(bone_id).unwrap();

            // 計算從當前關節到末端和目標的向量
            let to_end = (end_effector_pos - current_joint_pos).normalize();
            let to_target = (target_pos - current_joint_pos).normalize();

            // 計算使 `to_end` 對齊 `to_target` 所需的旋轉
            if let Some(rot) = UnitQuaternion::rotation_between(&to_end, &to_target) {
                if let Some(bone) = skeleton.bones.get_mut(&bone_id) {
                    // 應用旋轉到 Local Rotation
                    bone.local_rotation = rot * bone.local_rotation;
                    bone.local_rotation.renormalize();
                }
                // 立即更新子鏈的 FK，以便下一次迭代計算正確的位置
                skeleton.update_fk_from(bone_id);
            }
        }
    }

    /// 執行一次極向量解算，以控制肢體的彎曲方向。
    fn solve_pole_vector_pass(
        &self,
        skeleton: &mut SkeletonModel,
        middle_joint_id: u8,
        end_effector_id: u8,
        pole_target_pos: Vector3<f32>,
    ) {
        // 1. 獲取肢體鏈的三個關鍵關節ID：根部、中間、末端。
        let limb_root_bone_id = match skeleton
            .bones
            .get(&middle_joint_id)
            .and_then(|b| b.parent_id)
        {
            Some(id) => id,
            None => return, // 中間關節沒有父節點，不是一個有效的肢體。
        };

        // 2. 獲取關節的當前世界座標。
        let (root_pos, mid_pos, end_pos) = match (
            skeleton.get_joint_position(limb_root_bone_id),
            skeleton.get_joint_position(middle_joint_id),
            skeleton.get_joint_position(end_effector_id),
        ) {
            (Some(r), Some(m), Some(e)) => (r, m, e),
            _ => return, // 找不到任何一個關節
        };

        // 3. 計算當前肢體平面與目標平面的法線。
        let limb_vec = end_pos - root_pos;

        let current_plane_normal = (mid_pos - root_pos).cross(&limb_vec);
        let target_plane_normal = (pole_target_pos - root_pos).cross(&limb_vec);

        // 4. 計算將當前平面旋轉至目標平面所需的旋轉量。
        if let (Some(current_normal), Some(target_normal)) = (
            current_plane_normal.try_normalize(1e-6),
            target_plane_normal.try_normalize(1e-6),
        ) {
            if let Some(correction_rot) =
                UnitQuaternion::rotation_between(&current_normal, &target_normal)
            {
                // 5. 將此旋轉應用於肢體的根部骨骼 (如上臂、大腿)。
                if let Some(root_bone) = skeleton.bones.get_mut(&limb_root_bone_id) {
                    root_bone.local_rotation = correction_rot * root_bone.local_rotation;
                    root_bone.local_rotation.renormalize();
                }

                // 6. 更新子鏈的 FK，使旋轉生效。
                skeleton.update_fk_from(limb_root_bone_id);
            }
        }
    }

    /// 應用骨架模型中定義的關節限制 (Joint Limits)。
    /// 這會防止膝蓋反折或手肘過度彎曲。
    fn apply_joint_limits(&self, skeleton: &mut SkeletonModel) {
        let mut any_changed = false;

        // 遍歷所有骨骼，檢查並應用限制
        for bone in skeleton.bones.values_mut() {
            // 如果沒有定義限制，則跳過
            if bone.min_local_rotation_axis_angle.is_none()
                && bone.max_local_rotation_axis_angle.is_none()
            {
                continue;
            }

            let min_limit = bone
                .min_local_rotation_axis_angle
                .unwrap_or(Vector3::from_element(-std::f32::consts::PI));
            let max_limit = bone
                .max_local_rotation_axis_angle
                .unwrap_or(Vector3::from_element(std::f32::consts::PI));

            let (r, p, y) = bone.local_rotation.euler_angles();

            let clamped_r = r.clamp(min_limit.x, max_limit.x);
            let clamped_p = p.clamp(min_limit.y, max_limit.y);
            let clamped_y = y.clamp(min_limit.z, max_limit.z);

            if (r - clamped_r).abs() > 1e-4
                || (p - clamped_p).abs() > 1e-4
                || (y - clamped_y).abs() > 1e-4
            {
                bone.local_rotation =
                    UnitQuaternion::from_euler_angles(clamped_r, clamped_p, clamped_y);
                any_changed = true;
            }
        }

        if any_changed {
            skeleton.update_fk();
        }
    }
}
