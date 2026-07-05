#![allow(dead_code)]

use crate::fusion::assignment::TrackerBoneAssigner;
use crate::fusion::{confidence, weighting};
use crate::ik::goals::Goal;
use crate::imu::calibration::MagCalibration;
use crate::imu::drift::ZuptDetector;
use crate::imu::trajectory::{ImuTrajectoryEstimator, TrajectoryIntegrationMode};
use crate::net::tracker::Tracker;
use crate::skeleton::model::SkeletonModel;
use crate::smoothing::OneEuroFilter;
use nalgebra::{Quaternion, UnitQuaternion, Vector3};
use std::collections::HashMap;
use std::time::Instant;

const AUTHORITY_WEIGHT: f32 = 100.0;
const DEFAULT_IMU_POSITION_WEIGHT: f32 = 0.35;

/// FusionEngine interprets tracker data and converts it into IK goals.
pub struct FusionEngine {
    pub assigner: TrackerBoneAssigner,
    pub calibration_offsets: HashMap<u8, UnitQuaternion<f32>>,
    /// Cached quaternions from device (injected directly from firmware Madgwick).
    ekf_quaternions: HashMap<u8, UnitQuaternion<f32>>,
    filters: HashMap<u8, OneEuroFilter>,
    imu_trajectory: ImuTrajectoryEstimator,
    pub smoothing_min_cutoff: f32,
    pub smoothing_beta: f32,
    pub drift_correction: f32,
    pub imu_position_weight: f32,
    pub zupt_enabled: bool,
    _zupt_offsets: HashMap<u8, UnitQuaternion<f32>>,
    zupt_detectors: HashMap<u8, ZuptDetector>,
    zupt_window_size: usize,
    zupt_accel_var_threshold: f32,
    zupt_gyro_threshold: f32,
    last_rotations: HashMap<u8, UnitQuaternion<f32>>,
    last_stationary_times: HashMap<u8, Instant>,
    pub mag_calibrations: HashMap<u8, MagCalibration>,
    pub mag_calibration_points: HashMap<u8, Vec<Vector3<f32>>>,
    pub mag_calibration_active: HashMap<u8, bool>,
    is_leg_calibrating: bool,
    leg_calibration_data: Vec<(f32, UnitQuaternion<f32>, UnitQuaternion<f32>)>,
}

/// Pose from an authoritative source such as Quest head or controllers.
pub struct AuthoritativePose {
    pub position: Vector3<f32>,
    pub rotation: UnitQuaternion<f32>,
}

pub(crate) struct MockTracker {
    pub position: Vector3<f32>,
    pub rotation: UnitQuaternion<f32>,
}

impl FusionEngine {
    pub fn new() -> Self {
        Self {
            assigner: TrackerBoneAssigner::new(),
            calibration_offsets: HashMap::new(),
            ekf_quaternions: HashMap::new(),
            filters: HashMap::new(),
            imu_trajectory: ImuTrajectoryEstimator::new(),
            smoothing_min_cutoff: 1.0,
            smoothing_beta: 0.5,
            drift_correction: 0.0,
            imu_position_weight: DEFAULT_IMU_POSITION_WEIGHT,
            zupt_enabled: true,
            _zupt_offsets: HashMap::new(),
            zupt_detectors: HashMap::new(),
            zupt_window_size: 8,
            zupt_accel_var_threshold: 0.0005,
            zupt_gyro_threshold: 0.02,
            last_rotations: HashMap::new(),
            last_stationary_times: HashMap::new(),
            mag_calibrations: HashMap::new(),
            mag_calibration_points: HashMap::new(),
            mag_calibration_active: HashMap::new(),
            is_leg_calibrating: false,
            leg_calibration_data: Vec::new(),
        }
    }

