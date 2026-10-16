use crate::app::types::BackendCommand;
use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        State,
    },
    http::{header, HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::get,
    Router,
};
use futures::sink::SinkExt;
use futures::stream::StreamExt;
use std::sync::{Arc, Mutex};
use tokio::sync::broadcast;

pub struct ServerState {
    /// Broadcast channel carrying JSON-encoded `WsServerMessage` strings.
    pub broadcast_tx: broadcast::Sender<String>,
    /// Forwarded to the backend task; wrapped in Arc+Mutex so the async
    /// receive-handler can clone it without needing async access.
    pub cmd_tx: Arc<Mutex<std::sync::mpsc::Sender<BackendCommand>>>,
}

pub fn router(state: Arc<ServerState>) -> Router {
    Router::new()
        .route("/ws", get(ws_handler))
        .with_state(state)
}

/// Browsers let any web page open a WebSocket to localhost, so a site the user visits could
/// otherwise send commands (e.g. point OSC output at another machine). Only pages served from
/// this machine may connect; clients without an Origin header are local programs
/// (mesh_bridge, tools, tests), not web pages.
pub fn origin_allowed(origin: Option<&str>) -> bool {
    let Some(origin) = origin else { return true };
    let Some(authority) = origin.strip_prefix("http://") else { return false };
    let host = match authority.rsplit_once(':') {
        Some((host, port)) if !port.is_empty() && port.bytes().all(|b| b.is_ascii_digit()) => host,
        _ => authority,
    };
    matches!(host, "127.0.0.1" | "localhost" | "[::1]")
}

async fn ws_handler(
    ws: WebSocketUpgrade,
    headers: HeaderMap,
    State(state): State<Arc<ServerState>>,
) -> Response {
    // An Origin header that is not valid text counts as a foreign origin.
    let origin = headers.get(header::ORIGIN).map(|value| value.to_str().unwrap_or("?"));
    if !origin_allowed(origin) {
        log::warn!("Refused a WebSocket connection from origin {:?}", origin);
        return StatusCode::FORBIDDEN.into_response();
    }
    ws.on_upgrade(move |socket| handle_socket(socket, state))
}

async fn handle_socket(socket: WebSocket, state: Arc<ServerState>) {
    let (mut sink, mut stream) = socket.split();
    let mut rx = state.broadcast_tx.subscribe();
    // Request freshly aged state after subscribing, even when trackers are idle.
    if let Ok(tx) = state.cmd_tx.lock() {
        let _ = tx.send(BackendCommand::RequestSnapshot);
    }

    // Forward broadcast messages → WebSocket client.
    let mut send_task = tokio::spawn(async move {
        loop {
            let msg = match rx.recv().await {
                Ok(msg) => msg,
                Err(broadcast::error::RecvError::Lagged(_)) => continue,
                Err(broadcast::error::RecvError::Closed) => break,
            };
            if sink.send(Message::Text(msg)).await.is_err() {
                break;
            }
        }
    });

    // Receive commands from WebSocket client → backend mpsc channel.
    let cmd_tx = Arc::clone(&state.cmd_tx);
    let mut recv_task = tokio::spawn(async move {
        while let Some(Ok(msg)) = stream.next().await {
            if let Message::Text(text) = msg {
                match serde_json::from_str::<BackendCommand>(&text) {
                    Ok(cmd) => {
                        if let Ok(tx) = cmd_tx.lock() {
                            let _ = tx.send(cmd);
                        }
                    }
                    Err(e) => {
                        // Any local program can send this: keep one bad message from flooding the log.
                        let shown: String = text.chars().take(200).collect();
                        let more = if text.chars().nth(200).is_some() { "…" } else { "" };
                        log::warn!("Unrecognised command from client: {}{} — {}", shown, more, e);
                    }
                }
            }
        }
    });

    // Stop both directions once either side closes. When sending fails first (the client has
    // gone), the receive side still forwards the commands that arrived before the close: aborting
    // it at once dropped e.g. the last commands a client sent just before disconnecting.
    tokio::select! {
        _ = &mut send_task => {
            if tokio::time::timeout(std::time::Duration::from_secs(2), &mut recv_task).await.is_err() {
                recv_task.abort();
                let _ = recv_task.await;
            }
        }
        _ = &mut recv_task => { send_task.abort(); let _ = send_task.await; }
    }
}
