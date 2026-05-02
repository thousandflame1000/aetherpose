use nalgebra::{SMatrix, SVector, UnitQuaternion, Vector3};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::Instant;

type StateVector = SVector<f32, 9>;
type CovarianceMatrix = SMatrix<f32, 9, 9>;
type MeasurementMatrix = SMatrix<f32, 3, 9>;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TrajectoryIntegrationMode {
    Rk4,
    Euler,
}

impl Default for TrajectoryIntegrationMode {
    fn default() -> Self {
        Self::Rk4
    }
}

#[derive(Debug, Clone, Copy)]
pub struct TrajectoryEstimate {
    pub position: Vector3<f32>,
    pub velocity: Vector3<f32>,
    pub linear_acceleration: Vector3<f32>,
    pub stationary: bool,
}

#[derive(Debug, Clone, Copy)]
pub struct TrajectoryConfig {
    pub gravity_mps2: f32,
    pub accel_process_noise: f32,
    pub bias_process_noise: f32,
    pub zero_velocity_noise: f32,
    pub bias_measurement_noise: f32,
    pub min_dt: f32,
    pub max_dt: f32,
}

impl Default for TrajectoryConfig {
    fn default() -> Self {
        Self {
            gravity_mps2: 9.81,
            accel_process_noise: 2.0,
            bias_process_noise: 0.15,
            zero_velocity_noise: 0.05,
            bias_measurement_noise: 0.35,
            min_dt: 1.0 / 240.0,
            max_dt: 0.05,
        }
    }
}

#[derive(Debug, Clone)]
struct TrackerTrajectoryState {
    bone_id: u8,
    anchor_position: Vector3<f32>,
    state: StateVector,
    covariance: CovarianceMatrix,
    last_timestamp: Option<Instant>,
    last_sample_counter: u64,
}

impl TrackerTrajectoryState {
    fn new(bone_id: u8, anchor_position: Vector3<f32>) -> Self {
        Self {
            bone_id,
            anchor_position,
            state: StateVector::zeros(),
            covariance: CovarianceMatrix::identity() * 0.1,
            last_timestamp: None,
            last_sample_counter: 0,
        }
    }

    fn position_delta(&self) -> Vector3<f32> {
        self.state.fixed_rows::<3>(0).into_owned()
    }

    fn velocity(&self) -> Vector3<f32> {
        self.state.fixed_rows::<3>(3).into_owned()
    }

    fn accel_bias(&self) -> Vector3<f32> {
        self.state.fixed_rows::<3>(6).into_owned()
    }

    fn set_position_delta(&mut self, value: Vector3<f32>) {
        self.state.fixed_rows_mut::<3>(0).copy_from(&value);
    }

    fn set_velocity(&mut self, value: Vector3<f32>) {
        self.state.fixed_rows_mut::<3>(3).copy_from(&value);
    }
}

pub struct ImuTrajectoryEstimator {
    config: TrajectoryConfig,
    mode: TrajectoryIntegrationMode,
    trackers: HashMap<u8, TrackerTrajectoryState>,
}

impl Default for ImuTrajectoryEstimator {
    fn default() -> Self {
        Self::new()
    }
}

impl ImuTrajectoryEstimator {
    pub fn new() -> Self {
        Self {
            config: TrajectoryConfig::default(),
            mode: TrajectoryIntegrationMode::default(),
            trackers: HashMap::new(),
        }
    }

    pub fn set_integration_mode(&mut self, mode: TrajectoryIntegrationMode) {
        self.mode = mode;
    }

    pub fn integration_mode(&self) -> TrajectoryIntegrationMode {
        self.mode
    }

