#![allow(dead_code)]

use crate::{
    ik::goals::Goal,
    imu::calibration::MagCalibration, // 引入磁力計校準
    net::tracker::Tracker,
    skeleton::model::SkeletonModel,
    smoothing::OneEuroFilter, // 引入姿態平滑濾波器
};
use nalgebra::{UnitQuaternion, Vector3};
use std::collections::HashMap;
use crate::imu::drift::ZuptDetector;

/// FusionEngine is responsible for interpreting sensor data (trackers)
/// and converting it into a set of weighted goals for the IK solver.
/// This is the "brain" of the evidence-driven system.
use crate::fusion::assignment::TrackerBoneAssigner;
use crate::fusion::confidence; // Add this
use crate::fusion::weighting;

pub struct FusionEngine {
    pub assigner: TrackerBoneAssigner,
    pub calibration_offsets: HashMap<u8, UnitQuaternion<f32>>,
    // --- [新增] 內部狀態管理 ---
    filters: HashMap<u8, OneEuroFilter>,
    pub smoothing_min_cutoff: f32,
    pub smoothing_beta: f32,
    pub drift_correction: f32,
    // ZUPT state (optional, for runtime parameter updates)
    _zupt_offsets: HashMap<u8, UnitQuaternion<f32>>,
    zupt_detectors: HashMap<u8, ZuptDetector>,
    zupt_window_size: usize,
    zupt_accel_var_threshold: f32,
    zupt_gyro_threshold: f32,
    // last rotations for approximate angular velocity estimation
    last_rotations: HashMap<u8, UnitQuaternion<f32>>,
    // --- [新增] 磁力計校準狀態 ---
    pub mag_calibrations: HashMap<u8, MagCalibration>,
    pub mag_calibration_points: HashMap<u8, Vec<Vector3<f32>>>,
    pub mag_calibration_active: HashMap<u8, bool>,
    // --- [新增] 腿部校準狀態 ---
    is_leg_calibrating: bool,
    leg_calibration_data: Vec<(f32, UnitQuaternion<f32>, UnitQuaternion<f32>)>, // (HeadY, UpLegRot, LegRot)
}

/// Represents an authoritative pose from a source like a VR headset or controllers.
pub struct AuthoritativePose {
    pub position: Vector3<f32>,
    pub rotation: UnitQuaternion<f32>,
}

/// A mock representation of a single sensor tracker.
pub(crate) struct MockTracker {
    pub position: Vector3<f32>,
    pub rotation: UnitQuaternion<f32>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use nalgebra::{UnitQuaternion, Vector3};

    #[test]
    fn construct_mocktracker() {
        let _m = MockTracker {
            position: Vector3::zeros(),
            rotation: UnitQuaternion::identity(),
        };
        // ensure it compiles and fields are accessible
        assert_eq!(_m.position, Vector3::zeros());
        assert_eq!(_m.rotation, UnitQuaternion::identity());
    }
}

impl FusionEngine {
    pub fn new() -> Self {
        Self {
            assigner: TrackerBoneAssigner::new(),
            calibration_offsets: HashMap::new(),
            // --- [新增] 初始化狀態 ---
            filters: HashMap::new(),
            smoothing_min_cutoff: 1.0, // 預設值
            smoothing_beta: 0.5,       // 預設值
            drift_correction: 0.0,     // 預設值
            _zupt_offsets: HashMap::new(),
            zupt_detectors: HashMap::new(),
            zupt_window_size: 8,
            zupt_accel_var_threshold: 0.0005,
            zupt_gyro_threshold: 0.02,
            last_rotations: HashMap::new(),
            mag_calibrations: HashMap::new(),
            mag_calibration_points: HashMap::new(),
            mag_calibration_active: HashMap::new(),
            is_leg_calibrating: false,
            leg_calibration_data: Vec::new(),
        }
    }

