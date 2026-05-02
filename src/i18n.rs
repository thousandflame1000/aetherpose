use std::path::{Path, PathBuf};

use std::collections::HashMap;
use std::fs;
use std::io::Write;

#[allow(dead_code)]
pub struct I18n {
    current: String,
    data: HashMap<String, HashMap<String, String>>, // lang -> (key -> val)
    display_names: HashMap<String, String>, // lang -> human readable name
}

impl I18n {
    pub fn load_dir(path: &str, default: &str) -> Self {
        let mut data = HashMap::new();
        let mut display_names: HashMap<String, String> = HashMap::new();
        let candidate_dirs = candidate_i18n_dirs(path);

        for dir in candidate_dirs {
            load_lang_maps_from_dir(&dir, &mut data, &mut display_names);
            if !data.is_empty() {
                break;
            }
        }
        // ensure default exists
        if !data.contains_key(default) {
            data.insert(default.to_string(), HashMap::new());
        }
        // ensure default exists
        if !data.contains_key(default) {
            data.insert(default.to_string(), HashMap::new());
        }
        if !display_names.contains_key(default) {
            display_names.insert(default.to_string(), default.to_string());
        }
        Self { current: default.to_string(), data, display_names }
    }

    #[allow(dead_code)]
    pub fn available_langs(&self) -> Vec<String> {
        let mut v: Vec<String> = self.data.keys().cloned().collect();
        v.sort();
        v
    }

    pub fn available_langs_with_display(&self) -> Vec<(String,String)> {
        let mut v: Vec<(String,String)> = self.data.keys().cloned().map(|k| {
            let display = self.display_names.get(&k).cloned().unwrap_or_else(|| k.clone());
            (k, display)
        }).collect();
        v.sort_by(|a,b| a.0.cmp(&b.0));
        v
    }

    pub fn set_lang(&mut self, lang: &str) -> bool {
        if self.data.contains_key(lang) {
            self.current = lang.to_string();
            true
        } else {
            false
        }
    }

    pub fn t(&self, key: &str) -> String {
        if let Some(map) = self.data.get(&self.current) {
            if let Some(v) = map.get(key) {
                return v.clone();
            }
        }
        // fallback: try en
        if let Some(map) = self.data.get("en") {
            if let Some(v) = map.get(key) {
                return v.clone();
            }
        }
        // last resort: return key
        key.to_string()
    }

    pub fn export_lang(&self, lang: &str, out_path: &str) -> std::io::Result<()> {
        if let Some(map) = self.data.get(lang) {
            let text = serde_json::to_string_pretty(map).unwrap_or_else(|_| "{}".to_string());
            let mut f = fs::File::create(out_path)?;
            f.write_all(text.as_bytes())?;
            f.flush()?;
            Ok(())
        } else {
            Err(std::io::Error::new(std::io::ErrorKind::NotFound, "lang not found"))
        }
    }
}

fn candidate_i18n_dirs(path: &str) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    let direct = PathBuf::from(path);
    dirs.push(direct.clone());

    if let Ok(exe) = std::env::current_exe() {
        if let Some(exe_dir) = exe.parent() {
            dirs.push(exe_dir.join(path));
        }
    }

    dirs.push(Path::new(env!("CARGO_MANIFEST_DIR")).join(path));

    let mut deduped = Vec::new();
    for dir in dirs {
        if !deduped.iter().any(|existing: &PathBuf| existing == &dir) {
            deduped.push(dir);
        }
    }
    deduped
}

fn load_lang_maps_from_dir(
    dir: &Path,
    data: &mut HashMap<String, HashMap<String, String>>,
    display_names: &mut HashMap<String, String>,
) {
    if !dir.exists() {
        return;
    }

    if let Ok(entries) = std::fs::read_dir(dir) {
        for e in entries.flatten() {
            if let Some(ext) = e.path().extension() {
                if ext == "json" {
                    if let Some(fname) = e.path().file_stem().and_then(|s| s.to_str()) {
                        if let Ok(text) = fs::read_to_string(e.path()) {
                            if let Ok(map) = serde_json::from_str::<HashMap<String, String>>(&text) {
                                if let Some(name) = map.get("__lang_name") {
                                    display_names.insert(fname.to_string(), name.clone());
                                }
                                data.insert(fname.to_string(), map);
                            }
                        }
                    }
                }
            }
        }
    }
}
