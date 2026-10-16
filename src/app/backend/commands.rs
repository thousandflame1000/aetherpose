use super::*;
use chrono::Local;
use crate::fusion::LegCalibrationError;

impl BackendRuntime {
    pub(super) async fn handle_commands(&mut self) -> bool {
        let mut snapshot_dirty = false;

        while let Ok(cmd) = self.cmd_rx.try_recv() {
            if self.handle_command(cmd).await {
                snapshot_dirty = true;
            }
        }

        snapshot_dirty
    }

    async fn handle_command(&mut self, cmd: BackendCommand) -> bool {
        match cmd {
            BackendCommand::RequestSnapshot => true,
            BackendCommand::SetIkSmoothness(value) => {
                // Refused values still answer with a snapshot, which puts the page's slider back.
                let Some(value) = setting(value, 0.0, 1.0) else { return true };
                self.ik_smoothness_weight = value;
                self.config.ik_smoothness = value;
                self.mark_config_changed();
                true
            }
            BackendCommand::ResetYaw => {
                self.fusion.reset_yaw(&self.net_trackers);
                true
            }
            BackendCommand::SetOscTarget(ip, port) => {
                // An unusable target keeps the working one (and config.json) and is reported.
                match OscSender::new(&ip, port).await {
                    Ok(sender) => {
                        self.osc_sender = Some(sender);
                        self.osc_error = None;
                        self.config.osc_ip = ip;
                        self.config.osc_port = port;
                        self.mark_config_changed();
                    }
                    Err(e) => {
                        error!("OSC target update failed: {}", e);
                        self.osc_error = Some(format!("{}:{} ({})", ip, port, e));
                    }
                }
                true
            }
            BackendCommand::AssignTracker(tracker_id, bone_id) => {
                self.assign_tracker(tracker_id, bone_id);
                true
            }
            BackendCommand::UnassignTracker(tracker_id) => {
                self.fusion.assigner.unassign(tracker_id);
                self.config.tracker_assignments.remove(&tracker_id);
                self.sync_unassigned_config();
                self.mark_config_changed();
                true
            }
            BackendCommand::ForgetTracker(tracker_id) => {
                self.fusion.assigner.map.remove(&tracker_id);
                self.fusion.assigner.unassigned.remove(&tracker_id);
                self.config.tracker_assignments.remove(&tracker_id);
                self.trackers.remove(&tracker_id);
                self.net_trackers.remove(&tracker_id);
                self.sync_unassigned_config();
                self.mark_config_changed();
                true
            }
            BackendCommand::SetProportions { leg, arm, spine } => {
                let (Some(leg), Some(arm), Some(spine)) =
                    (setting(leg, 0.5, 1.5), setting(arm, 0.5, 1.5), setting(spine, 0.5, 1.5))
                else {
                    return true;
                };
                self.prop_leg = leg;
                self.prop_arm = arm;
                self.prop_spine = spine;
                self.skeleton
                    .adjust_proportions(self.prop_leg, self.prop_arm, self.prop_spine);
                self.skeleton.set_leg_ratio(self.leg_ratio);
                self.config.prop_leg = leg;
                self.config.prop_arm = arm;
                self.config.prop_spine = spine;
                self.mark_config_changed();
                true
            }
            BackendCommand::ResetMounting => {
                self.fusion.reset_mounting(&self.net_trackers);
                true
            }
            BackendCommand::ClearAllCalibration => {
                self.fusion.clear_all_calibration();
                true
            }
            BackendCommand::SetDriftCorrection(value) => {
                let Some(value) = setting(value, 0.0, 1.0) else { return true };
                self.fusion.drift_correction = value;
                if value == 0.0 {
                    self.fusion.clear_drift_corrections();
                }
                self.config.drift_correction = value;
                self.mark_config_changed();
                true
            }
            BackendCommand::AutoAssign => {
                self.fusion.auto_assign(&self.net_trackers);
                self.persist_assignments();
                true
            }
            BackendCommand::StartRecording => {
                self.start_default_recorder();
                true
            }
            BackendCommand::StopRecording => {
                self.recorder = None;
                self.recorder_error = None;
                true
            }
            BackendCommand::SetRecorderConfig {
                enabled,
                filename,
                batch_size,
                flush_interval_ms,
            } => {
                self.configure_recorder(enabled, filename, batch_size, flush_interval_ms);
                true
            }
            BackendCommand::SetSerialConfig { enabled, port, baud } => {
                if let Some(enabled) = enabled {
                    self.config.serial_enabled = enabled;
                }
                if let Some(port) = port {
                    self.config.serial_port = Some(port);
                }
                if let Some(baud) = baud {
                    self.config.serial_baud = baud;
                }
                self.mark_config_changed();
                self.start_serial_manager_from_config();
                true
            }
            BackendCommand::SetSmoothingParams { min_cutoff, beta } => {
                let (Some(min_cutoff), Some(beta)) = (setting(min_cutoff, 0.01, 5.0), setting(beta, 0.0, 10.0)) else {
                    return true;
                };
                self.fusion.smoothing_min_cutoff = min_cutoff;
                self.fusion.smoothing_beta = beta;
                self.config.smoothing_min_cutoff = min_cutoff;
                self.config.smoothing_beta = beta;
                self.mark_config_changed();
                true
            }
            BackendCommand::SetTrajectoryIntegrationMode(mode) => {
                self.config.trajectory_integration_mode = mode;
                self.fusion.set_trajectory_integration_mode(mode);
                self.mark_config_changed();
                true
            }
            BackendCommand::SetZuptEnabled(enabled) => {
                self.config.zupt_enabled = enabled;
                self.fusion.set_zupt_enabled(enabled);
                self.mark_config_changed();
                true
            }
            BackendCommand::SetZuptParams {
                window_size,
                accel_var_threshold,
                gyro_threshold,
            } => {
                // Same limits as the page: a window of 1-200 samples (it sizes a buffer), thresholds > 0.
                if let Some(window_size) = window_size {
                    self.config.zupt_window_size = window_size.clamp(1, 200);
                }
                let positive = |value: &f32| value.is_finite() && *value > 0.0;
                if let Some(accel_var_threshold) = accel_var_threshold.filter(positive) {
                    self.config.zupt_accel_var_threshold = accel_var_threshold;
                }
                if let Some(gyro_threshold) = gyro_threshold.filter(positive) {
                    self.config.zupt_gyro_threshold = gyro_threshold;
                }

                self.fusion.set_zupt_params(
                    self.config.zupt_window_size,
                    self.config.zupt_accel_var_threshold,
                    self.config.zupt_gyro_threshold,
                );
                self.mark_config_changed();
                true
            }
            BackendCommand::StartLegCalibration => {
                self.fusion.start_leg_calibration();
                self.leg_calibration_result = None;
                true
            }
            BackendCommand::StopLegCalibration => {
                if !self.fusion.is_leg_calibrating() {
                    return false;
                }
                let total_leg_length = self.current_leg_length();
                self.leg_calibration_result = Some(match self.fusion.stop_leg_calibration(total_leg_length) {
                    Ok(new_ratio) => {
                        info!("Leg ratio calibrated to {:.3}", new_ratio);
                        self.leg_ratio = new_ratio;
                        self.skeleton.set_leg_ratio(self.leg_ratio);
                        self.config.leg_ratio = new_ratio;
                        self.mark_config_changed();
                        format!("done:{:.3}", new_ratio)
                    }
                    Err(LegCalibrationError::NoSamples) => "no_samples".to_string(),
                    Err(LegCalibrationError::SmallSwing(metres)) => format!("small_swing:{:.3}", metres),
                    Err(LegCalibrationError::Unsolvable) => "unsolvable".to_string(),
                    Err(LegCalibrationError::OutOfRange(ratio)) => format!("out_of_range:{:.3}", ratio),
                });
                true
            }
            BackendCommand::SetLegRatio(value) => {
                // The range config.json is held to when it loads.
                let Some(value) = setting(value, 0.2, 3.0) else { return true };
                self.leg_ratio = value;
                self.skeleton.set_leg_ratio(value);
                self.config.leg_ratio = value;
                self.leg_calibration_result = None;
                self.mark_config_changed();
                true
            }
            BackendCommand::SetFloorOffset(value) => {
                let Some(value) = setting(value, -2.0, 2.0) else { return true };
                self.floor_offset = value;
                self.config.floor_offset = value;
                self.mark_config_changed();
                true
            }
            BackendCommand::AutoFloor => {
                if let Some(min_y) = self.current_foot_min_y() {
                    self.floor_offset -= min_y;
                    self.config.floor_offset = self.floor_offset;
                    self.mark_config_changed();
                }
                true
            }
            BackendCommand::StartShakeAssign(bone_id) => {
                if self.skeleton.bones.contains_key(&bone_id) {
                    self.pending_shake_bone = Some(bone_id);
                } else {
                    log::warn!("Shake-assign to unknown bone {} ignored", bone_id);
                }
                true
            }
            BackendCommand::CancelShakeAssign => {
                self.pending_shake_bone = None;
                true
            }
        }
    }

