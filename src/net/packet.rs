use serde::Deserialize;

// 定義接收到的 JSON 封包格式, 以及從二進位轉換後的通用結構
#[derive(Deserialize, Clone, Debug)]
pub struct PacketData {
    pub id: u8,
    #[serde(default)]
    pub sequence: Option<u16>,
    #[serde(default)]
    pub batt: Option<f32>,
    #[serde(default)]
    pub quat: Option<[f32; 4]>, // [x, y, z, w]
    #[serde(default)]
    pub accel: Option<[f32; 3]>,
    #[serde(default)]
    pub mag: Option<[f32; 3]>, // [x, y, z]
}
