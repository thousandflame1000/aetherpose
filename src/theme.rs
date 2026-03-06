#![allow(dead_code)]

use eframe::epaint::Color32;
use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::Write;
use std::path::Path;
use std::error::Error;

// Centralized UI theme tokens (public for use across the crate)
// Modernized palette (soft dark slate + accent)
pub const UI_BTN_PRIMARY: Color32 = Color32::from_rgb(64, 160, 255); // bright blue
pub const UI_BTN_SECONDARY: Color32 = Color32::from_rgb(120, 120, 140); // muted
pub const UI_BTN_DANGER: Color32 = Color32::from_rgb(220, 90, 90);

pub const UI_WINDOW_FILL: Color32 = Color32::from_rgb(18, 24, 33); // dark slate
pub const UI_PANEL_FILL: Color32 = Color32::from_rgb(24, 30, 40);
pub const UI_CANVAS_FILL: Color32 = Color32::from_rgb(14, 18, 24);
pub const UI_ACCENT: Color32 = Color32::from_rgb(64, 160, 255);
pub const UI_GRID: Color32 = Color32::from_rgb(48, 56, 72);
pub const UI_DIR: Color32 = Color32::from_rgb(100, 120, 200);
pub const UI_TRACKER: Color32 = Color32::from_rgb(160, 120, 255);
pub const UI_LEFT_LIMB: Color32 = Color32::from_rgb(0, 200, 200);
pub const UI_RIGHT_LIMB: Color32 = Color32::from_rgb(255, 175, 90);
pub const UI_MAG_COLOR: Color32 = Color32::from_rgb(80, 220, 140);
pub const UI_SELECTION: Color32 = Color32::from_rgb(90, 160, 255);
pub const UI_BATT_HIGH: Color32 = Color32::from_rgb(90, 200, 100);
pub const UI_BATT_MED: Color32 = Color32::from_rgb(200, 160, 70);
pub const UI_BATT_LOW: Color32 = Color32::from_rgb(200, 80, 80);

// Widget background tokens
pub const UI_WIDGET_INACTIVE: Color32 = Color32::from_rgb(40, 44, 52);
pub const UI_WIDGET_HOVER: Color32 = Color32::from_rgb(50, 55, 65);
pub const UI_WIDGET_ACTIVE: Color32 = Color32::from_rgb(60, 65, 75);

// Status and misc tokens
pub const UI_STATUS_ACTIVE: Color32 = Color32::GREEN;
pub const UI_STATUS_TIMEOUT: Color32 = Color32::RED;
pub const UI_STATUS_STATIONARY: Color32 = Color32::YELLOW;
pub const UI_STATUS_MOVING: Color32 = Color32::GRAY;
pub const UI_STATUS_ERROR: Color32 = Color32::RED;

pub const UI_LOSS_HIGH: Color32 = Color32::RED;
pub const UI_LOSS_MED: Color32 = Color32::YELLOW;
pub const UI_LOSS_LOW: Color32 = Color32::GRAY;

pub const UI_HINT_TEXT: Color32 = Color32::from_gray(150);
pub const UI_STROKE_GRAY: Color32 = Color32::from_gray(60);
pub const UI_BATT_BG: Color32 = Color32::from_gray(50);

// Layout / metric tokens
pub const GAP_XS: f32 = 8.0;
pub const GAP_SM: f32 = 10.0;
pub const GAP_MD: f32 = 12.0;
pub const ICON_SIZE: f32 = 16.0;
pub const BTN_W: f32 = 120.0;
pub const BTN_H: f32 = 32.0;
pub const BATTERY_W: f32 = 72.0;
pub const BATTERY_H: f32 = 20.0;

// button padding (separate floats since egui::Vec2 isn't const-constructible here)
pub const BTN_PAD_X: f32 = 12.0;
pub const BTN_PAD_Y: f32 = 8.0;

