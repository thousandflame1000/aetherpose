use crate::net::packet::PacketData;

use std::time::{Duration, Instant};

/// Represents the state and basic metrics of a tracker device.
#[allow(dead_code)]
#[derive(Debug, Clone)]
pub struct Tracker {
    pub id: u8,
    pub last_seen: Instant,
    /// Raw gyroscope reading, rad/s [x, y, z]
    pub gyro: Option<[f32; 3]>,
    /// Accelerometer reading, m/s² [x, y, z]
    pub accel: Option<[f32; 3]>,
    /// Magnetometer reading, uT [x, y, z] (None or all-zeros = 6-axis)
    pub mag: Option<[f32; 3]>,
    /// Time delta in seconds since the previous sample
    pub dt: Option<f32>,
    pub stationary: bool,

    // Metrics
    pub received_packets: u64,
    pub lost_packets: u64,
    pub last_sequence: Option<u16>,
    pub rssi: Option<i32>,
}

impl Tracker {
    pub fn new(id: u8) -> Self {
        Self {
            id,
            last_seen: Instant::now(),
            gyro: None,
            accel: None,
            mag: None,
            dt: None,
            stationary: false,
            received_packets: 0,
            lost_packets: 0,
            last_sequence: None,
            rssi: None,
        }
    }

    pub fn update_data(&mut self, packet_data: &PacketData) {
        self.last_seen = Instant::now();
        self.received_packets = self.received_packets.saturating_add(1);

        if let Some(seq) = packet_data.sequence {
            if let Some(last) = self.last_sequence {
                let expected = last.wrapping_add(1);
                if seq != expected {
                    let missed = seq.wrapping_sub(expected) as u64;
                    self.lost_packets = self.lost_packets.saturating_add(missed);
                }
            }
            self.last_sequence = Some(seq);
        }

        if let Some(g) = packet_data.gyro {
            self.gyro = Some(g);
        }
        if let Some(a) = packet_data.accel {
            self.accel = Some(a);
        }
        if let Some(m) = packet_data.mag {
            self.mag = Some(m);
        }
        if let Some(dt) = packet_data.dt {
            self.dt = Some(dt);
        }
    }

    /// Returns whether the tracker is considered online given a timeout.
    pub fn is_online(&self, offline_after: Duration) -> bool {
        Instant::now().duration_since(self.last_seen) <= offline_after
    }
}