    /// Processes tracker data and generates IK goals.
    /// This is the main entry point for the fusion logic.
    ///
    /// # Arguments
    /// * `skeleton` - The current state of the skeleton.
    /// * `trackers` - A map of available trackers from the network.
    /// * `quest_head` - Optional authoritative pose for the head.
    ///
    /// # Returns
    /// A vector of `Goal`s for the IK solver.
    pub fn process(
        &mut self, // 改為 &mut self 以更新內部狀態 (如 filter)
        skeleton: &SkeletonModel,
        trackers: &HashMap<u8, Tracker>, // Changed i32 to u8 here
        quest_head: Option<&AuthoritativePose>,
        quest_left_hand: Option<&AuthoritativePose>,
        quest_right_hand: Option<&AuthoritativePose>,
    ) -> Vec<Goal> {
        let mut generated_goals = Vec::new();

        // --- 1. Process Authoritative Sources (Hard Constraints) ---
        // These goals get a very high weight to "lock" the bones in place.
        const AUTHORITY_WEIGHT: f32 = 100.0;

        if let Some(head) = quest_head {
            // VRChat Bone ID for Head is 4
            generated_goals.push(Goal::Rotation {
                bone_id: 4,
                target_rotation: head.rotation,
                weight: AUTHORITY_WEIGHT,
            });
            generated_goals.push(Goal::Position {
                // Position goals are crucial for authoritative sources
                bone_id: 4,
                target_position: head.position,
                weight: AUTHORITY_WEIGHT,
            });
        }

        // 處理左手 (Left Hand) - 假設 Bone ID 為 33 (視你的骨架定義而定，通常 31:UpArm, 32:ForeArm, 33:Hand)
        if let Some(l_hand) = quest_left_hand {
            generated_goals.push(Goal::Rotation {
                bone_id: 33,
                target_rotation: l_hand.rotation,
                weight: AUTHORITY_WEIGHT,
            });
            generated_goals.push(Goal::Position {
                bone_id: 33,
                target_position: l_hand.position,
                weight: AUTHORITY_WEIGHT,
            });
        }

        // 處理右手 (Right Hand) - 假設 Bone ID 為 43
        if let Some(r_hand) = quest_right_hand {
            generated_goals.push(Goal::Rotation {
                bone_id: 43,
                target_rotation: r_hand.rotation,
                weight: AUTHORITY_WEIGHT,
            });
            generated_goals.push(Goal::Position {
                bone_id: 43,
                target_position: r_hand.position,
                weight: AUTHORITY_WEIGHT,
            });
        }

        for (tracker_id, tracker) in trackers.iter() {
            if let Some(bone_id) = self.assigner.get_bone_id(*tracker_id) {
                if let Some(quat) = tracker.quat {
                    // 計算信心度與權重
                    let confidence = confidence::calculate_confidence(tracker, 1000); // 1 second
                    let weight = weighting::calculate_weight(confidence);

                    // --- 姿態處理流程 ---
                    // 1. 原始四元數
                    let raw_rotation = UnitQuaternion::new_normalize(nalgebra::Quaternion::new(
                        quat[3], quat[0], quat[1], quat[2],
                    ));

                    // 2. 應用姿態平滑 (One Euro Filter)
                    let filter = self.filters.entry(*tracker_id).or_insert_with(|| {
                        OneEuroFilter::new(self.smoothing_min_cutoff, self.smoothing_beta)
                    });
                    filter.update_params(self.smoothing_min_cutoff, self.smoothing_beta);
                    let smoothed_rotation = filter.filter(raw_rotation);

                    // 3. 應用掛載校準 (Mounting Offset)
                    let target_rotation = match self.calibration_offsets.get(tracker_id) {
                        Some(offset) => offset * smoothed_rotation,
                        None => raw_rotation,
                    };

                    // 4. 應用漂移補償 (Drift Correction)
                    let final_rotation = self.apply_drift_correction(bone_id, target_rotation, quest_head);

                    // --- 5. 產生 IK 目標 (Rotation 或 Pole) ---
                    if let Some(goal) = self.make_pole_goal(skeleton, bone_id, final_rotation, weight) {
                        generated_goals.push(goal);
                    } else {
                        generated_goals.push(self.make_rotation_goal(bone_id, final_rotation, weight));
                    }

                    // 5. 處理磁力計校準數據收集
                    self.collect_mag_point(*tracker_id, tracker);

                    // 6. 處理腿部校準數據收集
                    // 我們需要同時收集頭部高度 (來自 Quest) 和左腿的旋轉 (來自 IMU)
                    if self.is_leg_calibrating {
                        if let Some(_head) = quest_head {
                            // 檢查是否收集到了左大腿 (10) 和左小腿 (11) 的數據
                            // 這裡我們簡單地在迴圈中檢查，這意味著每一幀可能會多次嘗試 push，
                            // 但由於我們需要成對的數據，我們應該在迴圈外處理，或者這裡簡化處理：
                            // 為了效率，我們只在處理到 "左小腿 (11)" 時，去回溯找 "左大腿 (10)" 的資料。
                            // 但由於 trackers 是 HashMap 迭代順序不固定，最好的方法是在 process 的最後統一收集。
                            // 暫時我們先略過這裡，改在 process 函數的最後面統一處理。
                        }
                    }
                } else {
                    // Tracker 存在但沒有旋轉數據
                }
            } else {
                log::warn!("No bone assigned for Tracker ID: {}", tracker_id);
            }
        }

        // --- 統一收集腿部校準數據 ---
        self.collect_leg_calibration(trackers, quest_head);

        generated_goals
    }

