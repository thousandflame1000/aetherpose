use crate::skeleton::{bone::BoneId, model::SkeletonModel};
use nalgebra::{UnitQuaternion, Vector3};

/// A target or regularization term understood by the IK solver.
#[derive(Clone, Debug)]
pub enum Goal {
    Position {
        bone_id: BoneId,
        target_position: Vector3<f32>,
        weight: f32,
    },
    Rotation {
        bone_id: BoneId,
        target_rotation: UnitQuaternion<f32>,
        weight: f32,
    },
    PosePrior {
        pose: SkeletonModel,
        weight: f32,
    },
    JointLimits {
        weight: f32,
    },
    TemporalSmoothness {
        weight: f32,
    },
}

impl Goal {
    pub fn bone_id(&self) -> Option<BoneId> {
        match self {
            Goal::Position { bone_id, .. } | Goal::Rotation { bone_id, .. } => Some(*bone_id),
            _ => None,
        }
    }
}
