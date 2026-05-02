#![allow(dead_code)]

use crate::skeleton::SkeletonModel;
use nalgebra::{UnitQuaternion, Vector3};
use rosc::{encoder, OscMessage, OscPacket, OscType};
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Mutex;
use tokio::net::UdpSocket;

pub struct OscSender {
    socket: UdpSocket,
    target_addr: SocketAddr,
    last_rotation_degrees: Mutex<HashMap<String, [f32; 3]>>,
}

impl OscSender {
    pub async fn new(target_ip: &str, target_port: u16) -> std::io::Result<Self> {
        let socket = UdpSocket::bind("0.0.0.0:0").await?;
        let target_addr = format!("{}:{}", target_ip, target_port)
            .parse()
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidInput, e))?;

        log::info!("OSC Sender initialized, targeting {}", target_addr);
        Ok(Self {
            socket,
            target_addr,
            last_rotation_degrees: Mutex::new(HashMap::new()),
        })
    }

    pub async fn send_skeleton(&self, skeleton: &SkeletonModel) {
        let mappings = [
            (0, "hips"),
            (4, "head"),
            (2, "chest"),
            (12, "left_foot"),
            (22, "right_foot"),
            (11, "left_knee"),
            (21, "right_knee"),
            (32, "left_elbow"),
            (42, "right_elbow"),
        ];

        for (bone_id, name) in mappings {
            if let Some(bone) = skeleton.bones.get(&bone_id) {
                self.send_tracker(name, bone.global_position, bone.global_rotation)
                    .await;
            }
        }
    }

    async fn send_tracker(&self, name: &str, pos: Vector3<f32>, rot: UnitQuaternion<f32>) {
        let addr_pos = format!("/tracking/trackers/{}/position", name);
        let args_pos = vec![
            OscType::Float(pos.x),
            OscType::Float(pos.y),
            OscType::Float(-pos.z),
        ];
        self.send_packet(&addr_pos, args_pos).await;

        let [pitch_deg, yaw_deg, roll_deg] = self.continuous_rotation_degrees(name, rot);
        let addr_rot = format!("/tracking/trackers/{}/rotation", name);
        let args_rot = vec![
            OscType::Float(pitch_deg),
            OscType::Float(yaw_deg),
            OscType::Float(roll_deg),
        ];
        self.send_packet(&addr_rot, args_rot).await;
    }

    fn continuous_rotation_degrees(&self, name: &str, rot: UnitQuaternion<f32>) -> [f32; 3] {
        let (roll, pitch, yaw) = rot.euler_angles();
        let current = [
            pitch.to_degrees(),
            -yaw.to_degrees(),
            -roll.to_degrees(),
        ];

        let mut rotations = self
            .last_rotation_degrees
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let previous = rotations.get(name).copied();
        let unwrapped = previous.map_or(current, |prev| {
            [
                unwrap_degrees(prev[0], current[0]),
                unwrap_degrees(prev[1], current[1]),
                unwrap_degrees(prev[2], current[2]),
            ]
        });

        rotations.insert(name.to_string(), unwrapped);
        unwrapped
    }

    async fn send_packet(&self, addr: &str, args: Vec<OscType>) {
        let packet = OscPacket::Message(OscMessage {
            addr: addr.to_string(),
            args,
        });
        if let Ok(buf) = encoder::encode(&packet) {
            let _ = self.socket.send_to(&buf, self.target_addr).await;
        }
    }
}

fn unwrap_degrees(previous: f32, current: f32) -> f32 {
    let mut unwrapped = current;
    let delta = current - previous;
    if delta > 180.0 {
        unwrapped -= 360.0;
    } else if delta < -180.0 {
        unwrapped += 360.0;
    }
    unwrapped
}

#[cfg(test)]
mod tests {
    use super::unwrap_degrees;

    #[test]
    fn unwraps_positive_wrap_boundary() {
        let previous = 179.0;
        let current = -179.0;
        assert!((unwrap_degrees(previous, current) - 181.0).abs() < 1e-4);
    }

    #[test]
    fn unwraps_negative_wrap_boundary() {
        let previous = -179.0;
        let current = 179.0;
        assert!((unwrap_degrees(previous, current) + 181.0).abs() < 1e-4);
    }
}
