use crate::skeleton::BoneId;
use std::collections::{HashMap, HashSet};

pub struct TrackerBoneAssigner {
    // Tracker ID -> Bone ID 的映射表
    pub map: HashMap<u8, BoneId>,
    /// Trackers the user set to "未指派": automatic assignment leaves them without a bone.
    pub unassigned: HashSet<u8>,
}

impl Default for TrackerBoneAssigner {
    fn default() -> Self {
        Self::new()
    }
}

impl TrackerBoneAssigner {
    pub fn new() -> Self {
        // Starts empty: tracker IDs come from each board's MAC address, so a
        // fixed ID table would only claim bones for IDs that never connect.
        // Saved assignments are loaded from config; new trackers get a free
        // bone from FusionEngine::assign_unassigned.
        Self { map: HashMap::new(), unassigned: HashSet::new() }
    }

    pub fn get_bone_id(&self, tracker_id: u8) -> Option<BoneId> {
        self.map.get(&tracker_id).copied()
    }

    pub fn set_assignment(&mut self, tracker_id: u8, bone_id: BoneId) {
        self.unassigned.remove(&tracker_id);
        self.map.insert(tracker_id, bone_id);
    }

    /// Takes the tracker's bone away and keeps it that way until it is assigned again.
    pub fn unassign(&mut self, tracker_id: u8) {
        self.map.remove(&tracker_id);
        self.unassigned.insert(tracker_id);
    }

    /// Assigns `bone_id` to `tracker_id` so that no other tracker keeps it: a
    /// tracker already on that bone takes the bone `tracker_id` had (a swap),
    /// or none. Returns each displaced tracker with its new bone.
    pub fn assign_exclusive(&mut self, tracker_id: u8, bone_id: BoneId) -> Vec<(u8, Option<BoneId>)> {
        self.unassigned.remove(&tracker_id);
        let previous = self.map.get(&tracker_id).copied().filter(|bone| *bone != bone_id);
        let mut holders: Vec<u8> = self
            .map
            .iter()
            .filter(|(id, bone)| **id != tracker_id && **bone == bone_id)
            .map(|(id, _)| *id)
            .collect();
        holders.sort();
        self.map.insert(tracker_id, bone_id);
        holders
            .into_iter()
            .enumerate()
            .map(|(index, holder)| {
                let next = if index == 0 { previous } else { None };
                match next {
                    Some(bone) => self.map.insert(holder, bone),
                    None => self.map.remove(&holder),
                };
                (holder, next)
            })
            .collect()
    }
}
