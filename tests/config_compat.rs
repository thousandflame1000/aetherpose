use aetherpose::AppConfig;

#[test]
fn udp_tracker_input_does_not_share_the_osc_output_port() {
    let config = AppConfig::default();
    assert_ne!(config.udp_input_port, config.osc_port);
    // A config.json saved before the field existed gets the default as well.
    let mut json = serde_json::to_value(&config).unwrap();
    json.as_object_mut().unwrap().remove("udp_input_port");
    let loaded: AppConfig = serde_json::from_value(json).unwrap();
    assert_eq!(loaded.udp_input_port, 9003);
}

#[test]
fn the_saved_project_config_still_loads() {
    // AppConfig::load falls back to defaults on a parse error, which would
    // silently discard the user's settings and tracker assignments.
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/config.json");
    let Ok(text) = std::fs::read_to_string(path) else { return };
    let config: AppConfig = serde_json::from_str(&text).expect("config.json no longer parses");
    assert!(config.osc_port > 0);
}

#[test]
fn an_unreadable_config_is_kept_and_reported() {
    let dir = std::env::temp_dir().join(format!("aetherpose_config_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("config.json");
    std::fs::write(&path, "{ \"osc_port\": 9000, oops").unwrap();
    let config = AppConfig::load_from(&path);
    let warning = config.load_warning.clone().expect("a warning for the page");
    assert!(warning.ends_with("|config.json.bad"), "{}", warning);
    assert_eq!(std::fs::read_to_string(dir.join("config.json.bad")).unwrap(), "{ \"osc_port\": 9000, oops");
    assert_eq!(config.osc_port, AppConfig::default().osc_port);
    // A missing file is simply the defaults, without a warning.
    assert!(AppConfig::load_from(&dir.join("absent.json")).load_warning.is_none());
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn missing_settings_take_the_defaults_not_zero() {
    // Saved before the filter settings existed: min_cutoff 0 and beta 0 would freeze the filter.
    let loaded: AppConfig = serde_json::from_str(r#"{"osc_ip":"10.0.0.2","osc_port":9000}"#).unwrap();
    let defaults = AppConfig::default();
    assert_eq!(loaded.osc_ip, "10.0.0.2");
    assert_eq!(loaded.smoothing_min_cutoff, defaults.smoothing_min_cutoff);
    assert_eq!(loaded.smoothing_beta, defaults.smoothing_beta);
    assert_eq!(loaded.ik_smoothness, defaults.ik_smoothness);
    assert_eq!(loaded.prop_leg, defaults.prop_leg);
}

#[test]
fn out_of_range_settings_in_config_json_are_kept_in_range() {
    let dir = std::env::temp_dir().join(format!("aetherpose_config_range_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("config.json");
    std::fs::write(&path, r#"{"ik_smoothness":50,"leg_ratio":0,"smoothing_min_cutoff":1e39,"zupt_window_size":4000000000,"prop_arm":1.2}"#).unwrap();
    let config = AppConfig::load_from(&path);
    let defaults = AppConfig::default();
    assert!(config.load_warning.is_none());
    assert_eq!(config.ik_smoothness, 1.0);
    assert_eq!(config.leg_ratio, 0.2);
    assert_eq!(config.smoothing_min_cutoff, defaults.smoothing_min_cutoff, "an f32 overflow becomes the default");
    assert_eq!(config.zupt_window_size, 200);
    assert_eq!(config.prop_arm, 1.2, "values in range are kept");
    let _ = std::fs::remove_dir_all(&dir);
}
