use super::*;
use chrono::Local;

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
            BackendCommand::SetIkSmoothness(value) => {
                self.ik_smoothness_weight = value;
                false
            }
            BackendCommand::ResetYaw => {
                self.fusion.reset_yaw(&self.net_trackers);
                true
            }
            BackendCommand::SetOscTarget(ip, port) => {
                self.osc_sender = match OscSender::new(&ip, port).await {
                    Ok(sender) => Some(sender),
                    Err(e) => {
                        error!("OSC target update failed: {}", e);
                        None
                    }
                };
                false
            }
            BackendCommand::AssignTracker(tracker_id, bone_id) => {
                self.fusion.assigner.set_assignment(tracker_id, bone_id);
                true
            }
            BackendCommand::SetProportions { leg, arm, spine } => {
                self.prop_leg = leg;
                self.prop_arm = arm;
                self.prop_spine = spine;
                self.skeleton
                    .adjust_proportions(self.prop_leg, self.prop_arm, self.prop_spine);
                self.skeleton.set_leg_ratio(self.leg_ratio);
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
                self.fusion.drift_correction = value;
                false
            }
            BackendCommand::AutoAssign => {
                self.fusion.auto_assign(&self.net_trackers);
                true
            }
            BackendCommand::StartMagCalibration(tracker_id) => {
                self.fusion.start_mag_calibration(tracker_id);
                self.mag_calibrating_tracker_id = Some(tracker_id);
                true
            }
            BackendCommand::StopMagCalibration(tracker_id) => {
                self.fusion.stop_mag_calibration(tracker_id);
                self.mag_calibrating_tracker_id = None;
                true
            }
            BackendCommand::StartRecording => {
                self.start_default_recorder();
                true
            }
            BackendCommand::StopRecording => {
                self.recorder = None;
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
                self.config.save();
                self.start_serial_manager_from_config();
                true
            }
            BackendCommand::SetSmoothingParams { min_cutoff, beta } => {
                self.fusion.smoothing_min_cutoff = min_cutoff;
                self.fusion.smoothing_beta = beta;
                false
            }
            BackendCommand::SetTrajectoryIntegrationMode(mode) => {
                self.config.trajectory_integration_mode = mode;
                self.fusion.set_trajectory_integration_mode(mode);
                self.config.save();
                false
            }
            BackendCommand::SetZuptEnabled(enabled) => {
                self.config.zupt_enabled = enabled;
                self.fusion.set_zupt_enabled(enabled);
                self.config.save();
                false
            }
            BackendCommand::SetZuptParams {
                window_size,
                accel_var_threshold,
                gyro_threshold,
            } => {
                if let Some(window_size) = window_size {
                    self.config.zupt_window_size = window_size;
                }
                if let Some(accel_var_threshold) = accel_var_threshold {
                    self.config.zupt_accel_var_threshold = accel_var_threshold;
                }
                if let Some(gyro_threshold) = gyro_threshold {
                    self.config.zupt_gyro_threshold = gyro_threshold;
                }

                self.fusion.set_zupt_params(
                    self.config.zupt_window_size,
                    self.config.zupt_accel_var_threshold,
                    self.config.zupt_gyro_threshold,
                );
                self.config.save();
                false
            }
            BackendCommand::StartLegCalibration => {
                self.fusion.start_leg_calibration();
                false
            }
            BackendCommand::StopLegCalibration => {
                let total_leg_length = self.current_leg_length();
                if let Some(new_ratio) = self.fusion.stop_leg_calibration(total_leg_length) {
                    info!("Leg ratio calibrated to {:.3}", new_ratio);
                    self.leg_ratio = new_ratio;
                    self.skeleton.set_leg_ratio(self.leg_ratio);
                }
                true
            }
            BackendCommand::SetFloorOffset(value) => {
                self.floor_offset = value;
                true
            }
            BackendCommand::AutoFloor => {
                if let Some(min_y) = self.current_foot_min_y() {
                    self.floor_offset -= min_y;
                }
                true
            }
            BackendCommand::StartShakeAssign(bone_id) => {
                self.pending_shake_bone = Some(bone_id);
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
        let want_enable = enabled.unwrap_or(self.recorder.is_some());
        if !want_enable {
            self.recorder = None;
            return;
        }

        if self.recorder.is_none() {
            self.recorder = self.build_recorder(filename, batch_size, flush_interval_ms);
            return;
        }

        if filename.is_none() && batch_size.is_none() && flush_interval_ms.is_none() {
            return;
        }

        if let Some(existing) = self.recorder.take() {
            let next_filename = filename.unwrap_or(existing.filename.clone());
            let next_batch_size = batch_size.unwrap_or(existing.batch_size);
            let next_flush_interval_ms = flush_interval_ms.unwrap_or(existing.flush_interval_ms);

            self.recorder = self.build_recorder(
                Some(next_filename),
                Some(next_batch_size),
                Some(next_flush_interval_ms),
            );

            if self.recorder.is_none() {
                self.recorder = Some(existing);
            }
        }
    }

    fn build_recorder(
        &self,
        filename: Option<String>,
        batch_size: Option<usize>,
        flush_interval_ms: Option<u64>,
    ) -> Option<Recorder> {
        if filename.is_none() && batch_size.is_none() && flush_interval_ms.is_none() {
            return match Recorder::new(&self.skeleton) {
                Ok(recorder) => Some(recorder),
                Err(e) => {
                    error!("Recorder init failed: {}", e);
                    None
                }
            };
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
            Ok(recorder) => Some(recorder),
            Err(e) => {
                error!("Recorder reconfigure failed: {}", e);
                None
            }
        }
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