// common geometry tokens
pub const CORNER_ROUND_MD: f32 = 8.0;
pub const STROKE_W: f32 = 1.25;
pub const UI_MAG_POINT: Color32 = Color32::YELLOW;

// Axes
pub const UI_AXIS_X: Color32 = Color32::RED;
pub const UI_AXIS_Y: Color32 = Color32::GREEN;
pub const UI_AXIS_Z: Color32 = Color32::BLUE;

// Foreground / border token
pub const UI_FOREGROUND: Color32 = Color32::WHITE;
pub const UI_BORDER: Color32 = Color32::WHITE;
// Re-export keys for convenience (optional)
// (Previously had recorder i18n constants here; removed to avoid unused symbol warnings)

// Keep this file focused on visual tokens only.

// Theme variant abstraction -------------------------------------------------
#[derive(Serialize, Deserialize, Clone, Copy, PartialEq, Eq, Debug)]
#[serde(rename_all = "lowercase")]
pub enum ThemeVariant {
	Dark,
	Light,
	Solarized,
}

pub struct Theme {
	pub btn_primary: Color32,
	pub btn_secondary: Color32,
	pub btn_danger: Color32,

	pub window_fill: Color32,
	pub panel_fill: Color32,
	pub canvas_fill: Color32,
	pub accent: Color32,
	pub grid: Color32,
	pub dir: Color32,
	pub tracker: Color32,
	pub left_limb: Color32,
	pub right_limb: Color32,
	pub mag_color: Color32,
	pub selection: Color32,
	pub batt_high: Color32,
	pub batt_med: Color32,
	pub batt_low: Color32,

	pub widget_inactive: Color32,
	pub widget_hover: Color32,
	pub widget_active: Color32,

	pub status_active: Color32,
	pub status_timeout: Color32,
	pub status_stationary: Color32,
	pub status_moving: Color32,
	pub status_error: Color32,

	pub loss_high: Color32,
	pub loss_med: Color32,
	pub loss_low: Color32,

	pub hint_text: Color32,
	pub stroke_gray: Color32,
	pub batt_bg: Color32,
	pub mag_point: Color32,

	pub axis_x: Color32,
	pub axis_y: Color32,
	pub axis_z: Color32,

	pub foreground: Color32,
	pub border: Color32,
}

impl Theme {
	pub fn dark() -> Self {
		Self {
			btn_primary: UI_BTN_PRIMARY,
			btn_secondary: UI_BTN_SECONDARY,
			btn_danger: UI_BTN_DANGER,
			window_fill: UI_WINDOW_FILL,
			panel_fill: UI_PANEL_FILL,
			canvas_fill: UI_CANVAS_FILL,
			accent: UI_ACCENT,
			grid: UI_GRID,
			dir: UI_DIR,
			tracker: UI_TRACKER,
			left_limb: UI_LEFT_LIMB,
			right_limb: UI_RIGHT_LIMB,
			mag_color: UI_MAG_COLOR,
			selection: UI_SELECTION,
			batt_high: UI_BATT_HIGH,
			batt_med: UI_BATT_MED,
			batt_low: UI_BATT_LOW,
			widget_inactive: UI_WIDGET_INACTIVE,
			widget_hover: UI_WIDGET_HOVER,
			widget_active: UI_WIDGET_ACTIVE,
			status_active: UI_STATUS_ACTIVE,
			status_timeout: UI_STATUS_TIMEOUT,
			status_stationary: UI_STATUS_STATIONARY,
			status_moving: UI_STATUS_MOVING,
			status_error: UI_STATUS_ERROR,
			loss_high: UI_LOSS_HIGH,
			loss_med: UI_LOSS_MED,
			loss_low: UI_LOSS_LOW,
			hint_text: UI_HINT_TEXT,
			stroke_gray: UI_STROKE_GRAY,
			batt_bg: UI_BATT_BG,
			mag_point: UI_MAG_POINT,
			axis_x: UI_AXIS_X,
			axis_y: UI_AXIS_Y,
			axis_z: UI_AXIS_Z,
			foreground: UI_FOREGROUND,
			border: UI_BORDER,
		}
	}