    fn start_default_recorder(&mut self) {
        if self.recorder.is_some() {
            return;
        }

        match Recorder::new(&self.skeleton) {
            Ok(recorder) => self.recorder = Some(recorder),
            Err(e) => error!("Recorder init failed: {}", e),
        }
    }

    fn configure_recorder(
        &mut self,
        enabled: Option<bool>,
        filename: Option<String>,
        batch_size: Option<usize>,
        flush_interval_ms: Option<u64>,
    ) {
        // The page's limits. The batch sizes a buffer up front: a huge value would abort the
        // backend on allocation, and an interval of 0 would flush on every frame.
        let batch_size = batch_size.map(|value| value.clamp(1, 10_000));
        let flush_interval_ms = flush_interval_ms.map(|value| value.clamp(10, 60_000));
        let want_enable = enabled.unwrap_or(self.recorder.is_some());
        if !want_enable {
            self.recorder = None;
            self.recorder_error = None;
            return;
        }

        if self.recorder.is_none() {
            match self.build_recorder(filename, batch_size, flush_interval_ms) {
                Ok(recorder) => {
                    self.recorder = Some(recorder);
                    self.recorder_error = None;
                }
                Err(e) => self.recorder_error = Some(e),
            }
            return;
        }

        if filename.is_none() && batch_size.is_none() && flush_interval_ms.is_none() {
            return;
        }

        if let Some(existing) = self.recorder.take() {
            let next_filename = filename.unwrap_or(existing.filename.clone());
            let next_batch_size = batch_size.unwrap_or(existing.batch_size);
            let next_flush_interval_ms = flush_interval_ms.unwrap_or(existing.flush_interval_ms);

            match self.build_recorder(
                Some(next_filename),
                Some(next_batch_size),
                Some(next_flush_interval_ms),
            ) {
                Ok(recorder) => {
                    self.recorder = Some(recorder);
                    self.recorder_error = None;
                }
                Err(e) => {
                    self.recorder = Some(existing);
                    self.recorder_error = Some(e);
                }
            }
        }
    }

