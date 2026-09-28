use anyhow::Result;
use tokio::net::UdpSocket;

pub async fn bind_udp_socket(port: u16) -> Result<UdpSocket> {
    let bind_addr = format!("0.0.0.0:{}", port);
    let socket = UdpSocket::bind(&bind_addr).await?;
    log::info!("UDP socket bound at {}", socket.local_addr()?);
    Ok(socket)
}
