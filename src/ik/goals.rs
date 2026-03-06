#![allow(dead_code)]

use crate::skeleton::{bone::BoneId, model::SkeletonModel};
use nalgebra::{UnitQuaternion, Vector3};

/// Represents a single goal or constraint for the IK solver.
/// Each goal contributes to the total energy function that the solver tries to minimize.
#[derive(Clone, Debug)]
pub enum Goal {
    /// Pushes a bone's position towards a target position in global space.
    /// Corresponds to the ||f(q) - x_target||^2 term.
    Position {
        bone_id: BoneId,
        target_position: Vector3<f32>,
        weight: f32,
    },
    /// Pushes a bone's rotation towards a target rotation in global space.
    /// Corresponds to the ||Log(R_target^-1 * R(q))||^2 term.
    Rotation {
        bone_id: BoneId,
        target_rotation: UnitQuaternion<f32>,
        weight: f32,
    },
    /// Pulls the entire skeleton's pose towards a reference "prior" pose.
    /// Corresponds to the ||q - q_prior||^2 term.
    PosePrior {
        pose: SkeletonModel, // The target pose (e.g., a T-pose)
        weight: f32,
    },
    /// Penalizes joints for exceeding their natural limits.
    /// Corresponds to the ||W_lim * phi(q)||^2 term.
    JointLimits { weight: f32 },
    /// Penalizes large changes in joint angles between frames to ensure smoothness.
    /// Corresponds to the ||q_t - q_{t-1}||^2 term.
    TemporalSmoothness {
        // q_{t-1} is fetched from the skeleton's previous state
        weight: f32,
    },
    // --- [新增] 極向量約束 ---
    /// Constrains the bending direction of a limb.
    Pole {
        /// The ID of the middle joint of the limb (e.g., elbow or knee).
        /// This is the joint whose orientation we want to control.
        middle_joint_id: BoneId,

        /// The ID of the end-effector of the limb (e.g., hand or foot).
        /// This helps the solver identify the full IK chain.
        end_effector_id: BoneId,

        /// A point in world space that the `middle_joint` should "point towards".
        pole_target_position: Vector3<f32>,

        /// The weight of this constraint.
        weight: f32,
    },
}

impl Goal {
    pub fn bone_id(&self) -> Option<BoneId> {
        match self {
            Goal::Position { bone_id, .. } => Some(*bone_id),
            Goal::Rotation { bone_id, .. } => Some(*bone_id),
            Goal::Pole {
                end_effector_id, ..
            } => Some(*end_effector_id), // The pole goal affects the whole chain up to the end effector
            _ => None,
        }
    }
}
