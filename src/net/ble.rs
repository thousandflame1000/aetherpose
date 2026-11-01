use btleplug::api::{Central, CentralEvent, Manager as _, Peripheral as _, ScanFilter, WriteType};
use btleplug::platform::Manager;
use futures::stream::StreamExt;
use log::{error, info};
use crossbeam_channel::Sender;
use tokio::sync::mpsc::UnboundedSender;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use std::sync::atomic::Ordering;
use crate::backpress::BackpressStats;
use tokio::time;
use uuid::Uuid;
use crate::net::protocol::{ImuDataPacket, encode_sync_quat};
use crate::net::packet::PacketData;
use crate::connection_type::ConnectionType;

// BLE UUIDs matching tracker firmware
const TRACKER_SERVICE_UUID:        Uuid = Uuid::from_u128(0x19B10000_E8F2_537E_4F6C_D104768A1214);
const TRACKER_CHARACTERISTIC_UUID: Uuid = Uuid::from_u128(0x19B10001_E8F2_537E_4F6C_D104768A1214);
/// Write characteristic: host → device, 16 bytes [x,y,z,w] EKF sync quaternion
const TRACKER_SYNC_UUID:           Uuid = Uuid::from_u128(0x19B10002_E8F2_537E_4F6C_D104768A1214);

/// The firmware notifies at ~100 Hz. On Windows a tracker that resets or loses
/// power often never ends its notification stream, which left it marked as
/// connected (and ignored by the scan loop) until the backend was restarted.
/// This much silence is treated as a disconnect so the scan loop reconnects it.
const NOTIFY_STALL_TIMEOUT: Duration = Duration::from_secs(3);
const BLE_OPERATION_TIMEOUT: Duration = Duration::from_secs(8);

/// Owns one attempt/subscription. Every failure, task cancellation and normal
/// disconnect must release its claim, including failures before spawning.
struct ConnectionClaim<K: Eq + std::hash::Hash> {
    seen: Arc<Mutex<std::collections::HashSet<K>>>,
    id: K,
}
impl<K: Eq + std::hash::Hash> Drop for ConnectionClaim<K> {
    fn drop(&mut self) {
        if let Ok(mut seen) = self.seen.lock() { seen.remove(&self.id); }
    }
}

#[cfg(test)]
mod reconnect_tests {
    use super::*;

    #[test]
    fn failed_attempt_releases_only_its_device() {
        let seen = Arc::new(Mutex::new([69u8, 31].into_iter().collect()));
        let attempt = || -> Result<(), ()> {
            let _claim = ConnectionClaim { seen: seen.clone(), id: 69 };
            Err(()) // service discovery/subscription failure
        };
        assert!(attempt().is_err());
        assert!(!seen.lock().unwrap().contains(&69));
        assert!(seen.lock().unwrap().contains(&31));
    }

    #[tokio::test]
    async fn cancelled_subscription_releases_device() {
        let seen = Arc::new(Mutex::new([69u8].into_iter().collect()));
        let claim = ConnectionClaim { seen: seen.clone(), id: 69 };
        let task = tokio::spawn(async move {
            let _claim = claim;
            std::future::pending::<()>().await;
        });
        tokio::task::yield_now().await;
        task.abort();
        let _ = task.await;
        assert!(seen.lock().unwrap().is_empty());
    }
}

/// Shared map: tracker_id → latest EKF quaternion [x,y,z,w] to sync back to device.
/// Written by ingest.rs when loss rate is low; read by BLE notification task.
pub type SyncQuatMap = Arc<Mutex<HashMap<u8, [f32; 4]>>>;

