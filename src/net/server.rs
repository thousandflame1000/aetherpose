#![allow(dead_code)]

use anyhow::Result;
use serde_json;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::net::UdpSocket;
use tokio::sync::Mutex;

use crate::net::packet::PacketData;
use crate::net::tracker::Tracker;

// 綁定 UDP Port 並返回 UdpSocket
pub async fn bind_udp_socket(port: u16) -> Result<UdpSocket> {
    let bind_addr = format!("0.0.0.0:{}", port);
    let socket = UdpSocket::bind(&bind_addr).await?;
    log::info!("[Init] UDP Server 啟動成功，正在監聽: {}", socket.local_addr()?);
    Ok(socket)
}

/// Starts the UDP server to listen for tracker data.
/// Parses incoming JSON packets into `PacketData` and updates the shared `trackers` map.
pub async fn start_udp_server(
    socket: UdpSocket,
    trackers: Arc<Mutex<HashMap<u8, Tracker>>>,
    port: u16,
) -> Result<()> {
    let mut buf = vec![0u8; 1500]; // Buffer for incoming data

    log::info!("UDP server started on port {}", port);

    // Spawn a periodic scanner to mark offline trackers and log metrics
    {
        let trackers_scanner = Arc::clone(&trackers);
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(Duration::from_secs(5));
            loop {
                interval.tick().await;
                let tmap = trackers_scanner.lock().await;
                let offline_after = Duration::from_millis(2000);
                for (id, tr) in tmap.iter() {
                    if !tr.is_online(offline_after) {
                        log::warn!("Tracker {} seems offline (last_seen {:?})", id, tr.last_seen);
                    }
                }
                // Emit aggregate metrics
                let total: usize = tmap.len();
                let total_recv: u64 = tmap.values().map(|t| t.received_packets).sum();
                log::debug!("Tracker metrics: count={}, total_received={} ", total, total_recv);
            }
        });
    }

    loop {
        let (len, addr) = socket.recv_from(&mut buf).await?;
        log::debug!("Received {} bytes from {}", len, addr);

        // Try parse JSON into PacketData
        match serde_json::from_slice::<PacketData>(&buf[..len]) {
            Ok(packet) => {
                let mut map = trackers.lock().await;
                let id = packet.id;
                let entry = map.entry(id).or_insert_with(|| Tracker::new(id));
                entry.update_data(&packet);
                log::trace!("Updated tracker {} (recv_count={})", id, entry.received_packets);
            }
            Err(e) => {
                log::warn!("Failed to parse packet from {}: {}", addr, e);
            }
        }
    }
}
