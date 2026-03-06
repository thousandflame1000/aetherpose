use eframe::egui;

// Simple icon helper utilities. Use Unicode glyphs or custom font glyphs.
pub fn icon_button(ui: &mut egui::Ui, icon: &str, tooltip: &str) -> egui::Response {
    ui.add(egui::Button::new(icon).small()).on_hover_text(tooltip)
}

pub fn icon_button_disabled(ui: &mut egui::Ui, icon: &str, tooltip: &str) -> egui::Response {
    let mut b = egui::Button::new(icon).small();
    b = b.sense(egui::Sense::click());
    let resp = ui.add_enabled(false, b);
    resp.on_hover_text(tooltip)
}

// Common icon constants
pub const ICON_APPLY: &str = "⚙";
pub const ICON_PLAY: &str = "▶";
pub const ICON_STOP: &str = "■";
pub const ICON_CLEAR: &str = "🧹";
pub const ICON_EXPORT: &str = "⬇";
pub const ICON_IMPORT: &str = "⬆";
pub const ICON_TRUNCATE: &str = "🗑";
pub const ICON_RELOAD: &str = "🔁";
pub const ICON_GLOBE: &str = "🌐";
pub const ICON_CHECK: &str = "✔";
pub const ICON_CANCEL: &str = "✖";
