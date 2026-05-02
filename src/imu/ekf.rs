/// 7-state IMU EKF: quaternion (4) + gyroscope bias (3)
///
/// World frame convention: Z-up (matches firmware LSM9DS1 orientation).
/// Gravity reference vector: [0, 0, 9.81] m/s².
///
/// State vector x = [qw, qx, qy, qz, bx, by, bz]
/// - q : orientation quaternion (body → world)
/// - b : gyro bias in body frame (rad/s)
///
/// Process model (continuous, discretised with Euler):
///   ω_corr = ω_meas − b
///   q̇ = 0.5 · Ω(ω_corr) · q
///   ḃ = 0  (random walk)
///
/// Measurements:
///   - Accelerometer: expected gravity in body frame
///   - Magnetometer:  expected horizontal magnetic reference in body frame
///                    (only when mag norm is in a sensible range)
use nalgebra::{Matrix4, Quaternion, SMatrix, SVector, UnitQuaternion, Vector3};

type State = SVector<f32, 7>;
type Cov = SMatrix<f32, 7, 7>;

const GRAVITY: f32 = 9.81;

/// Noise parameters — all tunable at runtime.
#[derive(Clone, Copy, Debug)]
pub struct EkfConfig {
    /// Gyro measurement noise std (rad/s). Drives process noise on quat rows.
    pub gyro_noise: f32,
    /// Gyro bias random walk std (rad/s per sqrt(s)).
    pub bias_noise: f32,
    /// Accelerometer measurement noise std (m/s², normalised domain).
    pub accel_noise: f32,
    /// Magnetometer measurement noise std (normalised domain).
    pub mag_noise: f32,
    /// Minimum accel norm fraction of gravity to trust accel measurement.
    pub accel_norm_min: f32,
    /// Maximum accel norm fraction of gravity to trust accel measurement.
    pub accel_norm_max: f32,
    /// Valid magnetometer norm range (uT).
    pub mag_norm_min: f32,
    pub mag_norm_max: f32,
}

impl Default for EkfConfig {
    fn default() -> Self {
        Self {
            gyro_noise: 0.01,
            bias_noise: 0.0005,
            accel_noise: 0.1,
            mag_noise: 0.1,
            accel_norm_min: 0.7,
            accel_norm_max: 1.3,
            mag_norm_min: 10.0,
            mag_norm_max: 80.0,
        }
    }
}

pub struct ImuEkf {
    /// Full 7-element state vector.
    state: State,
    /// 7×7 covariance matrix.
    cov: Cov,
    pub config: EkfConfig,
    initialised: bool,
}

impl Default for ImuEkf {
    fn default() -> Self {
        Self::new(EkfConfig::default())
    }
}

impl ImuEkf {
    pub fn new(config: EkfConfig) -> Self {
        let mut state = State::zeros();
        // Identity quaternion: [qw=1, qx=0, qy=0, qz=0]
        state[0] = 1.0;

        let cov = Cov::identity() * 0.1;

        Self {
            state,
            cov,
            config,
            initialised: false,
        }
    }

    /// Returns current orientation estimate.
    pub fn quaternion(&self) -> UnitQuaternion<f32> {
        let q = Quaternion::new(self.state[0], self.state[1], self.state[2], self.state[3]);
        UnitQuaternion::new_normalize(q)
    }

    /// Returns estimated gyro bias (rad/s).
    pub fn gyro_bias(&self) -> Vector3<f32> {
        Vector3::new(self.state[4], self.state[5], self.state[6])
    }

    /// Full update step: predict with gyro, then correct with accel (+ optional mag).
    ///
    /// * `gyro`  — raw gyroscope reading, rad/s, body frame
    /// * `accel` — accelerometer reading, m/s², body frame
    /// * `mag`   — magnetometer reading, uT, body frame (pass zeros to skip)
    /// * `dt`    — time since last call, seconds
    pub fn update(
        &mut self,
        gyro: [f32; 3],
        accel: [f32; 3],
        mag: [f32; 3],
        dt: f32,
    ) {
        let dt = dt.clamp(1.0 / 240.0, 0.05);

        if !self.initialised {
            self.initialise_from_accel_mag(accel, mag);
            return;
        }

        self.predict(gyro, dt);
        self.correct_accel(accel);

        let mag_v = Vector3::new(mag[0], mag[1], mag[2]);
        let mag_norm = mag_v.norm();
        if mag_norm >= self.config.mag_norm_min && mag_norm <= self.config.mag_norm_max {
            self.correct_mag(mag_v / mag_norm);
        }

        self.renormalise_quaternion();
    }