    pub fn process(
        &mut self,
        skeleton: &SkeletonModel,
        trackers: &HashMap<u8, Tracker>,
        quest_head: Option<&AuthoritativePose>,
        quest_left_hand: Option<&AuthoritativePose>,
        quest_right_hand: Option<&AuthoritativePose>,
    ) -> Vec<Goal> {
        let mut generated_goals = Vec::new();

        if let Some(head) = quest_head {
            generated_goals.push(Goal::Rotation {
                bone_id: 4,
                target_rotation: head.rotation,
                weight: AUTHORITY_WEIGHT,
            });
            generated_goals.push(Goal::Position {
                bone_id: 4,
                target_position: head.position,
                weight: AUTHORITY_WEIGHT,
            });
        }

        if let Some(left_hand) = quest_left_hand {
            generated_goals.push(Goal::Rotation {
                bone_id: 33,
                target_rotation: left_hand.rotation,
                weight: AUTHORITY_WEIGHT,
            });
            generated_goals.push(Goal::Position {
                bone_id: 33,
                target_position: left_hand.position,
                weight: AUTHORITY_WEIGHT,
            });
        }

        if let Some(right_hand) = quest_right_hand {
            generated_goals.push(Goal::Rotation {
                bone_id: 43,
                target_rotation: right_hand.rotation,
                weight: AUTHORITY_WEIGHT,
            });
            generated_goals.push(Goal::Position {
                bone_id: 43,
                target_position: right_hand.position,
                weight: AUTHORITY_WEIGHT,
            });
        }

        for (tracker_id, tracker) in trackers {
            let Some(bone_id) = self.assigner.get_bone_id(*tracker_id) else {
                log::warn!("No bone assigned for Tracker ID: {}", tracker_id);
                continue;
            };

            // Use EKF-fused quaternion computed in update_ekf() (called from ingest).
            let Some(raw_rotation) = self.ekf_quaternions.get(tracker_id).copied() else {
                continue;
            };

            let confidence = confidence::calculate_confidence(tracker, 1000);
            let weight = weighting::calculate_weight(confidence);

            let filter = self.filters.entry(*tracker_id).or_insert_with(|| {
                OneEuroFilter::new(self.smoothing_min_cutoff, self.smoothing_beta)
            });
            filter.update_params(self.smoothing_min_cutoff, self.smoothing_beta);
            let smoothed_rotation = filter.filter(raw_rotation);

            let calibrated_rotation = self
                .calibration_offsets
                .get(tracker_id)
                .copied()
                .unwrap_or_else(UnitQuaternion::identity)
                * smoothed_rotation;
            let final_rotation =
                self.apply_drift_correction(bone_id, calibrated_rotation, quest_head);

            if let Some(goal) = self.make_pole_goal(skeleton, bone_id, final_rotation, weight) {
                generated_goals.push(goal);
            } else {
                generated_goals.push(self.make_rotation_goal(bone_id, final_rotation, weight));
            }

            if let (Some(accel), Some(anchor_position)) =
                (tracker.accel, skeleton.get_joint_position(bone_id))
            {
                let estimate = self.imu_trajectory.update(
                    *tracker_id,
                    bone_id,
                    anchor_position,
                    tracker.received_packets,
                    final_rotation,
                    accel,
                    tracker.stationary,
                );

                let authority_locked = self.is_position_authoritative(
                    bone_id,
                    quest_head,
                    quest_left_hand,
                    quest_right_hand,
                );
                let position_weight = weight * self.imu_position_weight;
                let _ = (estimate.velocity, estimate.linear_acceleration, estimate.stationary);

                if self.should_emit_position_goal(bone_id)
                    && !authority_locked
                    && position_weight > 0.0
                {
                    generated_goals.push(Goal::Position {
                        bone_id,
                        target_position: estimate.position,
                        weight: position_weight,
                    });
                }
            }

            self.collect_mag_point(*tracker_id, tracker);
        }

        self.collect_leg_calibration(trackers, quest_head);
        generated_goals
    }

