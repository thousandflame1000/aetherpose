use crate::ik::goals::Goal;
use crate::skeleton::model::SkeletonModel;
use nalgebra::{UnitQuaternion, Vector3};

/// A lightweight IK solver built around CCD, pole-vector correction, and
/// a few post-pass regularization steps.
pub struct IkSolver {
    iterations: usize,
    threshold: f32,
    previous_pose: Option<SkeletonModel>,
}

impl Default for IkSolver {
    fn default() -> Self {
        Self::new()
    }
}

impl IkSolver {
    pub fn new() -> Self {
        Self {
            iterations: 10,
            threshold: 0.001,
            previous_pose: None,
        }
    }

    pub fn solve(&mut self, skeleton: &mut SkeletonModel, goals: &[Goal]) {
        let mut position_goals = Vec::new();
        let mut pole_goals = Vec::new();
        let mut rotation_goals = Vec::new();
        let mut pose_prior = None;
        let mut temporal_smoothness = None;
        let mut joint_limit_weight = 1.0;

        for goal in goals {
            match goal {
                Goal::Position { .. } => position_goals.push(goal),
                Goal::Pole { .. } => pole_goals.push(goal),
                Goal::Rotation { .. } => rotation_goals.push(goal),
                Goal::PosePrior { pose, weight } if *weight > 0.0 => {
                    pose_prior = Some((pose, *weight));
                }
                Goal::TemporalSmoothness { weight } if *weight > 0.0 => {
                    temporal_smoothness = Some(*weight);
                }
                Goal::JointLimits { weight } if *weight > 0.0 => {
                    joint_limit_weight = *weight;
                }
                _ => {}
            }
        }

        for _ in 0..self.iterations {
            let mut solved = true;

            for goal in &position_goals {
                if let Goal::Position {
                    bone_id,
                    target_position,
                    weight,
                } = goal
                {
                    if *weight <= 0.0 {
                        continue;
                    }

                    self.solve_ccd_pass(skeleton, *bone_id, *target_position);
                    if let Some(current_pos) = skeleton.get_joint_position(*bone_id) {
                        if (target_position - current_pos).norm_squared()
                            > self.threshold * self.threshold
                        {
                            solved = false;
                        }
                    }
                }
            }

            for goal in &pole_goals {
                if let Goal::Pole {
                    middle_joint_id,
                    end_effector_id,
                    pole_target_position,
                    weight,
                } = goal
                {
                    if *weight <= 0.0 {
                        continue;
                    }

                    self.solve_pole_vector_pass(
                        skeleton,
                        *middle_joint_id,
                        *end_effector_id,
                        *pole_target_position,
                    );
                }
            }

            self.apply_joint_limits(skeleton, joint_limit_weight);

            if solved {
                break;
            }
        }

        self.apply_rotation_goals(skeleton, &rotation_goals);
        self.apply_pose_prior(skeleton, pose_prior);
        self.apply_temporal_smoothness(skeleton, temporal_smoothness);
        self.apply_joint_limits(skeleton, joint_limit_weight);
        skeleton.update_fk();
        self.previous_pose = Some(skeleton.clone());
    }

    fn apply_rotation_goals(&self, skeleton: &mut SkeletonModel, rotation_goals: &[&Goal]) {
        for goal in rotation_goals {
            if let Goal::Rotation {
                bone_id,
                target_rotation,
                weight,
            } = goal
            {
                if *weight <= 0.0 {
                    continue;
                }

                let parent_rotation = skeleton
                    .bones
                    .get(bone_id)
                    .and_then(|bone| bone.parent_id)
                    .and_then(|parent_id| skeleton.bones.get(&parent_id).map(|bone| bone.global_rotation));

                if let Some(bone) = skeleton.bones.get_mut(bone_id) {
                    bone.local_rotation = if let Some(parent_rotation) = parent_rotation {
                        parent_rotation.inverse() * *target_rotation
                    } else {
                        *target_rotation
                    };
                    bone.local_rotation.renormalize();
                }
            }
        }
    }

    fn apply_pose_prior(
        &self,
        skeleton: &mut SkeletonModel,
        pose_prior: Option<(&SkeletonModel, f32)>,
    ) {
        let Some((pose, weight)) = pose_prior else {
            return;
        };
        let blend = weight.clamp(0.0, 1.0);
        if blend <= 0.0 {
            return;
        }

        for (bone_id, bone) in &mut skeleton.bones {
            if let Some(prior_bone) = pose.bones.get(bone_id) {
                bone.local_rotation = bone.local_rotation.slerp(&prior_bone.local_rotation, blend);
                bone.local_rotation.renormalize();
            }
        }
    }

