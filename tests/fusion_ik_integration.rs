use aetherpose::fusion::{AuthoritativePose, FusionEngine};
use aetherpose::skeleton::model::SkeletonModel;
use aetherpose::net::tracker::Tracker;
use aetherpose::ik::goals::Goal;
use nalgebra::{UnitQuaternion, Vector3};
use std::collections::HashMap;

#[test]
fn test_process_with_authoritative_head() {
    let mut fusion = FusionEngine::new();
    let skel = SkeletonModel::new_humanoid();
    let trackers: HashMap<u8, Tracker> = HashMap::new();

    let head = AuthoritativePose {
        position: Vector3::new(0.0, 1.6, 0.0),
        rotation: UnitQuaternion::identity(),
    };

    let goals = fusion.process(&skel, &trackers, Some(&head), None, None);
    // Expect at least a rotation and a position goal for head (bone id 4)
    let mut found_rot = false;
    let mut found_pos = false;
    for g in goals {
        match g {
            Goal::Rotation { bone_id: 4, .. } => found_rot = true,
            Goal::Position { bone_id: 4, .. } => found_pos = true,
            _ => {}
        }
    }
    assert!(found_rot && found_pos, "Authoritative head should produce head goals");
}

#[test]
fn test_process_with_assigned_tracker() {
    let mut fusion = FusionEngine::new();
    let skel = SkeletonModel::new_humanoid();
    let mut trackers: HashMap<u8, Tracker> = HashMap::new();

    // create a tracker with rotation and accel
    let mut t = Tracker::new(10);
    t.quat = Some([0.0, 0.0, 0.0, 1.0]);
    t.accel = Some([0.0, 1.0, 0.0]);
    trackers.insert(10u8, t);

    // assign tracker 10 -> bone 10
    fusion.assigner.set_assignment(10, 10);

    let goals = fusion.process(&skel, &trackers, None, None, None);
    // Expect at least one goal targeting bone 10
    let mut found = false;
    for g in goals {
        if let Some(bid) = g.bone_id() {
            if bid == 10 {
                found = true;
                break;
            }
        }
    }
    assert!(found, "Assigned tracker should produce a goal for assigned bone");
}

#[test]
fn test_zupt_params_and_stationary_query() {
    let mut fusion = FusionEngine::new();

    // Use tracker id 12 (foot) and simulate stable accel
    let accel = [0.0_f32, 1.0_f32, 0.0_f32];
    // initial calls should not panic and return a bool
    for _ in 0..10 {
        let _ = fusion.is_tracker_stationary(12, accel, None);
    }

    // change params and ensure call still works
    fusion.set_zupt_params(4, 10.0, 1.0);
    let stationary = fusion.is_tracker_stationary(12, accel, None);
    // ensure return type is bool and the call completed
    let _stationary_val: bool = stationary;
}

#[test]
fn test_zupt_disable_forces_non_stationary() {
    let mut fusion = FusionEngine::new();
    fusion.set_zupt_enabled(false);

    for _ in 0..10 {
        assert!(!fusion.is_tracker_stationary(12, [0.0, 1.0, 0.0], None));
    }
}