    // --- [新增] 從 main.rs 移入的管理方法 ---

    pub fn start_mag_calibration(&mut self, tracker_id: u8) {
        self.mag_calibration_active.insert(tracker_id, true);
        self.mag_calibration_points
            .entry(tracker_id)
            .or_default()
            .clear();
        log::info!("開始對 Tracker #{} 進行磁力計校準", tracker_id);
    }

    pub fn stop_mag_calibration(&mut self, tracker_id: u8) {
        self.mag_calibration_active.insert(tracker_id, false);
        if let Some(points) = self.mag_calibration_points.get(&tracker_id) {
            if let Some(calib) = MagCalibration::calibrate(points) {
                log::info!("Tracker #{} 磁力計校準完成", tracker_id);
                self.mag_calibrations.insert(tracker_id, calib);
            } else {
                log::error!("Tracker #{} 磁力計校準失敗：數據不足或無效", tracker_id);
            }
        }
    }

    pub fn start_leg_calibration(&mut self) {
        self.is_leg_calibrating = true;
        self.leg_calibration_data.clear();
        log::info!("開始腿部比例校準...");
    }

    pub fn stop_leg_calibration(&mut self, total_leg_length: f32) -> Option<f32> {
        self.is_leg_calibrating = false;
        if self.leg_calibration_data.is_empty() {
            log::warn!("腿部校準失敗：沒有收集到數據");
            return None;
        }

        // 1. 找出站立幀 (Max Y) 和 蹲下幀 (Min Y)
        let mut max_y = -f32::INFINITY;
        let mut min_y = f32::INFINITY;
        let mut stand_frame = None;
        let mut squat_frame = None;

        for frame in &self.leg_calibration_data {
            if frame.0 > max_y {
                max_y = frame.0;
                stand_frame = Some(frame);
            }
            if frame.0 < min_y {
                min_y = frame.0;
                squat_frame = Some(frame);
            }
        }

        let stand = stand_frame?;
        let squat = squat_frame?;
        let delta_h = max_y - min_y;

        if delta_h < 0.15 {
            // 至少要有 15cm 的高度變化
            log::warn!("腿部校準失敗：高度變化不足 ({:.2}m)，請蹲深一點", delta_h);
            return None;
        }

        // 2. 計算垂直投影因子 (Vertical Projection Factor)
        // 骨頭向量在 Local 空間是 (0, -1, 0) (向下)
        // 我們計算它在 Global Y 軸上的投影長度比例 (即 cos(theta))
        let get_vertical_factor = |rot: &UnitQuaternion<f32>| -> f32 {
            let bone_vec = rot * Vector3::new(0.0, -1.0, 0.0);
            bone_vec.y.abs() // 取絕對值，因為我們只關心垂直長度分量
        };

        let u_t_stand = get_vertical_factor(&stand.1); // 大腿站立
        let u_s_stand = get_vertical_factor(&stand.2); // 小腿站立
        let u_t_squat = get_vertical_factor(&squat.1); // 大腿蹲下
        let u_s_squat = get_vertical_factor(&squat.2); // 小腿蹲下

        // 3. 解方程式求 Ratio (R)
        // 公式推導：
        // Delta_H = L_total * ( (R * term_t + term_s) / (R + 1) )
        // R = (L_total * term_s - Delta_H) / (Delta_H - L_total * term_t)

        let term_t = u_t_stand - u_t_squat;
        let term_s = u_s_stand - u_s_squat;

        let numerator = total_leg_length * term_s - delta_h;
        let denominator = delta_h - total_leg_length * term_t;

        if denominator.abs() < 1e-4 {
            return None;
        }

        let r = numerator / denominator;

        if r > 0.2 && r < 3.0 {
            // 合理範圍檢查
            log::info!("腿部校準成功！計算出的比例 (大腿/小腿): {:.3}", r);
            return Some(r);
        }

        log::warn!("腿部校準計算出異常比例: {:.3}，請重試", r);
        None
    }

