use serde::{Serialize, Deserialize};

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum ConnectionType {
    Serial,
    Ble,
    Udp,
    Unknown,
}

impl Default for ConnectionType {
    fn default() -> Self {
        Self::Unknown
    }
}
