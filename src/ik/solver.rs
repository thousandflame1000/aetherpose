use crate::ik::goals::Goal;
use crate::skeleton::model::SkeletonModel;
use nalgebra::{UnitQuaternion, Vector3};

/// A lightweight IK solver built around CCD and a few post-pass regularization steps.
pub struct IkSolver {
    iterations: usize,
    threshold: f32,
    previous_pose: Option<SkeletonModel>,
    /// Where the root stands without an anchor (its position the first time it was solved).
    root_rest: Option<Vector3<f32>>,
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
            root_rest: None,
        }
    }

    pub fn solve(&mut self, skeleton: &mut SkeletonModel, goals: &[Goal]) {
        let mut position_goals = Vec::new();
        let mut rotation_goals = Vec::new();
        let mut pose_prior = None;
        let mut temporal_smoothness = None;
        let mut joint_limit_weight = 1.0;
        let mut anchor = None;

        for goal in goals {
            match goal {
                Goal::Position { .. } => position_goals.push(goal),
                Goal::Rotation { .. } => rotation_goals.push(goal),
                Goal::Anchor { bone_id, target_position } => anchor = Some((*bone_id, *target_position)),
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

            self.apply_joint_limits(skeleton, joint_limit_weight);

            if solved {
                break;
            }
        }

        self.apply_rotation_goals(skeleton, &rotation_goals);
        self.apply_pose_prior(skeleton, pose_prior);
        self.apply_temporal_smoothness(skeleton, temporal_smoothness);
        self.apply_joint_limits(skeleton, joint_limit_weight);
        self.apply_anchor(skeleton, anchor);
        self.previous_pose = Some(skeleton.clone());
    }

    /// Puts the root back where it rests, then (with an anchor) moves it so the anchored bone
    /// lands on its target. Without this the root never moved: a headset lower than the
    /// skeleton's head, or across the room, was out of reach for rotations alone.
    fn apply_anchor(&mut self, skeleton: &mut SkeletonModel, anchor: Option<(u8, Vector3<f32>)>) {
        let Some(root_id) = skeleton.bones.values().find(|bone| bone.parent_id.is_none()).map(|bone| bone.id) else {
            return;
        };
        let rest = *self.root_rest.get_or_insert_with(|| skeleton.bones[&root_id].local_position);
        if let Some(root) = skeleton.bones.get_mut(&root_id) {
            root.local_position = rest;
        }
        skeleton.update_fk();
        let Some((bone_id, target)) = anchor else { return };
        let Some(current) = skeleton.get_joint_position(bone_id) else { return };
        if let Some(root) = skeleton.bones.get_mut(&root_id) {
            root.local_position += target - current;
        }
        skeleton.update_fk();
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
                // `rotation` turns the bone in world space; its local rotation is in the parent's frame.
                let parent_rotation = skeleton
                    .bones
                    .get(&bone_id)
                    .and_then(|bone| bone.parent_id)
                    .and_then(|parent_id| skeleton.bones.get(&parent_id))
                    .map_or_else(UnitQuaternion::identity, |parent| parent.global_rotation);
                if let Some(bone) = skeleton.bones.get_mut(&bone_id) {
                    bone.local_rotation =
                        parent_rotation.inverse() * rotation * parent_rotation * bone.local_rotation;
                    bone.local_rotation.renormalize();
                }
                skeleton.update_fk_from(bone_id);
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::skeleton::bone::Bone;

    #[test]
    fn an_anchor_moves_the_whole_body_onto_its_target() {
        let mut skeleton = SkeletonModel::new_humanoid();
        skeleton.update_fk();
        let before = skeleton.clone();
        let mut solver = IkSolver::new();
        // A headset lower than the skeleton's head and off to one side.
        let target = Vector3::new(0.6, 1.2, -0.4);
        solver.solve(&mut skeleton, &[Goal::Anchor { bone_id: 4, target_position: target }]);
        assert!((skeleton.get_joint_position(4).unwrap() - target).norm() < 1e-5);
        let shift = target - before.get_joint_position(4).unwrap();
        for (id, bone) in &skeleton.bones {
            let moved = bone.global_position - before.bones[id].global_position;
            assert!((moved - shift).norm() < 1e-5, "bone {id} moved with the rest");
        }
        // Without it, the body goes back to where it stands.
        solver.solve(&mut skeleton, &[]);
        assert!((skeleton.get_joint_position(0).unwrap() - before.get_joint_position(0).unwrap()).norm() < 1e-5);
    }

    #[test]
    fn a_ccd_step_points_the_end_at_the_target() {
        // A chain of six segments under a turned root. One CCD pass turns the end's five
        // parents in turn; the last of them (bone 1, whose parent is the turned root) must then
        // point the end straight at the target, which needs its world-space correction turned
        // into its parent's frame.
        let mut skeleton = SkeletonModel::new();
        skeleton.add_bone(Bone::new(0, "root".into(), None, Vector3::zeros(), None, None));
        for id in 1..=6 {
            skeleton.add_bone(Bone::new(id, format!("segment {id}"), Some(id - 1), Vector3::new(0.0, 0.4, 0.0), None, None));
        }
        skeleton.bones.get_mut(&0).unwrap().local_rotation =
            UnitQuaternion::from_axis_angle(&Vector3::x_axis(), 1.1) * UnitQuaternion::from_axis_angle(&Vector3::z_axis(), 0.6);
        skeleton.update_fk();
        let target = Vector3::new(0.9, 0.7, -0.5);
        IkSolver::new().solve_ccd_pass(&mut skeleton, 6, target);
        let joint = skeleton.get_joint_position(1).unwrap();
        let to_end = skeleton.get_joint_position(6).unwrap() - joint;
        let to_target = target - joint;
        assert!(to_end.angle(&to_target) < 1e-3, "{to_end:?} against {to_target:?}");
    }
}