    /// Feed raw IMU data into the per-tracker EKF and cache the result.
    /// Write a device-side quaternion ([x,y,z,w]) directly into the cached map.
    pub fn inject_quaternion(&mut self, tracker_id: u8, xyzw: [f32; 4]) {
        let q = UnitQuaternion::new_normalize(Quaternion::new(xyzw[3], xyzw[0], xyzw[1], xyzw[2]));
        self.ekf_quaternions.insert(tracker_id, q);
    }

    pub fn start_mag_calibration(&mut self, tracker_id: u8) {
        self.mag_calibration_active.insert(tracker_id, true);
        self.mag_calibration_points
            .entry(tracker_id)
            .or_default()
            .clear();
        log::info!("Starting magnetometer calibration for tracker {}", tracker_id);
    }

    pub fn stop_mag_calibration(&mut self, tracker_id: u8) {
        self.mag_calibration_active.insert(tracker_id, false);
        if let Some(points) = self.mag_calibration_points.get(&tracker_id) {
            if let Some(calibration) = MagCalibration::calibrate(points) {
                self.mag_calibrations.insert(tracker_id, calibration);
                log::info!("Stored magnetometer calibration for tracker {}", tracker_id);
            } else {
                log::warn!(
                    "Magnetometer calibration for tracker {} needs more spread",
                    tracker_id
                );
            }
        }
    }

    pub fn start_leg_calibration(&mut self) {
        self.is_leg_calibrating = true;
        self.leg_calibration_data.clear();
        log::info!("Starting leg calibration");
    }

    pub fn stop_leg_calibration(&mut self, total_leg_length: f32) -> Option<f32> {
        self.is_leg_calibrating = false;
        if self.leg_calibration_data.is_empty() {
            log::warn!("Leg calibration has no samples");
            return None;
        }

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
            log::warn!("Leg calibration height swing too small: {:.3}m", delta_h);
            return None;
        }

        let vertical_factor = |rotation: &UnitQuaternion<f32>| -> f32 {
            let bone_vec = rotation * Vector3::new(0.0, -1.0, 0.0);
            bone_vec.y.abs()
        };

        let thigh_stand = vertical_factor(&stand.1);
        let shin_stand = vertical_factor(&stand.2);
        let thigh_squat = vertical_factor(&squat.1);
        let shin_squat = vertical_factor(&squat.2);

        let thigh_term = thigh_stand - thigh_squat;
        let shin_term = shin_stand - shin_squat;
        let numerator = total_leg_length * shin_term - delta_h;
        let denominator = delta_h - total_leg_length * thigh_term;

        if denominator.abs() < 1e-4 {
            return None;
        }

