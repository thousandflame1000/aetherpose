use std::mem;

// Frame magic for framed packets
pub const FRAME_MAGIC_LO: u8 = 0xAA;
pub const FRAME_MAGIC_HI: u8 = 0x55;

/// Packet type 0x03 – raw IMU only (45 bytes, legacy v1)
pub const PACKET_TYPE_RAW_IMU: u8 = 0x03;
/// Packet type 0x04 – raw IMU + onboard Mahony quaternion (61 bytes, v2)
pub const PACKET_TYPE_IMU_V2: u8 = 0x04;

/// Raw packed struct matching firmware v1 `RawImuPacket` (45 bytes).
#[repr(C, packed)]
#[derive(Debug, Copy, Clone)]
struct RawImuPacketV1 {
    packet_type: u8,
    id: u8,
    sequence: u16,
    gyro: [f32; 3],
    accel: [f32; 3],
    batt: u8,
    mag: [f32; 3],
    dt: f32,
}

/// Raw packed struct matching firmware v2 `RawImuPacketV2` (61 bytes).
/// Adds onboard Mahony quaternion [x, y, z, w].
#[repr(C, packed)]
#[derive(Debug, Copy, Clone)]
struct RawImuPacketV2 {
    packet_type: u8,
    id: u8,
    sequence: u16,
    gyro: [f32; 3],
    accel: [f32; 3],
    batt: u8,
    mag: [f32; 3],
    dt: f32,
    quat: [f32; 4],  // [x, y, z, w] from onboard Mahony
}

pub const RAW_PACKET_SIZE: usize = mem::size_of::<RawImuPacketV1>();

/// Safe, aligned packet used throughout Rust code.
/// `quat` is `Some` only when received from a v2 (0x04) firmware packet.
#[derive(Debug, Clone)]
pub struct ImuDataPacket {
    pub packet_type: u8,
    pub id: u8,
    pub sequence: u16,
    /// rad/s
    pub gyro: [f32; 3],
    /// m/s²
    pub accel: [f32; 3],
    pub batt: u8,
    /// uT (zeros = 6-axis mode)
    pub mag: [f32; 3],
    /// seconds
    pub dt: f32,
    /// [x, y, z, w] onboard Mahony estimate (None for v1 packets)
    pub quat: Option<[f32; 4]>,
}

impl ImuDataPacket {
    pub fn from_bytes(data: &[u8]) -> Option<Self> {
        let v1_size = mem::size_of::<RawImuPacketV1>();
        let v2_size = mem::size_of::<RawImuPacketV2>();

        // ── direct (unframed) path ────────────────────────────────────────────
        if data.len() == v2_size {
            return Self::try_parse_v2_raw(data);
        }
        if data.len() == v1_size {
            return Self::try_parse_v1_raw(data);
        }

        // ── framed: [0xAA, 0x55, len, payload..., crc16_le] ─────────────────
        if data.len() < 5 || data[0] != FRAME_MAGIC_LO || data[1] != FRAME_MAGIC_HI {
            return None;
        }
        let plen = data[2] as usize;
        let expected = 2 + 1 + plen + 2;
        if data.len() != expected {
            return None;
        }
        let payload = &data[3..3 + plen];
        let crc_bytes = &data[3 + plen..3 + plen + 2];
        let seen_crc = u16::from_le_bytes([crc_bytes[0], crc_bytes[1]]);
        if crc16_ccitt_false(payload) != seen_crc {
            return None;
        }

        if plen == v2_size {
            Self::try_parse_v2_raw(payload)
        } else if plen == v1_size {
            Self::try_parse_v1_raw(payload)
        } else {
            None
        }
    }

    fn try_parse_v1_raw(payload: &[u8]) -> Option<Self> {
        unsafe {
            let ptr = payload.as_ptr() as *const RawImuPacketV1;
            let raw = std::ptr::read_unaligned(ptr);
            if !raw_v1_is_valid(&raw) {
                return None;
            }
            Some(Self {
                packet_type: raw.packet_type,
                id: raw.id,
                sequence: raw.sequence,
                gyro: raw.gyro,
                accel: raw.accel,
                batt: raw.batt,
                mag: raw.mag,
                dt: raw.dt,
                quat: None,
            })
        }
    }

