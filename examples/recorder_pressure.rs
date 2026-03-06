use aetherpose::recording::Recorder;
use aetherpose::skeleton::model::SkeletonModel;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

fn main() {
    // lightweight skeleton
    let skeleton = SkeletonModel::new_humanoid();

    // create recorder with aggressive small batch/flush to exercise IO
    let rec = Recorder::new_with_options(&skeleton, "pressure_test.csv".to_string(), 16, Duration::from_millis(200)).expect("recorder init");
    let rec = Arc::new(Mutex::new(rec));

    let threads = 4usize;
    let duration_secs = 5u64;
    let start = Instant::now();

    let mut handles = Vec::new();
    for i in 0..threads {
        let rec_clone = rec.clone();
        let sk = skeleton.clone();
        let start_clone = start.clone();
        let handle = thread::spawn(move || {
            let mut frames_sent = 0u64;
            while start_clone.elapsed().as_secs() < duration_secs {
                // send as fast as possible
                if let Ok(mut r) = rec_clone.lock() {
                    let _ = r.record_frame(&sk);
                }
                frames_sent += 1;
                // tiny pause to avoid burning CPU fully
                if frames_sent % 100 == 0 {
                    thread::sleep(Duration::from_micros(50));
                }
            }
            println!("worker {} sent {} frames", i, frames_sent);
        });
        handles.push(handle);
    }

    for h in handles {
        let _ = h.join();
    }

    // drop recorder to close channel and flush
    let rc = Arc::try_unwrap(rec).ok().and_then(|m| m.into_inner().ok());
    if let Some(r) = rc {
        println!("recorder file: {}", r.filename);
        println!("dropped: {}", r.dropped_count.load(std::sync::atomic::Ordering::Relaxed));
        println!("write_errors: {}", r.write_error_count.load(std::sync::atomic::Ordering::Relaxed));
    } else {
        println!("Could not unwrap recorder Arc (still in use)");
    }

    println!("Pressure test finished");
}
