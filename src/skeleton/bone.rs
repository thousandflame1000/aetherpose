#![allow(dead_code)]
use nalgebra::{UnitQuaternion, Vector3};

pub type BoneId = u8;

// 定義完整的骨頭結構
#[derive(Debug, Clone)] // Removed Copy trait
pub struct Bone {
    pub id: BoneId,
    pub name: String, // Reintroduced name field
    pub parent_id: Option<BoneId>,
    pub local_position: Vector3<f32>,         // 相對於父骨頭的位置
    pub local_rotation: UnitQuaternion<f32>,  // 相對於父骨頭的旋轉
    pub global_position: Vector3<f32>,        // 世界座標位置
    pub global_rotation: UnitQuaternion<f32>, // 世界座標旋轉
    pub min_local_rotation_axis_angle: Option<Vector3<f32>>, // Minimum local rotation limits (axis-angle)
    pub max_local_rotation_axis_angle: Option<Vector3<f32>>, // Maximum local rotation limits (axis-angle)
}

impl Bone {
    pub fn new(
        id: BoneId,
        name: String, // Changed to String
        parent_id: Option<BoneId>,
        local_position: Vector3<f32>,
        min_local_rotation_axis_angle: Option<Vector3<f32>>,
        max_local_rotation_axis_angle: Option<Vector3<f32>>,
    ) -> Self {
        Self {
            id,
            name, // Storing the name
            parent_id,
            local_position,
            local_rotation: UnitQuaternion::identity(),
            global_position: Vector3::zeros(),
            global_rotation: UnitQuaternion::identity(),
            min_local_rotation_axis_angle,
            max_local_rotation_axis_angle,
        }
    }
}
