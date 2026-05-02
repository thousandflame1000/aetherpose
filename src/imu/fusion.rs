#![allow(dead_code)]

use crate::{
    ik::goals::Goal, imu, imu::calibration::MagCalibration, imu::smoothing::OneEuroFilter,
    net::tracker::Tracker, skeleton::model::SkeletonModel,
};
use crate::imu::drift::ZuptDetector;
use nalgebra::{UnitQuaternion, Vector3};
use std::collections::HashMap;
use std::time::Instant;

/// Manages the assignment of tracker IDs to bone IDs.
#[derive(Default, Debug)]
pub struct Assigner {
    assignments: HashMap<u8, u8>, // Tracker ID -> Bone ID
}

impl Default for FusionEngine {
    fn default() -> Self {
        Self::new()
    }
}

impl Assigner {
    pub fn set_assignment(&mut self, tracker_id: u8, bone_id: u8) {
        log::info!("Assigning Tracker #{} to Bone #{}", tracker_id, bone_id);
        self.assignments.insert(tracker_id, bone_id);
    }

    pub fn get_bone_id(&self, tracker_id: u8) -> Option<u8> {
        self.assignments.get(&tracker_id).copied()
    }

    /// Automatically assigns trackers to bones based on a predefined list.
    /// Sorts trackers by ID and assigns them in order: Hip, Chest, L.Leg, R.Leg, etc.
    pub fn auto_assign(&mut self, trackers: &HashMap<u8, Tracker>) {
        let mut sorted_ids: Vec<u8> = trackers.keys().copied().collect();
        sorted_ids.sort();

        // 定義分配順序：臀 -> 胸 -> 左大腿 -> 右大腿 -> 左小腿 -> 右小腿 -> 左腳 -> 右腳
        let bone_order = [0, 2, 10, 20, 11, 21, 12, 22];

        log::info!("Auto-assigning {} trackers...", sorted_ids.len());
        self.assignments.clear();

        for (i, &tracker_id) in sorted_ids.iter().enumerate() {
            if i < bone_order.len() {
                self.set_assignment(tracker_id, bone_order[i]);
            }
        }
    }
}

/// The `FusionEngine` is the core of the tracking system. It takes raw sensor data,
/// processes it through the IMU pipeline, applies calibration, and outputs
/// goals for the Inverse Kinematics (IK) solver.
pub struct FusionEngine {
    pub assigner: Assigner,
    // Stores the rotation needed to align each tracker's forward direction with the world's forward.
    yaw_offsets: HashMap<u8, UnitQuaternion<f32>>,
    // Stores the rotation needed to correct for how the tracker is mounted on the body.
    mounting_rotations: HashMap<u8, UnitQuaternion<f32>>,
    // ZUPT State: Stores the accumulated drift correction for ZUPT (Zero Velocity Update)
    zupt_offsets: HashMap<u8, UnitQuaternion<f32>>,
    // Per-tracker ZUPT detectors
    zupt_detectors: HashMap<u8, ZuptDetector>,
    // Per-tracker last process timestamp (for angular velocity estimation)
    last_process_times: HashMap<u8, Instant>,
    // Default parameters for ZUPT detectors (used when creating/recreating detectors)
    zupt_window_size: usize,
    zupt_accel_var_threshold: f32,
    zupt_gyro_threshold: f32,
    // State: Stores the previous rotation to calculate angular velocity
    last_rotations: HashMap<u8, UnitQuaternion<f32>>,
    // Magnetometer Calibration State
    pub mag_calibration_points: HashMap<u8, Vec<Vector3<f32>>>,
    pub mag_calibration_active: HashMap<u8, bool>,
    pub mag_calibrations: HashMap<u8, MagCalibration>, // 儲存校準結果
    filters: HashMap<u8, OneEuroFilter>,               // One Euro Filters
    // Leg Calibration State
    leg_calibration_data: Vec<(f32, f32)>, // (Thigh Pitch, Shin Pitch)
}

impl FusionEngine {
    pub fn new() -> Self {
        Self {
            assigner: Assigner::default(),
            yaw_offsets: HashMap::new(),
            mounting_rotations: HashMap::new(),
            zupt_offsets: HashMap::new(),
            last_rotations: HashMap::new(),
            mag_calibration_points: HashMap::new(),
            mag_calibration_active: HashMap::new(),
            mag_calibrations: HashMap::new(),
            filters: HashMap::new(),
            zupt_detectors: HashMap::new(),
            last_process_times: HashMap::new(),
            // default ZUPT detector parameters
            zupt_window_size: 8,
            zupt_accel_var_threshold: 0.0005,
            zupt_gyro_threshold: 0.02,
            leg_calibration_data: Vec::new(),
        }
    }