        let ratio = numerator / denominator;
        if (0.2..3.0).contains(&ratio) {
            log::info!("Leg calibration ratio resolved to {:.3}", ratio);
            Some(ratio)
        } else {
            log::warn!("Leg calibration ratio {:.3} is outside the expected range", ratio);
            None
        }
    }

    pub fn auto_assign(&mut self, trackers: &HashMap<u8, Tracker>) {
        let mut sorted_ids: Vec<u8> = trackers.keys().copied().collect();
        sorted_ids.sort();

        let priority_bones = [2, 32, 42, 4, 11, 21, 0, 12];
        self.assigner.map.clear();

        for (index, tracker_id) in sorted_ids.iter().enumerate() {
            if let Some(&bone_id) = priority_bones.get(index) {
                self.assigner.set_assignment(*tracker_id, bone_id);
                log::info!("Auto assigned tracker {} to bone {}", tracker_id, bone_id);
            } else {
                log::warn!("Tracker {} could not be auto-assigned", tracker_id);
            }
        }
    }

    pub fn reset_yaw(&mut self, trackers: &HashMap<u8, Tracker>) {
        for id in trackers.keys() {
            if let Some(&rotation) = self.ekf_quaternions.get(id) {
                let forward = rotation * Vector3::z();
                let flat_forward = Vector3::new(forward.x, 0.0, forward.z);
                if let Some(normalized_forward) = flat_forward.try_normalize(1e-6) {
                    let yaw_rotation =
                        UnitQuaternion::rotation_between(&Vector3::z(), &normalized_forward)
                            .unwrap_or_else(UnitQuaternion::identity);
                    self.calibration_offsets.insert(*id, yaw_rotation.inverse());
                }
            }
        }
    }

    pub fn reset_mounting(&mut self, trackers: &HashMap<u8, Tracker>) {
        for id in trackers.keys() {
            if let Some(&rotation) = self.ekf_quaternions.get(id) {
                self.calibration_offsets.insert(*id, rotation.inverse());
            }
        }
    }

    pub fn clear_all_calibration(&mut self) {
        self.calibration_offsets.clear();
        self.mag_calibration_points.clear();
        self.mag_calibration_active.clear();
        self.last_rotations.clear();
        self.last_stationary_times.clear();
        self.ekf_quaternions.clear();
        self.imu_trajectory.clear();
        log::info!("Cleared calibration offsets and IMU trajectory state");
    }

    pub fn set_zupt_params(
        &mut self,
        window_size: usize,
        accel_var_threshold: f32,
        gyro_threshold: f32,
    ) {
        self.zupt_window_size = window_size;
        self.zupt_accel_var_threshold = accel_var_threshold;
        self.zupt_gyro_threshold = gyro_threshold;

        let keys: Vec<u8> = self.zupt_detectors.keys().copied().collect();
        for tracker_id in keys {
            self.zupt_detectors.insert(
                tracker_id,
                ZuptDetector::new(window_size, accel_var_threshold, gyro_threshold),
            );
        }
    }

    pub fn set_zupt_enabled(&mut self, enabled: bool) {
        self.zupt_enabled = enabled;
    }

    pub fn set_trajectory_integration_mode(&mut self, mode: TrajectoryIntegrationMode) {
        self.imu_trajectory.set_integration_mode(mode);
    }

    pub fn trajectory_integration_mode(&self) -> TrajectoryIntegrationMode {
        self.imu_trajectory.integration_mode()
    }

    /// Estimate stationary state for a tracker using the existing ZUPT detector.
    pub fn is_tracker_stationary(
        &mut self,
        tracker_id: u8,
        accel: [f32; 3],
        rot_opt: Option<[f32; 4]>,
    ) -> bool {
        use crate::imu::pose::FilteredPose;

        let accel_v = Vector3::new(accel[0], accel[1], accel[2]);
        let current_rot = if let Some(q) = rot_opt {
            UnitQuaternion::new_normalize(Quaternion::new(q[3], q[0], q[1], q[2]))
        } else {
            self.last_rotations
                .get(&tracker_id)
                .copied()
                .unwrap_or_else(UnitQuaternion::identity)
        };

        if !self.zupt_enabled {
            self.last_rotations.insert(tracker_id, current_rot);
            return false;
        }

        let now = Instant::now();
        let dt = self
            .last_stationary_times
            .get(&tracker_id)
            .map(|t| now.duration_since(*t).as_secs_f32())
            .unwrap_or(1.0 / 119.0)
            .clamp(1.0 / 240.0, 0.05);
        self.last_stationary_times.insert(tracker_id, now);

        let last_rotation = self
            .last_rotations
            .get(&tracker_id)
            .copied()
            .unwrap_or(current_rot);

        // 從四元數差分估算角速度 (rad/s)，軸方向來自 delta_q
        let q_delta = current_rot * last_rotation.inverse();
        let angular_velocity = q_delta
            .axis_angle()
            .map(|(axis, angle)| axis.into_inner() * (angle / dt))
            .unwrap_or(Vector3::zeros());

        let filtered = FilteredPose {
            rotation: current_rot,
            angular_velocity,
            acceleration: accel_v,
            magnetic_field: Vector3::zeros(),
        };

        let detector = self.zupt_detectors.entry(tracker_id).or_insert_with(|| {
            ZuptDetector::new(
                self.zupt_window_size,
                self.zupt_accel_var_threshold,
                self.zupt_gyro_threshold,
            )
        });

        let stationary = detector.update(&filtered);
        self.last_rotations.insert(tracker_id, current_rot);
        stationary
    }

    fn apply_drift_correction(
        &self,
        bone_id: u8,
        target_rotation: UnitQuaternion<f32>,
        quest_head: Option<&AuthoritativePose>,
    ) -> UnitQuaternion<f32> {
        let mut final_rotation = target_rotation;

        if let Some(head) = quest_head {
            if (bone_id == 0 || bone_id == 1) && self.drift_correction > 0.0 {
                let imu_yaw = extract_yaw_rotation(&target_rotation);
                let head_yaw = extract_yaw_rotation(&head.rotation);
                let correction_factor = (self.drift_correction * 0.01).clamp(0.0, 1.0);
                let corrected_yaw = imu_yaw.slerp(&head_yaw, correction_factor);
                let yaw_correction = corrected_yaw * imu_yaw.inverse();
                final_rotation = yaw_correction * target_rotation;
            }
        }

        final_rotation
    }

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

        let Some(head) = quest_head else {
            return;
        };

        let mut up_leg_rot = None;
        let mut leg_rot = None;

        for (tracker_id, tracker) in trackers {
            let Some(bone_id) = self.assigner.get_bone_id(*tracker_id) else {
                continue;
            };
            let Some(&ekf_rot) = self.ekf_quaternions.get(tracker_id) else {
                continue;
            };
            let _ = tracker; // no longer need tracker.quat

            let offset = self
                .calibration_offsets
                .get(tracker_id)
                .copied()
                .unwrap_or_else(UnitQuaternion::identity);
            let final_rotation = offset * ekf_rot;

            if bone_id == 10 {
                up_leg_rot = Some(final_rotation);
            }
            if bone_id == 11 {
                leg_rot = Some(final_rotation);
            }
        }

        if let (Some(up_leg), Some(leg)) = (up_leg_rot, leg_rot) {
            self.leg_calibration_data.push((head.position.y, up_leg, leg));
        }
    }

    fn make_pole_goal(
        &self,
        _skeleton: &SkeletonModel,
        _bone_id: u8,
        _final_rotation: UnitQuaternion<f32>,
        _weight: f32,
    ) -> Option<Goal> {
        None
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

    fn should_emit_position_goal(&self, bone_id: u8) -> bool {
        matches!(bone_id, 0 | 4 | 12 | 22 | 33 | 43)
    }

    fn is_position_authoritative(
        &self,
        bone_id: u8,
        quest_head: Option<&AuthoritativePose>,
        quest_left_hand: Option<&AuthoritativePose>,
        quest_right_hand: Option<&AuthoritativePose>,
    ) -> bool {
        match bone_id {
            4 => quest_head.is_some(),
            33 => quest_left_hand.is_some(),
            43 => quest_right_hand.is_some(),
            _ => false,
        }
    }
}

impl Default for FusionEngine {
    fn default() -> Self {
        Self::new()
    }
}

fn extract_yaw_rotation(rotation: &UnitQuaternion<f32>) -> UnitQuaternion<f32> {
    let forward = rotation * Vector3::z();
    let flat_forward = Vector3::new(forward.x, 0.0, forward.z);
    flat_forward
        .try_normalize(1e-6)
        .map_or_else(UnitQuaternion::identity, |normalized| {
            UnitQuaternion::rotation_between(&Vector3::z(), &normalized)
                .unwrap_or_else(UnitQuaternion::identity)
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn construct_mocktracker() {
        let tracker = MockTracker {
            position: Vector3::zeros(),
            rotation: UnitQuaternion::identity(),
        };

        assert_eq!(tracker.position, Vector3::zeros());
        assert_eq!(tracker.rotation, UnitQuaternion::identity());
    }

    #[test]
    fn position_goals_only_for_roots_and_end_effectors() {
        let engine = FusionEngine::new();
        assert!(engine.should_emit_position_goal(0));
        assert!(engine.should_emit_position_goal(12));
        assert!(!engine.should_emit_position_goal(2));
    }
}
