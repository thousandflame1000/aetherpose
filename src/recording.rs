use crate::skeleton::model::SkeletonModel;
use chrono::Local;
use crossbeam_channel::{bounded, Sender};
use std::fs::File;
use std::io::Write;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

/// Recorder now sends CSV lines to a background thread to avoid blocking the main loop.
pub struct Recorder {
    tx: Sender<String>,
    start_time: Instant,
    bone_ids: Vec<u8>, // 儲存要錄製的骨骼 ID 順序
    // metadata & counters
    pub filename: String,
    pub batch_size: usize,
    pub flush_interval_ms: u64,
    pub dropped_count: Arc<AtomicU64>,
    pub write_error_count: Arc<AtomicU64>,
}

impl Recorder {
    pub fn new(skeleton: &SkeletonModel) -> std::io::Result<Self> {
        let timestamp = Local::now().format("%Y-%m-%d_%H-%M-%S");
        let filename = format!("recording_{}.csv", timestamp);
        Self::new_with_options(skeleton, filename, 128, Duration::from_millis(500))
    }
    pub fn new_with_options(
        skeleton: &SkeletonModel,
        filename: String,
        batch_size: usize,
        flush_interval: Duration,
    ) -> std::io::Result<Self> {

        // 動態生成 CSV 標頭
        let mut header = "timestamp_ms,".to_string();
        let mut bone_ids: Vec<u8> = skeleton.bones.keys().copied().collect();
        bone_ids.sort(); // 確保順序一致

        for id in &bone_ids {
            header.push_str(&format!("bone_{}_pos_x,bone_{}_pos_y,bone_{}_pos_z,bone_{}_rot_x,bone_{}_rot_y,bone_{}_rot_z,bone_{}_rot_w,", id, id, id, id, id, id, id));
        }
        header.pop(); // 移除最後一個逗號

        // 有界頻道，避免用量失控
        let (tx, rx) = bounded::<String>(1024);

        // counters shared between main thread and background writer
        let dropped_count = Arc::new(AtomicU64::new(0));
        let write_error_count = Arc::new(AtomicU64::new(0));

        // Spawn background thread to own the file and perform batched I/O
        let filename_clone = filename.clone();
        let header_clone = header.clone();
        let write_error_count_bg = write_error_count.clone();
        let batch_size_local = batch_size;
        let flush_interval_local = flush_interval;
        std::thread::spawn(move || {
            match File::create(&filename_clone) {
                Ok(mut file) => {
                    let _ = writeln!(file, "{}", header_clone);
                    let mut buf: Vec<String> = Vec::with_capacity(batch_size_local);
                    let mut last_flush = Instant::now();
                    loop {
                        // try receive with timeout to allow periodic flush
                        match rx.recv_timeout(Duration::from_millis(100)) {
                            Ok(line) => {
                                buf.push(line);
                                // flush if batch full
                                if buf.len() >= batch_size_local {
                                    if let Err(e) = write_batch(&mut file, &mut buf) {
                                        log::error!("錄製寫入失敗: {}", e);
                                        write_error_count_bg.fetch_add(1, Ordering::Relaxed);
                                        // backoff briefly before retrying
                                        std::thread::sleep(Duration::from_millis(200));
                                    }
                                    last_flush = Instant::now();
                                }
                            }
                            Err(crossbeam_channel::RecvTimeoutError::Timeout) => {
                                // timed out - check flush interval
                                if !buf.is_empty() && last_flush.elapsed() >= flush_interval_local {
                                    if let Err(e) = write_batch(&mut file, &mut buf) {
                                        log::error!("錄製寫入失敗: {}", e);
                                        write_error_count_bg.fetch_add(1, Ordering::Relaxed);
                                        std::thread::sleep(Duration::from_millis(200));
                                    }
                                    last_flush = Instant::now();
                                }
                            }
                            Err(crossbeam_channel::RecvTimeoutError::Disconnected) => {
                                // Channel closed - flush remaining and exit
                                if !buf.is_empty() {
                                    if let Err(e) = write_batch(&mut file, &mut buf) {
                                        log::error!("錄製寫入失敗: {}", e);
                                    }
                                }
                                let _ = file.flush();
                                log::info!("錄製檔案已關閉: {}", filename_clone);
                                break;
                            }
                        }
                    }
                }
                Err(e) => {
                    log::error!("無法建立錄製檔案: {}", filename_clone);
                    let _ = e;
                }
            }
        });

        log::info!("開始錄製至 {} (background thread)", filename);

        Ok(Self {
            tx,
            start_time: Instant::now(),
            bone_ids,
            filename,
            batch_size,
            flush_interval_ms: flush_interval.as_millis() as u64,
            dropped_count,
            write_error_count,
        })
    }

    /// 非同步送出一列 CSV，若通道已關閉或錯誤則回傳 Err
    pub fn record_frame(&mut self, skeleton: &SkeletonModel) -> std::io::Result<()> {
        let elapsed_ms = self.start_time.elapsed().as_millis();
        let mut record = format!("{},", elapsed_ms);

        for id in &self.bone_ids {
            if let Some(bone) = skeleton.bones.get(id) {
                let pos = bone.global_position;
                let rot = bone.global_rotation.coords; // 這是一個 Vector4 (x,y,z,w)
                record.push_str(&format!(
                    "{},{},{},{},{},{},{},",
                    pos.x, pos.y, pos.z, rot.x, rot.y, rot.z, rot.w
                ));
            }
        }
        record.pop(); // 移除最後一個逗號

        // Non-blocking send; if channel is full, return an error indicating drop
        match self.tx.try_send(record) {
            Ok(()) => Ok(()),
            Err(e) => {
                // increment dropped counter for observability
                self.dropped_count.fetch_add(1, Ordering::Relaxed);
                Err(std::io::Error::new(
                    std::io::ErrorKind::WouldBlock,
                    format!("send failed (channel full or closed): {}", e),
                ))
            }
        }
    }
}

fn write_batch(file: &mut File, buf: &mut Vec<String>) -> std::io::Result<()> {
    if buf.is_empty() {
        return Ok(());
    }
    // join with newlines in one allocation
    let joined = buf.join("\n");
    buf.clear();
    writeln!(file, "{}", joined)?;
    file.flush()?;
    Ok(())
}
