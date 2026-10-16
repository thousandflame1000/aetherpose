use serde::{Serialize, Deserialize};

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Default)]
#[serde(rename_all = "lowercase")]
pub enum ConnectionType {
    Serial,
    Ble,
    Udp,
    #[default]
    Unknown,
}
