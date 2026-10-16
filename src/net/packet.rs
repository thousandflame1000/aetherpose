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

impl PacketData {
    /// False for NaN or infinite values and for a quaternion that is not roughly unit length.
    /// Such values come from sensor glitches, firmware bugs or stray senders, and once in the
    /// filters and the IK they never wash out, so the packet is dropped.
    pub fn is_usable(&self) -> bool {
        let finite = |values: &[f32]| values.iter().all(|value| value.is_finite());
        let quat_ok = self.quat.is_none_or(|q| {
            let norm = q.iter().map(|value| value * value).sum::<f32>().sqrt();
            finite(&q) && (0.5..=1.5).contains(&norm)
        });
        self.batt.is_none_or(f32::is_finite)
            && self.dt.is_none_or(f32::is_finite)
            && self.gyro.is_none_or(|v| finite(&v))
            && self.accel.is_none_or(|v| finite(&v))
            && self.mag.is_none_or(|v| finite(&v))
            && quat_ok
    }
}