    /// Update default ZUPT parameters and recreate existing detectors with new params.
    pub fn set_zupt_params(&mut self, window_size: usize, accel_var_threshold: f32, gyro_threshold: f32) {
        self.zupt_window_size = window_size;
        self.zupt_accel_var_threshold = accel_var_threshold;
        self.zupt_gyro_threshold = gyro_threshold;

        // Recreate per-tracker detectors to apply new params immediately.
        let keys: Vec<u8> = self.zupt_detectors.keys().copied().collect();
        for tid in keys {
            self.zupt_detectors.insert(tid, ZuptDetector::new(window_size, accel_var_threshold, gyro_threshold));
        }
    }

    /// Processes all active trackers and generates IK goals.
    /// This is the heart of the real-time tracking loop.
    pub fn process(
        &mut self,
        _skeleton: &SkeletonModel,
        trackers: &HashMap<u8, Tracker>,
        drift_correction: f32,
        smoothing_min_cutoff: f32,
        smoothing_beta: f32,
    ) -> Vec<Goal> {
        let mut goals = Vec::new();

        for (tracker_id, tracker_data) in trackers.iter() {
            // Ensure the tracker has data and is assigned to a bone.
            if let (Some(quat), Some(accel), Some(bone_id)) = (
                tracker_data.quat,  // [x,y,z,w]
                tracker_data.accel, // [x,y,z]
                self.assigner.get_bone_id(*tracker_id),
            ) {
                // 磁力計數據是可選的，如果沒有則使用零向量
                let mag = tracker_data.mag.unwrap_or([0.0, 0.0, 0.0]);

                // --- IMU Processing Pipeline ---
                // 1. Filter: Convert raw array data into a structured `FilteredPose`.
                let filtered_pose = imu::filter::filter_raw_data(quat, accel, mag);

                // 如果正在進行磁力計校準，則收集點
                if *self
                    .mag_calibration_active
                    .get(tracker_id)
                    .unwrap_or(&false)
                {
                    self.mag_calibration_points
                        .entry(*tracker_id)
                        .or_default()
                        .push(filtered_pose.magnetic_field);
                }

                // 2. Drift Compensation: Use accelerometer to correct roll/pitch drift.
                let drift_compensated_pose =
                    imu::drift::compensate_drift(filtered_pose, drift_correction);

                // Get calibration parameters or use default.
                // We use copied().unwrap_or_default() because MagCalibration is Copy.
                let mag_calib = self
                    .mag_calibrations
                    .get(tracker_id)
                    .copied()
                    .unwrap_or_default();

                // 3. Sensor Calibration: Apply pre-determined sensor corrections.
                let sensor_calibrated_pose =
                    imu::calibration::apply_sensor_calibration(drift_compensated_pose, &mag_calib);

                // --- Angular Velocity Estimation ---
                // 固件只傳送已融合的四元數，沒有原始陀螺儀數據。
                // 從連續幀的四元數差分估算角速度，供 ZUPT 判斷使用。
                let now = Instant::now();
                let estimated_angular_velocity = {
                    let prev_rot = self.last_rotations.get(tracker_id).copied();
                    let dt = self.last_process_times.get(tracker_id)
                        .map(|t| now.duration_since(*t).as_secs_f32())
                        .unwrap_or(0.0);
                    if let (Some(prev), true) = (prev_rot, dt > 1e-6 && dt < 0.5) {
                        let q_delta = prev.inverse() * sensor_calibrated_pose.rotation;
                        q_delta.axis_angle()
                            .map(|(axis, angle)| axis.into_inner() * (angle / dt))
                            .unwrap_or(Vector3::zeros())
                    } else {
                        Vector3::zeros()
                    }
                };
                self.last_process_times.insert(*tracker_id, now);

                // --- ZUPT (Zero Velocity Update) for Feet ---
                // 使用 `ZuptDetector` 進行更穩健的靜止偵測，取代簡單的閾值檢查。
                let mut zupt_corrected_rotation = sensor_calibrated_pose.rotation;

                // 判斷是否為腳部 (12: L.Foot, 22: R.Foot)
                if bone_id == 12 || bone_id == 22 {
                    let detector = self.zupt_detectors.entry(*tracker_id).or_insert_with(|| {
                        // 參數可未來暴露為設定：window_size, accel_var_threshold, gyro_threshold
                        ZuptDetector::new(8, 0.0005, 0.02)
                    });

                    // ZuptDetector currently expects a `FilteredPose` reference; build a
                    // lightweight temporary from the calibrated pose fields.
                    let tmp_filtered = imu::pose::FilteredPose {
                        rotation: sensor_calibrated_pose.rotation,
                        angular_velocity: estimated_angular_velocity,
                        acceleration: sensor_calibrated_pose.acceleration,
                        magnetic_field: sensor_calibrated_pose.magnetic_field,
                    };

                    let is_stationary = detector.update(&tmp_filtered);

                    let last_rot = self
                        .last_rotations
                        .get(tracker_id)
                        .copied()
                        .unwrap_or(sensor_calibrated_pose.rotation);

                    let current_zupt_offset = self
                        .zupt_offsets
                        .entry(*tracker_id)
                        .or_insert(UnitQuaternion::identity());

                    if is_stationary {
                        // If stationary, lock yaw by updating the offset to preserve previous orientation
                        let target_rot = *current_zupt_offset * last_rot;
                        *current_zupt_offset =
                            target_rot * sensor_calibrated_pose.rotation.inverse();
                    }

                    zupt_corrected_rotation = *current_zupt_offset * sensor_calibrated_pose.rotation;
                }

                // 更新歷史狀態
                self.last_rotations
                    .insert(*tracker_id, sensor_calibrated_pose.rotation);

                // --- One Euro Filter Smoothing ---
                let filter = self
                    .filters
                    .entry(*tracker_id)
                    .or_insert_with(|| OneEuroFilter::new(smoothing_min_cutoff, smoothing_beta));
                filter.update_params(smoothing_min_cutoff, smoothing_beta); // 即時更新參數

                let smoothed_rotation = filter.filter(zupt_corrected_rotation);

                // --- Body-level Calibration ---
                // 4. Apply mounting and yaw calibration.
                let yaw_offset = self
                    .yaw_offsets
                    .get(tracker_id)
                    .cloned()
                    .unwrap_or_default();
                // 注意順序：先應用 ZUPT 修正後的姿態，再應用校準
                let final_rotation = yaw_offset * smoothed_rotation;

                // --- Leg Calibration Data Collection ---
                // 如果正在校準腿部，且此 Tracker 是左大腿(10)或左小腿(11) (簡化：只用左腿做範例)
                // 實際應用應同時收集雙腿數據
                if !self.leg_calibration_data.is_empty() { // 使用非空來判斷是否正在校準
                     // 這裡我們需要同時拿到大腿和小腿的數據，這在單一 Tracker 迴圈中比較難
                     // 所以我們改在 process 函式的最後，統一收集
                }

                // --- Create IK Goal ---
                goals.push(Goal::Rotation {
                    bone_id,
                    target_rotation: final_rotation,
                    weight: 1.0, // Use a fixed weight for now.
                });
            }
        }

        // --- Leg Calibration Logic (Post-Loop) ---
        // 檢查是否正在校準 (利用 capacity 或 flag，這裡假設 capacity > 0 代表啟用)
        if self.leg_calibration_data.capacity() > 0 {
            // 嘗試獲取左大腿(10) 和 左小腿(11) 的 Pitch 角度
            // 注意：這裡需要從 goals 或 trackers 中獲取處理後的姿態
            // 為簡化，我們假設 trackers 中已經有處理過的 rotation (這在上面的迴圈中已經更新到 last_rotations)

            // 尋找分配到 10 (L.UpLeg) 和 11 (L.Leg) 的 Tracker ID
            let mut thigh_rot = None;
            let mut shin_rot = None;

            for (tid, &bid) in self.assigner.assignments.iter() {
                if bid == 10 {
                    thigh_rot = self.last_rotations.get(tid);
                }
                if bid == 11 {
                    shin_rot = self.last_rotations.get(tid);
                }
            }

            if let (Some(t_rot), Some(s_rot)) = (thigh_rot, shin_rot) {
                // 取得 Pitch (X軸旋轉)
                let (pitch_t, _, _) = t_rot.euler_angles();
                let (pitch_s, _, _) = s_rot.euler_angles();
                self.leg_calibration_data.push((pitch_t, pitch_s));
            }
        }

        goals
    }

