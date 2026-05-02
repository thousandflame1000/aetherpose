use crate::net::tracker::Tracker;
use std::time::Duration;

/// Calculates a confidence score for a tracker based on how recently it was seen.
/// Confidence ranges from 0.0 to 1.0.
///
/// # Arguments
/// * `tracker` - The tracker for which to calculate confidence.
/// * `max_unseen_duration_ms` - The maximum duration (in milliseconds) a tracker
///   can be unseen before its confidence drops to 0.
///
/// # Returns
/// A f32 representing the confidence (0.0 to 1.0).
pub fn calculate_confidence(tracker: &Tracker, max_unseen_duration_ms: u64) -> f32 {
    let elapsed = tracker.last_seen.elapsed();
    // Guard against zero max duration
    if max_unseen_duration_ms == 0 {
        return 0.0;
    }
    let max_duration = Duration::from_millis(max_unseen_duration_ms);

    if elapsed >= max_duration {
        0.0
    } else {
        // Linear decay, clamped to [0,1]
        let v = 1.0 - (elapsed.as_secs_f32() / max_duration.as_secs_f32());
        v.clamp(0.0, 1.0)
    }
}
