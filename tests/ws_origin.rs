use aetherpose::app::ws_server::origin_allowed;

#[test]
fn local_pages_and_local_programs_may_connect() {
    for origin in [None, Some("http://127.0.0.1:18080"), Some("http://localhost:18090"), Some("http://localhost"), Some("http://[::1]:18080")] {
        assert!(origin_allowed(origin), "{origin:?}");
    }
}

#[test]
fn other_sites_may_not_connect() {
    for origin in [
        "https://evil.example",
        "http://evil.example:18080",
        "http://127.0.0.1.evil.example",
        "http://localhost.evil.example:80",
        "null",
        "file://",
        "http://127.0.0.1:",
        "?",
    ] {
        assert!(!origin_allowed(Some(origin)), "{origin}");
    }
}
