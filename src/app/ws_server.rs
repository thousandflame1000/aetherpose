use crate::app::types::BackendCommand;
use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        State,
    },
    response::IntoResponse,
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

async fn ws_handler(
    ws: WebSocketUpgrade,
    State(state): State<Arc<ServerState>>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_socket(socket, state))
}

async fn handle_socket(socket: WebSocket, state: Arc<ServerState>) {
    let (mut sink, mut stream) = socket.split();
    let mut rx = state.broadcast_tx.subscribe();

    // Forward broadcast messages → WebSocket client.
    let send_task = tokio::spawn(async move {
        while let Ok(msg) = rx.recv().await {
            if sink.send(Message::Text(msg)).await.is_err() {
                break;
            }
        }
    });

    // Receive commands from WebSocket client → backend mpsc channel.
    let cmd_tx = Arc::clone(&state.cmd_tx);
    let recv_task = tokio::spawn(async move {
        while let Some(Ok(msg)) = stream.next().await {
            if let Message::Text(text) = msg {
                match serde_json::from_str::<BackendCommand>(&text) {
                    Ok(cmd) => {
                        if let Ok(tx) = cmd_tx.lock() {
                            let _ = tx.send(cmd);
                        }
                    }
                    Err(e) => log::warn!("Unrecognised command from client: {} — {:?}", text, e),
                }
            }
        }
    });

    // Stop both directions as soon as either side closes.
    tokio::select! {
        _ = send_task => {}
        _ = recv_task => {}
    }
}
