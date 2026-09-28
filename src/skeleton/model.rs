use crate::skeleton::bone::{Bone, BoneId};
use nalgebra::{UnitQuaternion, Vector3};
use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct SkeletonModel {
    pub bones: HashMap<BoneId, Bone>,
    pub children: HashMap<BoneId, Vec<BoneId>>,
}

impl Default for SkeletonModel {
    fn default() -> Self {
        Self::new()
    }
}

impl SkeletonModel {
    pub fn new() -> Self {
        Self {
            bones: HashMap::new(),
            children: HashMap::new(),
        }
    }

    pub fn add_bone(&mut self, bone: Bone) {
        if let Some(parent_id) = bone.parent_id {
            self.children.entry(parent_id).or_default().push(bone.id);
        }
        self.bones.insert(bone.id, bone);
    }

    pub fn new_humanoid() -> Self {
        let mut skel = Self::new();
        let rad = |deg: f32| deg.to_radians();

        skel.add_bone(Bone::new(
            0,
            "Hip".to_string(),
            None,
            Vector3::new(0.0, 1.0, 0.0),
            None,
            None,
        ));

        skel.add_bone(Bone::new(
            1,
            "Waist".to_string(),
            Some(0),
            Vector3::new(0.0, 0.15, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            2,
            "Chest".to_string(),
            Some(1),
            Vector3::new(0.0, 0.25, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            3,
            "Neck".to_string(),
            Some(2),
            Vector3::new(0.0, 0.20, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            4,
            "Head".to_string(),
            Some(3),
            Vector3::new(0.0, 0.15, 0.0),
            None,
            None,
        ));

        let knee_min = Some(Vector3::new(rad(-150.0), rad(-5.0), rad(-5.0)));
        let knee_max = Some(Vector3::new(rad(0.0), rad(5.0), rad(5.0)));

        skel.add_bone(Bone::new(
            10,
            "L_UpLeg".to_string(),
            Some(0),
            Vector3::new(-0.15, -0.1, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            11,
            "L_Leg".to_string(),
            Some(10),
            Vector3::new(0.0, -0.4, 0.0),
            knee_min,
            knee_max,
        ));
        skel.add_bone(Bone::new(
            12,
            "L_Foot".to_string(),
            Some(11),
            Vector3::new(0.0, -0.4, 0.0),
            None,
            None,
        ));

        skel.add_bone(Bone::new(
            20,
            "R_UpLeg".to_string(),
            Some(0),
            Vector3::new(0.15, -0.1, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            21,
            "R_Leg".to_string(),
            Some(20),
            Vector3::new(0.0, -0.4, 0.0),
            knee_min,
            knee_max,
        ));
        skel.add_bone(Bone::new(
            22,
            "R_Foot".to_string(),
            Some(21),
            Vector3::new(0.0, -0.4, 0.0),
            None,
            None,
        ));

        let elbow_min = Some(Vector3::new(rad(-10.0), rad(0.0), rad(-10.0)));
        let elbow_max = Some(Vector3::new(rad(10.0), rad(160.0), rad(10.0)));

        skel.add_bone(Bone::new(
            30,
            "L_Shoulder".to_string(),
            Some(3),
            Vector3::new(-0.1, -0.05, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            31,
            "L_UpperArm".to_string(),
            Some(30),
            Vector3::new(-0.15, 0.0, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            32,
            "L_ForeArm".to_string(),
            Some(31),
            Vector3::new(-0.25, 0.0, 0.0),
            elbow_min,
            elbow_max,
        ));
        skel.add_bone(Bone::new(
            33,
            "L_Hand".to_string(),
            Some(32),
            Vector3::new(-0.1, 0.0, 0.0),
            None,
            None,
        ));

        skel.add_bone(Bone::new(
            40,
            "R_Shoulder".to_string(),
            Some(3),
            Vector3::new(0.1, -0.05, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            41,
            "R_UpperArm".to_string(),
            Some(40),
            Vector3::new(0.15, 0.0, 0.0),
            None,
            None,
        ));
        skel.add_bone(Bone::new(
            42,
            "R_ForeArm".to_string(),
            Some(41),
            Vector3::new(0.25, 0.0, 0.0),
            elbow_min,
            elbow_max,
        ));
        skel.add_bone(Bone::new(
            43,
            "R_Hand".to_string(),
            Some(42),
            Vector3::new(0.1, 0.0, 0.0),
            None,
            None,
        ));

        skel
    }

    pub fn update_fk(&mut self) {
        let update_order = [
            0, 1, 2, 3, 4, 10, 11, 12, 20, 21, 22, 30, 31, 32, 33, 40, 41, 42, 43,
        ];

        for id in update_order {
            if let Some(bone) = self.bones.get(&id).cloned() {
                let (parent_pos, parent_rot) = match bone.parent_id {
                    Some(pid) => self
                        .bones
                        .get(&pid)
                        .map(|parent| (parent.global_position, parent.global_rotation))
                        .unwrap_or_else(|| (Vector3::zeros(), UnitQuaternion::identity())),
                    None => (Vector3::zeros(), UnitQuaternion::identity()),
                };

                if let Some(current) = self.bones.get_mut(&id) {
                    current.global_rotation = parent_rot * current.local_rotation;
                    current.global_position =
                        parent_pos + (current.global_rotation * current.local_position);
                }
            }
        }
    }

    pub fn update_fk_from(&mut self, start_bone_id: BoneId) {
        let mut stack = vec![start_bone_id];

        while let Some(id) = stack.pop() {
            let (parent_pos, parent_rot) = {
                let bone = match self.bones.get(&id) {
                    Some(bone) => bone,
                    None => continue,
                };

                match bone.parent_id {
                    Some(pid) => self
                        .bones
                        .get(&pid)
                        .map(|parent| (parent.global_position, parent.global_rotation))
                        .unwrap_or_else(|| (Vector3::zeros(), UnitQuaternion::identity())),
                    None => (Vector3::zeros(), UnitQuaternion::identity()),
                }
            };

            if let Some(current) = self.bones.get_mut(&id) {
                current.global_rotation = parent_rot * current.local_rotation;
                current.global_position =
                    parent_pos + (current.global_rotation * current.local_position);
            }

            if let Some(child_ids) = self.children.get(&id) {
                stack.extend(child_ids);
            }
        }
    }

    pub fn get_joint_position(&self, bone_id: BoneId) -> Option<Vector3<f32>> {
        self.bones.get(&bone_id).map(|bone| bone.global_position)
    }

    pub fn adjust_proportions(&mut self, leg_scale: f32, arm_scale: f32, spine_scale: f32) {
        let base_spine = [
            (1, Vector3::new(0.0, 0.15, 0.0)),
            (2, Vector3::new(0.0, 0.25, 0.0)),
            (3, Vector3::new(0.0, 0.20, 0.0)),
            (4, Vector3::new(0.0, 0.15, 0.0)),
        ];

        let base_legs = [
            (10, Vector3::new(-0.15, -0.1, 0.0)),
            (11, Vector3::new(0.0, -0.4, 0.0)),
            (12, Vector3::new(0.0, -0.4, 0.0)),
            (20, Vector3::new(0.15, -0.1, 0.0)),
            (21, Vector3::new(0.0, -0.4, 0.0)),
            (22, Vector3::new(0.0, -0.4, 0.0)),
        ];

        let base_arms = [
            (31, Vector3::new(-0.15, 0.0, 0.0)),
            (32, Vector3::new(-0.25, 0.0, 0.0)),
            (41, Vector3::new(0.15, 0.0, 0.0)),
            (42, Vector3::new(0.25, 0.0, 0.0)),
        ];

        for (id, base) in &base_spine {
            if let Some(bone) = self.bones.get_mut(id) {
                bone.local_position = *base * spine_scale;
            }
        }

        for (id, base) in &base_legs {
            if let Some(bone) = self.bones.get_mut(id) {
                bone.local_position = if *id == 10 || *id == 20 {
                    Vector3::new(base.x, base.y * leg_scale, base.z)
                } else {
                    *base * leg_scale
                };
            }
        }

        for (id, base) in &base_arms {
            if let Some(bone) = self.bones.get_mut(id) {
                bone.local_position = *base * arm_scale;
            }
        }
    }

    pub fn set_leg_ratio(&mut self, ratio: f32) {
        let adjust_leg = |bones: &mut HashMap<BoneId, Bone>,
                          leg_id: BoneId,
                          foot_id: BoneId,
                          ratio: f32|
         -> Option<()> {
            let leg_bone = bones.get(&leg_id)?;
            let foot_bone = bones.get(&foot_id)?;

            let thigh_len = leg_bone.local_position.norm();
            let shin_len = foot_bone.local_position.norm();
            let total_len = thigh_len + shin_len;

            if total_len < 1e-4 {
                return None;
            }

            let new_shin_len = total_len / (ratio + 1.0);
            let new_thigh_len = total_len - new_shin_len;

            if let Some(bone) = bones.get_mut(&leg_id) {
                if let Some(dir) = bone.local_position.try_normalize(1e-6) {
                    bone.local_position = dir * new_thigh_len;
                }
            }

            if let Some(bone) = bones.get_mut(&foot_id) {
                if let Some(dir) = bone.local_position.try_normalize(1e-6) {
                    bone.local_position = dir * new_shin_len;
                }
            }

            Some(())
        };

        adjust_leg(&mut self.bones, 11, 12, ratio);
        adjust_leg(&mut self.bones, 21, 22, ratio);
        self.update_fk();
    }
}
