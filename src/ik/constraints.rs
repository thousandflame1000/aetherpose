use nalgebra::Vector3;

pub fn calculate_joint_limit_penalty(
    q_i: &Vector3<f32>,
    q_min: Option<&Vector3<f32>>,
    q_max: Option<&Vector3<f32>>,
) -> Vector3<f32> {
    let mut penalty = Vector3::zeros();

    for i in 0..3 {
        if let Some(min_val) = q_min.map(|v| v[i]) {
            if q_i[i] < min_val {
                penalty[i] = min_val - q_i[i];
            }
        }
        if let Some(max_val) = q_max.map(|v| v[i]) {
            if q_i[i] > max_val {
                penalty[i] = q_i[i] - max_val;
            }
        }
    }
    penalty
}