    pub fn update(
        &mut self,
        tracker_id: u8,
        bone_id: u8,
        anchor_position: Vector3<f32>,
        sample_counter: u64,
        rotation: UnitQuaternion<f32>,
        accel_body: [f32; 3],
        stationary: bool,
    ) -> TrajectoryEstimate {
        let now = Instant::now();
        let state = self
            .trackers
            .entry(tracker_id)
            .or_insert_with(|| TrackerTrajectoryState::new(bone_id, anchor_position));

        if state.bone_id != bone_id {
            *state = TrackerTrajectoryState::new(bone_id, anchor_position);
        }

        if sample_counter == state.last_sample_counter {
            return TrajectoryEstimate {
                position: state.anchor_position + state.position_delta(),
                velocity: state.velocity(),
                linear_acceleration: Vector3::zeros(),
                stationary,
            };
        }

        let linear_acceleration =
            world_linear_acceleration(rotation, accel_body, self.config.gravity_mps2);

        let dt = state
            .last_timestamp
            .map(|last| {
                (now - last)
                    .as_secs_f32()
                    .clamp(self.config.min_dt, self.config.max_dt)
            })
            .unwrap_or(self.config.min_dt);

        predict(state, linear_acceleration, dt, self.config, self.mode);

        if stationary {
            apply_zero_velocity_update(state, self.config);
            apply_bias_measurement_update(state, linear_acceleration, self.config);
            state.set_velocity(Vector3::zeros());
        }

        state.last_timestamp = Some(now);
        state.last_sample_counter = sample_counter;

        TrajectoryEstimate {
            position: state.anchor_position + state.position_delta(),
            velocity: state.velocity(),
            linear_acceleration,
            stationary,
        }
    }

    pub fn clear(&mut self) {
        self.trackers.clear();
    }
}

fn world_linear_acceleration(
    rotation: UnitQuaternion<f32>,
    accel_body: [f32; 3],
    gravity_mps2: f32,
) -> Vector3<f32> {
    let measured_world = rotation * Vector3::new(accel_body[0], accel_body[1], accel_body[2]);
    // Firmware Madgwick 使用 Z-up，重力參考向量為 [0, 0, g]
    measured_world - Vector3::new(0.0, 0.0, gravity_mps2)
}

fn predict(
    state: &mut TrackerTrajectoryState,
    measured_linear_acceleration: Vector3<f32>,
    dt: f32,
    config: TrajectoryConfig,
    mode: TrajectoryIntegrationMode,
) {
    let corrected_accel = measured_linear_acceleration - state.accel_bias();
    let (position_delta, velocity) = match mode {
        TrajectoryIntegrationMode::Rk4 => {
            rk4_integrate(state.position_delta(), state.velocity(), corrected_accel, dt)
        }
        TrajectoryIntegrationMode::Euler => {
            euler_integrate(state.position_delta(), state.velocity(), corrected_accel, dt)
        }
    };
    state.set_position_delta(position_delta);
    state.set_velocity(velocity);

    let dt2 = dt * dt;
    let dt3 = dt2 * dt;
    let dt4 = dt2 * dt2;

    let mut transition = CovarianceMatrix::identity();
    for axis in 0..3 {
        transition[(axis, axis + 3)] = dt;
        transition[(axis, axis + 6)] = -0.5 * dt2;
        transition[(axis + 3, axis + 6)] = -dt;
    }

    let accel_var = config.accel_process_noise * config.accel_process_noise;
    let bias_var = config.bias_process_noise * config.bias_process_noise;
    let mut process_noise = CovarianceMatrix::zeros();
    for axis in 0..3 {
        process_noise[(axis, axis)] = 0.25 * dt4 * accel_var;
        process_noise[(axis, axis + 3)] = 0.5 * dt3 * accel_var;
        process_noise[(axis + 3, axis)] = 0.5 * dt3 * accel_var;
        process_noise[(axis + 3, axis + 3)] = dt2 * accel_var;
        process_noise[(axis + 6, axis + 6)] = dt * bias_var;
    }

    state.covariance =
        transition * state.covariance * transition.transpose() + process_noise;
}

fn apply_zero_velocity_update(state: &mut TrackerTrajectoryState, config: TrajectoryConfig) {
    let mut measurement = MeasurementMatrix::zeros();
    for axis in 0..3 {
        measurement[(axis, axis + 3)] = 1.0;
    }

    kalman_update(
        state,
        Vector3::zeros(),
        measurement,
        config.zero_velocity_noise,
    );
}

