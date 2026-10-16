use super::*;
use crate::app::types::{QuestInputData, VrBridgePacket, VrPoseData};
use crate::fusion::AuthoritativePose;
use nalgebra::{Quaternion, UnitQuaternion, Vector3};
use std::time::Instant;

/// Headset input older than this is ignored, so a headset that stops sending
/// does not keep pinning the head and hands to its last pose.
pub(super) const QUEST_STALE_AFTER: Duration = Duration::from_millis(500);

/// The headset input if it arrived less than QUEST_STALE_AFTER before `now`.
pub(super) fn fresh_input(data: &QuestInputData, now: Instant) -> Option<&QuestInputData> {
    data.received_at
        .filter(|at| now.saturating_duration_since(*at) < QUEST_STALE_AFTER)
        .map(|_| data)
}

/// Age of the latest head pose, shown on the page; None before the first one.
pub(super) fn head_age_ms(data: &QuestInputData, now: Instant) -> Option<u64> {
    data.head
        .as_ref()
        .and(data.received_at)
        .map(|at| now.saturating_duration_since(at).as_millis() as u64)
}

/// A pose with non-finite numbers or a rotation far from unit length is dropped: normalising
/// a zero quaternion gives NaN, and NaN or infinity would stay in the IK for good.
fn to_authoritative_pose(pose: VrPoseData) -> Option<AuthoritativePose> {
    let finite = pose.pos.iter().chain(pose.rot.iter()).all(|value| value.is_finite());
    let norm = pose.rot.iter().map(|value| value * value).sum::<f32>().sqrt();
    if !finite || !(0.5..=1.5).contains(&norm) {
        return None;
    }
    Some(AuthoritativePose {
        position: Vector3::new(pose.pos[0], pose.pos[1], pose.pos[2]),
        rotation: UnitQuaternion::new_normalize(Quaternion::new(pose.rot[3], pose.rot[0], pose.rot[1], pose.rot[2])),
    })
}

/// The headset input carried by one bridge datagram (JSON), or None if it is not one.
pub(super) fn input_from_datagram(bytes: &[u8], now: Instant) -> Option<QuestInputData> {
    let packet = serde_json::from_slice::<VrBridgePacket>(bytes).ok()?;
    Some(QuestInputData {
        head: packet.head.and_then(to_authoritative_pose),
        left_hand: packet.left_hand.and_then(to_authoritative_pose),
        right_hand: packet.right_hand.and_then(to_authoritative_pose),
        received_at: Some(now),
    })
}

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

        // Head and both hands with full-precision floats exceed 256 bytes; a datagram larger
        // than the buffer is cut off (or refused on Windows) and the pose silently lost.
        let mut buf = [0u8; 2048];
        loop {
            if let Ok((len, _addr)) = quest_socket.recv_from(&mut buf).await {
                if let Some(input) = input_from_datagram(&buf[..len], Instant::now()) {
                    if quest_tx.send(input).is_err() {
                        break;
                    }
                }
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input(received_at: Option<Instant>) -> QuestInputData {
        let pose = AuthoritativePose {
            position: Vector3::new(0.0, 1.7, 0.0),
            rotation: UnitQuaternion::identity(),
        };
        QuestInputData { head: Some(pose), left_hand: None, right_hand: None, received_at }
    }

    #[test]
    fn bridge_datagrams_become_validated_poses() {
        let now = Instant::now();
        let full = br#"{"head":{"pos":[0.0123456789,1.6987654321,-0.0456789012],"rot":[0.0123456789,0.7012345678,-0.0234567891,0.7123456789]},
            "left_hand":{"pos":[-0.3123456789,1.1234567891,0.2345678912],"rot":[0.1234567891,0.2345678912,0.3456789123,0.8987654321]},
            "right_hand":{"pos":[0.3123456789,1.1234567891,0.2345678912],"rot":[0.1234567891,-0.2345678912,-0.3456789123,0.8987654321]}}"#;
        assert!(full.len() > 256, "this datagram is larger than the old buffer");
        let input = input_from_datagram(full, now).unwrap();
        assert!(input.head.is_some() && input.left_hand.is_some() && input.right_hand.is_some());

        let broken = br#"{"head":{"pos":[0,1.7,0],"rot":[0,0,0,0]},"left_hand":{"pos":[1e39,1,0],"rot":[0,0,0,1]},"right_hand":null}"#;
        let input = input_from_datagram(broken, now).unwrap();
        assert!(input.head.is_none() && input.left_hand.is_none() && input.right_hand.is_none());
        assert!(input_from_datagram(b"not json", now).is_none());
    }

    #[test]
    fn stale_headset_input_is_ignored() {
        let now = Instant::now();
        let recent = input(Some(now));
        assert!(fresh_input(&recent, now + Duration::from_millis(100)).is_some());
        assert!(fresh_input(&recent, now + QUEST_STALE_AFTER).is_none());
        assert!(fresh_input(&input(None), now).is_none());
        assert_eq!(head_age_ms(&recent, now + Duration::from_millis(250)), Some(250));
        assert_eq!(head_age_ms(&input(None), now), None);
    }
}
