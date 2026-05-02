use nalgebra::{UnitQuaternion, Vector3};
use std::f32::consts::PI;
use std::time::Instant;

#[derive(Debug, Clone)]
pub struct OneEuroFilter {
    min_cutoff: f32, // 最小截止頻率 (Hz)，越低越平滑但延遲越高
    beta: f32,       // 速度係數，越高則在快速移動時延遲越低
    d_cutoff: f32,   // 導數的截止頻率 (通常設為 1.0 Hz)
    last_time: Option<Instant>,
    last_val: Option<UnitQuaternion<f32>>,
    last_dx: Vector3<f32>, // 估算的角速度
}

impl OneEuroFilter {
    pub fn new(min_cutoff: f32, beta: f32) -> Self {
        Self {
            min_cutoff,
            beta,
            d_cutoff: 1.0,
            last_time: None,
            last_val: None,
            last_dx: Vector3::zeros(),
        }
    }

    pub fn update_params(&mut self, min_cutoff: f32, beta: f32) {
        self.min_cutoff = min_cutoff;
        self.beta = beta;
    }

    fn alpha(cutoff: f32, dt: f32) -> f32 {
        // Guard against zero or near-zero cutoff which would cause division by zero.
        let cutoff_safe = if cutoff <= 1e-6 { 1e-6 } else { cutoff };
        let tau = 1.0 / (2.0 * PI * cutoff_safe);
        1.0 / (1.0 + tau / dt)
    }

    pub fn filter(&mut self, val: UnitQuaternion<f32>) -> UnitQuaternion<f32> {
        let now = Instant::now();

        let last_time = match self.last_time {
            Some(t) => t,
            None => {
                self.last_time = Some(now);
                self.last_val = Some(val);
                return val;
            }
        };

        let dt = (now - last_time).as_secs_f32();
        if dt <= 0.0 {
            return self.last_val.unwrap_or(val);
        }

        let prev_val = match &self.last_val {
            Some(p) => *p,
            None => {
                self.last_time = Some(now);
                self.last_val = Some(val);
                return val;
            }
        };

        // 1. 計算角速度 (Derivative)
        // delta_q = val * prev_val^-1
        let delta_q = val * prev_val.inverse();
        let (axis, angle) = if let Some((axis, angle)) = delta_q.axis_angle() {
            (axis.into_inner(), angle)
        } else {
            (Vector3::zeros(), 0.0)
        };
        let dx = axis * (angle / dt);

        // 2. 濾波角速度
        let a_d = Self::alpha(self.d_cutoff, dt);
        let edx = self.last_dx.lerp(&dx, a_d);
        self.last_dx = edx;

        // 3. 動態調整截止頻率
        // 速度越快 (edx.magnitude 越大)，cutoff 越高，延遲越低
        let cutoff = self.min_cutoff + self.beta * edx.magnitude();

        // 4. 濾波姿態 (使用 Slerp)
        let a = Self::alpha(cutoff, dt);
        let result = prev_val.slerp(&val, a);

        self.last_time = Some(now);
        self.last_val = Some(result);

        result
    }
}
