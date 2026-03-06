#![allow(dead_code)]

use std::mem;

// Frame magic for framed packets
pub const FRAME_MAGIC_LO: u8 = 0xAA;
pub const FRAME_MAGIC_HI: u8 = 0x55;

// Expose raw packet size for external modules (e.g., BLE reassembly)
pub const RAW_PACKET_SIZE: usize = mem::size_of::<RawFullDataPacket>();

/// 定義封包類型常數 (必須與 Arduino 端一致)
pub const PACKET_TYPE_FULL: u8 = 0x02;

/// 這是與 Arduino 端 `__attribute__((packed))` 對應的原始結構。
/// 因為是 packed，直接存取欄位是不安全的 (Unaligned access)，
/// 所以我們將其設為私有 (private)，不讓外部直接使用。
#[repr(C, packed)]
#[derive(Debug, Copy, Clone)]
struct RawFullDataPacket {
    packet_type: u8,
    id: u8,
    sequence: u16,
    quat: [f32; 4],
    accel: [f32; 3],
    batt: u8,
    mag: [f32; 3],
}

/// 這是給 Rust 主程式使用的安全結構。
/// 所有的欄位都已經被複製出來，可以安全地讀取和列印。
#[derive(Debug, Clone)]
pub struct FullDataPacket {
    pub packet_type: u8,
    pub id: u8,
    pub sequence: u16,
    pub quat: [f32; 4],
    pub accel: [f32; 3],
    pub batt: u8,
    pub mag: [f32; 3],
}

impl FullDataPacket {
    /// 從藍牙接收到的位元組陣列解析出資料
    ///
    /// 用法範例:
    /// ```rust,no_run
    /// // let data = ...; // 從藍牙收到的 &[u8]
    /// // if let Some(packet) = FullDataPacket::from_bytes(data) {
    /// //     println!("收到封包: {:?}", packet);
    /// // }
    /// ```
    pub fn from_bytes(data: &[u8]) -> Option<Self> {
        // 支援兩種格式：
        // 1) Legacy: 直接傳 RawFullDataPacket 的 bytes (sizeof = mem::size_of::<RawFullDataPacket>())
        // 2) Framed: [MAGIC_LO (0xAA), MAGIC_HI (0x55), len:u8, payload..., crc16_le: u16]
        let raw_size = mem::size_of::<RawFullDataPacket>();

        let result: Option<Self> = if data.len() == raw_size {
            // Legacy path
            unsafe {
                let ptr = data.as_ptr() as *const RawFullDataPacket;
                let raw = std::ptr::read_unaligned(ptr);
                if raw.packet_type != PACKET_TYPE_FULL {
                    None
                } else if raw.batt > 100 {
                    None
                } else if raw.quat[0] == 0.0
                    && raw.quat[1] == 0.0
                    && raw.quat[2] == 0.0
                    && raw.quat[3] == 0.0
                {
                    None
                } else {
                    Some(FullDataPacket {
                        packet_type: raw.packet_type,
                        id: raw.id,
                        sequence: raw.sequence,
                        quat: raw.quat,
                        accel: raw.accel,
                        batt: raw.batt,
                        mag: raw.mag,
                    })
                }
            }
        } else {
            // Framed path: need at least magic(2)+len(1)+crc(2)
            if data.len() < 5 {
                None
            } else if data[0] != FRAME_MAGIC_LO || data[1] != FRAME_MAGIC_HI {
                None
            } else {
                let plen = data[2] as usize;
                if plen != raw_size {
                    None
                } else {
                    let expected_len = 2 + 1 + plen + 2;
                    if data.len() != expected_len {
                        None
                    } else {
                        let payload_start = 3;
                        let payload_end = payload_start + plen;
                        let payload = &data[payload_start..payload_end];
                        let crc_bytes = &data[payload_end..payload_end + 2];
                        let seen_crc = u16::from_le_bytes([crc_bytes[0], crc_bytes[1]]);

                        if crc16_ccitt_false(payload) != seen_crc {
                            None
                        } else {
                            // parse payload into RawFullDataPacket
                            unsafe {
                                let ptr = payload.as_ptr() as *const RawFullDataPacket;
                                let raw = std::ptr::read_unaligned(ptr);
                                if raw.packet_type != PACKET_TYPE_FULL {
                                    None
                                } else if raw.batt > 100 {
                                    None
                                } else if raw.quat[0] == 0.0
                                    && raw.quat[1] == 0.0
                                    && raw.quat[2] == 0.0
                                    && raw.quat[3] == 0.0
                                {
                                    None
                                } else {
                                    Some(FullDataPacket {
                                        packet_type: raw.packet_type,
                                        id: raw.id,
                                        sequence: raw.sequence,
                                        quat: raw.quat,
                                        accel: raw.accel,
                                        batt: raw.batt,
                                        mag: raw.mag,
                                    })
                                }
                            }
                        }
                    }
                }
            }
        };

        result
    }
}