    fn try_parse_v2_raw(payload: &[u8]) -> Option<Self> {
        unsafe {
            let ptr = payload.as_ptr() as *const RawImuPacketV2;
            let raw = std::ptr::read_unaligned(ptr);
            if !raw_v2_is_valid(&raw) {
                return None;
            }
            Some(Self {
                packet_type: raw.packet_type,
                id: raw.id,
                sequence: raw.sequence,
                gyro: raw.gyro,
                accel: raw.accel,
                batt: raw.batt,
                mag: raw.mag,
                dt: raw.dt,
                quat: Some(raw.quat),
            })
        }
    }
}

/// A sensor glitch, a firmware bug or a stray sender on the network can deliver NaN or
/// infinite values; once inside the filters and the IK they would never wash out.
fn all_finite(values: &[f32]) -> bool {
    values.iter().all(|value| value.is_finite())
}

fn raw_v1_is_valid(raw: &RawImuPacketV1) -> bool {
    // Copies: a packed struct's fields cannot be borrowed.
    let (gyro, accel, mag) = (raw.gyro, raw.accel, raw.mag);
    raw.packet_type == PACKET_TYPE_RAW_IMU
        && raw.batt <= 100
        && raw.dt > 0.0
        && raw.dt <= 1.0
        && all_finite(&gyro)
        && all_finite(&accel)
        && all_finite(&mag)
}

fn raw_v2_is_valid(raw: &RawImuPacketV2) -> bool {
    let (gyro, accel, mag, quat) = (raw.gyro, raw.accel, raw.mag, raw.quat);
    let norm = quat.iter().map(|value| value * value).sum::<f32>().sqrt();
    raw.packet_type == PACKET_TYPE_IMU_V2
        && raw.batt <= 100
        && raw.dt > 0.0
        && raw.dt <= 1.0
        && all_finite(&gyro)
        && all_finite(&accel)
        && all_finite(&mag)
        && all_finite(&quat)
        && (0.5..=1.5).contains(&norm)  // a unit quaternion; zero cannot be normalised
}

fn crc16_ccitt_false(data: &[u8]) -> u16 {
    let mut crc: u16 = 0xFFFF;
    for &b in data {
        crc ^= (b as u16) << 8;
        for _ in 0..8 {
            crc = if (crc & 0x8000) != 0 {
                (crc << 1) ^ 0x1021
            } else {
                crc << 1
            };
        }
    }
    crc
}

