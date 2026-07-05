use super::*;


impl BackendRuntime {
    pub(super) fn ingest_udp_packets(&mut self) -> bool {
        let mut received_any = false;
        let mut loop_count = 0;

        while let Ok((len, _addr)) = self.socket.try_recv_from(&mut self.udp_buf) {
            if loop_count >= UDP_PACKET_BUDGET_PER_TICK { break; }
            loop_count += 1;

            if let Some(packet) = net::protocol::ImuDataPacket::from_bytes(&self.udp_buf[..len]) {
                let data = PacketData {
                    id:       packet.id,
                    sequence: Some(packet.sequence),
                    batt:     Some(packet.batt as f32),
                    gyro:     Some(packet.gyro),
                    accel:    Some(packet.accel),
                    mag:      Some(packet.mag),
                    dt:       Some(packet.dt),
                    quat:     packet.quat,
                };
                self.process_packet(data, ConnectionType::Udp);
                received_any = true;
            }
        }
        received_any
    }

    pub(super) fn ingest_serial_packets(&mut self) -> bool {
        let mut received_any = false;
        while let Ok((data, source)) = self.serial_rx.try_recv() {
            self.process_packet(data, source);
            received_any = true;
        }
        received_any
    }

    fn process_packet(&mut self, data: PacketData, source: ConnectionType) {
        self.packet_count += 1;

        let is_new_tracker = !self.trackers.contains_key(&data.id);
        let assigned_bone = self.fusion.assigner.get_bone_id(data.id);

        // ── Update TrackerState ───────────────────────────────────────────────
        {
            let tracker_state = self.trackers.entry(data.id).or_insert_with(|| TrackerState {
                id: data.id,
                connection_type: source,
                battery: data.batt.unwrap_or(100.0),
                rssi: -50,
                accel: data.accel,
                last_update: std::time::Instant::now(),
                assigned_bone,
                tps: 0,
                rotation: None,
                stationary: false,
                last_sequence: data.sequence.unwrap_or(0),
                received_packets: 0,
                lost_packets: 0,
                mag: data.mag,
                is_mag_calibrating: false,
            });

            // ── Sequence-based loss tracking ──────────────────────────────────
            let mut missed: u32 = 0;
            if let Some(new_sequence) = data.sequence {
                if tracker_state.received_packets > 0 {
                    let diff = if new_sequence > tracker_state.last_sequence {
                        new_sequence - tracker_state.last_sequence
                    } else if new_sequence < tracker_state.last_sequence
                        && (tracker_state.last_sequence - new_sequence) > (u16::MAX / 2)
                    {
                        (u16::MAX - tracker_state.last_sequence) + new_sequence + 1
                    } else {
                        1
                    };
                    if diff > 1 {
                        missed = (diff - 1) as u32;
                        tracker_state.lost_packets += missed as u64;
                    }
                }
                tracker_state.last_sequence = new_sequence;
            }

            // ── Consecutive-loss hysteresis counters ──────────────────────────
            let consec_lost = self.tracker_consec_lost.entry(data.id).or_insert(0);
            let consec_good = self.tracker_consec_good.entry(data.id).or_insert(0);
            if missed > 0 {
                *consec_lost += missed;
                *consec_good = 0;
            } else {
                *consec_good += 1;
                *consec_lost = 0;
            }
            tracker_state.received_packets += 1;
            *self.tracker_packet_counts.entry(data.id).or_insert(0) += 1;
            tracker_state.connection_type = source;
            tracker_state.last_update = std::time::Instant::now();
            tracker_state.assigned_bone = assigned_bone;

            if let Some(battery) = data.batt { tracker_state.battery = battery; }
            if let Some(accel)   = data.accel { tracker_state.accel = Some(accel); }
            if let Some(mag)     = data.mag   { tracker_state.mag = Some(mag); }
        }

        // ── Quaternion: device Mahony only (computed on MCU at 119 Hz) ─────────
        // No host-side EKF. Gyro bias is handled by Ki on the firmware side.
        let selected_quat = data.quat;

        // Feed device quat into fusion so IK/skeleton can use it.
        if let Some(q) = selected_quat {
            self.fusion.inject_quaternion(data.id, q);
        }

        // ── Stationarity ─────────────────────────────────────────────────────
        let stationary = data.accel
            .map(|accel| {
                let rot = selected_quat.map(|q| [q[0], q[1], q[2], q[3]]);
                self.fusion.is_tracker_stationary(data.id, accel, rot)
            })
            .unwrap_or(false);

        let is_mag_calibrating = self.fusion.mag_calibration_active
            .get(&data.id).copied().unwrap_or(false);

        // ── Shake-assign ──────────────────────────────────────────────────────
        if let Some(target_bone) = self.pending_shake_bone {
            if let Some(accel) = data.accel {
                let magnitude = (accel[0].powi(2) + accel[1].powi(2) + accel[2].powi(2)).sqrt();
                if magnitude > 25.0 {
                    self.fusion.assigner.set_assignment(data.id, target_bone);
                    self.config.tracker_assignments.insert(data.id, target_bone);
                    self.pending_shake_bone = None;
                    info!("Shake assign: tracker #{} -> bone {}", data.id, target_bone);
                }
            }
        }

        // ── Update TrackerState with final rotation ───────────────────────────
        if let Some(tracker_state) = self.trackers.get_mut(&data.id) {
            tracker_state.stationary      = stationary;
            tracker_state.is_mag_calibrating = is_mag_calibrating;
            tracker_state.assigned_bone   = self.fusion.assigner.get_bone_id(data.id);
            if let Some(q) = selected_quat {
                tracker_state.rotation = Some(q);
            }
        }

        // ── Update net_trackers ───────────────────────────────────────────────
        self.net_trackers
            .entry(data.id)
            .and_modify(|tracker| {
                tracker.update_data(&data);
                tracker.stationary = stationary;
            })
            .or_insert_with(|| {
                let mut tracker = crate::net::tracker::Tracker::new(data.id);
                tracker.update_data(&data);
                tracker.stationary = stationary;
                tracker
            });

        // ── Auto-assign on first packet from a new tracker ───────────────────
        if is_new_tracker {
            self.fusion.auto_assign(&self.net_trackers);
            info!("New tracker #{} connected — auto-assigned", data.id);
        }
    }
}
