use aetherpose::fusion::FusionEngine;
use aetherpose::ik::solver::IkSolver;
use aetherpose::net::tracker::Tracker;
use aetherpose::skeleton::model::SkeletonModel;
use nalgebra::UnitQuaternion;
use std::collections::HashMap;

// End-to-end dynamic validation: feed synthetic tracker streams into FusionEngine
// and IK solver over many frames, ensuring no NaN/panic and values remain finite.
#[test]
fn e2e_dynamic_validation() {
    let mut fusion = FusionEngine::new();
    let mut ik = IkSolver::new();

    let mut skeleton = SkeletonModel::new_humanoid();

    // prepare a small set of trackers (some assigned, some intermittent)
    let mut trackers: HashMap<u8, Tracker> = HashMap::new();
    for id in 1u8..=6u8 {
        let mut t = Tracker::new(id);
        // start with identity rotation
        t.quat = Some([0.0, 0.0, 0.0, 1.0]);
        t.accel = Some([0.0, 9.81, 0.0]);
        trackers.insert(id, t);
    }

    // run many frames with deterministic but stressful input patterns
    for frame in 0..200 {
        // vary rotations: slow oscillation + occasional large jumps
        for (i, (_id, tr)) in trackers.iter_mut().enumerate() {
            let phase = (frame as f32) * 0.05 + (i as f32) * 0.3;
            let yaw = (phase).sin() * 0.3; // moderate yaw
            let pitch = (phase * 0.6).sin() * 0.2;
            let roll = if frame % 50 == 0 { std::f32::consts::PI } else { (phase * 0.3).sin() * 0.1 };
            let q = UnitQuaternion::from_euler_angles(roll, pitch, yaw);
            tr.quat = Some([q.i, q.j, q.k, q.w]);

            // occasional missing accel/quaternion to simulate packet loss
            if frame % 37 == 0 && (i % 2) == 0 {
                tr.quat = None;
                tr.accel = None;
            } else {
                tr.accel = Some([0.0 + pitch, 9.81, 0.0 + roll]);
            }
        }

        // process fusion -> goals
        let goals = fusion.process(&skeleton, &trackers, None, None, None);

        // apply IK solving step
        // clone skeleton to mutate locally
        ik.solve(&mut skeleton, &goals);

        // sanity checks: all bone positions finite and within reasonable bounds
        for (_id, bone) in skeleton.bones.iter() {
            let p = bone.global_position;
            assert!(p.x.is_finite() && p.y.is_finite() && p.z.is_finite(), "Position NaN/inf at frame {}", frame);
            // bounds check (avoid runaway values)
            assert!(p.x.abs() < 1000.0 && p.y.abs() < 1000.0 && p.z.abs() < 1000.0, "Position out of bounds at frame {}: {:?}", frame, p);
            // rotation should be normalized unit quaternion
            let r = bone.global_rotation.coords;
            assert!(r[0].is_finite() && r[1].is_finite() && r[2].is_finite() && r[3].is_finite(), "Rotation NaN/inf at frame {}", frame);
        }
    }
}
