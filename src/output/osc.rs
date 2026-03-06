#![allow(dead_code)]

use rosc::{OscMessage, OscPacket, OscType, encoder};
use tokio::net::UdpSocket;
use std::net::SocketAddr;
use crate::skeleton::SkeletonModel;
use nalgebra::{Vector3, UnitQuaternion};

pub struct OscSender {
    socket: UdpSocket,
    target_addr: SocketAddr,
}

impl OscSender {
    pub async fn new(target_ip: &str, target_port: u16) -> std::io::Result<Self> {
        // 綁定到任意本地埠口 (0.0.0.0:0)
        let socket = UdpSocket::bind("0.0.0.0:0").await?;
        let target_addr = format!("{}:{}", target_ip, target_port).parse()
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidInput, e))?;
        
        log::info!("OSC Sender initialized, targeting {}", target_addr);
        Ok(Self {
            socket,
            target_addr,
        })
    }

    pub async fn send_skeleton(&self, skeleton: &SkeletonModel) {
        // VRChat OSC Trackers 對應表
        // BoneId -> VRChat Tracker Name
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
                self.send_tracker(name, bone.global_position, bone.global_rotation).await;
            }
        }
    }

    async fn send_tracker(&self, name: &str, pos: Vector3<f32>, rot: UnitQuaternion<f32>) {
        // 1. 發送位置 (Position)
        let addr_pos = format!("/tracking/trackers/{}/position", name);
        // 注意: VRChat 使用 Unity 座標系 (左手系, Y-Up)，Rust 通常是右手系。
        // 這裡做一個簡單的 Z 軸反轉嘗試適配，實際可能需要更複雜的轉換。
        let args_pos = vec![
            OscType::Float(pos.x),
            OscType::Float(pos.y),
            OscType::Float(-pos.z), 
        ];
        self.send_packet(&addr_pos, args_pos).await;

        // 2. 發送旋轉 (Rotation) - VRChat 預期歐拉角 (Euler Angles)
        let (roll, pitch, yaw) = rot.euler_angles();
        let addr_rot = format!("/tracking/trackers/{}/rotation", name);
        // 順序通常是 Pitch(X), Yaw(Y), Roll(Z)
        let args_rot = vec![
            OscType::Float(pitch.to_degrees()),
            OscType::Float(-yaw.to_degrees()), // 嘗試反轉 Yaw 以匹配左手系
            OscType::Float(-roll.to_degrees()),
        ];
        self.send_packet(&addr_rot, args_rot).await;
    }

    async fn send_packet(&self, addr: &str, args: Vec<OscType>) {
        let packet = OscPacket::Message(OscMessage { addr: addr.to_string(), args });
        if let Ok(buf) = encoder::encode(&packet) {
            let _ = self.socket.send_to(&buf, self.target_addr).await;
        }
    }
}