	pub fn light() -> Self {
		// Simple light-theme variants (tuned for contrast)
		Self {
			btn_primary: Color32::from_rgb(20, 110, 60),
			btn_secondary: Color32::from_rgb(40, 90, 150),
			btn_danger: Color32::from_rgb(160, 50, 50),
			window_fill: Color32::from_rgb(245, 245, 247),
			panel_fill: Color32::from_rgb(250, 250, 252),
			canvas_fill: Color32::from_rgb(238, 238, 240),
			accent: Color32::from_rgb(10, 120, 200),
			grid: Color32::from_rgb(200, 200, 200),
			dir: Color32::from_rgb(80, 80, 200),
			tracker: Color32::from_rgb(140, 80, 255),
			left_limb: Color32::from_rgb(0, 140, 140),
			right_limb: Color32::from_rgb(220, 120, 30),
			mag_color: Color32::from_rgb(20, 160, 20),
			selection: Color32::from_rgb(0, 90, 180),
			batt_high: Color32::from_rgb(60, 160, 60),
			batt_med: Color32::from_rgb(200, 160, 40),
			batt_low: Color32::from_rgb(200, 60, 60),
			widget_inactive: Color32::from_rgb(240, 240, 242),
			widget_hover: Color32::from_rgb(230, 230, 232),
			widget_active: Color32::from_rgb(220, 220, 224),
			status_active: Color32::GREEN,
			status_timeout: Color32::RED,
			status_stationary: Color32::YELLOW,
			status_moving: Color32::GRAY,
			status_error: Color32::RED,
			loss_high: Color32::RED,
			loss_med: Color32::YELLOW,
			loss_low: Color32::GRAY,
			hint_text: Color32::from_gray(90),
			stroke_gray: Color32::from_gray(160),
			batt_bg: Color32::from_gray(220),
			mag_point: Color32::YELLOW,
			axis_x: Color32::RED,
			axis_y: Color32::GREEN,
			axis_z: Color32::BLUE,
			foreground: Color32::BLACK,
			border: Color32::from_gray(160),
		}
	}

	pub fn from_variant(v: ThemeVariant) -> Self {
		match v {
			ThemeVariant::Dark => Self::dark(),
			ThemeVariant::Light => Self::light(),
			ThemeVariant::Solarized => Self::solarized(),
		}
	}

	pub fn solarized() -> Self {
		// A soft Solarized-like palette for comparison
		Self {
			btn_primary: Color32::from_rgb(38, 139, 210),
			btn_secondary: Color32::from_rgb(133, 153, 0),
			btn_danger: Color32::from_rgb(220, 50, 47),
			window_fill: Color32::from_rgb(7, 54, 66),
			panel_fill: Color32::from_rgb(0, 43, 54),
			canvas_fill: Color32::from_rgb(1, 30, 32),
			accent: Color32::from_rgb(38, 139, 210),
			grid: Color32::from_rgb(88, 110, 117),
			dir: Color32::from_rgb(42, 161, 152),
			tracker: Color32::from_rgb(108, 113, 196),
			left_limb: Color32::from_rgb(42, 161, 152),
			right_limb: Color32::from_rgb(203, 75, 22),
			mag_color: Color32::from_rgb(133, 153, 0),
			selection: Color32::from_rgb(38, 139, 210),
			batt_high: Color32::from_rgb(133, 153, 0),
			batt_med: Color32::from_rgb(181, 137, 0),
			batt_low: Color32::from_rgb(220, 50, 47),
			widget_inactive: Color32::from_rgb(7, 54, 66),
			widget_hover: Color32::from_rgb(15, 65, 75),
			widget_active: Color32::from_rgb(22, 77, 86),
			status_active: Color32::GREEN,
			status_timeout: Color32::RED,
			status_stationary: Color32::YELLOW,
			status_moving: Color32::GRAY,
			status_error: Color32::RED,
			loss_high: Color32::RED,
			loss_med: Color32::YELLOW,
			loss_low: Color32::GRAY,
			hint_text: Color32::from_gray(150),
			stroke_gray: Color32::from_gray(90),
			batt_bg: Color32::from_gray(40),
			mag_point: Color32::YELLOW,
			axis_x: UI_AXIS_X,
			axis_y: UI_AXIS_Y,
			axis_z: UI_AXIS_Z,
			foreground: Color32::from_rgb(131, 148, 150),
			border: Color32::from_gray(90),
		}
	}

