use crate::skeleton::model::SkeletonModel;
use log::error;
use rosc::{encoder, OscMessage, OscPacket, OscType};
use std::net::SocketAddr;
use tokio::net::UdpSocket;

pub struct OscSender {
    socket: UdpSocket,
    target_addr: SocketAddr,
}

impl OscSender {
    pub async fn new(ip: &str, port: u16) -> Result<Self, Box<dyn std::error::Error>> {
        let socket = UdpSocket::bind("0.0.0.0:0").await?;
        let addr_str = format!("{}:{}", ip, port);
        let target_addr = addr_str.parse()?;
        Ok(Self {
            socket,
            target_addr,
        })
    }

    pub async fn send_skeleton(&self, skeleton: &SkeletonModel) {
        // VRChat OSC Trackers 映射
        // 1: Hip, 2: L.Foot, 3: R.Foot, 4: L.Elbow, 5: R.Elbow, 6: L.Knee, 7: R.Knee, 8: Chest
        let assignments = [
            (0, 1),  // Hip
            (12, 2), // L.Foot
            (22, 3), // R.Foot
            (32, 4), // L.Elbow (ForeArm) - 近似
            (42, 5), // R.Elbow (ForeArm) - 近似
            (11, 6), // L.Knee (Leg)
            (21, 7), // R.Knee (Leg)
            (2, 8),  // Chest
        ];

        for (bone_id, tracker_idx) in assignments {
            if let Some(bone) = skeleton.bones.get(&bone_id) {
                let pos = bone.global_position;
                let rot = bone.global_rotation;

                // 轉換座標系 (假設 VRChat 需要)
                // 這裡做一個簡單的映射，實際可能需要根據 Unity 座標系調整 (X反轉等)
                let vrc_pos = vec![
                    OscType::Float(pos.x),
                    OscType::Float(pos.y),
                    OscType::Float(pos.z),
                ];

                let (r, p, y) = rot.euler_angles();
                let vrc_rot = vec![
                    OscType::Float(r.to_degrees()),
                    OscType::Float(y.to_degrees()),
                    OscType::Float(p.to_degrees()),
                ];

                self.send_message(
                    format!("/tracking/trackers/{}/position", tracker_idx),
                    vrc_pos,
                )
                .await;
                self.send_message(
                    format!("/tracking/trackers/{}/rotation", tracker_idx),
                    vrc_rot,
                )
                .await;
            }
        }

        // Head (通常 VRChat 使用 HMD，但若需要覆蓋可傳送)
        if let Some(head) = skeleton.bones.get(&4) {
            let pos = head.global_position;
            let rot = head.global_rotation;
            let (r, p, y) = rot.euler_angles();

            self.send_message(
                "/tracking/trackers/head/position".to_string(),
                vec![
                    OscType::Float(pos.x),
                    OscType::Float(pos.y),
                    OscType::Float(pos.z),
                ],
            )
            .await;
            self.send_message(
                "/tracking/trackers/head/rotation".to_string(),
                vec![
                    OscType::Float(r.to_degrees()),
                    OscType::Float(y.to_degrees()),
                    OscType::Float(p.to_degrees()),
                ],
            )
            .await;
        }
    }

    async fn send_message(&self, addr: String, args: Vec<OscType>) {
        let packet = OscPacket::Message(OscMessage { addr, args });
        if let Ok(buf) = encoder::encode(&packet) {
            if let Err(e) = self.socket.send_to(&buf, self.target_addr).await {
                error!("OSC Send Error: {}", e);
            }
        }
    }
}