    // ── Initialisation ────────────────────────────────────────────────────────

    fn initialise_from_accel_mag(&mut self, accel: [f32; 3], mag: [f32; 3]) {
        let a = Vector3::new(accel[0], accel[1], accel[2]);
        let norm = a.norm();
        if norm < 0.1 {
            return; // can't initialise without gravity
        }
        let a_norm = a / norm;

        // Compute roll and pitch from gravity (Z-up).
        // gravity_body points toward [0,0,1] in world.
        let pitch = (-a_norm.x).asin();
        let roll = a_norm.y.atan2(a_norm.z);

        // Compute yaw from magnetometer if available.
        let m = Vector3::new(mag[0], mag[1], mag[2]);
        let mag_norm = m.norm();
        let yaw = if mag_norm >= self.config.mag_norm_min && mag_norm <= self.config.mag_norm_max {
            let m_norm = m / mag_norm;
            // Tilt-compensated yaw.
            let mx = m_norm.x * pitch.cos()
                + m_norm.y * roll.sin() * pitch.sin()
                + m_norm.z * roll.cos() * pitch.sin();
            let my = m_norm.y * roll.cos() - m_norm.z * roll.sin();
            (-my).atan2(mx)
        } else {
            0.0
        };

        let q = UnitQuaternion::from_euler_angles(roll, pitch, yaw);
        self.state[0] = q.w;
        self.state[1] = q.i;
        self.state[2] = q.j;
        self.state[3] = q.k;
        self.state[4] = 0.0;
        self.state[5] = 0.0;
        self.state[6] = 0.0;

        self.initialised = true;
    }

    // ── Predict step ─────────────────────────────────────────────────────────

    fn predict(&mut self, gyro: [f32; 3], dt: f32) {
        let qw = self.state[0];
        let qx = self.state[1];
        let qy = self.state[2];
        let qz = self.state[3];
        let bx = self.state[4];
        let by = self.state[5];
        let bz = self.state[6];

        // Bias-corrected angular velocity.
        let wx = gyro[0] - bx;
        let wy = gyro[1] - by;
        let wz = gyro[2] - bz;

        // Quaternion derivative: q_dot = 0.5 * Omega(w) * q
        // Omega(w) = [[ 0, -wx, -wy, -wz],
        //             [wx,   0,  wz, -wy],
        //             [wy, -wz,   0,  wx],
        //             [wz,  wy, -wx,   0]]
        let dqw = 0.5 * (-wx * qx - wy * qy - wz * qz);
        let dqx = 0.5 * ( wx * qw + wz * qy - wy * qz);
        let dqy = 0.5 * ( wy * qw - wz * qx + wx * qz);
        let dqz = 0.5 * ( wz * qw + wy * qx - wx * qy);

        self.state[0] += dqw * dt;
        self.state[1] += dqx * dt;
        self.state[2] += dqy * dt;
        self.state[3] += dqz * dt;
        // bias unchanged

        // ── Covariance prediction ─────────────────────────────────────────────
        // State transition Jacobian F (7×7)
        // ∂q_new/∂q  = I + 0.5*dt*Omega(w)  (4×4 block)
        // ∂q_new/∂b  = -0.5*dt * G(q)        (4×3 block)
        // ∂b_new/∂q  = 0
        // ∂b_new/∂b  = I

        // Omega(w) for the 4×4 block (rows: qw,qx,qy,qz; cols: qw,qx,qy,qz):
        let omega = Matrix4::new(
             0.0, -wx, -wy, -wz,
             wx,  0.0,  wz, -wy,
             wy, -wz,  0.0,  wx,
             wz,  wy,  -wx, 0.0,
        );

        // G(q) = 0.5 * [[-qx, -qy, -qz],
        //               [ qw, -qz,  qy],
        //               [ qz,  qw, -qx],
        //               [-qy,  qx,  qw]]
        let g = SMatrix::<f32, 4, 3>::from_column_slice(&[
            -qx,  qw,  qz, -qy,
            -qy, -qz,  qw,  qx,
            -qz,  qy, -qx,  qw,
        ]) * 0.5;

        let mut f = SMatrix::<f32, 7, 7>::identity();
        // Top-left 4×4: I + 0.5*dt*Omega
        for r in 0..4 {
            for c in 0..4 {
                f[(r, c)] += 0.5 * dt * omega[(r, c)];
            }
        }
        // Top-right 4×3: -dt * G
        for r in 0..4 {
            for c in 0..3 {
                f[(r, 4 + c)] = -dt * g[(r, c)];
            }
        }

        // Process noise Q
        let gyro_var = (self.config.gyro_noise * dt).powi(2);
        let bias_var = (self.config.bias_noise * dt.sqrt()).powi(2);
        let mut q_noise = SMatrix::<f32, 7, 7>::zeros();
        for i in 0..4 {
            q_noise[(i, i)] = gyro_var;
        }
        for i in 4..7 {
            q_noise[(i, i)] = bias_var;
        }

        self.cov = f * self.cov * f.transpose() + q_noise;
    }

