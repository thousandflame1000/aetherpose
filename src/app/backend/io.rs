use super::*;
use crate::app::config::append_and_rotate_log;
use chrono::Local;
use log::warn;
use tokio::sync::mpsc::UnboundedReceiver;

impl BackendRuntime {
    pub(super) fn start_ble_manager(&self) {
        let ble_tx = self.serial_tx.clone();
        let ble_stats = self.bp_stats.clone();
        let (status_tx, status_rx) = tokio::sync::mpsc::unbounded_channel::<String>();

        Self::spawn_status_forwarder(
            self.tx.clone(),
            self.serial_running_flag.clone(),
            None,
            status_rx,
            "status_ble.log",
            "BLE",
        );

        let sync_quats_clone = self.sync_quats.clone();
        tokio::spawn(async move {
            crate::net::connection::run_ble_manager(ble_tx, ble_stats, Some(status_tx), sync_quats_clone).await;
        });
    }

    pub(super) fn start_serial_manager_from_config(&mut self) {
        self.stop_serial_manager();

        if !self.config.serial_enabled {
            let _ = self.tx.send(GuiUpdate::status(false, None));
            return;
        }

        let Some(port_name) = self.config.serial_port.clone() else {
            warn!("serial enabled but no serial port configured");
            let _ = self.tx.send(GuiUpdate::status(false, None));
            return;
        };

        let baud = self.config.serial_baud;
        let (stop_tx, stop_rx) = watch::channel(false);
        let (status_tx, status_rx) = tokio::sync::mpsc::unbounded_channel::<String>();
        let serial_tx = self.serial_tx.clone();
        let serial_stats = self.bp_stats.clone();

        self.serial_stop_tx = Some(stop_tx);
        self.serial_running_flag.store(true, Ordering::Relaxed);

        Self::spawn_status_forwarder(
            self.tx.clone(),
            self.serial_running_flag.clone(),
            Some(self.serial_status_shared.clone()),
            status_rx,
            "status_serial.log",
            "SERIAL",
        );

        tokio::spawn(async move {
            crate::net::connection::run_serial_manager(
                port_name,
                baud,
                serial_tx,
                serial_stats,
                stop_rx,
                Some(status_tx),
            )
            .await;
        });
    }

    fn stop_serial_manager(&mut self) {
        self.serial_running_flag.store(false, Ordering::Relaxed);

        if let Some(stop_tx) = self.serial_stop_tx.take() {
            let _ = stop_tx.send(true);
        }

        if let Ok(mut status) = self.serial_status_shared.lock() {
            *status = None;
        }
    }

    pub(super) fn spawn_backpressure_reporter(&self) {
        let stats_reporter = self.bp_stats.clone();
        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(Duration::from_secs(1));
            loop {
                ticker.tick().await;
                let (sent, dropped_full, disconnected, sum_ns, count) =
                    stats_reporter.snapshot_and_reset();
                let avg_ms = if count > 0 {
                    (sum_ns as f64) / (count as f64) / 1_000_000.0
                } else {
                    0.0
                };

                info!(
                    "Backpress stats (1s): sent={} dropped_full={} disconnected={} avg_try_send_ms={:.6}",
                    sent, dropped_full, disconnected, avg_ms
                );
            }
        });
    }

    fn spawn_status_forwarder(
        tx: mpsc::Sender<GuiUpdate>,
        serial_running_flag: Arc<AtomicBool>,
        status_shared: Option<Arc<Mutex<Option<String>>>>,
        mut status_rx: UnboundedReceiver<String>,
        log_path: &'static str,
        source_tag: &'static str,
    ) {
        tokio::spawn(async move {
            while let Some(msg) = status_rx.recv().await {
                if let Some(shared) = &status_shared {
                    if let Ok(mut lock) = shared.lock() {
                        *lock = Some(msg.clone());
                    }
                }

                let line = format!(
                    "{} [{}] {}\n",
                    Local::now().format("%Y-%m-%d %H:%M:%S"),
                    source_tag,
                    msg
                );
                append_and_rotate_log(log_path, &line);

                let _ = tx.send(GuiUpdate::status(
                    serial_running_flag.load(Ordering::Relaxed),
                    Some(msg),
                ));
            }
        });
    }
}