    /// Resets the forward direction (yaw) for all active trackers.
    pub fn reset_yaw(&mut self, trackers: &HashMap<u8, Tracker>) {
        log::info!("Resetting Yaw for all active trackers...");
        for (id, tracker) in trackers {
            if let Some(quat) = tracker.quat {
                let current_rot = UnitQuaternion::from_quaternion(nalgebra::Quaternion::new(
                    quat[3], quat[0], quat[1], quat[2],
                ));
                let (_roll, _pitch, yaw) = current_rot.euler_angles();
                let yaw_only_quat = UnitQuaternion::from_euler_angles(0.0, 0.0, yaw);
                self.yaw_offsets.insert(*id, yaw_only_quat.inverse());
            }
        }
    }

    /// Resets the mounting orientation for all trackers.
    pub fn reset_mounting(&mut self, _trackers: &HashMap<u8, Tracker>) {
        log::info!("Resetting mounting rotation (not implemented yet).");
    }

    /// Clears all stored calibration data.
    pub fn clear_all_calibration(&mut self) {
        log::info!("Clearing all calibration data (Yaw, Mounting).");
        self.yaw_offsets.clear();
        self.mounting_rotations.clear();
        self.zupt_offsets.clear();
        self.last_rotations.clear();
        self.last_process_times.clear();
        self.mag_calibration_points.clear();
        self.mag_calibration_active.clear();
        self.filters.clear();
    }