pub async fn run_ble_client(
    tx: Sender<(PacketData, ConnectionType)>,
    stats: Arc<BackpressStats>,
    status_tx: Option<UnboundedSender<String>>,
    sync_quats: SyncQuatMap,
) {
    // The page shows these; run_ble_manager restarts this client after a failure.
    let report = |msg: String| { let _ = status_tx.as_ref().map(|s| s.send(msg)); };
    let manager = match Manager::new().await {
        Ok(m) => m,
        Err(e) => { error!("BLE Manager 初始化失敗: {}", e); report(format!("ble_unavailable:{}", e)); return; }
    };
    let adapters = match manager.adapters().await {
        Ok(a) => a,
        Err(e) => { error!("無法取得 BLE Adapter: {}", e); report(format!("ble_unavailable:{}", e)); return; }
    };
    let adapter = match adapters.into_iter().next() {
        Some(a) => a,
        None => { error!("找不到藍牙適配器"); report("ble_unavailable:no Bluetooth adapter".into()); return; }
    };

    info!("開始 BLE 掃描...");
    if let Err(e) = adapter.start_scan(ScanFilter::default()).await {
        error!("啟動掃描失敗: {}", e); report(format!("ble_unavailable:{}", e)); return;
    }
    report("ble_scanning".into());

    let mut events = match adapter.events().await {
        Ok(e) => e,
        Err(e) => { error!("無法取得 BLE 事件串流: {}", e); return; }
    };

    // Track peripherals already connecting/connected to avoid duplicate attempts.
    // Shared (not just local) so the per-device notification task can clear its
    // own entry on disconnect — otherwise a tracker that drops mid-session is
    // permanently ignored by the scan loop and the whole app must be restarted
    // to reconnect it.
    let seen_ids: Arc<Mutex<std::collections::HashSet<btleplug::platform::PeripheralId>>> =
        Arc::new(Mutex::new(std::collections::HashSet::new()));

    let mut retry_tick = time::interval(Duration::from_secs(5));
    let mut retry_queue = std::collections::VecDeque::new();
    loop {
        let event = if let Some(id) = retry_queue.pop_front() {
            CentralEvent::DeviceUpdated(id)
        } else {
            tokio::select! {
                event = events.next() => match event { Some(event) => event, None => break },
                _ = retry_tick.tick() => {
                    // Windows need not emit another discovery after a failed
                    // attempt; revisit cached peripherals without an app restart.
                    if let Ok(Ok(peripherals)) = time::timeout(BLE_OPERATION_TIMEOUT, adapter.peripherals()).await {
                        retry_queue.extend(peripherals.into_iter().map(|p| p.id()));
                    }
                    continue;
                }
            }
        };
        let (id, ev_name) = match event {
            CentralEvent::DeviceDiscovered(id) => (id, "Discovered"),
            CentralEvent::DeviceUpdated(id)    => (id, "Updated"),
            _ => continue,
        };

        if seen_ids.lock().is_ok_and(|set| set.contains(&id)) { continue; }

        if let Ok(peripheral) = adapter.peripheral(&id).await {
                let properties = peripheral.properties().await.unwrap_or(None);
                let name = properties.as_ref()
                    .and_then(|p| p.local_name.clone())
                    .unwrap_or_else(|| "?".to_string());

                let is_target = properties.as_ref().is_some_and(|p| {
                    p.local_name.iter().any(|n| n.starts_with("Aetherpose Tracker"))
                        || p.services.contains(&TRACKER_SERVICE_UUID)
                });

                // Every nearby BLE device reports updates; only trackers are worth the info log.
                if !is_target {
                    log::debug!("[BLE] {} {:?} name={:?} (not a tracker)", ev_name, id, name);
                    continue;
                }
                info!("[BLE] {} {:?} name={:?}", ev_name, id, name);
                if let Ok(true) = peripheral.is_connected().await {
                    // No claim means no task owns this OS connection. Rebuild
                    // it instead of skipping an orphaned Windows GATT session.
                    let _ = time::timeout(BLE_OPERATION_TIMEOUT, peripheral.disconnect()).await;
                }

                if let Ok(mut set) = seen_ids.lock() { set.insert(id.clone()); }
                let claim = ConnectionClaim { seen: seen_ids.clone(), id: id.clone() };

                let rssi_str = properties.as_ref().and_then(|p| p.rssi)
                    .map(|r| r.to_string()).unwrap_or_else(|| "未知".to_string());
                let _ = status_tx.as_ref().map(|s| s.send(format!("ble_discovered:{}:{}dBm", id, rssi_str)));
                info!("發現追蹤器 (RSSI: {} dBm)，嘗試連線...", rssi_str);

                time::sleep(Duration::from_millis(200)).await;

                let mut connected = false;
                for i in 0..5 {
                    match time::timeout(BLE_OPERATION_TIMEOUT, peripheral.connect()).await {
                        Ok(Ok(_)) => {
                            connected = true;
                            let _ = adapter.stop_scan().await;
                            time::sleep(Duration::from_millis(500)).await;
                            break;
                        }
                        result => {
                            error!("連線失敗 (嘗試 {}/5): {:?}", i + 1, result);
                            let _ = status_tx.as_ref().map(|s| s.send(format!("ble_connect_error:{}:{:?}", id, result)));
                            time::sleep(Duration::from_millis(1000 + (i as u64 * 500))).await;
                        }
                    }
                }

                let filter = ScanFilter::default();
                if let Err(e) = adapter.start_scan(filter).await {
                    error!("重新啟動掃描失敗: {}", e);
                }

                if !connected {
                    if let Ok(mut set) = seen_ids.lock() { set.remove(&id); }
                    continue;
                }

                info!("連線成功，搜尋服務...");
                if !matches!(time::timeout(BLE_OPERATION_TIMEOUT, peripheral.discover_services()).await, Ok(Ok(()))) {
                    error!("搜尋服務失敗或逾時");
                    let _ = time::timeout(BLE_OPERATION_TIMEOUT, peripheral.disconnect()).await;
                    continue;
                }

                let chars = peripheral.characteristics();
                let data_char = chars.iter().find(|c| c.uuid == TRACKER_CHARACTERISTIC_UUID);
                let sync_char = chars.iter().find(|c| c.uuid == TRACKER_SYNC_UUID).cloned();

                if let Some(c) = data_char {
                    info!("訂閱數據特徵...");
                    if !matches!(time::timeout(BLE_OPERATION_TIMEOUT, peripheral.subscribe(c)).await, Ok(Ok(()))) {
                        error!("訂閱失敗或逾時");
                        let _ = status_tx.as_ref().map(|s| s.send(format!("ble_subscribe_error:{}:failed or timed out", id)));
                        let _ = time::timeout(BLE_OPERATION_TIMEOUT, peripheral.disconnect()).await;
                        continue;
                    }

                    let tx_clone           = tx.clone();
                    let stats_clone        = stats.clone();
                    let sync_quats_clone   = sync_quats.clone();
                    let sync_char_clone    = sync_char;
                    let p_clone            = peripheral.clone();
                    let status_tx_for_task = status_tx.clone();

                    let mut notification_stream = match time::timeout(BLE_OPERATION_TIMEOUT, peripheral.notifications()).await {
                        Ok(Ok(s)) => s,
                        result => {
                            error!("無法取得通知串流: {:?}", result.err());
                            let _ = time::timeout(BLE_OPERATION_TIMEOUT, peripheral.disconnect()).await;
                            continue;
                        }
                    };

                    info!("BLE 裝置訂閱成功，等待韌體 ID...");
                    let _ = status_tx.as_ref().map(|s| s.send(format!("ble_connected:{}", id)));

                    tokio::spawn(async move {
                        let _claim = claim;
                        let mut buf: Vec<u8> = Vec::with_capacity(512);
                        // Sync write throttle: send every 300ms when stable
                        let mut last_sync_sent = Instant::now();
                        const SYNC_INTERVAL: Duration = Duration::from_millis(300);

                        loop {
                            let data = match time::timeout(NOTIFY_STALL_TIMEOUT, notification_stream.next()).await {
                                Ok(Some(data)) => data,
                                Ok(None) => break,
                                Err(_) => {
                                    info!("BLE 裝置 {} 超過 {} 秒沒有資料，視為斷線",
                                          p_clone.address(), NOTIFY_STALL_TIMEOUT.as_secs());
                                    break;
                                }
                            };
                            buf.extend_from_slice(&data.value);

                            // Use a read cursor so we only drain buf once per
                            // notification instead of O(remaining) per packet.
                            let mut pos = 0usize;
                            loop {
                                let slice = &buf[pos..];
                                let before = pos;

                                // ── Framed path ──────────────────────────────
                                if slice.len() >= 3
                                    && slice[0] == crate::net::protocol::FRAME_MAGIC_LO
                                    && slice[1] == crate::net::protocol::FRAME_MAGIC_HI
                                {
                                    let plen  = slice[2] as usize;
                                    let total = 2 + 1 + plen + 2;
                                    if slice.len() < total { break; }

                                    if let Some(packet) = ImuDataPacket::from_bytes(&slice[0..total]) {
                                        let device_id = packet.id;
                                        let p_data = packet_to_data(&packet);
                                        send_packet(&tx_clone, &stats_clone, p_data);

                                        // ── Sync write-back ───────────────────
                                        if let Some(ref sync_c) = sync_char_clone {
                                            if last_sync_sent.elapsed() >= SYNC_INTERVAL {
                                                let sync_payload = sync_quats_clone
                                                    .lock()
                                                    .ok()
                                                    .and_then(|map| map.get(&device_id).copied())
                                                    .map(encode_sync_quat);
                                                if let Some(payload) = sync_payload {
                                                    let _ = time::timeout(BLE_OPERATION_TIMEOUT, p_clone.write(sync_c, &payload, WriteType::WithoutResponse)).await;
                                                    last_sync_sent = Instant::now();
                                                }
                                            }
                                        }
                                    }
                                    pos += total;
                                    continue;
                                }

                                // ── Legacy raw path ──────────────────────────
                                let raw_size = crate::net::protocol::RAW_PACKET_SIZE;
                                if slice.len() >= raw_size {
                                    if let Some(packet) = ImuDataPacket::from_bytes(&slice[0..raw_size]) {
                                        let p_data = packet_to_data(&packet);
                                        send_packet(&tx_clone, &stats_clone, p_data);
                                        pos += raw_size;
                                        continue;
                                    } else {
                                        pos += 1;
                                        continue;
                                    }
                                }

                                if pos == before { break; }
                            }
                            // Single drain per notification batch
                            if pos > 0 { buf.drain(0..pos); }
                        }

                        info!("BLE 裝置 {} 斷線", p_clone.address());
                        let _ = status_tx_for_task.as_ref().map(|s| {
                            s.send(format!("ble_disconnected:{}", p_clone.address()))
                        });
                        let _ = time::timeout(BLE_OPERATION_TIMEOUT, p_clone.disconnect()).await;

                        // _claim drops here and also on task cancellation.
                    });
                } else {
                    let _ = time::timeout(BLE_OPERATION_TIMEOUT, peripheral.disconnect()).await;
                }
        }
    }
}

