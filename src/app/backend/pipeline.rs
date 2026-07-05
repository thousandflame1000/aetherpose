use super::*;
use crate::app::types::{GuiSnapshot, WsBone};
use crate::ik::goals::Goal;

impl BackendRuntime {
    pub(super) async fn run_pose_pipeline(&mut self) {
        let quest_data = self.quest_rx.borrow_and_update();
        let mut ik_goals = self.fusion.process(
            &self.skeleton,
            &self.net_trackers,
            quest_data.head.as_ref(),
            quest_data.left_hand.as_ref(),
            quest_data.right_hand.as_ref(),
        );
        ik_goals.push(Goal::PosePrior {
            pose: self.t_pose.clone(),
            weight: 0.02,
        });
        ik_goals.push(Goal::TemporalSmoothness {
            weight: self.ik_smoothness_weight,
        });
        ik_goals.push(Goal::JointLimits { weight: 1.0 });

        self.skeleton.update_fk();
        self.ik_solver.solve(&mut self.skeleton, &ik_goals);

        for bone in self.skeleton.bones.values_mut() {
            bone.global_position.y += self.floor_offset;
        }

        let mut stop_recording_on_error = false;
        if let Some(recorder) = &mut self.recorder {
            if let Err(e) = recorder.record_frame(&self.skeleton) {
                error!("Recorder write failed, stopping recorder: {}", e);
                stop_recording_on_error = true;
            }
        }
        if stop_recording_on_error {
            self.recorder = None;
        }

        if let Some(sender) = &self.osc_sender {
            sender.send_skeleton(&self.skeleton).await;
        }
    }

    pub(super) fn refresh_tracker_tps(&mut self) {
        if self.last_tps_update.elapsed() < Duration::from_secs(1) {
            return;
        }

        for (tracker_id, count) in &self.tracker_packet_counts {
            if let Some(tracker) = self.trackers.get_mut(tracker_id) {
                tracker.tps = *count;
            }
        }

        self.tracker_packet_counts.clear();
        self.last_tps_update = std::time::Instant::now();
    }

    pub(super) fn publish_snapshot(&mut self) {
        self.sync_tracker_ui_state();

        if let Ok(mut shared) = self.shared_skel.write() {
            *shared = self.skeleton.clone();
        }

        let (
            recorder_dropped_count,
            recorder_write_errors,
            recorder_filename,
            recorder_batch_size,
            recorder_flush_interval_ms,
        ) = self.recorder_metrics();

        let bones: Vec<WsBone> = self
            .skeleton
            .bones
            .values()
            .map(|b| WsBone {
                id: b.id,
                name: b.name.clone(),
                parent_id: b.parent_id,
                pos: [
                    b.global_position.x,
                    b.global_position.y,
                    b.global_position.z,
                ],
            })
            .collect();

        let snapshot = GuiSnapshot {
            packet_count: self.packet_count,
            trackers: self.trackers.clone(),
            mag_calibration_points: self.fusion.mag_calibration_points.clone(),
            mag_calibrating_tracker_id: self.mag_calibrating_tracker_id,
            is_recording: self.recorder.is_some(),
            recorder_dropped_count,
            recorder_write_errors,
            recorder_filename,
            recorder_batch_size,
            recorder_flush_interval_ms,
            mag_calibrations: self.fusion.mag_calibrations.clone(),
            leg_ratio: self.leg_ratio,
            floor_offset: self.floor_offset,
            pending_shake_bone: self.pending_shake_bone,
            serial_running: self.serial_running(),
            serial_status_msg: self.current_serial_status(),
            bones,
        };

        let _ = self.tx.send(GuiUpdate::Snapshot(snapshot));
    }

    fn sync_tracker_ui_state(&mut self) {
        for tracker in self.trackers.values_mut() {
            tracker.assigned_bone = self.fusion.assigner.get_bone_id(tracker.id);
            tracker.is_mag_calibrating = self
                .fusion
                .mag_calibration_active
                .get(&tracker.id)
                .copied()
                .unwrap_or(false);
        }
    }

    fn recorder_metrics(&self) -> (u64, u64, Option<String>, usize, u64) {
        if let Some(recorder) = &self.recorder {
            (
                recorder.dropped_count.load(Ordering::Relaxed),
                recorder.write_error_count.load(Ordering::Relaxed),
                Some(recorder.filename.clone()),
                recorder.batch_size,
                recorder.flush_interval_ms,
            )
        } else {
            (
                0,
                0,
                None,
                DEFAULT_RECORDER_BATCH_SIZE,
                DEFAULT_RECORDER_FLUSH_INTERVAL_MS,
            )
        }
    }

    fn serial_running(&self) -> bool {
        self.serial_running_flag.load(Ordering::Relaxed)
    }

    fn current_serial_status(&self) -> Option<String> {
        self.serial_status_shared
            .lock()
            .ok()
            .and_then(|status| status.clone())
    }
}
