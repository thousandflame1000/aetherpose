#![allow(dead_code)]

use crate::skeleton::bone::{Bone, BoneId};
use nalgebra::{UnitQuaternion, Vector3};
use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct SkeletonModel {
    pub bones: HashMap<BoneId, Bone>,
    /// 儲存骨骼的親子關係 (Parent -> Children)，用於快速遍歷子樹
    pub children: HashMap<BoneId, Vec<BoneId>>,
}

impl Default for SkeletonModel {
    fn default() -> Self {
        Self::new()
    }
}

impl SkeletonModel {
    pub fn new() -> Self {
        Self {
            bones: HashMap::new(),
            children: HashMap::new(),
        }
    }

}

impl SkeletonModel {
    pub fn add_bone(&mut self, bone: Bone) {
        if let Some(parent_id) = bone.parent_id {
            self.children.entry(parent_id).or_default().push(bone.id);
        }
        self.bones.insert(bone.id, bone);
    }

    // 建立標準人體骨架 (簡化版)
    pub fn new_humanoid() -> Self {
        let mut skel = Self::new();

        // 輔助函式：將角度轉為弧度
        let rad = |deg: f32| deg.to_radians();

        // 定義骨頭 ID
        // 0: Hip, 1: Waist, 2: Chest, 3: Neck, 4: Head
        // 10: L_UpLeg, 11: L_Leg, 12: L_Foot
        // 20: R_UpLeg, 21: R_Leg, 22: R_Foot
        // 30: L_Shoulder, 31: L_UpperArm, 32: L_ForeArm
        // 40: R_Shoulder, 41: R_UpperArm, 42: R_ForeArm, 43: R_Hand

        // Root (Hip)
        skel.add_bone(Bone::new(
            0,
            "Hip".to_string(),
            None,
            Vector3::new(0.0, 1.0, 0.0),
            None,
            None,
        ));

        // Spine
        skel.add_bone(Bone::new(
            1,
            "Waist".to_string(),
            Some(0),
            Vector3::new(0.0, 0.15, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            2,
            "Chest".to_string(),
            Some(1),
            Vector3::new(0.0, 0.25, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            3,
            "Neck".to_string(),
            Some(2),
            Vector3::new(0.0, 0.20, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            4,
            "Head".to_string(),
            Some(3),
            Vector3::new(0.0, 0.15, 0.0),
            None,
            None,
        ));

        // --- 腿部關節限制 ---
        // 膝蓋 (Knee): 鉸鏈關節，假設繞 X 軸旋轉。
        // 限制只能向後彎曲 (例如 -150度 到 0度)，避免膝蓋反折。
        // Y 和 Z 軸給予很小的容許範圍，保持穩定。
        let knee_min = Some(Vector3::new(rad(-150.0), rad(-5.0), rad(-5.0)));
        let knee_max = Some(Vector3::new(rad(0.0), rad(5.0), rad(5.0)));

        // Legs
        skel.add_bone(Bone::new(
            10,
            "L_UpLeg".to_string(),
            Some(0),
            Vector3::new(-0.15, -0.1, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            11,
            "L_Leg".to_string(),
            Some(10),
            Vector3::new(0.0, -0.4, 0.0),
            knee_min,
            knee_max,
        ));
        skel.add_bone(Bone::new(
            12,
            "L_Foot".to_string(),
            Some(11),
            Vector3::new(0.0, -0.4, 0.0),
            None,
            None,
        ));

        skel.add_bone(Bone::new(
            20,
            "R_UpLeg".to_string(),
            Some(0),
            Vector3::new(0.15, -0.1, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            21,
            "R_Leg".to_string(),
            Some(20),
            Vector3::new(0.0, -0.4, 0.0),
            knee_min,
            knee_max,
        ));
        skel.add_bone(Bone::new(
            22,
            "R_Foot".to_string(),
            Some(21),
            Vector3::new(0.0, -0.4, 0.0),
            None,
            None,
        ));

        // --- 手臂關節限制 ---
        // 手肘 (Elbow): 鉸鏈關節。
        // 這裡假設主要繞 Y 軸彎曲 (視 T-Pose 的座標系定義而定)，給予較寬的範圍測試。
        let elbow_min = Some(Vector3::new(rad(-10.0), rad(0.0), rad(-10.0)));
        let elbow_max = Some(Vector3::new(rad(10.0), rad(160.0), rad(10.0)));

        // Arms
        skel.add_bone(Bone::new(
            30,
            "L_Shoulder".to_string(),
            Some(3),
            Vector3::new(-0.1, -0.05, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            31,
            "L_UpperArm".to_string(),
            Some(30),
            Vector3::new(-0.15, 0.0, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            32,
            "L_ForeArm".to_string(),
            Some(31),
            Vector3::new(-0.25, 0.0, 0.0),
            elbow_min,
            elbow_max,
        ));
        skel.add_bone(Bone::new(
            33,
            "L_Hand".to_string(),
            Some(32),
            Vector3::new(-0.1, 0.0, 0.0),
            None,
            None,
        )); // 新增左手

        skel.add_bone(Bone::new(
            40,
            "R_Shoulder".to_string(),
            Some(3),
            Vector3::new(0.1, -0.05, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            41,
            "R_UpperArm".to_string(),
            Some(40),
            Vector3::new(0.15, 0.0, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            42,
            "R_ForeArm".to_string(),
            Some(41),
            Vector3::new(0.25, 0.0, 0.0),
            elbow_min,
            elbow_max,
        ));
        skel.add_bone(Bone::new(
            43,
            "R_Hand".to_string(),
            Some(42),
            Vector3::new(0.1, 0.0, 0.0),
            None,
            None,
        )); // 新增右手

        skel
    }

    // 正向運動學 (Forward Kinematics): 從 Local 計算 Global
    pub fn update_fk(&mut self) {
        // 簡單的層級遍歷 (這裡用寫死的順序以求效能與簡單)
        let update_order = vec![
            0, 1, 2, 3, 4, 10, 11, 12, 20, 21, 22, 30, 31, 32, 33, 40, 41, 42, 43,
        ];

        for id in update_order {
            if let Some(bone) = self.bones.get(&id).cloned() {
                let (parent_pos, parent_rot) = if let Some(pid) = bone.parent_id {
                    let p = self.bones.get(&pid).unwrap();
                    (p.global_position, p.global_rotation)
                } else {
                    (Vector3::zeros(), UnitQuaternion::identity()) // World Origin
                };

                let current = self.bones.get_mut(&id).unwrap();
                current.global_rotation = parent_rot * current.local_rotation;
                current.global_position =
                    parent_pos + (current.global_rotation * current.local_position);
            }
        }
    }

    /// 取得骨骼的長度 (其 local_position 的範數)
    pub fn get_bone_length(&self, bone_id: BoneId) -> Option<f32> {
        self.bones.get(&bone_id).map(|b| b.local_position.norm())
    }

    /// 從指定的骨骼開始，更新其子鏈的正向運動學 (FK)
    pub fn update_fk_from(&mut self, start_bone_id: BoneId) {
        let mut stack = vec![start_bone_id];

        while let Some(id) = stack.pop() {
            // 1. 取得父骨骼的 Global Transform (為了借用檢查，需在獨立區塊讀取)
            let (parent_pos, parent_rot) = {
                let bone = match self.bones.get(&id) {
                    Some(b) => b,
                    None => continue,
                };

                if let Some(pid) = bone.parent_id {
                    if let Some(p) = self.bones.get(&pid) {
                        (p.global_position, p.global_rotation)
                    } else {
                        (Vector3::zeros(), UnitQuaternion::identity())
                    }
                } else {
                    (Vector3::zeros(), UnitQuaternion::identity())
                }
            };

            // 2. 更新當前骨骼
            if let Some(current) = self.bones.get_mut(&id) {
                current.global_rotation = parent_rot * current.local_rotation;
                current.global_position =
                    parent_pos + (current.global_rotation * current.local_position);
            }

            // 3. 將子骨骼加入堆疊以繼續遍歷
            if let Some(child_ids) = self.children.get(&id) {
                stack.extend(child_ids);
            }
        }
    }

    /// Traverses from the given bone up to the root, executing a closure on each bone.
    /// This is required by the IK solver to build the Jacobian chain.
    pub fn for_each_parent_bone<F>(&self, start_bone_id: BoneId, mut action: F)
    where
        F: FnMut(&Bone),
    {
        let mut current_id_opt = Some(start_bone_id);
        while let Some(current_id) = current_id_opt {
            if let Some(bone) = self.bones.get(&current_id) {
                action(bone);
                current_id_opt = bone.parent_id;
            } else {
                break; // Should not happen in a valid skeleton
            }
        }
    }

    // The solver uses "joint" terminology, so we provide wrappers.
    // In our model, a bone's state represents the joint at its base.

    pub fn get_joint_position(&self, bone_id: BoneId) -> Option<Vector3<f32>> {
        self.bones.get(&bone_id).map(|b| b.global_position)
    }

    pub fn get_joint_rotation(&self, bone_id: BoneId) -> Option<UnitQuaternion<f32>> {
        self.bones.get(&bone_id).map(|b| b.global_rotation)
    }

    /// 調整骨架比例
    /// 這是一個簡化的實作，假設骨架結構是標準的 new_humanoid 結構。
    pub fn adjust_proportions(&mut self, leg_scale: f32, arm_scale: f32, spine_scale: f32) {
        // 定義基礎長度 (必須與 new_humanoid 中的數值一致)
        // 脊椎: 主要沿 Y 軸生長
        let base_spine = [
            (1, Vector3::new(0.0, 0.15, 0.0)), // Waist
            (2, Vector3::new(0.0, 0.25, 0.0)), // Chest
            (3, Vector3::new(0.0, 0.20, 0.0)), // Neck
            (4, Vector3::new(0.0, 0.15, 0.0)), // Head
        ];

        // 腿部:
        // UpLeg (10, 20) 包含髖部寬度(X)與垂直偏移(Y)。我們通常只想縮放 Y (長度)。
        // Leg/Foot (11, 12, 21, 22) 是肢體長度，通常沿 Y 軸負方向。
        let base_legs = [
            (10, Vector3::new(-0.15, -0.1, 0.0)), // L_UpLeg (Hip offset + length mixed, simplified)
            (11, Vector3::new(0.0, -0.4, 0.0)),   // L_Leg
            (12, Vector3::new(0.0, -0.4, 0.0)),   // L_Foot
            (20, Vector3::new(0.15, -0.1, 0.0)),  // R_UpLeg
            (21, Vector3::new(0.0, -0.4, 0.0)),   // R_Leg
            (22, Vector3::new(0.0, -0.4, 0.0)),   // R_Foot
        ];

        // 手臂:
        // Shoulder (30, 40) 是肩膀寬度，通常不隨手長改變。
        // UpperArm/ForeArm (31, 32, 41, 42) 是手臂長度，沿 X 軸。
        let base_arms = [
            // (30, Vector3::new(-0.1, -0.05, 0.0)),  // L_Shoulder (不縮放，保持肩寬)
            (31, Vector3::new(-0.15, 0.0, 0.0)), // L_UpperArm
            (32, Vector3::new(-0.25, 0.0, 0.0)), // L_ForeArm
            // (40, Vector3::new(0.1, -0.05, 0.0)),   // R_Shoulder (不縮放，保持肩寬)
            (41, Vector3::new(0.15, 0.0, 0.0)), // R_UpperArm
            (42, Vector3::new(0.25, 0.0, 0.0)), // R_ForeArm
        ];

        // 應用脊椎縮放 (Uniform)
        for (id, base) in &base_spine {
            if let Some(bone) = self.bones.get_mut(id) {
                bone.local_position = *base * spine_scale;
            }
        }

        // 應用腿部縮放 (非 Uniform: 保持 X 寬度，縮放 Y 長度)
        for (id, base) in &base_legs {
            if let Some(bone) = self.bones.get_mut(id) {
                // 如果是 UpLeg (10, 20)，保持 X (寬度) 不變
                if *id == 10 || *id == 20 {
                    bone.local_position = Vector3::new(base.x, base.y * leg_scale, base.z);
                } else {
                    bone.local_position = *base * leg_scale;
                }
            }
        }

        // 應用手臂縮放 (Uniform，但不包含肩膀)
        for (id, base) in &base_arms {
            if let Some(bone) = self.bones.get_mut(id) {
                bone.local_position = *base * arm_scale;
            }
        }
    }

    /// 設定大腿與小腿的長度比例 (Thigh / Shin)
    /// 保持總腿長不變，重新分配膝蓋的位置。
    pub fn set_leg_ratio(&mut self, ratio: f32) {
        let adjust_leg = |bones: &mut HashMap<BoneId, Bone>,
                          _upleg_id: BoneId,
                          leg_id: BoneId,
                          foot_id: BoneId,
                          ratio: f32|
         -> Option<()> {
            // 取得目前的骨骼 (注意：UpLeg 的長度是由 Leg 的 local_position 決定的)
            let leg_bone = bones.get(&leg_id)?;
            let foot_bone = bones.get(&foot_id)?;

            let thigh_len = leg_bone.local_position.norm();
            let shin_len = foot_bone.local_position.norm();
            let total_len = thigh_len + shin_len;

            if total_len < 1e-4 {
                return None;
            }

            // 計算新的長度
            // ratio = thigh / shin  => thigh = ratio * shin
            // total = (ratio + 1) * shin
            let new_shin_len = total_len / (ratio + 1.0);
            let new_thigh_len = total_len - new_shin_len;

            // 更新 Leg (膝蓋) 的位置 -> 影響大腿長度
            if let Some(b) = bones.get_mut(&leg_id) {
                if let Some(dir) = b.local_position.try_normalize(1e-6) {
                    b.local_position = dir * new_thigh_len;
                }
            }
            // 更新 Foot (腳踝) 的位置 -> 影響小腿長度
            if let Some(b) = bones.get_mut(&foot_id) {
                if let Some(dir) = b.local_position.try_normalize(1e-6) {
                    b.local_position = dir * new_shin_len;
                }
            }
            Some(())
        };

        adjust_leg(&mut self.bones, 10, 11, 12, ratio); // 左腿
        adjust_leg(&mut self.bones, 20, 21, 22, ratio); // 右腿
        self.update_fk();
    }
}
