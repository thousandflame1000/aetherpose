pub mod i18n;
pub mod backpress;
pub mod ui_icons;
pub mod fusion;
pub mod ik;
pub mod imu;
pub mod net;
pub mod osc;
pub mod output;
pub mod skeleton;
pub mod recording;
pub mod app;
pub mod smoothing;
pub mod state;
pub mod theme;
pub mod connection_type;
pub mod ui;

pub use app::gui::AetherposeApp;
pub use app::config::AppConfig;
pub use app::render::{
    bone_name, camera_transform, configure_style, draw_magnetometer_points, draw_skeleton,
    format_matrix4, setup_custom_fonts, ui_battery_bar, CameraTransform, DrawCtx,
};
pub use app::types::{
    BackendCommand, CameraProjectionMode, GuiUpdate, QuestInputData, Tab, TrackerState,
    TrajectoryIntegrationMode, VrBridgePacket, VrPoseData,
};
pub use theme::*;
