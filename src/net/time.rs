#![allow(dead_code)]

use std::time::{Duration, Instant};

/// Returns the current high-resolution instant.
pub fn now() -> Instant {
    Instant::now()
}

/// Calculates the duration between two instants.
pub fn duration_since(earlier: Instant, later: Instant) -> Duration {
    later.duration_since(earlier)
}