	pub fn to_def(&self) -> ThemeDef {
			ThemeDef {
				btn_primary: color_to_rgb(self.btn_primary),
				btn_secondary: color_to_rgb(self.btn_secondary),
				btn_danger: color_to_rgb(self.btn_danger),
				window_fill: color_to_rgb(self.window_fill),
				panel_fill: color_to_rgb(self.panel_fill),
				canvas_fill: color_to_rgb(self.canvas_fill),
				accent: color_to_rgb(self.accent),
				grid: color_to_rgb(self.grid),
				dir: color_to_rgb(self.dir),
				tracker: color_to_rgb(self.tracker),
				left_limb: color_to_rgb(self.left_limb),
				right_limb: color_to_rgb(self.right_limb),
				mag_color: color_to_rgb(self.mag_color),
				selection: color_to_rgb(self.selection),
				batt_high: color_to_rgb(self.batt_high),
				batt_med: color_to_rgb(self.batt_med),
				batt_low: color_to_rgb(self.batt_low),
				widget_inactive: color_to_rgb(self.widget_inactive),
				widget_hover: color_to_rgb(self.widget_hover),
				widget_active: color_to_rgb(self.widget_active),
				hint_text: color_to_rgb(self.hint_text),
				stroke_gray: color_to_rgb(self.stroke_gray),
				batt_bg: color_to_rgb(self.batt_bg),
				mag_point: color_to_rgb(self.mag_point),
				axis_x: color_to_rgb(self.axis_x),
				axis_y: color_to_rgb(self.axis_y),
				axis_z: color_to_rgb(self.axis_z),
				foreground: color_to_rgb(self.foreground),
				border: color_to_rgb(self.border),
			}
		}