    fn apply_temporal_smoothness(
        &self,
        skeleton: &mut SkeletonModel,
        temporal_smoothness: Option<f32>,
    ) {
        let Some(weight) = temporal_smoothness else {
            return;
        };
        let Some(previous_pose) = &self.previous_pose else {
            return;
        };
        let blend = weight.clamp(0.0, 1.0);
        if blend <= 0.0 {
            return;
        }

        for (bone_id, bone) in &mut skeleton.bones {
            if let Some(previous_bone) = previous_pose.bones.get(bone_id) {
                bone.local_rotation =
                    bone.local_rotation.slerp(&previous_bone.local_rotation, blend);
                bone.local_rotation.renormalize();
            }
        }
    }

    fn solve_ccd_pass(
        &self,
        skeleton: &mut SkeletonModel,
        end_effector_id: u8,
        target_pos: Vector3<f32>,
    ) {
        const CHAIN_LEN: usize = 5;

        let mut bones_to_update = Vec::new();
        let mut current_bone_id = Some(end_effector_id);

        for _ in 0..CHAIN_LEN {
            let Some(bone_id) = current_bone_id else {
                break;
            };
            let Some(bone) = skeleton.bones.get(&bone_id) else {
                break;
            };
            let Some(parent_id) = bone.parent_id else {
                break;
            };
            bones_to_update.push(parent_id);
            current_bone_id = Some(parent_id);
        }

        for bone_id in bones_to_update {
            let (end_effector_pos, current_joint_pos) = match (
                skeleton.get_joint_position(end_effector_id),
                skeleton.get_joint_position(bone_id),
            ) {
                (Some(end_effector_pos), Some(current_joint_pos)) => {
                    (end_effector_pos, current_joint_pos)
                }
                _ => continue,
            };

            let to_end = match (end_effector_pos - current_joint_pos).try_normalize(1e-6) {
                Some(value) => value,
                None => continue,
            };
            let to_target = match (target_pos - current_joint_pos).try_normalize(1e-6) {
                Some(value) => value,
                None => continue,
            };

            if let Some(rotation) = UnitQuaternion::rotation_between(&to_end, &to_target) {
                if let Some(bone) = skeleton.bones.get_mut(&bone_id) {
                    bone.local_rotation = rotation * bone.local_rotation;
                    bone.local_rotation.renormalize();
                }
                skeleton.update_fk_from(bone_id);
            }
        }
    }

    fn solve_pole_vector_pass(
        &self,
        skeleton: &mut SkeletonModel,
        middle_joint_id: u8,
        end_effector_id: u8,
        pole_target_pos: Vector3<f32>,
    ) {
        let Some(root_bone_id) = skeleton
            .bones
            .get(&middle_joint_id)
            .and_then(|bone| bone.parent_id)
        else {
            return;
        };

        let (root_pos, mid_pos, end_pos) = match (
            skeleton.get_joint_position(root_bone_id),
            skeleton.get_joint_position(middle_joint_id),
            skeleton.get_joint_position(end_effector_id),
        ) {
            (Some(root_pos), Some(mid_pos), Some(end_pos)) => (root_pos, mid_pos, end_pos),
            _ => return,
        };

        let limb_vec = end_pos - root_pos;
        let current_plane_normal = (mid_pos - root_pos).cross(&limb_vec);
        let target_plane_normal = (pole_target_pos - root_pos).cross(&limb_vec);

        if let (Some(current_normal), Some(target_normal)) = (
            current_plane_normal.try_normalize(1e-6),
            target_plane_normal.try_normalize(1e-6),
        ) {
            if let Some(correction_rot) =
                UnitQuaternion::rotation_between(&current_normal, &target_normal)
            {
                if let Some(root_bone) = skeleton.bones.get_mut(&root_bone_id) {
                    root_bone.local_rotation = correction_rot * root_bone.local_rotation;
                    root_bone.local_rotation.renormalize();
                }
                skeleton.update_fk_from(root_bone_id);
            }
        }
    }

    fn apply_joint_limits(&self, skeleton: &mut SkeletonModel, weight: f32) {
        let blend = weight.clamp(0.0, 1.0);
        let mut any_changed = false;

        for bone in skeleton.bones.values_mut() {
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

            let (roll, pitch, yaw) = bone.local_rotation.euler_angles();
            let clamped_roll = roll.clamp(min_limit.x, max_limit.x);
            let clamped_pitch = pitch.clamp(min_limit.y, max_limit.y);
            let clamped_yaw = yaw.clamp(min_limit.z, max_limit.z);

            if (roll - clamped_roll).abs() > 1e-4
                || (pitch - clamped_pitch).abs() > 1e-4
                || (yaw - clamped_yaw).abs() > 1e-4
            {
                let clamped_rotation =
                    UnitQuaternion::from_euler_angles(clamped_roll, clamped_pitch, clamped_yaw);
                bone.local_rotation = if blend >= 1.0 {
                    clamped_rotation
                } else {
                    bone.local_rotation.slerp(&clamped_rotation, blend)
                };
                bone.local_rotation.renormalize();
                any_changed = true;
            }
        }

        if any_changed {
            skeleton.update_fk();
        }
    }
}
