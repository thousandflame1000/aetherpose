use crate::app::backend;
use crate::app::config::AppConfig;
use crate::app::types::{BackendCommand, GuiUpdate, WsServerMessage, WsSnapshot};
use crate::app::ws_server::{router, ServerState};
use crate::skeleton::model::SkeletonModel;
use log::error;
use std::sync::{mpsc, Arc, Mutex, RwLock};
use tokio::sync::broadcast;

pub async fn run() {
    init_logging();

    let config = AppConfig::load();
    let (gui_tx, gui_rx) = mpsc::channel::<GuiUpdate>();
    let (cmd_tx, cmd_rx) = mpsc::channel::<BackendCommand>();
    let shared_skel = Arc::new(RwLock::new(SkeletonModel::new_humanoid()));

    // Broadcast channel: serialised JSON strings → all WS clients.
    let (broadcast_tx, _) = broadcast::channel::<String>(64);

    // Bridge thread: receive GuiUpdate from backend and forward as JSON.
    let bc_tx = broadcast_tx.clone();
    std::thread::spawn(move || {
        for update in gui_rx {
            let msg = match update {
                GuiUpdate::Snapshot(snap) => {
                    let ws_snap = WsSnapshot::from_snapshot(snap);
                    WsServerMessage::Snapshot(ws_snap)
                }
                GuiUpdate::Status {
                    serial_running,
                    serial_status_msg,
                } => WsServerMessage::Status {
                    serial_running,
                    serial_status_msg,
                },
            };
            if let Ok(json) = serde_json::to_string(&msg) {
                // Ignore SendError when no clients are connected.
                let _ = bc_tx.send(json);
            }
        }
    });

    // Backend thread: owns its own Tokio runtime to avoid nesting runtimes.
    let skel_clone = shared_skel.clone();
    let config_clone = config.clone();
    std::thread::spawn(move || {
        let rt = match tokio::runtime::Runtime::new() {
            Ok(rt) => rt,
            Err(e) => {
                error!("Failed to create backend Tokio runtime: {}", e);
                return;
            }
        };
        rt.block_on(async move {
            backend::run(skel_clone, gui_tx, cmd_rx, config_clone).await;
        });
    });

    // WebSocket server runs on the main (axum) Tokio runtime.
    let state = Arc::new(ServerState {
        broadcast_tx,
        cmd_tx: Arc::new(Mutex::new(cmd_tx)),
    });

    let addr = "127.0.0.1:9009";
    let listener = match tokio::net::TcpListener::bind(addr).await {
        Ok(l) => l,
        Err(e) => {
            error!("Cannot bind WebSocket server on {}: {}", addr, e);
            return;
        }
    };

    log::info!(
        "Aetherpose backend running — WebSocket: ws://{}/ws",
        addr
    );

    axum::serve(listener, router(state)).await.unwrap();
}

fn init_logging() {
    if std::env::var("RUST_LOG").is_err() {
        std::env::set_var("RUST_LOG", "info");
    }
    env_logger::init();
}