fn apply_bias_measurement_update(
    state: &mut TrackerTrajectoryState,
    measured_linear_acceleration: Vector3<f32>,
    config: TrajectoryConfig,
) {
    let mut measurement = MeasurementMatrix::zeros();
    for axis in 0..3 {
        measurement[(axis, axis + 6)] = 1.0;
    }

    kalman_update(
        state,
        measured_linear_acceleration,
        measurement,
        config.bias_measurement_noise,
    );
}

fn kalman_update(
    state: &mut TrackerTrajectoryState,
    measurement_value: Vector3<f32>,
    measurement_model: MeasurementMatrix,
    noise_std: f32,
) {
    let noise = SMatrix::<f32, 3, 3>::identity() * noise_std.max(1e-4).powi(2);
    let innovation = measurement_value - (measurement_model * state.state);
    let innovation_cov =
        measurement_model * state.covariance * measurement_model.transpose() + noise;

    let Some(innovation_cov_inv) = innovation_cov.try_inverse() else {
        return;
    };

    let gain = state.covariance * measurement_model.transpose() * innovation_cov_inv;
    state.state += gain * innovation;
    let identity = CovarianceMatrix::identity();
    state.covariance = (identity - gain * measurement_model) * state.covariance;
}

fn rk4_integrate(
    position: Vector3<f32>,
    velocity: Vector3<f32>,
    acceleration: Vector3<f32>,
    dt: f32,
) -> (Vector3<f32>, Vector3<f32>) {
    let k1_pos = velocity;
    let k1_vel = acceleration;

    let k2_pos = velocity + 0.5 * dt * k1_vel;
    let k2_vel = acceleration;

    let k3_pos = velocity + 0.5 * dt * k2_vel;
    let k3_vel = acceleration;

    let k4_pos = velocity + dt * k3_vel;
    let k4_vel = acceleration;

    let next_position =
        position + (dt / 6.0) * (k1_pos + 2.0 * k2_pos + 2.0 * k3_pos + k4_pos);
    let next_velocity =
        velocity + (dt / 6.0) * (k1_vel + 2.0 * k2_vel + 2.0 * k3_vel + k4_vel);

    (next_position, next_velocity)
}

fn euler_integrate(
    position: Vector3<f32>,
    velocity: Vector3<f32>,
    acceleration: Vector3<f32>,
    dt: f32,
) -> (Vector3<f32>, Vector3<f32>) {
    let next_position = position + velocity * dt;
    let next_velocity = velocity + acceleration * dt;
    (next_position, next_velocity)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rk4_matches_constant_acceleration() {
        let acceleration = Vector3::new(1.0, 0.0, 0.0);
        let (position, velocity) =
            rk4_integrate(Vector3::zeros(), Vector3::zeros(), acceleration, 1.0);

        assert!((position.x - 0.5).abs() < 1e-4);
        assert!((velocity.x - 1.0).abs() < 1e-4);
    }

    #[test]
    fn stationary_update_pulls_velocity_towards_zero() {
        let config = TrajectoryConfig::default();
        let mut state = TrackerTrajectoryState::new(12, Vector3::zeros());
        state.set_velocity(Vector3::new(3.0, -1.0, 0.5));
        let before = state.velocity().norm();

        apply_zero_velocity_update(&mut state, config);

        assert!(state.velocity().norm() < before);
    }

    #[test]
    fn euler_and_rk4_follow_different_paths() {
        let acceleration = Vector3::new(1.0, 0.0, 0.0);
        let (rk4_position, _) =
            rk4_integrate(Vector3::zeros(), Vector3::zeros(), acceleration, 1.0);
        let (euler_position, _) =
            euler_integrate(Vector3::zeros(), Vector3::zeros(), acceleration, 1.0);

        assert!((rk4_position.x - euler_position.x).abs() > 0.1);
    }

    #[test]
    fn same_sample_counter_does_not_reintegrate() {
        let mut estimator = ImuTrajectoryEstimator::new();
        let rotation = UnitQuaternion::identity();
        let accel = [1.0, 9.81, 0.0];

        let first = estimator.update(1, 12, Vector3::zeros(), 1, rotation, accel, false);
        let second = estimator.update(1, 12, Vector3::zeros(), 1, rotation, accel, false);

        assert_eq!(first.position, second.position);
        assert_eq!(first.velocity, second.velocity);
    }
}
