use std::sync::atomic::{AtomicU64, Ordering};

pub struct BackpressStats {
    pub sent_success: AtomicU64,
    pub sent_fail_full: AtomicU64,
    pub sent_disconnected: AtomicU64,
    pub try_send_success_time_ns: AtomicU64,
    pub try_send_success_count: AtomicU64,
}

impl BackpressStats {
    pub fn new() -> Self {
        Self {
            sent_success: AtomicU64::new(0),
            sent_fail_full: AtomicU64::new(0),
            sent_disconnected: AtomicU64::new(0),
            try_send_success_time_ns: AtomicU64::new(0),
            try_send_success_count: AtomicU64::new(0),
        }
    }

    /// Snapshot counters and reset them to zero. Returns (success, full, disconnected, sum_ns, count)
    pub fn snapshot_and_reset(&self) -> (u64, u64, u64, u64, u64) {
        let s = self.sent_success.swap(0, Ordering::Relaxed);
        let f = self.sent_fail_full.swap(0, Ordering::Relaxed);
        let d = self.sent_disconnected.swap(0, Ordering::Relaxed);
        let sum_ns = self.try_send_success_time_ns.swap(0, Ordering::Relaxed);
        let cnt = self.try_send_success_count.swap(0, Ordering::Relaxed);
        (s, f, d, sum_ns, cnt)
    }
}

impl Default for BackpressStats {
    fn default() -> Self {
        Self::new()
    }
}
