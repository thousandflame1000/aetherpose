use nalgebra::Vector3;

#[derive(Debug, Clone, Copy, serde::Serialize, serde::Deserialize)]
pub struct MagCalibration {
    pub offset: [f32; 3],
    pub scale: [f32; 3],
}

impl Default for MagCalibration {
    fn default() -> Self {
        Self {
            offset: [0.0; 3],
            scale: [1.0; 3],
        }
    }
}

impl MagCalibration {
    /// Simple hard-iron offset and soft-iron scale calibration from a point cloud.
    pub fn calibrate(points: &[Vector3<f32>]) -> Option<Self> {
        if points.len() < 10 {
            return None;
        }

        let mut min = Vector3::new(f32::MAX, f32::MAX, f32::MAX);
        let mut max = Vector3::new(f32::MIN, f32::MIN, f32::MIN);

        for p in points {
            min.x = min.x.min(p.x);
            min.y = min.y.min(p.y);
            min.z = min.z.min(p.z);
            max.x = max.x.max(p.x);
            max.y = max.y.max(p.y);
            max.z = max.z.max(p.z);
        }

        let offset = (min + max) / 2.0;
        let half_range = (max - min) / 2.0;
        let avg_radius = (half_range.x + half_range.y + half_range.z) / 3.0;
        if avg_radius < 1e-6 {
            return None;
        }

        let scale = Vector3::new(
            avg_radius / half_range.x.max(1e-6),
            avg_radius / half_range.y.max(1e-6),
            avg_radius / half_range.z.max(1e-6),
        );

        Some(Self {
            offset: [offset.x, offset.y, offset.z],
            scale: [scale.x, scale.y, scale.z],
        })
    }
}
