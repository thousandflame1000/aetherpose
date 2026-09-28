use crate::net::packet::PacketData;
use std::time::Instant;

/// Tracker data needed by fusion and assignment.
#[derive(Debug, Clone)]
pub struct Tracker {
    pub id: u8,
    pub last_seen: Instant,
    pub accel: Option<[f32; 3]>,
    pub mag: Option<[f32; 3]>,
    pub stationary: bool,
    pub received_packets: u64,
}

impl Tracker {
    pub fn new(id: u8) -> Self {
        Self {
            id,
            last_seen: Instant::now(),
            accel: None,
            mag: None,
            stationary: false,
            received_packets: 0,
        }
    }

    pub fn update_data(&mut self, packet_data: &PacketData) {
        self.last_seen = Instant::now();
        self.received_packets = self.received_packets.saturating_add(1);

        if let Some(accel) = packet_data.accel {
            self.accel = Some(accel);
        }
        if let Some(mag) = packet_data.mag {
            self.mag = Some(mag);
        }
    }
}
