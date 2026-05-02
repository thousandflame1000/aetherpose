use aetherpose::fusion::FusionEngine;
use aetherpose::ik::solver::IkSolver;
use aetherpose::net::tracker::Tracker;
use aetherpose::skeleton::model::SkeletonModel;
use nalgebra::UnitQuaternion;
use std::collections::HashMap;

// Stress test: simulate 10k frames of tracker streams to catch long-running issues
#[test]
fn e2e_stress_10k() {
    let mut fusion = FusionEngine::new();
    let mut ik = IkSolver::new();
    let mut skeleton = SkeletonModel::new_humanoid();

    let mut trackers: HashMap<u8, Tracker> = HashMap::new();
    for id in 1u8..=6u8 {
        let mut t = Tracker::new(id);
        t.quat = Some([0.0, 0.0, 0.0, 1.0]);
        t.accel = Some([0.0, 9.81, 0.0]);
        trackers.insert(id, t);
    }

    for frame in 0..10_000u32 {
        for (i, (_id, tr)) in trackers.iter_mut().enumerate() {
            let phase = (frame as f32) * 0.02 + (i as f32) * 0.15;
            let yaw = (phase).sin() * 0.25;
            let pitch = (phase * 0.5).sin() * 0.15;
            let roll = if frame % 500 == 0 { std::f32::consts::PI } else { (phase * 0.2).sin() * 0.08 };
            let q = UnitQuaternion::from_euler_angles(roll, pitch, yaw);
            tr.quat = Some([q.i, q.j, q.k, q.w]);

            if frame % 123 == 0 && (i % 3) == 0 {
                tr.quat = None;
                tr.accel = None;
            } else {
                tr.accel = Some([0.0 + pitch, 9.81, 0.0 + roll]);
            }
        }

        let goals = fusion.process(&skeleton, &trackers, None, None, None);
        ik.solve(&mut skeleton, &goals);

        if frame % 1000 == 0 {
            for (_id, bone) in skeleton.bones.iter() {
                let p = bone.global_position;
                assert!(p.x.is_finite() && p.y.is_finite() && p.z.is_finite(), "NaN/Inf detected at frame {}", frame);
                assert!(p.x.abs() < 1e6 && p.y.abs() < 1e6 && p.z.abs() < 1e6, "Out of bounds at frame {}", frame);
            }
        }
    }
}
