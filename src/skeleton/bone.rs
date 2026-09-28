use nalgebra::{UnitQuaternion, Vector3};

pub type BoneId = u8;

#[derive(Debug, Clone)]
pub struct Bone {
    pub id: BoneId,
    pub name: String,
    pub parent_id: Option<BoneId>,
    pub local_position: Vector3<f32>,
    pub local_rotation: UnitQuaternion<f32>,
    pub global_position: Vector3<f32>,
    pub global_rotation: UnitQuaternion<f32>,
    pub min_local_rotation_axis_angle: Option<Vector3<f32>>,
    pub max_local_rotation_axis_angle: Option<Vector3<f32>>,
}

impl Bone {
    pub fn new(
        id: BoneId,
        name: String,
        parent_id: Option<BoneId>,
        local_position: Vector3<f32>,
        min_local_rotation_axis_angle: Option<Vector3<f32>>,
        max_local_rotation_axis_angle: Option<Vector3<f32>>,
    ) -> Self {
        Self {
            id,
            name,
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