    // ── Accelerometer correction ──────────────────────────────────────────────

    fn correct_accel(&mut self, accel: [f32; 3]) {
        let a = Vector3::new(accel[0], accel[1], accel[2]);
        let a_norm = a.norm();
        // Skip during strong dynamic acceleration or free-fall.
        let g_frac = a_norm / GRAVITY;
        if g_frac < self.config.accel_norm_min || g_frac > self.config.accel_norm_max {
            return;
        }

        let q = self.quaternion();
        let g_exp = q.inverse() * Vector3::new(0.0, 0.0, GRAVITY);
        let residual = a - g_exp;
        let h = self.accel_jacobian(&q);
        self.kalman_update_3(residual, &h, self.config.accel_noise);
    }

    fn accel_jacobian(&self, q: &UnitQuaternion<f32>) -> SMatrix<f32, 3, 7> {
        let qw = q.w;
        let qx = q.i;
        let qy = q.j;
        let qz = q.k;
        let g = GRAVITY;

        // g_body = R(q)^T * [0,0,g]
        // gx = 2g(qx*qz - qw*qy)
        // gy = 2g(qy*qz + qw*qx)
        // gz = g(qw²-qx²-qy²+qz²)
        let mut h = SMatrix::<f32, 3, 7>::zeros();
        h[(0, 0)] = -2.0 * qy * g;
        h[(0, 1)] =  2.0 * qz * g;
        h[(0, 2)] = -2.0 * qw * g;
        h[(0, 3)] =  2.0 * qx * g;

        h[(1, 0)] =  2.0 * qx * g;
        h[(1, 1)] =  2.0 * qw * g;
        h[(1, 2)] =  2.0 * qz * g;
        h[(1, 3)] =  2.0 * qy * g;

        h[(2, 0)] =  2.0 * qw * g;
        h[(2, 1)] = -2.0 * qx * g;
        h[(2, 2)] = -2.0 * qy * g;
        h[(2, 3)] =  2.0 * qz * g;
        h
    }

    // ── Magnetometer correction ───────────────────────────────────────────────

    fn correct_mag(&mut self, m_body_norm: Vector3<f32>) {
        let q = self.quaternion();

        // Project magnetometer to world frame, then flatten to horizontal plane
        // to build a yaw-only reference (avoids dip-angle coupling).
        let m_world = q * m_body_norm;
        let bx = (m_world.x * m_world.x + m_world.y * m_world.y).sqrt();
        let bz = m_world.z;
        let b_world_norm = Vector3::new(bx, 0.0, bz).normalize();

        // Expected in body frame.
        let m_expected = q.inverse() * b_world_norm;
        let residual = m_body_norm - m_expected;

        let h = self.mag_jacobian(&q, &b_world_norm);
        self.kalman_update_3(residual, &h, self.config.mag_noise);
    }

