use nalgebra::Vector3;

/// Simple ZUPT (zero-velocity) / stationary detector.
/// Maintains a short sliding window of acceleration magnitudes and angular
/// velocity to decide whether the sensor is stationary.
pub struct ZuptDetector {
    window: std::collections::VecDeque<f32>,
    window_size: usize,
    accel_var_threshold: f32,
    gyro_threshold: f32,
}

/// Largest window, as on the page. The window is allocated up front, so a huge value from a
/// hand-edited config.json would otherwise abort the backend at start-up.
pub const MAX_ZUPT_WINDOW: usize = 200;

impl ZuptDetector {
    pub fn new(window_size: usize, accel_var_threshold: f32, gyro_threshold: f32) -> Self {
        // A zero window would never be trimmed and grow without bound.
        let window_size = window_size.clamp(1, MAX_ZUPT_WINDOW);
        Self {
            window: std::collections::VecDeque::with_capacity(window_size),
            window_size,
            accel_var_threshold,
            gyro_threshold,
        }
    }

    pub fn update(&mut self, acceleration: Vector3<f32>, angular_velocity: Vector3<f32>) -> bool {
        let mag = acceleration.norm();

        if self.window.len() == self.window_size {
            self.window.pop_front();
        }
        self.window.push_back(mag);

        if self.window.len() < self.window_size {
            return false;
        }

        let mean: f32 = self.window.iter().sum::<f32>() / self.window.len() as f32;
        let var: f32 = self
            .window
            .iter()
            .map(|v| {
                let d = v - mean;
                d * d
            })
            .sum::<f32>()
            / self.window.len() as f32;

        var <= self.accel_var_threshold && angular_velocity.norm() <= self.gyro_threshold
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zero_window_does_not_grow() {
        let mut d = ZuptDetector::new(0, 0.0005, 0.02);
        for _ in 0..100 {
            d.update(Vector3::new(0.0, 1.0, 0.0), Vector3::zeros());
        }
        assert_eq!(d.window.len(), 1);
    }

    #[test]
    fn a_huge_window_is_capped() {
        let mut d = ZuptDetector::new(usize::MAX, 0.0005, 0.02);
        let still = |d: &mut ZuptDetector| d.update(Vector3::new(0.0, 9.81, 0.0), Vector3::zeros());
        for _ in 0..MAX_ZUPT_WINDOW - 1 {
            assert!(!still(&mut d));
        }
        assert!(still(&mut d), "a full window of {MAX_ZUPT_WINDOW} still samples is stationary");
    }

    #[test]
    fn test_zupt_detects_stationary() {
        let mut d = ZuptDetector::new(8, 0.0005, 0.02);

        for i in 0..12 {
            let noise = if i % 2 == 0 { 0.001 } else { -0.001 };
            let stationary = d.update(
                Vector3::new(0.0, 1.0 + noise, 0.0),
                Vector3::new(0.0, 0.0, 0.0),
            );
            if i < 7 {
                assert!(!stationary, "need warmup samples");
            } else {
                assert!(stationary, "should detect stationary after window filled");
            }
        }
    }

    #[test]
    fn test_zupt_detects_motion() {
        let mut d = ZuptDetector::new(8, 0.0005, 0.02);

        for i in 0..12 {
            let a = if i < 6 { 1.0 } else { 1.5 };
            let ang = if i < 6 { 0.0 } else { 0.5 };
            let stationary = d.update(Vector3::new(0.0, a, 0.0), Vector3::new(ang, 0.0, 0.0));
            if i < 7 {
                assert!(!stationary);
            } else {
                assert!(!stationary, "should not be stationary when motion present");
            }
        }
    }
}
