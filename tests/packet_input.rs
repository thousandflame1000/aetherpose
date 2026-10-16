use aetherpose::net::connection::split_serial_lines;
use aetherpose::net::packet::PacketData;

#[test]
fn a_serial_line_split_across_reads_is_kept_whole() {
    let mut pending = Vec::new();
    let line = "{\"id\":7,\"accel\":[0.0,0.0,9.81],\"note\":\"右前臂\"}";
    let bytes = line.as_bytes();
    // Split inside the JSON and inside a multi-byte character.
    let cut = line.find("右").unwrap() + 1;
    assert!(split_serial_lines(&mut pending, &bytes[..10]).is_empty());
    assert!(split_serial_lines(&mut pending, &bytes[10..cut]).is_empty());
    let mut rest = bytes[cut..].to_vec();
    rest.extend_from_slice(b"\r\n{\"id\":8}\n{\"id\"");
    let lines = split_serial_lines(&mut pending, &rest);
    assert_eq!(lines, vec![bytes.to_vec(), b"{\"id\":8}".to_vec()]);
    assert_eq!(pending, b"{\"id\"".to_vec());
}

#[test]
fn endless_garbage_without_a_newline_is_dropped() {
    let mut pending = Vec::new();
    assert!(split_serial_lines(&mut pending, &vec![b'x'; 70 * 1024]).is_empty());
    assert!(pending.is_empty());
}

fn packet(json: &str) -> PacketData {
    serde_json::from_str(json).unwrap()
}

#[test]
fn packets_with_unusable_values_are_refused() {
    assert!(packet(r#"{"id":1,"accel":[0.0,0.0,9.81],"quat":[0.0,0.0,0.0,1.0]}"#).is_usable());
    assert!(packet(r#"{"id":1}"#).is_usable());
    // f32 overflows to infinity; JSON cannot spell NaN, other paths can.
    assert!(!packet(r#"{"id":1,"accel":[1e39,0.0,9.81]}"#).is_usable());
    assert!(!packet(r#"{"id":1,"quat":[0.0,0.0,0.0,0.0]}"#).is_usable());
    let mut nan = packet(r#"{"id":1}"#);
    nan.gyro = Some([f32::NAN, 0.0, 0.0]);
    assert!(!nan.is_usable());
}
