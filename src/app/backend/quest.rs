use super::*;
use crate::app::types::{QuestInputData, VrBridgePacket, VrPoseData};
use crate::fusion::AuthoritativePose;
use nalgebra::{Quaternion, UnitQuaternion, Vector3};

pub(super) fn spawn_quest_listener(quest_tx: watch::Sender<QuestInputData>) {
    tokio::spawn(async move {
        let quest_socket = match UdpSocket::bind(("0.0.0.0", QUEST_BRIDGE_PORT)).await {
            Ok(socket) => socket,
            Err(e) => {
                error!("Quest bridge bind failed on {}: {}", QUEST_BRIDGE_PORT, e);
                return;
            }
        };

        info!("Quest bridge listening on 0.0.0.0:{}", QUEST_BRIDGE_PORT);

        let mut buf = [0u8; 256];
        loop {
            if let Ok((len, _addr)) = quest_socket.recv_from(&mut buf).await {
                if let Ok(packet) = serde_json::from_slice::<VrBridgePacket>(&buf[..len]) {
                    let to_authoritative_pose = |pose: VrPoseData| AuthoritativePose {
                        position: Vector3::new(pose.pos[0], pose.pos[1], pose.pos[2]),
                        rotation: UnitQuaternion::new_normalize(Quaternion::new(
                            pose.rot[3],
                            pose.rot[0],
                            pose.rot[1],
                            pose.rot[2],
                        )),
                    };

                    let input = QuestInputData {
                        head: packet.head.map(to_authoritative_pose),
                        left_hand: packet.left_hand.map(to_authoritative_pose),
                        right_hand: packet.right_hand.map(to_authoritative_pose),
                    };

                    if quest_tx.send(input).is_err() {
                        break;
                    }
                }
            }
        }
    });
}
