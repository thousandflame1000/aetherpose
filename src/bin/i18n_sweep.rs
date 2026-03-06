use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::Path;

fn collect_keys_from_src(dir: &Path) -> Vec<String> {
    let mut keys = Vec::new();
    if dir.is_dir() {
        for entry in fs::read_dir(dir).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            if path.is_dir() {
                keys.extend(collect_keys_from_src(&path));
            } else if let Some(ext) = path.extension() {
                if ext == "rs" {
                    if let Ok(mut f) = File::open(&path) {
                        let mut contents = String::new();
                        let _ = f.read_to_string(&mut contents);
                        // find occurrences of t("...") or t('...')
                        let mut start = 0usize;
                        while let Some(idx) = contents[start..].find(".t(\"") {
                            let abs = start + idx + 4; // start of key
                            if let Some(end) = contents[abs..].find("\"") {
                                let key = &contents[abs..abs + end];
                                keys.push(key.to_string());
                                start = abs + end + 1;
                            } else {
                                break;
                            }
                        }
                    }
                }
            }
        }
    }
    keys
}

fn load_json_map(path: &Path) -> serde_json::Map<String, serde_json::Value> {
    if path.exists() {
        if let Ok(mut f) = File::open(path) {
            let mut contents = String::new();
            let _ = f.read_to_string(&mut contents);
            if let Ok(serde_json::Value::Object(map)) = serde_json::from_str(&contents) {
                return map;
            }
        }
    }
    serde_json::Map::new()
}

fn save_json_map(path: &Path, map: &serde_json::Map<String, serde_json::Value>) -> std::io::Result<()> {
    let v = serde_json::Value::Object(map.clone());
    let mut f = File::create(path)?;
    let s = serde_json::to_string_pretty(&v)?;
    f.write_all(s.as_bytes())?;
    Ok(())
}

fn main() {
    println!("i18n sweep: scanning source for i18n keys...");
    let keys = collect_keys_from_src(Path::new("src"));
    println!("Found {} keys", keys.len());

    let i18n_dir = Path::new("i18n");
    if !i18n_dir.exists() {
        println!("i18n directory not found; creating");
        let _ = fs::create_dir_all(i18n_dir);
    }

    for entry in fs::read_dir(i18n_dir).unwrap() {
        if let Ok(entry) = entry {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) == Some("json") {
                println!("Processing {}", path.display());
                let mut map = load_json_map(&path);
                let mut changed = false;
                for k in &keys {
                    if !map.contains_key(k) {
                        // for en.json default to key, for others empty
                        let val = if path.file_stem().and_then(|s| s.to_str()) == Some("en") {
                            serde_json::Value::String(k.clone())
                        } else {
                            serde_json::Value::String("".to_string())
                        };
                        map.insert(k.clone(), val);
                        changed = true;
                    }
                }
                if changed {
                    if let Err(e) = save_json_map(&path, &map) {
                        eprintln!("Failed to save {}: {}", path.display(), e);
                    } else {
                        println!("Updated {}", path.display());
                    }
                }
            }
        }
    }

    println!("i18n sweep complete.");
}
