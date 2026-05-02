use crate::net::packet::PacketData;
use crate::connection_type::ConnectionType;
use crossbeam_channel::Sender;
use std::sync::Arc;
use std::time::Duration;
use tokio::time;
use crate::backpress::BackpressStats;
use tokio::sync::{watch, mpsc::UnboundedSender};

// Connection manager helpers (serial + BLE restart/backoff)

fn backoff_delay_ms(attempt: u32, base_ms: u64, max_ms: u64) -> u64 {
    let factor = 2u64.pow(std::cmp::min(attempt, 10));
    std::cmp::min(base_ms.saturating_mul(factor), max_ms)
}

pub async fn run_serial_manager(
    port_name: String,
    baud_rate: u32,
    tx: Sender<(PacketData, ConnectionType)>,
    stats: Arc<BackpressStats>,
    stop_rx: watch::Receiver<bool>,
    status_tx: Option<UnboundedSender<String>>,
) {
    let mut attempt: u32 = 0;
    loop {
        // check cancellation
        if *stop_rx.borrow() {
            log::info!("run_serial_manager: stop requested for {}", port_name);
            break;
        }

        match serialport::new(&port_name, baud_rate)
            .timeout(std::time::Duration::from_millis(500))
            .open()
        {
            Ok(mut port) => {
                log::info!("Serial {} opened at {}", port_name, baud_rate);
                if let Some(ref s) = status_tx {
                    let _ = s.send(format!("opened:{}", port_name));
                }
                attempt = 0;

                let tx_clone = tx.clone();
                let stats_clone = stats.clone();
                let port_name_clone = port_name.clone();
                let status_clone = status_tx.clone();

                let stop_rx_block = stop_rx.clone();
                let handle = tokio::task::spawn_blocking(move || {
                    let mut buf: Vec<u8> = vec![0u8; 1024];
                    loop {
                        if *stop_rx_block.borrow() {
                            log::info!("serial reader for {} received stop signal", port_name_clone);
                            break;
                        }
                        match port.read(buf.as_mut_slice()) {
                            Ok(read) if read > 0 => {
                                let data = &buf[..read];
                                if let Ok(s) = std::str::from_utf8(data) {
                                    // 嘗試逐行解析 JSON 封包
                                    for line in s.lines() {
                                        if line.trim().is_empty() { continue; }
                                        match serde_json::from_str::<PacketData>(line) {
                                            Ok(packet) => {
                                                let _ = tx_clone.send((packet, ConnectionType::Serial));
                                                stats_clone.sent_success.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                                            }
                                            Err(e) => {
                                                log::warn!("Failed to parse PacketData line from {}: {} -- line='{}'", port_name_clone, e, line);
                                                if let Some(ref s) = status_clone {
                                                    let _ = s.send(format!("parse_error:{}:{}", port_name_clone, e));
                                                }
                                            }
                                        }
                                    }
                                } else {
                                    // 非 UTF-8 資料
                                    log::warn!("Received non-UTF8 data from {} ({} bytes)", port_name_clone, read);
                                    if let Some(ref s) = status_clone {
                                        let _ = s.send(format!("non_utf8:{}:{} bytes", port_name_clone, read));
                                    }
                                }
                            }
                            Ok(_) => {}
                            Err(e) => {
                                log::error!("Serial read error on {}: {}", port_name_clone, e);
                                if let Some(ref s) = status_clone {
                                    let _ = s.send(format!("error:{}:{}", port_name_clone, e));
                                }
                                break;
                            }
                        }
                    }
                    log::info!("Serial reader for {} exiting read loop", port_name_clone);
                });

                let _ = handle.await;
                if let Some(ref s) = status_tx {
                    let _ = s.send(format!("disconnected:{}", port_name));
                }
                log::warn!("Serial {} disconnected, will attempt reconnect", port_name);
            }
            Err(e) => {
                log::error!("Failed to open serial {}: {}", port_name, e);
                if let Some(ref s) = status_tx {
                    let _ = s.send(format!("error:{}:{}", port_name, e));
                }
            }
        }
        // 通知 UI 我們會在稍後嘗試重連（不會過度發送）
        if let Some(ref s) = status_tx {
            let _ = s.send(format!("reconnect_scheduled:{}:{}", port_name, attempt));
        }

        attempt = attempt.saturating_add(1);
        let delay_ms = backoff_delay_ms(attempt, 500, 10_000);
        log::info!("Reconnecting serial {} after {} ms (attempt {})", port_name, delay_ms, attempt);
        time::sleep(Duration::from_millis(delay_ms)).await;
    }
}

pub async fn run_ble_manager(
    tx: Sender<(PacketData, ConnectionType)>,
    stats: Arc<BackpressStats>,
    status_tx: Option<tokio::sync::mpsc::UnboundedSender<String>>,
    sync_quats: crate::net::ble::SyncQuatMap,
) {
    let mut attempt: u32 = 0;
    loop {
        log::info!("Starting BLE client (attempt {})", attempt + 1);
        crate::net::ble::run_ble_client(tx.clone(), stats.clone(), status_tx.clone(), sync_quats.clone()).await;
        log::warn!("BLE client task ended, will restart");
        attempt = attempt.saturating_add(1);
        let delay_ms = backoff_delay_ms(attempt, 500, 10_000);
        log::info!("Restarting BLE client after {} ms (attempt {})", delay_ms, attempt);
        time::sleep(Duration::from_millis(delay_ms)).await;
    }
}