// ── Sync packet: host → device (16 bytes, [x,y,z,w] floats) ────────────────
/// Encode an EKF quaternion [x,y,z,w] as 16 raw bytes for BLE write.
pub fn encode_sync_quat(q: [f32; 4]) -> [u8; 16] {
    let mut buf = [0u8; 16];
    buf[0..4].copy_from_slice(&q[0].to_le_bytes());
    buf[4..8].copy_from_slice(&q[1].to_le_bytes());
    buf[8..12].copy_from_slice(&q[2].to_le_bytes());
    buf[12..16].copy_from_slice(&q[3].to_le_bytes());
    buf
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_v1(id: u8, seq: u16, batt: u8) -> RawImuPacketV1 {
        RawImuPacketV1 {
            packet_type: PACKET_TYPE_RAW_IMU,
            id, sequence: seq,
            gyro: [0.01, -0.02, 0.03],
            accel: [0.0, 0.0, 9.81],
            batt,
            mag: [20.0, 5.0, -40.0],
            dt: 1.0 / 119.0,
        }
    }

    fn make_v2(id: u8, seq: u16, batt: u8) -> RawImuPacketV2 {
        RawImuPacketV2 {
            packet_type: PACKET_TYPE_IMU_V2,
            id, sequence: seq,
            gyro: [0.01, -0.02, 0.03],
            accel: [0.0, 0.0, 9.81],
            batt,
            mag: [20.0, 5.0, -40.0],
            dt: 1.0 / 119.0,
            quat: [0.0, 0.0, 0.0, 1.0],
        }
    }

    #[test]
    fn sizes() {
        assert_eq!(mem::size_of::<RawImuPacketV1>(), 45);
        assert_eq!(mem::size_of::<RawImuPacketV2>(), 61);
    }

    #[test]
    fn parse_v1_direct() {
        let raw = make_v1(1, 42, 80);
        let bytes = unsafe {
            std::slice::from_raw_parts(
                (&raw as *const RawImuPacketV1) as *const u8,
                mem::size_of::<RawImuPacketV1>(),
            )
        };
        let pkt = ImuDataPacket::from_bytes(bytes).unwrap();
        assert_eq!(pkt.id, 1);
        assert!(pkt.quat.is_none());
    }

    #[test]
    fn parse_v2_direct() {
        let raw = make_v2(2, 10, 90);
        let bytes = unsafe {
            std::slice::from_raw_parts(
                (&raw as *const RawImuPacketV2) as *const u8,
                mem::size_of::<RawImuPacketV2>(),
            )
        };
        let pkt = ImuDataPacket::from_bytes(bytes).unwrap();
        assert_eq!(pkt.id, 2);
        assert!(pkt.quat.is_some());
    }

    fn v1_bytes(raw: &RawImuPacketV1) -> Vec<u8> {
        unsafe { std::slice::from_raw_parts((raw as *const RawImuPacketV1) as *const u8, mem::size_of::<RawImuPacketV1>()) }.to_vec()
    }

    fn v2_bytes(raw: &RawImuPacketV2) -> Vec<u8> {
        unsafe { std::slice::from_raw_parts((raw as *const RawImuPacketV2) as *const u8, mem::size_of::<RawImuPacketV2>()) }.to_vec()
    }

    #[test]
    fn non_finite_or_degenerate_values_are_dropped() {
        let broken_v2: [fn(&mut RawImuPacketV2); 5] = [
            |raw| raw.accel = [f32::NAN, 0.0, 9.81],
            |raw| raw.gyro = [f32::INFINITY, 0.0, 0.0],
            |raw| raw.mag = [0.0, f32::NEG_INFINITY, 0.0],
            |raw| raw.quat = [0.0, 0.0, 0.0, f32::NAN],
            |raw| raw.quat = [0.0; 4],
        ];
        for (case, break_packet) in broken_v2.iter().enumerate() {
            let mut raw = make_v2(3, 1, 90);
            break_packet(&mut raw);
            assert!(ImuDataPacket::from_bytes(&v2_bytes(&raw)).is_none(), "v2 case {case}");
        }
        let mut raw = make_v1(3, 1, 90);
        raw.mag = [f32::NAN, 0.0, 0.0];
        assert!(ImuDataPacket::from_bytes(&v1_bytes(&raw)).is_none());
        assert!(ImuDataPacket::from_bytes(&v2_bytes(&make_v2(3, 1, 90))).is_some());
    }

    #[test]
    fn parse_v2_framed() {
        let raw = make_v2(7, 321, 90);
        let payload = unsafe {
            std::slice::from_raw_parts(
                (&raw as *const RawImuPacketV2) as *const u8,
                mem::size_of::<RawImuPacketV2>(),
            )
        };
        let mut frame = Vec::new();
        frame.push(FRAME_MAGIC_LO);
        frame.push(FRAME_MAGIC_HI);
        frame.push(payload.len() as u8);
        frame.extend_from_slice(payload);
        let crc = crc16_ccitt_false(payload);
        frame.extend_from_slice(&crc.to_le_bytes());
        let pkt = ImuDataPacket::from_bytes(&frame).unwrap();
        assert_eq!(pkt.id, 7);
        assert!(pkt.quat.is_some());
    }
}