// CRC16-CCITT (false) implementation (poly 0x1021, init 0xFFFF)
fn crc16_ccitt_false(data: &[u8]) -> u16 {
    let mut crc: u16 = 0xFFFF;
    for &b in data {
        crc ^= (b as u16) << 8;
        for _ in 0..8 {
            if (crc & 0x8000) != 0 {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc <<= 1;
            }
        }
    }
    crc
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::mem;

    #[test]
    fn test_from_bytes_valid() {
        let raw = RawFullDataPacket {
            packet_type: PACKET_TYPE_FULL,
            id: 5,
            sequence: 123u16,
            quat: [0.0f32, 0.0, 0.0, 1.0],
            accel: [0.0f32, 9.81, 0.0],
            batt: 85u8,
            mag: [10.0f32, 11.0, 12.0],
        };

        let bytes: &[u8] = unsafe {
            std::slice::from_raw_parts(
                (&raw as *const RawFullDataPacket) as *const u8,
                mem::size_of::<RawFullDataPacket>(),
            )
        };

        let pkt = FullDataPacket::from_bytes(bytes).expect("should parse");
        assert_eq!(pkt.packet_type, PACKET_TYPE_FULL);
        assert_eq!(pkt.id, 5);
        assert_eq!(pkt.sequence, 123u16);
        assert_eq!(pkt.batt, 85u8);
    }

    #[test]
    fn test_framed_packet_valid_crc() {
        let raw = RawFullDataPacket {
            packet_type: PACKET_TYPE_FULL,
            id: 7,
            sequence: 321u16,
            quat: [0.0f32, 0.0, 0.0, 1.0],
            accel: [0.1f32, 9.7, 0.0],
            batt: 90u8,
            mag: [1.0f32, 2.0, 3.0],
        };

        let payload: &[u8] = unsafe {
            std::slice::from_raw_parts(
                (&raw as *const RawFullDataPacket) as *const u8,
                mem::size_of::<RawFullDataPacket>(),
            )
        };

        let mut frame = Vec::new();
        frame.push(FRAME_MAGIC_LO);
        frame.push(FRAME_MAGIC_HI);
        frame.push(payload.len() as u8);
        frame.extend_from_slice(payload);
        let crc = crc16_ccitt_false(payload);
        frame.extend_from_slice(&crc.to_le_bytes());

        let pkt = FullDataPacket::from_bytes(&frame).expect("should parse framed packet");
        assert_eq!(pkt.id, 7);
        assert_eq!(pkt.batt, 90u8);
    }

    #[test]
    fn test_framed_packet_bad_crc() {
        let raw = RawFullDataPacket {
            packet_type: PACKET_TYPE_FULL,
            id: 8,
            sequence: 1u16,
            quat: [0.0f32, 0.0, 0.0, 1.0],
            accel: [0.0f32, 9.8, 0.0],
            batt: 50u8,
            mag: [0.0f32, 0.0, 0.0],
        };

        let payload: &[u8] = unsafe {
            std::slice::from_raw_parts(
                (&raw as *const RawFullDataPacket) as *const u8,
                mem::size_of::<RawFullDataPacket>(),
            )
        };

        let mut frame = Vec::new();
        frame.push(FRAME_MAGIC_LO);
        frame.push(FRAME_MAGIC_HI);
        frame.push(payload.len() as u8);
        frame.extend_from_slice(payload);
        // append wrong crc
        frame.extend_from_slice(&0u16.to_le_bytes());

        assert!(FullDataPacket::from_bytes(&frame).is_none());
    }

    #[test]
    fn test_from_bytes_invalid_len() {
        let v = vec![0u8; mem::size_of::<RawFullDataPacket>() - 1];
        assert!(FullDataPacket::from_bytes(&v).is_none());
    }

    #[test]
    fn test_from_bytes_invalid_packet_type() {
        let raw = RawFullDataPacket {
            packet_type: 0xFF,
            id: 1,
            sequence: 0,
            quat: [0.0, 0.0, 0.0, 1.0],
            accel: [0.0, 0.0, 0.0],
            batt: 50,
            mag: [0.0, 0.0, 0.0],
        };

        let bytes: &[u8] = unsafe {
            std::slice::from_raw_parts(
                (&raw as *const RawFullDataPacket) as *const u8,
                mem::size_of::<RawFullDataPacket>(),
            )
        };

        assert!(FullDataPacket::from_bytes(bytes).is_none());
    }

    #[test]
    fn test_fragmented_framed_reassembly() {
        use std::mem;

        // 建立一個有效的 RawFullDataPacket
        let raw = RawFullDataPacket {
            packet_type: PACKET_TYPE_FULL,
            id: 42,
            sequence: 999u16,
            quat: [0.0f32, 0.0, 0.0, 1.0],
            accel: [0.0f32, 9.81, 0.0],
            batt: 77u8,
            mag: [0.1f32, 0.2, 0.3],
        };

        let payload: &[u8] = unsafe {
            std::slice::from_raw_parts(
                (&raw as *const RawFullDataPacket) as *const u8,
                mem::size_of::<RawFullDataPacket>(),
            )
        };

        // 建立 framed 封包
        let mut frame = Vec::new();
        frame.push(FRAME_MAGIC_LO);
        frame.push(FRAME_MAGIC_HI);
        frame.push(payload.len() as u8);
        frame.extend_from_slice(payload);
        let crc = crc16_ccitt_false(payload);
        frame.extend_from_slice(&crc.to_le_bytes());

        // 分割成兩段模擬 MTU 斷片
        let split = 10usize.min(frame.len());
        let chunk1 = &frame[..split];
        let chunk2 = &frame[split..];

        let mut buf: Vec<u8> = Vec::new();
        let mut parsed: Vec<FullDataPacket> = Vec::new();

        // 先接收第一段，應該還無法完成解析
        buf.extend_from_slice(chunk1);
        // 嘗試以主程式的重組邏輯解析
        loop {
            if buf.len() >= 5 && buf[0] == FRAME_MAGIC_LO && buf[1] == FRAME_MAGIC_HI {
                let plen = buf[2] as usize;
                let expected = 2 + 1 + plen + 2;
                if buf.len() >= expected {
                    if let Some(pkt) = FullDataPacket::from_bytes(&buf[..expected]) {
                        parsed.push(pkt);
                    }
                    buf.drain(..expected);
                    continue;
                }
            }
            break;
        }
        assert!(parsed.is_empty());

        // 接收第二段，這時應該能完成解析
        buf.extend_from_slice(chunk2);
        loop {
            if buf.len() >= 5 && buf[0] == FRAME_MAGIC_LO && buf[1] == FRAME_MAGIC_HI {
                let plen = buf[2] as usize;
                let expected = 2 + 1 + plen + 2;
                if buf.len() >= expected {
                    if let Some(pkt) = FullDataPacket::from_bytes(&buf[..expected]) {
                        parsed.push(pkt);
                    }
                    buf.drain(..expected);
                    continue;
                }
            }
            break;
        }

        assert_eq!(parsed.len(), 1);
        assert_eq!(parsed[0].id, 42);
        assert_eq!(parsed[0].batt, 77u8);
    }
}