    pub fn auto_assign(&mut self, trackers: &HashMap<u8, Tracker>) {
        let mut sorted_ids: Vec<u8> = trackers.keys().cloned().collect();
        sorted_ids.sort();

        // 定義分配優先順序 (根據常見的 VRChat 全身追蹤配置)
        // 優先順序：Hip -> L.Foot -> R.Foot -> Chest -> L.Knee -> R.Knee -> L.Elbow -> R.Elbow
        let priority_bones = [
            0,  // Hip
            12, // L.Foot
            22, // R.Foot
            2,  // Chest
            11, // L.Leg (Knee)
            21, // R.Leg (Knee)
            32, // L.ForeArm (Elbow)
            42, // R.ForeArm (Elbow)
        ];

        self.assigner.map.clear();

        for (i, &tracker_id) in sorted_ids.iter().enumerate() {
            if i < priority_bones.len() {
                let bone_id = priority_bones[i];
                self.assigner.set_assignment(tracker_id, bone_id);
                log::info!(
                    "Auto Assigned Tracker #{} to Bone ID {}",
                    tracker_id,
                    bone_id
                );
            } else {
                log::warn!(
                    "Tracker #{} could not be auto-assigned (no more slots)",
                    tracker_id
                );
            }
        }
    }

    /// 重置所有追蹤器的 Yaw 軸 (歸零方向)
    pub fn reset_yaw(&mut self, trackers: &HashMap<u8, Tracker>) {
        for (id, tracker) in trackers {
            if let Some(quat) = tracker.quat {
                let rot = UnitQuaternion::new_normalize(nalgebra::Quaternion::new(
                    quat[3], quat[0], quat[1], quat[2],
                ));

                // 提取 Yaw (繞 Y 軸的旋轉)
                // 假設 Forward 是 Z+ (0, 0, 1)，Up 是 Y+ (0, 1, 0)
                let forward = Vector3::z();
                let rotated_forward = rot * forward;

                // 投影到 XZ 平面 (Y=0)
                let flat_forward = Vector3::new(rotated_forward.x, 0.0, rotated_forward.z);

                if let Some(normalized_flat) = flat_forward.try_normalize(1e-6) {
                    let yaw_rot = UnitQuaternion::rotation_between(&Vector3::z(), &normalized_flat)
                        .unwrap_or(UnitQuaternion::identity());
                    self.calibration_offsets.insert(*id, yaw_rot.inverse());
                    log::info!("Tracker {} yaw reset. Offset applied.", id);
                }
            }
        }
    }