    fn build_recorder(
        &self,
        filename: Option<String>,
        batch_size: Option<usize>,
        flush_interval_ms: Option<u64>,
    ) -> Result<Recorder, String> {
        if filename.is_none() && batch_size.is_none() && flush_interval_ms.is_none() {
            return Recorder::new(&self.skeleton).map_err(|e| {
                error!("Recorder init failed: {}", e);
                format!("open:{}", e)
            });
        }

        let filename = filename.unwrap_or_else(|| {
            let ts = Local::now().format("%Y-%m-%d_%H-%M-%S").to_string();
            format!("recording_{}.csv", ts)
        });
        let batch_size = batch_size.unwrap_or(DEFAULT_RECORDER_BATCH_SIZE);
        let flush_interval_ms = flush_interval_ms.unwrap_or(DEFAULT_RECORDER_FLUSH_INTERVAL_MS);

        match Recorder::new_with_options(
            &self.skeleton,
            filename,
            batch_size,
            Duration::from_millis(flush_interval_ms),
        ) {
            Ok(recorder) => Ok(recorder),
            Err(e) => {
                error!("Recorder reconfigure failed: {}", e);
                Err(format!("open:{}", e))
            }
        }
    }

    /// Gives `bone_id` to one tracker only (see assign_exclusive) and saves
    /// the assignments that changed.
    pub(super) fn assign_tracker(&mut self, tracker_id: u8, bone_id: u8) {
        // Only the skeleton's bones: anything else would be saved and shown as a nameless part.
        if !self.skeleton.bones.contains_key(&bone_id) {
            log::warn!("Assignment of tracker {} to unknown bone {} ignored", tracker_id, bone_id);
            return;
        }
        let displaced = self.fusion.assigner.assign_exclusive(tracker_id, bone_id);
        self.config.tracker_assignments.insert(tracker_id, bone_id);
        for (other, bone) in displaced {
            info!("Tracker {} gave bone {} to tracker {}; it now has {:?}", other, bone_id, tracker_id, bone);
            match bone {
                Some(bone) => self.config.tracker_assignments.insert(other, bone),
                None => self.config.tracker_assignments.remove(&other),
            };
        }
        self.sync_unassigned_config();
        self.mark_config_changed();
    }

    fn current_leg_length(&self) -> f32 {
        if let (Some(up_leg), Some(leg), Some(foot)) = (
            self.skeleton.bones.get(&10),
            self.skeleton.bones.get(&11),
            self.skeleton.bones.get(&12),
        ) {
            let thigh_length = (leg.global_position - up_leg.global_position).magnitude();
            let shin_length = (foot.global_position - leg.global_position).magnitude();
            thigh_length + shin_length
        } else {
            0.9
        }
    }

    fn current_foot_min_y(&self) -> Option<f32> {
        let mut min_y = f32::MAX;

        if let Some(left_foot) = self.skeleton.bones.get(&12) {
            min_y = min_y.min(left_foot.global_position.y);
        }
        if let Some(right_foot) = self.skeleton.bones.get(&22) {
            min_y = min_y.min(right_foot.global_position.y);
        }

        (min_y != f32::MAX).then_some(min_y)
    }
}

/// Settings arrive from any local client, not only the page's sliders: keep them inside the
/// ranges the page offers, and refuse non-finite numbers, which would not survive a save to
/// config.json (JSON has no NaN or infinity).
pub(crate) fn setting(value: f32, min: f32, max: f32) -> Option<f32> {
    value.is_finite().then(|| value.clamp(min, max))
}

#[cfg(test)]
mod tests {
    use super::setting;

    #[test]
    fn settings_are_kept_in_range_and_finite() {
        assert_eq!(setting(0.4, 0.0, 1.0), Some(0.4));
        assert_eq!(setting(5.0, 0.0, 1.0), Some(1.0));
        assert_eq!(setting(-3.0, -2.0, 2.0), Some(-2.0));
        assert_eq!(setting(f32::NAN, 0.0, 1.0), None);
        assert_eq!(setting(f32::INFINITY, 0.0, 1.0), None);
    }
}
