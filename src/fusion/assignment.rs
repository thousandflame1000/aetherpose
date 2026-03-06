use crate::skeleton::BoneId;
use std::collections::HashMap;

pub struct TrackerBoneAssigner {
    // Tracker ID -> Bone ID 的映射表
    pub map: HashMap<u8, BoneId>,
}

impl Default for TrackerBoneAssigner {
    fn default() -> Self {
        Self::new()
    }
}

impl TrackerBoneAssigner {
    pub fn new() -> Self {
        let mut map = HashMap::new();
        // 預設映射範例 (需配合 Skeleton 定義)
        map.insert(1, 0); // Tracker 1 -> Hip
        map.insert(2, 2); // Tracker 2 -> Chest
        map.insert(3, 4); // Tracker 3 -> Head
        map.insert(4, 31); // Tracker 4 -> L_UpperArm
        map.insert(5, 41); // Tracker 5 -> R_UpperArm
        map.insert(6, 10); // Tracker 6 -> L_UpLeg
        map.insert(7, 20); // Tracker 7 -> R_UpLeg

        Self { map }
    }

    pub fn get_bone_id(&self, tracker_id: u8) -> Option<BoneId> {
        self.map.get(&tracker_id).copied()
    }

    pub fn set_assignment(&mut self, tracker_id: u8, bone_id: BoneId) {
        self.map.insert(tracker_id, bone_id);
    }
}