    /// 重置掛載 (Mounting Reset)
    /// 將當前追蹤器的姿態視為 "正向/歸零" 姿態 (Identity)。
    /// 這通常在使用者站直 (I-Pose) 時執行，用於校正追蹤器的安裝方向（如綁在側面或倒置）。
    pub fn reset_mounting(&mut self, trackers: &HashMap<u8, Tracker>) {
        for (id, tracker) in trackers {
            if let Some(quat) = tracker.quat {
                let raw_rotation = UnitQuaternion::new_normalize(nalgebra::Quaternion::new(
                    quat[3], quat[0], quat[1], quat[2],
                ));
                // 設定 Offset = Raw^-1，這樣 Offset * Raw = Identity
                self.calibration_offsets.insert(*id, raw_rotation.inverse());
                log::info!("Tracker {} mounting reset. Full offset applied.", id);
            }
        }
    }

    /// 清除所有校準數據 (Yaw and Mounting)
    pub fn clear_all_calibration(&mut self) {
        self.calibration_offsets.clear();
        log::info!("All calibration offsets have been cleared.");
    }
}

impl FusionEngine {
    /// Update default ZUPT parameters and recreate existing detectors with new params.
    pub fn set_zupt_params(&mut self, window_size: usize, accel_var_threshold: f32, gyro_threshold: f32) {
        self.zupt_window_size = window_size;
        self.zupt_accel_var_threshold = accel_var_threshold;
        self.zupt_gyro_threshold = gyro_threshold;

        let keys: Vec<u8> = self.zupt_detectors.keys().copied().collect();
        for tid in keys {
            self.zupt_detectors.insert(tid, ZuptDetector::new(window_size, accel_var_threshold, gyro_threshold));
        }
    }
}

impl FusionEngine {
    /// Estimate stationary state for a tracker using ZUPT detector.
    /// `accel` is in m/s^2, `rot_opt` is optional quaternion [x,y,z,w].
    pub fn is_tracker_stationary(&mut self, tracker_id: u8, accel: [f32; 3], rot_opt: Option<[f32; 4]>) -> bool {
        use crate::imu::pose::FilteredPose;
        use nalgebra::Quaternion;

        let accel_v = Vector3::new(accel[0], accel[1], accel[2]);

        let current_rot = if let Some(q) = rot_opt {
            UnitQuaternion::new_normalize(Quaternion::new(q[3], q[0], q[1], q[2]))
        } else {
            *self.last_rotations.get(&tracker_id).unwrap_or(&UnitQuaternion::identity())
        };

        let last = *self.last_rotations.get(&tracker_id).unwrap_or(&current_rot);
        let angle_diff = current_rot.angle_to(&last);

        // approximate angular velocity magnitude with angle_diff (rad per sample)
        let angvel = Vector3::new(angle_diff, 0.0, 0.0);

        let filtered = FilteredPose {
            rotation: current_rot,
            angular_velocity: angvel,
            acceleration: accel_v,
            magnetic_field: Vector3::zeros(),
        };

        let detector = self.zupt_detectors.entry(tracker_id).or_insert_with(|| {
            ZuptDetector::new(self.zupt_window_size, self.zupt_accel_var_threshold, self.zupt_gyro_threshold)
        });

        let stationary = detector.update(&filtered);

        self.last_rotations.insert(tracker_id, current_rot);
        stationary
    }
}

impl Default for FusionEngine {
    fn default() -> Self {
        Self::new()
    }
}

/// 從一個完整的旋轉中提取只包含 Yaw (繞 Y 軸) 的部分
fn extract_yaw_rotation(q: &UnitQuaternion<f32>) -> UnitQuaternion<f32> {
    // 1. 取一個標準的前向向量 (如 Z+)
    let forward_vec = Vector3::z();

    // 2. 將此向量應用旋轉
    let rotated_forward = q * forward_vec;

    // 3. 將旋轉後的向量投影到 XZ 平面 (忽略 Y 軸)
    let projected_forward = Vector3::new(rotated_forward.x, 0.0, rotated_forward.z);

    // 4. 計算從原始前向向量到投影後向量的旋轉
    // 這就是只包含 Yaw 的旋轉
    // 使用 try_normalize 避免向量長度為零時 panic
    projected_forward
        .try_normalize(1e-6)
        .map_or(UnitQuaternion::identity(), |normalized_proj| {
            UnitQuaternion::rotation_between(&forward_vec, &normalized_proj).unwrap_or_default()
        })
}

