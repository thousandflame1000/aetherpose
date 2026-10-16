use aetherpose::fusion::FusionEngine;
use aetherpose::net::tracker::Tracker;
use aetherpose::AppConfig;
use std::collections::HashMap;

fn connected(ids: &[u8]) -> HashMap<u8, Tracker> {
    ids.iter().map(|id| (*id, Tracker::new(*id))).collect()
}

#[test]
fn new_trackers_get_free_bones_and_keep_manual_assignments() {
    let mut fusion = FusionEngine::new();
    fusion.assign_unassigned(&connected(&[76]));
    assert_eq!(fusion.assigner.get_bone_id(76), Some(2), "first tracker takes the chest slot");

    // The user moves tracker 76 to the head; a tracker connecting later must not undo that.
    fusion.assigner.set_assignment(76, 4);
    fusion.assign_unassigned(&connected(&[31, 76]));
    assert_eq!(fusion.assigner.get_bone_id(76), Some(4));
    assert_eq!(fusion.assigner.get_bone_id(31), Some(2));

    fusion.assign_unassigned(&connected(&[31, 43, 76]));
    assert_eq!(fusion.assigner.get_bone_id(43), Some(32), "next free TransPose slot");
}

#[test]
fn an_unassigned_tracker_stays_without_a_bone_until_assigned_again() {
    let mut fusion = FusionEngine::new();
    fusion.assign_unassigned(&connected(&[76]));
    fusion.assigner.unassign(76);
    fusion.assign_unassigned(&connected(&[31, 76]));
    assert_eq!(fusion.assigner.get_bone_id(76), None);
    assert!(fusion.assigner.get_bone_id(31).is_some());
    fusion.assigner.assign_exclusive(76, 32);
    assert_eq!(fusion.assigner.get_bone_id(76), Some(32));
    assert!(!fusion.assigner.unassigned.contains(&76));
    fusion.assigner.unassign(76);
    fusion.auto_assign(&connected(&[31, 76]));
    assert!(fusion.assigner.get_bone_id(76).is_some(), "Auto Assign reassigns everything");
}

#[test]
fn a_bone_belongs_to_one_tracker() {
    let mut fusion = FusionEngine::new();
    fusion.assigner.set_assignment(31, 2);
    fusion.assigner.set_assignment(43, 32);
    // Giving tracker 43 the chest swaps: tracker 31 takes the left forearm.
    assert_eq!(fusion.assigner.assign_exclusive(43, 2), vec![(31, Some(32))]);
    assert_eq!(fusion.assigner.get_bone_id(43), Some(2));
    assert_eq!(fusion.assigner.get_bone_id(31), Some(32));
    // A tracker without a bone takes one: the holder is left unassigned.
    assert_eq!(fusion.assigner.assign_exclusive(76, 32), vec![(31, None)]);
    assert_eq!(fusion.assigner.get_bone_id(31), None);
    // Choosing the bone a tracker already has changes nothing.
    assert!(fusion.assigner.assign_exclusive(76, 32).is_empty());
    assert_eq!(fusion.assigner.get_bone_id(76), Some(32));
}

#[test]
fn unknown_tracker_ids_have_no_bone_until_they_connect() {
    let fusion = FusionEngine::new();
    for id in 0..=255u8 {
        assert_eq!(fusion.assigner.get_bone_id(id), None);
    }
}

#[test]
fn auto_assign_button_reassigns_everything_by_id_order() {
    let mut fusion = FusionEngine::new();
    fusion.assigner.set_assignment(76, 4);
    fusion.auto_assign(&connected(&[76, 31]));
    assert_eq!(fusion.assigner.get_bone_id(31), Some(2));
    assert_eq!(fusion.assigner.get_bone_id(76), Some(32));
}

#[test]
fn snapshot_settings_mirror_the_saved_config() {
    let config = AppConfig { prop_leg: 1.2, osc_port: 9100, ..AppConfig::default() };
    let json = serde_json::to_value(config.ws_settings()).unwrap();
    assert_eq!(json["prop_leg"], serde_json::json!(1.2f32));
    assert_eq!(json["osc_port"], 9100);
    assert_eq!(json["trajectory_integration_mode"], "rk4");
}