    fn mag_jacobian(
        &self,
        q: &UnitQuaternion<f32>,
        b: &Vector3<f32>,
    ) -> SMatrix<f32, 3, 7> {
        // Numerical Jacobian (2·ε perturbation) — clean and correct.
        let eps = 1e-4_f32;
        let mut h = SMatrix::<f32, 3, 7>::zeros();

        let base = q.inverse() * b;

        for col in 0..4 {
            let mut s_plus = self.state;
            let mut s_minus = self.state;
            s_plus[col] += eps;
            s_minus[col] -= eps;

            let qp = UnitQuaternion::new_normalize(Quaternion::new(
                s_plus[0], s_plus[1], s_plus[2], s_plus[3],
            ));
            let qm = UnitQuaternion::new_normalize(Quaternion::new(
                s_minus[0], s_minus[1], s_minus[2], s_minus[3],
            ));

            let fp = qp.inverse() * b;
            let fm = qm.inverse() * b;
            let diff = (fp - fm) / (2.0 * eps);

            for row in 0..3 {
                h[(row, col)] = diff[row];
            }
        }
        let _ = base; // suppress unused warning
        h
    }

    // ── Kalman update (3-measurement dimension) ───────────────────────────────

    fn kalman_update_3(
        &mut self,
        residual: SVector<f32, 3>,
        h: &SMatrix<f32, 3, 7>,
        noise_std: f32,
    ) {
        let r = SMatrix::<f32, 3, 3>::identity() * noise_std.powi(2).max(1e-8);
        let s = h * self.cov * h.transpose() + r;
        let Some(s_inv) = s.try_inverse() else {
            return;
        };
        let k = self.cov * h.transpose() * s_inv;
        self.state += k * residual;

        let i_kh = SMatrix::<f32, 7, 7>::identity() - k * h;
        self.cov = i_kh * self.cov;
    }

    // ── Quaternion maintenance ────────────────────────────────────────────────

    fn renormalise_quaternion(&mut self) {
        let norm = (self.state[0].powi(2)
            + self.state[1].powi(2)
            + self.state[2].powi(2)
            + self.state[3].powi(2))
        .sqrt();
        if norm > 1e-6 {
            self.state[0] /= norm;
            self.state[1] /= norm;
            self.state[2] /= norm;
            self.state[3] /= norm;
        } else {
            // Reset to identity if something went badly wrong.
            self.state[0] = 1.0;
            self.state[1] = 0.0;
            self.state[2] = 0.0;
            self.state[3] = 0.0;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identity_at_rest() {
        let mut ekf = ImuEkf::default();
        // Flat, Z-up at rest: gravity = [0, 0, 9.81], gyro = 0
        for _ in 0..200 {
            ekf.update(
                [0.0, 0.0, 0.0],
                [0.0, 0.0, GRAVITY],
                [0.0, 0.0, 0.0],
                1.0 / 119.0,
            );
        }
        let q = ekf.quaternion();
        // Should converge close to identity
        assert!((q.w - 1.0).abs() < 0.05, "qw={}", q.w);
        assert!(q.i.abs() < 0.05);
        assert!(q.j.abs() < 0.05);
    }

    #[test]
    fn bias_estimation_converges() {
        let mut ekf = ImuEkf::default();
        let true_bias = [0.05_f32, -0.03, 0.02];
        for _ in 0..500 {
            ekf.update(
                true_bias,
                [0.0, 0.0, GRAVITY],
                [0.0, 0.0, 0.0],
                1.0 / 119.0,
            );
        }
        let bias = ekf.gyro_bias();
        assert!((bias.x - true_bias[0]).abs() < 0.02, "bias_x={}", bias.x);
        assert!((bias.y - true_bias[1]).abs() < 0.02, "bias_y={}", bias.y);
        assert!((bias.z - true_bias[2]).abs() < 0.02, "bias_z={}", bias.z);
    }
}
