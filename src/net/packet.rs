use serde::Deserialize;

/// Unified packet received from a tracker (BLE, USB serial, or UDP).
/// All fields are optional to allow partial updates.
#[derive(Deserialize, Clone, Debug)]
pub struct PacketData {
    pub id: u8,
    #[serde(default)]
    pub sequence: Option<u16>,
    #[serde(default)]
    pub batt: Option<f32>,
    /// Raw gyroscope reading, rad/s [x, y, z]
    #[serde(default)]
    pub gyro: Option<[f32; 3]>,
    /// Accelerometer, m/s² [x, y, z]
    #[serde(default)]
    pub accel: Option<[f32; 3]>,
    /// Magnetometer, uT [x, y, z] — None or [0,0,0] means 6-axis mode
    #[serde(default)]
    pub mag: Option<[f32; 3]>,
    /// Delta time in seconds since previous sample
    #[serde(default)]
    pub dt: Option<f32>,
    /// Onboard Mahony quaternion [x, y, z, w] — present only in v2 (0x04) packets
    #[serde(default)]
    pub quat: Option<[f32; 4]>,
}
