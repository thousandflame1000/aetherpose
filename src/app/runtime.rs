use crate::app::backend;
use crate::app::config::AppConfig;
use crate::app::gui::AetherposeApp;
use crate::app::render::{configure_style, setup_custom_fonts};
use crate::app::types::{BackendCommand, GuiUpdate};
use crate::skeleton::model::SkeletonModel;
use eframe::egui;
use log::error;
use std::sync::{mpsc, Arc, RwLock};

pub fn run() -> eframe::Result<()> {
    init_logging();

    let config = AppConfig::load();
    let (tx, rx) = mpsc::channel::<GuiUpdate>();
    let (cmd_tx, cmd_rx) = mpsc::channel::<BackendCommand>();
    let shared_skel = Arc::new(RwLock::new(SkeletonModel::new_humanoid()));

    spawn_backend_thread(shared_skel.clone(), tx, cmd_rx, config.clone());
    run_gui(config, shared_skel, rx, cmd_tx)
}

fn init_logging() {
    if std::env::var("RUST_LOG").is_err() {
        std::env::set_var("RUST_LOG", "info");
    }
    env_logger::init();
}

fn spawn_backend_thread(
    shared_skel: Arc<RwLock<SkeletonModel>>,
    tx: mpsc::Sender<GuiUpdate>,
    cmd_rx: mpsc::Receiver<BackendCommand>,
    config: AppConfig,
) {
    std::thread::spawn(move || {
        let runtime = match tokio::runtime::Runtime::new() {
            Ok(runtime) => runtime,
            Err(e) => {
                error!("Failed to create Tokio runtime: {}", e);
                return;
            }
        };

        runtime.block_on(async move {
            backend::run(shared_skel, tx, cmd_rx, config).await;
        });
    });
}

fn run_gui(
    config: AppConfig,
    shared_skel: Arc<RwLock<SkeletonModel>>,
    rx: mpsc::Receiver<GuiUpdate>,
    cmd_tx: mpsc::Sender<BackendCommand>,
) -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_inner_size([1280.0, 720.0]),
        ..Default::default()
    };

    eframe::run_native(
        "Aetherpose Control Panel",
        options,
        Box::new(|cc| {
            setup_custom_fonts(&cc.egui_ctx);
            let theme = if let Some(def) = &config.theme_custom {
                crate::theme::Theme::from_def(def)
            } else {
                crate::theme::Theme::from_variant(config.theme_variant)
            };
            configure_style(&cc.egui_ctx, &theme);

            Ok(Box::new(AetherposeApp::new(
                rx,
                cmd_tx,
                config,
                shared_skel,
            )))
        }),
    )
}
