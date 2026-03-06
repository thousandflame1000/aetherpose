use btleplug::api::{Central, CentralEvent, Manager as _, Peripheral as _, ScanFilter};
use btleplug::platform::Manager;
use futures::stream::StreamExt;
use log::{error, info};
use crossbeam_channel::Sender;
use tokio::sync::mpsc::UnboundedSender;
use std::time::{Duration, Instant};
use std::sync::Arc;
use std::sync::atomic::Ordering;
use crate::backpress::BackpressStats;
use tokio::time;
use uuid::Uuid;
use crate::net::protocol::FullDataPacket;
use crate::net::packet::PacketData;
use crate::connection_type::ConnectionType;

// 定義在 tracker.ino 中設定的 UUID
const TRACKER_SERVICE_UUID: Uuid = Uuid::from_u128(0x19B10000_E8F2_537E_4F6C_D104768A1214);
const TRACKER_CHARACTERISTIC_UUID: Uuid = Uuid::from_u128(0x19B10001_E8F2_537E_4F6C_D104768A1214);

/// 啟動 BLE 客戶端任務
/// 這是一個非同步函式，應該在 Tokio Runtime 中被 spawn
pub async fn run_ble_client(tx: Sender<(PacketData, ConnectionType)>, stats: Arc<BackpressStats>, status_tx: Option<UnboundedSender<String>>) {
    let manager = match Manager::new().await {
        Ok(m) => m,
        Err(e) => {
            error!("BLE Manager 初始化失敗: {}", e);
            return;
        }
    };

    let adapters = match manager.adapters().await {
        Ok(a) => a,
        Err(e) => {
            error!("無法取得 BLE Adapter: {}", e);
            return;
        }
    };

    let adapter = match adapters.into_iter().next() {
        Some(a) => a,
        None => {
            error!("找不到藍牙適配器");
            return;
        }
    };

    info!("開始 BLE 掃描...");
    // [修改] 移除過濾器，掃描所有裝置 (ScanFilter::default())。
    // 這能解決 Windows 上因緩存或廣播封包截斷，導致找不到服務 UUID 而無法建立有效連線的問題。
    let filter = ScanFilter::default();
    if let Err(e) = adapter.start_scan(filter).await {
        error!("啟動掃描失敗: {}", e);
        return;
    }

    // [修改] 使用事件驅動模型取代輪詢，以更即時、穩定地處理裝置發現與連線
    let mut events = match adapter.events().await {
        Ok(e) => e,
        Err(e) => {
            error!("無法取得 BLE 事件串流: {}", e);
            return;
        }
    };

    while let Some(event) = events.next().await {
        match event {
            CentralEvent::DeviceDiscovered(id) => {
                // 發現新裝置，取得其 peripheral 物件
                if let Ok(peripheral) = adapter.peripheral(&id).await {
                    let properties = peripheral.properties().await.unwrap_or(None);

                    // 檢查是否為我們的追蹤器 (透過名稱或 Service UUID)
                    let is_target = properties
                        .as_ref()
                        .is_some_and(|p| {
                            // [修改] 配合 Arduino 端縮短的名稱 "Aether"
                            p.local_name.iter().any(|n| n.contains("Aether"))
                                || p.services.contains(&TRACKER_SERVICE_UUID)
                        });

                    if is_target {
                        // 檢查是否已連線，若已連線則跳過
                        if let Ok(true) = peripheral.is_connected().await {
                            continue;
                        }

                        // [還原] 不要在連線前停止掃描，這會導致 Windows 上的 Peripheral Handle 失效
                        // 我們改在連線成功後再停止掃描

                        // 顯示訊號強度，確認裝置是否在範圍內
                        let rssi_str = properties
                            .as_ref()
                            .and_then(|p| p.rssi)
                            .map(|r| r.to_string())
                            .unwrap_or_else(|| "未知".to_string());
                        let _ = status_tx.as_ref().map(|s| s.send(format!("ble_discovered:{}:{}dBm", id.to_string(), rssi_str)));
                        info!("發現追蹤器 (RSSI: {} dBm)，嘗試連線...", rssi_str);

                        // [新增] 在嘗試連線前稍作等待，讓 Windows 內部狀態穩定，避免 "Not connected" 錯誤
                        time::sleep(Duration::from_millis(200)).await;

                        let mut connected = false;

                        // [移除] 不要強制斷開，這會導致 Windows 剛建立的連線被切斷
                        // let _ = peripheral.disconnect().await;

                        // 調整重試機制：增加次數至 5 次，並使用遞增等待時間
                        for i in 0..5 {
                            match peripheral.connect().await {
                                Ok(_) => {
                                    connected = true;
                                    // [新增] 連線成功後停止掃描，節省頻寬並穩定連線
                                    let _ = adapter.stop_scan().await;
                                    time::sleep(Duration::from_millis(500)).await; // 連線後稍作等待，讓狀態穩定
                                    let _ = status_tx.as_ref().map(|s| s.send(format!("ble_connected:{}", id.to_string())));
                                    break;
                                }
                                Err(e) => {
                                    error!("連線失敗 (嘗試 {}/5): {}", i + 1, e);
                                    let _ = status_tx.as_ref().map(|s| s.send(format!("ble_connect_error:{}:{}", id.to_string(), e)));
                                    // [移除] 失敗時也不要過度積極斷線，以免干擾重試
                                    // let _ = peripheral.disconnect().await;
                                    // 遞增等待時間: 1s, 1.5s, 2s, 2.5s, 3s
                                    time::sleep(Duration::from_millis(1000 + (i as u64 * 500)))
                                        .await;
                                }
                            }
                        }

                        // 無論連線成功與否，都重新啟動掃描以發現其他裝置
                        // [修改] 同樣使用無過濾器的掃描
                        let filter = ScanFilter::default();
                        if let Err(e) = adapter.start_scan(filter).await {
                            error!("重新啟動掃描失敗: {}", e);
                        }

                        if !connected {
                            continue;
                        }

                        info!("連線成功，搜尋服務...");
                        if let Err(e) = peripheral.discover_services().await {
                            error!("搜尋服務失敗: {}", e);
                            let _ = peripheral.disconnect().await;
                            continue;
                        }

                        let chars = peripheral.characteristics();
                        let data_char =
                            chars.iter().find(|c| c.uuid == TRACKER_CHARACTERISTIC_UUID);

                        if let Some(c) = data_char {
                            info!("訂閱數據特徵...");
                            if let Err(e) = peripheral.subscribe(c).await {
                                error!("訂閱失敗: {}", e);
                                let _ = status_tx.as_ref().map(|s| s.send(format!("ble_subscribe_error:{}:{}", id.to_string(), e)));
                                let _ = peripheral.disconnect().await;
                                continue;
                            }

                            let tx_clone = tx.clone();
                            let stats_clone = stats.clone();
                            let mut notification_stream = match peripheral.notifications().await {
                                Ok(s) => s,
                                Err(e) => {
                                    error!("無法取得通知串流: {}", e);
                                    let _ = peripheral.disconnect().await;
                                    continue;
                                }
                            };

                            let p_clone = peripheral.clone();
                            let status_tx_for_task = status_tx.clone();

                            // 啟動一個獨立的非同步任務來處理這個裝置的數據流
                            tokio::spawn(async move {
                                // 每個裝置維護獨立的緩衝區以重組 MTU 分片，預先配置容量以減少 reallocation
                                let mut buf: Vec<u8> = Vec::with_capacity(1024);

                                while let Some(data) = notification_stream.next().await {
                                    info!("收到 BLE 數據，長度: {} bytes", data.value.len());

                                    // 附加到緩衝區
                                    buf.extend_from_slice(&data.value);

                                    // 嘗試從緩衝區解析可能的封包（支援 framed 與 legacy raw）
                                    loop {
                                        // 儲存當前緩衝長度，若解析沒有進展就跳出
                                        let before_len = buf.len();

                                        // 1) 如果緩衝以 framed magic 開頭，且長度足夠則解析整個 frame
                                        if buf.len() >= 3
                                            && buf[0] == crate::net::protocol::FRAME_MAGIC_LO
                                            && buf[1] == crate::net::protocol::FRAME_MAGIC_HI
                                        {
                                            let plen = buf[2] as usize;
                                            let total = 2 + 1 + plen + 2; // magic(2)+len(1)+payload+crc(2)
                                            if buf.len() < total {
                                                // 尚未收到完整 frame，等待更多分片
                                            } else {
                                                // 直接從緩衝切片解析，避免額外分配
                                                if let Some(packet) = FullDataPacket::from_bytes(&buf[0..total]) {
                                                    info!(
                                                        "解析成功 (framed): ID={}, Batt={}",
                                                        packet.id, packet.batt
                                                    );
                                                    let p_data = PacketData {
                                                        id: packet.id,
                                                        sequence: Some(packet.sequence),
                                                        batt: Some(packet.batt as f32),
                                                        quat: Some(packet.quat),
                                                        accel: Some(packet.accel),
                                                        mag: Some(packet.mag),
                                                    };
                                                    let start = Instant::now();
                                                    match tx_clone.try_send((p_data, ConnectionType::Ble)) {
                                                        Ok(()) => {
                                                            let elapsed = start.elapsed().as_nanos() as u64;
                                                            stats_clone.try_send_success_time_ns.fetch_add(elapsed, Ordering::Relaxed);
                                                            stats_clone.try_send_success_count.fetch_add(1, Ordering::Relaxed);
                                                            stats_clone.sent_success.fetch_add(1, Ordering::Relaxed);
                                                        }
                                                        Err(e) => {
                                                            use crossbeam_channel::TrySendError;
                                                            match e {
                                                                TrySendError::Full(_v) => {
                                                                    stats_clone.sent_fail_full.fetch_add(1, Ordering::Relaxed);
                                                                    error!("主通道已滿，丟棄 BLE 封包");
                                                                }
                                                                TrySendError::Disconnected(_) => {
                                                                    stats_clone.sent_disconnected.fetch_add(1, Ordering::Relaxed);
                                                                    error!("主通道已關閉，停止接收 BLE 數據");
                                                                    break;
                                                                }
                                                            }
                                                        }
                                                    }
                                                } else {
                                                    error!("framed 封包 CRC/格式錯誤，丟棄此 frame");
                                                }
                                                // 移除已處理的 bytes
                                                let _ = buf.drain(0..total);
                                                // 解析成功或失敗都繼續嘗試解析後面的資料
                                                continue;
                                            }
                                        }

                                        // 2) 嘗試 legacy raw：如果緩衝長度 >= Raw size，取出一個 candidate
                                                                let raw_size = crate::net::protocol::RAW_PACKET_SIZE;
                                                                if buf.len() >= raw_size {
                                                                    // 直接嘗試解析緩衝前方的 slice，避免分配
                                                                    if let Some(packet) = FullDataPacket::from_bytes(&buf[0..raw_size]) {
                                                                        info!(
                                                                            "解析成功 (legacy): ID={}, Batt={}",
                                                                            packet.id, packet.batt
                                                                        );
                                                                        let p_data = PacketData {
                                                                            id: packet.id,
                                                                            sequence: Some(packet.sequence),
                                                                            batt: Some(packet.batt as f32),
                                                                            quat: Some(packet.quat),
                                                                            accel: Some(packet.accel),
                                                                            mag: Some(packet.mag),
                                                                        };
                                                                        let start = Instant::now();
                                                                        match tx_clone.try_send((p_data, ConnectionType::Ble)) {
                                                                            Ok(()) => {
                                                                                let elapsed = start.elapsed().as_nanos() as u64;
                                                                                stats_clone.try_send_success_time_ns.fetch_add(elapsed, Ordering::Relaxed);
                                                                                stats_clone.try_send_success_count.fetch_add(1, Ordering::Relaxed);
                                                                                stats_clone.sent_success.fetch_add(1, Ordering::Relaxed);
                                                                            }
                                                                            Err(e) => {
                                                                                use crossbeam_channel::TrySendError;
                                                                                match e {
                                                                                    TrySendError::Full(_v) => {
                                                                                        stats_clone.sent_fail_full.fetch_add(1, Ordering::Relaxed);
                                                                                        error!("主通道已滿，丟棄 BLE 封包");
                                                                                    }
                                                                                    TrySendError::Disconnected(_) => {
                                                                                        stats_clone.sent_disconnected.fetch_add(1, Ordering::Relaxed);
                                                                                        error!("主通道已關閉，停止接收 BLE 數據");
                                                                                        break;
                                                                                    }
                                                                                }
                                                                            }
                                                                        }
                                                                        let _ = buf.drain(0..raw_size);
                                                                        continue; // 嘗試解析接下來的資料
                                                                    } else {
                                                                        // 解析失敗：丟棄第一個位元以避免無限迴圈
                                                                        let _ = buf.drain(0..1);
                                                                        continue;
                                                                    }
                                                                }

                                        // 若無法再解析（需要更多資料）或解析未推進，跳出解析迴圈
                                        if buf.len() == before_len {
                                            break;
                                        }
                                    }
                                }
                                info!("BLE 裝置 {} 斷線", p_clone.address());
                                let _ = status_tx_for_task.as_ref().map(|s| s.send(format!("ble_disconnected:{}", p_clone.address())));
                                let _ = p_clone.disconnect().await;
                            });
                        }
                    }
                }
            }
            _ => {} // 忽略其他事件，如 DeviceConnected, DeviceDisconnected 等
        }
    }
}