    /// Starts collecting magnetometer data for calibration for a specific tracker.
    pub fn start_mag_calibration(&mut self, tracker_id: u8) {
        log::info!(
            "Starting magnetometer calibration for Tracker #{}",
            tracker_id
        );
        self.mag_calibration_points
            .entry(tracker_id)
            .or_default()
            .clear(); // 清除舊數據
        self.mag_calibration_active.insert(tracker_id, true);
    }

    /// Stops collecting magnetometer data for calibration for a specific tracker.
    pub fn stop_mag_calibration(&mut self, tracker_id: u8) {
        log::info!(
            "Stopping magnetometer calibration for Tracker #{}",
            tracker_id
        );
        self.mag_calibration_active.insert(tracker_id, false);

        // 計算校準參數 (Min/Max 方法)
        if let Some(points) = self.mag_calibration_points.get(&tracker_id) {
            if points.len() > 100 {
                // 確保有足夠數據
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
                let avg_radius = (avg_dist.x + avg_dist.y + avg_dist.z) / 3.0;

                // 避免除以零
                let safe_div = |v: f32| if v.abs() < 1e-6 { 1.0 } else { v };

                let scale = Vector3::new(
                    avg_radius / safe_div(avg_dist.x),
                    avg_radius / safe_div(avg_dist.y),
                    avg_radius / safe_div(avg_dist.z),
                );

                let calib = MagCalibration {
                    offset: [offset.x, offset.y, offset.z],
                    scale: [scale.x, scale.y, scale.z],
                };

                log::info!("Tracker #{} Calibration Result: {:?}", tracker_id, calib);
                self.mag_calibrations.insert(tracker_id, calib);
            }
        }
    }

    /// Starts leg proportion calibration.
    pub fn start_leg_calibration(&mut self) {
        log::info!("Starting leg calibration...");
        self.leg_calibration_data.clear();
        self.leg_calibration_data.reserve(1000); // 預留空間並作為啟用標誌
    }

    /// Stops leg calibration and calculates the ideal thigh/shin ratio.
    pub fn stop_leg_calibration(&mut self) -> Option<f32> {
        log::info!(
            "Stopping leg calibration. Collected {} samples.",
            self.leg_calibration_data.len()
        );

        if self.leg_calibration_data.len() < 50 {
            log::warn!("Not enough data for calibration.");
            self.leg_calibration_data.clear();
            self.leg_calibration_data.shrink_to_fit(); // 清除啟用標誌
            return None;
        }

        // 計算邏輯：
        // 假設垂直半蹲，腳掌水平位移為 0
        // L1 * sin(theta1) + L2 * sin(theta2) = 0
        // Ratio = L1 / L2 = - sin(theta2) / sin(theta1)

        let mut total_ratio = 0.0;
        let mut count = 0;

        for (theta1, theta2) in &self.leg_calibration_data {
            // 過濾掉接近直立的數據 (sin 接近 0 會導致數值不穩)
            if theta1.abs() > 0.1 {
                let ratio = -theta2.sin() / theta1.sin();
                if ratio > 0.5 && ratio < 2.0 {
                    // 過濾極端值
                    total_ratio += ratio;
                    count += 1;
                }
            }
        }

        self.leg_calibration_data.clear();
        self.leg_calibration_data.shrink_to_fit();

        if count > 0 {
            Some(total_ratio / count as f32)
        } else {
            None
        }
    }
}