// ── helpers ──────────────────────────────────────────────────────────────────

fn packet_to_data(packet: &ImuDataPacket) -> PacketData {
    PacketData {
        id:       packet.id,
        sequence: Some(packet.sequence),
        batt:     Some(packet.batt as f32),
        gyro:     Some(packet.gyro),
        accel:    Some(packet.accel),
        mag:      Some(packet.mag),
        dt:       Some(packet.dt),
        quat:     packet.quat,
    }
}

fn send_packet(
    tx: &Sender<(PacketData, ConnectionType)>,
    stats: &Arc<BackpressStats>,
    p_data: PacketData,
) {
    let start = Instant::now();
    match tx.try_send((p_data, ConnectionType::Ble)) {
        Ok(()) => {
            let elapsed = start.elapsed().as_nanos() as u64;
            stats.try_send_success_time_ns.fetch_add(elapsed, Ordering::Relaxed);
            stats.try_send_success_count.fetch_add(1, Ordering::Relaxed);
            stats.sent_success.fetch_add(1, Ordering::Relaxed);
        }
        Err(e) => {
            use crossbeam_channel::TrySendError;
            match e {
                TrySendError::Full(_) => {
                    stats.sent_fail_full.fetch_add(1, Ordering::Relaxed);
                    error!("主通道已滿，丟棄 BLE 封包");
                }
                TrySendError::Disconnected(_) => {
                    stats.sent_disconnected.fetch_add(1, Ordering::Relaxed);
                    error!("主通道已關閉");
                }
            }
        }
    }
}
