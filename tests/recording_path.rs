use aetherpose::recording::{Recorder, RECORDINGS_DIR};
use aetherpose::skeleton::model::SkeletonModel;
use std::path::Path;
use std::time::Duration;

#[test]
fn recordings_stay_inside_the_recordings_folder() {
    let skeleton = SkeletonModel::new_humanoid();
    let name = format!("path_test_{}.csv", std::process::id());
    let recorder = Recorder::new_with_options(&skeleton, format!("../elsewhere/{}", name), 1, Duration::from_millis(10))
        .expect("recorder");
    assert_eq!(recorder.filename, format!("{}/{}", RECORDINGS_DIR, name));
    drop(recorder);

    // The file exists as soon as the recorder does.
    let path = Path::new(RECORDINGS_DIR).join(&name);
    assert!(path.exists(), "recording file not created in {}", RECORDINGS_DIR);
    assert!(!Path::new("../elsewhere").join(&name).exists());
    let _ = std::fs::remove_file(path);
}

#[cfg(windows)]
#[test]
fn a_name_windows_cannot_create_fails_the_start() {
    let skeleton = SkeletonModel::new_humanoid();
    assert!(Recorder::new_with_options(&skeleton, "bad?name.csv".to_string(), 1, Duration::from_millis(10)).is_err());
}

#[test]
fn an_existing_recording_is_never_overwritten() {
    let skeleton = SkeletonModel::new_humanoid();
    let name = format!("keep_test_{}.csv", std::process::id());
    let first = Recorder::new_with_options(&skeleton, name.clone(), 1, Duration::from_millis(10)).expect("first");
    let first_path = first.filename.clone();
    drop(first);
    std::fs::write(&first_path, "earlier recording\n").unwrap();
    let second = Recorder::new_with_options(&skeleton, name.clone(), 1, Duration::from_millis(10)).expect("second");
    let second_path = second.filename.clone();
    drop(second);
    assert_eq!(second_path, format!("{}/keep_test_{}_2.csv", RECORDINGS_DIR, std::process::id()));
    assert_eq!(std::fs::read_to_string(&first_path).unwrap(), "earlier recording\n");
    let _ = std::fs::remove_file(first_path);
    let _ = std::fs::remove_file(second_path);
}

#[test]
fn windows_device_names_are_refused() {
    let skeleton = SkeletonModel::new_humanoid();
    for name in ["nul.csv", "CON", "com1.csv", "Lpt9.data.csv", "aux .csv"] {
        assert!(Recorder::new_with_options(&skeleton, name.to_string(), 1, Duration::from_millis(10)).is_err(), "{name}");
    }
    let ok = Recorder::new_with_options(&skeleton, format!("console_{}.csv", std::process::id()), 1, Duration::from_millis(10)).expect("console_*.csv is fine");
    let path = ok.filename.clone();
    drop(ok);
    let _ = std::fs::remove_file(path);
}