impl FusionEngine {
    fn apply_drift_correction(
        &self,
        bone_id: u8,
        target_rotation: UnitQuaternion<f32>,
        quest_head: Option<&AuthoritativePose>,
    ) -> UnitQuaternion<f32> {
        // 預設為不變
        let mut final_rotation = target_rotation;

        if let Some(head) = quest_head {
            if (bone_id == 0 || bone_id == 1) && self.drift_correction > 0.0 {
                // a. 提取各自的 Yaw 旋轉
                let imu_yaw = extract_yaw_rotation(&target_rotation);
                let head_yaw = extract_yaw_rotation(&head.rotation);

                // b. 計算目標 Yaw，使用 slerp 平滑
                let correction_factor = (self.drift_correction * 0.01).clamp(0.0, 1.0);
                let corrected_imu_yaw = imu_yaw.slerp(&head_yaw, correction_factor);

                // c. 計算從原始 Yaw 到目標 Yaw 的修正量
                let yaw_correction = corrected_imu_yaw * imu_yaw.inverse();

                // d. 將修正量應用到完整的 IMU 旋轉上
                final_rotation = yaw_correction * target_rotation;
            }
        }

        final_rotation
    }
}

impl FusionEngine {
    fn collect_mag_point(&mut self, tracker_id: u8, tracker: &Tracker) {
        if self.mag_calibration_active.get(&tracker_id) == Some(&true) {
            if let Some(mag_data) = tracker.mag {
                self.mag_calibration_points
                    .entry(tracker_id)
                    .or_default()
                    .push(Vector3::from(mag_data));
            }
        }
    }

    fn collect_leg_calibration(
        &mut self,
        trackers: &HashMap<u8, Tracker>,
        quest_head: Option<&AuthoritativePose>,
    ) {
        if !self.is_leg_calibrating {
            return;
        }

        if let Some(head) = quest_head {
            // 尋找左大腿 (10) 和左小腿 (11) 的旋轉
            let mut up_leg_rot = None;
            let mut leg_rot = None;

            for (tid, tracker) in trackers {
                if let Some(bid) = self.assigner.get_bone_id(*tid) {
                    if let Some(q) = tracker.quat {
                        let raw = UnitQuaternion::new_normalize(nalgebra::Quaternion::new(
                            q[3], q[0], q[1], q[2],
                        ));
                        // 應用校準偏移
                        let offset = self
                            .calibration_offsets
                            .get(tid)
                            .cloned()
                            .unwrap_or(UnitQuaternion::identity());
                        let final_rot = offset * raw; // 暫時不套用 filter

                        if bid == 10 {
                            up_leg_rot = Some(final_rot);
                        }
                        if bid == 11 {
                            leg_rot = Some(final_rot);
                        }
                    }
                }
            }

            if let (Some(ul), Some(l)) = (up_leg_rot, leg_rot) {
                self.leg_calibration_data.push((head.position.y, ul, l));
            }
        }
    }
}

impl FusionEngine {
    fn make_pole_goal(
        &self,
        skeleton: &SkeletonModel,
        bone_id: u8,
        final_rotation: UnitQuaternion<f32>,
        weight: f32,
    ) -> Option<Goal> {
        let (middle_joint_id, end_effector_id) = match bone_id {
            11 => (11, 12),
            21 => (21, 22),
            32 => (32, 33),
            42 => (42, 43),
            _ => return None,
        };

        if let Some(middle_joint_pos) = skeleton.get_joint_position(middle_joint_id) {
            let local_pole_dir = Vector3::z();
            let world_pole_dir = final_rotation * local_pole_dir;
            let pole_target_position = middle_joint_pos + world_pole_dir * 0.5;
            Some(Goal::Pole {
                middle_joint_id,
                end_effector_id,
                pole_target_position,
                weight,
            })
        } else {
            None
        }
    }

    fn make_rotation_goal(
        &self,
        bone_id: u8,
        final_rotation: UnitQuaternion<f32>,
        weight: f32,
    ) -> Goal {
        Goal::Rotation {
            bone_id,
            target_rotation: final_rotation,
            weight,
        }
    }
}
