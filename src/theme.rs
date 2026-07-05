// Theme definitions — serializable only; rendering is handled by the Python frontend.

use serde::{Deserialize, Serialize};
use std::error::Error;
use std::fs::File;
use std::io::Write;
use std::path::Path;

#[derive(Serialize, Deserialize, Clone, Copy, PartialEq, Eq, Debug, Default)]
#[serde(rename_all = "lowercase")]
pub enum ThemeVariant {
    #[default]
    Dark,
    Light,
    Solarized,
}

/// Serializable theme token store. All colours are `[R, G, B]` triples (0–255).
/// The Python frontend reads this from `theme_custom.json` and applies it.
#[derive(Serialize, Deserialize, Debug, Clone)]
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
    pub stroke_w: f32,
    pub shadow_offset_y: f32,
    pub icon_btn_w: f32,
    pub icon_size: f32,
    pub gap_xxs: f32,
    pub gap_xs: f32,
    pub gap_sm: f32,
    pub gap_md: f32,
    pub btn_pad_x: f32,
    pub btn_pad_y: f32,
    pub battery_w: f32,
    pub battery_h: f32,
    pub btn_w: f32,
    pub btn_h: f32,
    pub swatch_w: f32,
    pub swatch_h: f32,
    pub table_min_col_width: f32,
    pub input_w_xl: f32,
    pub input_w_large: f32,
    pub input_w_med: f32,
    pub input_w_small: f32,
    pub scroll_max_h: f32,
    pub font_tiny: f32,
    pub font_small: f32,
    pub font_reg: f32,
    pub corner_round_sm: f32,
    pub corner_round_md: f32,
    pub bone_radius_head: f32,
    pub bone_radius_default: f32,
    pub point_radius: f32,
    pub window_margin: f32,
}

impl ThemeDef {
    pub fn dark() -> Self {
        Self {
            btn_primary:       [64, 160, 255],
            btn_secondary:     [120, 120, 140],
            btn_danger:        [220, 90, 90],
            window_fill:       [18, 24, 33],
            panel_fill:        [24, 30, 40],
            canvas_fill:       [14, 18, 24],
            accent:            [64, 160, 255],
            grid:              [48, 56, 72],
            dir:               [100, 120, 200],
            tracker:           [160, 120, 255],
            left_limb:         [0, 200, 200],
            right_limb:        [255, 175, 90],
            mag_color:         [80, 220, 140],
            selection:         [90, 160, 255],
            batt_high:         [90, 200, 100],
            batt_med:          [200, 160, 70],
            batt_low:          [200, 80, 80],
            widget_inactive:   [40, 44, 52],
            widget_hover:      [50, 55, 65],
            widget_active:     [60, 65, 75],
            hint_text:         [150, 150, 150],
            stroke_gray:       [60, 60, 60],
            batt_bg:           [50, 50, 50],
            mag_point:         [255, 255, 0],
            axis_x:            [255, 0, 0],
            axis_y:            [0, 255, 0],
            axis_z:            [0, 0, 255],
            foreground:        [255, 255, 255],
            border:            [255, 255, 255],
            stroke_w:          1.25,
            shadow_offset_y:   4.0,
            icon_btn_w:        48.0,
            icon_size:         16.0,
            gap_xxs:           4.0,
            gap_xs:            6.0,
            gap_sm:            8.0,
            gap_md:            10.0,
            btn_pad_x:         10.0,
            btn_pad_y:         6.0,
            battery_w:         72.0,
            battery_h:         20.0,
            btn_w:             120.0,
            btn_h:             32.0,
            swatch_w:          24.0,
            swatch_h:          12.0,
            table_min_col_width: 80.0,
            input_w_xl:        300.0,
            input_w_large:     260.0,
            input_w_med:       120.0,
            input_w_small:     100.0,
            scroll_max_h:      160.0,
            font_tiny:         10.0,
            font_small:        11.0,
            font_reg:          12.0,
            corner_round_sm:   4.0,
            corner_round_md:   8.0,
            bone_radius_head:  12.0,
            bone_radius_default: 7.0,
            point_radius:      4.0,
            window_margin:     14.0,
        }
    }

    pub fn export_to_file(&self, path: &str) -> Result<(), Box<dyn Error>> {
        let s = serde_json::to_string_pretty(self)?;
        let mut f = File::create(path)?;
        f.write_all(s.as_bytes())?;
        Ok(())
    }

    pub fn import_from_file<P: AsRef<Path>>(path: P) -> Result<Self, Box<dyn Error>> {
        let data = std::fs::read_to_string(path)?;
        Ok(serde_json::from_str(&data)?)
    }
}
