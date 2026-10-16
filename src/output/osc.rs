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
        let target_addr: std::net::SocketAddr = format!("{}:{}", target_ip, target_port)
            .parse()
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidInput, e))?;
        // Sends to port 0 or to 0.0.0.0 fail, and send errors are not reported per frame:
        // such a target would look active while nothing reaches VRChat.
        if target_addr.port() == 0 || target_addr.ip().is_unspecified() {
            return Err(std::io::Error::new(std::io::ErrorKind::InvalidInput, "no receiver at port 0 or address 0.0.0.0"));
        }

        log::info!("OSC Sender initialized, targeting {}", target_addr);
        Ok(Self {
            socket,
            target_addr,
            last_rotation_degrees: Mutex::new(HashMap::new()),
        })
    }

    pub async fn send_skeleton(&self, skeleton: &SkeletonModel) {
        for (bone_id, name) in VRCHAT_TRACKERS {
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

        let [x_deg, y_deg, z_deg] = self.continuous_rotation_degrees(name, rot);
        let addr_rot = format!("/tracking/trackers/{}/rotation", name);
        let args_rot = vec![
            OscType::Float(x_deg),
            OscType::Float(y_deg),
            OscType::Float(z_deg),
        ];
        self.send_packet(&addr_rot, args_rot).await;
    }

    fn continuous_rotation_degrees(&self, name: &str, rot: UnitQuaternion<f32>) -> [f32; 3] {
        let current = unity_euler_degrees(&rot);

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

/// VRChat's OSC trackers: numbered 1-8, plus "head", which only aligns the
/// OSC space with the headset. Named addresses such as "hips" are ignored.
/// VRChat assigns body parts itself during calibration.
pub const VRCHAT_TRACKERS: [(u8, &str); 9] = [
    (0, "1"),  // hips
    (2, "2"),  // chest
    (12, "3"), // left foot
    (22, "4"), // right foot
    (11, "5"), // left knee
    (21, "6"), // right knee
    (32, "7"), // left elbow
    (42, "8"), // right elbow
    (4, "head"),
];

/// Right-handed Y-up rotation as VRChat expects it: mirror Z into Unity's
/// left-handed frame (as the position does), then take Unity's Euler angles
/// in degrees, applied Z, then X, then Y (R = Ry * Rx * Rz).
pub fn unity_euler_degrees(rot: &UnitQuaternion<f32>) -> [f32; 3] {
    let q = rot.quaternion();
    let (x, y, z, w) = (-q.i, -q.j, q.k, q.w);
    let sin_x = (2.0 * (w * x - y * z)).clamp(-1.0, 1.0);
    let euler_x = sin_x.asin();
    let euler_y = (2.0 * (w * y + x * z)).atan2(1.0 - 2.0 * (x * x + y * y));
    let euler_z = (2.0 * (w * z + x * y)).atan2(1.0 - 2.0 * (x * x + z * z));
    [euler_x.to_degrees(), euler_y.to_degrees(), euler_z.to_degrees()]
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
    use super::{unity_euler_degrees, unwrap_degrees, VRCHAT_TRACKERS};
    use nalgebra::{Matrix3, Rotation3, UnitQuaternion, Vector3};

    #[tokio::test]
    async fn targets_that_cannot_receive_are_refused() {
        assert!(super::OscSender::new("127.0.0.1", 9000).await.is_ok());
        assert!(super::OscSender::new("127.0.0.1", 0).await.is_err());
        assert!(super::OscSender::new("0.0.0.0", 9000).await.is_err());
        assert!(super::OscSender::new("localhost", 9000).await.is_err());
    }

    #[test]
    fn tracker_addresses_are_ones_vrchat_accepts() {
        let names: Vec<&str> = VRCHAT_TRACKERS.iter().map(|(_, name)| *name).collect();
        assert_eq!(names, ["1", "2", "3", "4", "5", "6", "7", "8", "head"]);
    }

    #[test]
    fn euler_angles_rebuild_the_mirrored_rotation_in_unity_order() {
        let mirror = Matrix3::from_diagonal(&Vector3::new(1.0f32, 1.0, -1.0));
        let axes = [Vector3::x_axis(), Vector3::y_axis(), Vector3::z_axis()];
        for (i, angles) in [[0.3f32, -1.1, 2.0], [1.2, 0.4, -0.7], [-0.2, 2.9, 0.1], [0.0, 0.0, 0.0]].iter().enumerate() {
            let rot = UnitQuaternion::from_euler_angles(angles[0], angles[1], angles[2]);
            let [ex, ey, ez] = unity_euler_degrees(&rot).map(f32::to_radians);
            let rebuilt = Rotation3::from_axis_angle(&axes[1], ey)
                * Rotation3::from_axis_angle(&axes[0], ex)
                * Rotation3::from_axis_angle(&axes[2], ez);
            let expected = mirror * rot.to_rotation_matrix().matrix() * mirror;
            assert!((rebuilt.matrix() - expected).abs().max() < 1e-4, "case {i}");
        }
    }

    #[test]
    fn a_left_turn_is_a_negative_unity_yaw() {
        // +90 degrees about +Y in a right-handed frame turns +X toward -Z;
        // mirrored into Unity's left-handed frame that is a -90 degree yaw.
        let rot = UnitQuaternion::from_axis_angle(&Vector3::y_axis(), std::f32::consts::FRAC_PI_2);
        let [x, y, z] = unity_euler_degrees(&rot);
        assert!(x.abs() < 1e-3 && (y + 90.0).abs() < 1e-3 && z.abs() < 1e-3, "{x} {y} {z}");
    }

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