		pub fn from_def(def: &ThemeDef) -> Self {
			Self {
				btn_primary: Color32::from_rgb(def.btn_primary[0], def.btn_primary[1], def.btn_primary[2]),
				btn_secondary: Color32::from_rgb(def.btn_secondary[0], def.btn_secondary[1], def.btn_secondary[2]),
				btn_danger: Color32::from_rgb(def.btn_danger[0], def.btn_danger[1], def.btn_danger[2]),
				window_fill: Color32::from_rgb(def.window_fill[0], def.window_fill[1], def.window_fill[2]),
				panel_fill: Color32::from_rgb(def.panel_fill[0], def.panel_fill[1], def.panel_fill[2]),
				canvas_fill: Color32::from_rgb(def.canvas_fill[0], def.canvas_fill[1], def.canvas_fill[2]),
				accent: Color32::from_rgb(def.accent[0], def.accent[1], def.accent[2]),
				grid: Color32::from_rgb(def.grid[0], def.grid[1], def.grid[2]),
				dir: Color32::from_rgb(def.dir[0], def.dir[1], def.dir[2]),
				tracker: Color32::from_rgb(def.tracker[0], def.tracker[1], def.tracker[2]),
				left_limb: Color32::from_rgb(def.left_limb[0], def.left_limb[1], def.left_limb[2]),
				right_limb: Color32::from_rgb(def.right_limb[0], def.right_limb[1], def.right_limb[2]),
				mag_color: Color32::from_rgb(def.mag_color[0], def.mag_color[1], def.mag_color[2]),
				selection: Color32::from_rgb(def.selection[0], def.selection[1], def.selection[2]),
				batt_high: Color32::from_rgb(def.batt_high[0], def.batt_high[1], def.batt_high[2]),
				batt_med: Color32::from_rgb(def.batt_med[0], def.batt_med[1], def.batt_med[2]),
				batt_low: Color32::from_rgb(def.batt_low[0], def.batt_low[1], def.batt_low[2]),
				widget_inactive: Color32::from_rgb(def.widget_inactive[0], def.widget_inactive[1], def.widget_inactive[2]),
				widget_hover: Color32::from_rgb(def.widget_hover[0], def.widget_hover[1], def.widget_hover[2]),
				widget_active: Color32::from_rgb(def.widget_active[0], def.widget_active[1], def.widget_active[2]),
				status_active: UI_STATUS_ACTIVE,
				status_timeout: UI_STATUS_TIMEOUT,
				status_stationary: UI_STATUS_STATIONARY,
				status_moving: UI_STATUS_MOVING,
				status_error: UI_STATUS_ERROR,
				loss_high: UI_LOSS_HIGH,
				loss_med: UI_LOSS_MED,
				loss_low: UI_LOSS_LOW,
				hint_text: Color32::from_rgb(def.hint_text[0], def.hint_text[1], def.hint_text[2]),
				stroke_gray: Color32::from_rgb(def.stroke_gray[0], def.stroke_gray[1], def.stroke_gray[2]),
				batt_bg: Color32::from_rgb(def.batt_bg[0], def.batt_bg[1], def.batt_bg[2]),
				mag_point: Color32::from_rgb(def.mag_point[0], def.mag_point[1], def.mag_point[2]),
				axis_x: Color32::from_rgb(def.axis_x[0], def.axis_x[1], def.axis_x[2]),
				axis_y: Color32::from_rgb(def.axis_y[0], def.axis_y[1], def.axis_y[2]),
				axis_z: Color32::from_rgb(def.axis_z[0], def.axis_z[1], def.axis_z[2]),
				foreground: Color32::from_rgb(def.foreground[0], def.foreground[1], def.foreground[2]),
				border: Color32::from_rgb(def.border[0], def.border[1], def.border[2]),
			}
		}

		pub fn export_to_file(&self, path: &str) -> Result<(), Box<dyn Error>> {
			let def = self.to_def();
			let s = serde_json::to_string_pretty(&def)?;
			let mut f = File::create(path)?;
			f.write_all(s.as_bytes())?;
			Ok(())
		}

		pub fn import_from_file<P: AsRef<Path>>(path: P) -> Result<Self, Box<dyn Error>> {
			let data = std::fs::read_to_string(path)?;
			let def: ThemeDef = serde_json::from_str(&data)?;
			Ok(Self::from_def(&def))
		}
	}


fn color_to_rgb(c: Color32) -> [u8; 3] {
	[c.r(), c.g(), c.b()]
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ThemeDef {
	pub btn_primary: [u8; 3],
	pub btn_secondary: [u8; 3],
	pub btn_danger: [u8; 3],
	pub window_fill: [u8; 3],
	pub panel_fill: [u8; 3],
	pub canvas_fill: [u8; 3],
	pub accent: [u8; 3],
	pub grid: [u8; 3],
	pub dir: [u8; 3],
	pub tracker: [u8; 3],
	pub left_limb: [u8; 3],
	pub right_limb: [u8; 3],
	pub mag_color: [u8; 3],
	pub selection: [u8; 3],
	pub batt_high: [u8; 3],
	pub batt_med: [u8; 3],
	pub batt_low: [u8; 3],
	pub widget_inactive: [u8; 3],
	pub widget_hover: [u8; 3],
	pub widget_active: [u8; 3],
	pub hint_text: [u8; 3],
	pub stroke_gray: [u8; 3],
	pub batt_bg: [u8; 3],
	pub mag_point: [u8; 3],
	pub axis_x: [u8; 3],
	pub axis_y: [u8; 3],
	pub axis_z: [u8; 3],
	pub foreground: [u8; 3],
	pub border: [u8; 3],
}

