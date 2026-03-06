use crate::skeleton::bone::BoneId;
use nalgebra::Isometry3;

use std::collections::HashMap;

// Represents the dynamic pose of a skeleton at a given moment.
// It stores the calculated world-space transformations for each bone.
#[allow(dead_code)]
#[derive(Debug, Clone)]
pub struct SkeletonPose {
    pub bone_transforms: HashMap<BoneId, Isometry3<f32>>,
}

impl SkeletonPose {
    pub fn new() -> Self {
        Self {
            bone_transforms: HashMap::new(),
        }
    }
}

impl Default for SkeletonPose {
    fn default() -> Self {
        Self::new()
    }
}
