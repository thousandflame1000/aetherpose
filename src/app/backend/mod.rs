mod commands;
mod ingest;
mod io;
mod pipeline;
mod quest;

use self::quest::spawn_quest_listener;
use crate::app::config::AppConfig;
use crate::app::types::{BackendCommand, GuiUpdate, QuestInputData, TrackerState};
use crate::backpress::BackpressStats;
use crate::connection_type::ConnectionType;
use crate::fusion::FusionEngine;
use crate::ik::IkSolver;
use crate::net;
use crate::net::packet::PacketData;
use crate::net::ble::SyncQuatMap;
use crate::output::osc::OscSender;
use crate::recording::Recorder;
use crate::skeleton::model::SkeletonModel;
use crossbeam_channel::{bounded, Receiver, Sender};
use log::{error, info};
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex, RwLock};
use tokio::net::UdpSocket;
use tokio::sync::watch;
use tokio::time::{interval, Duration, Interval};

const QUEST_BRIDGE_PORT: u16 = 9002;
const UDP_PACKET_BUDGET_PER_TICK: usize = 50;
const DEFAULT_RECORDER_BATCH_SIZE: usize = 128;
const DEFAULT_RECORDER_FLUSH_INTERVAL_MS: u64 = 500;
/// Slider drags send a command per input event; write config.json at most this often.
const CONFIG_SAVE_INTERVAL: Duration = Duration::from_millis(500);

pub async fn run(
    shared_skel: Arc<RwLock<SkeletonModel>>,
    tx: mpsc::Sender<GuiUpdate>,
    cmd_rx: mpsc::Receiver<BackendCommand>,
    config: AppConfig,
) {
    let (quest_tx, quest_rx) = watch::channel(QuestInputData {
        head: None,
        left_hand: None,
        right_hand: None,
        received_at: None,
    });

    // UDP tracker input has its own port: the OSC output goes to osc_port
    // (VRChat listens there), so sharing it looped our own OSC back in and a
    // running VRChat made the bind, and with it the whole backend, fail.
    let socket = match net::bind_udp_socket(config.udp_input_port).await {
        Ok(socket) => Some(socket),
        Err(e) => {
            error!("UDP tracker input disabled: port {} bind failed: {}", config.udp_input_port, e);
            None
        }
    };

    spawn_quest_listener(quest_tx);

    let mut backend = BackendRuntime::new(shared_skel, tx, cmd_rx, config, socket, quest_rx).await;
    backend.start_ble_manager();
    backend.start_serial_manager_from_config();
    backend.spawn_backpressure_reporter();
    backend.run_loop().await;
}

struct BackendRuntime {
    shared_skel: Arc<RwLock<SkeletonModel>>,
    tx: mpsc::Sender<GuiUpdate>,
    cmd_rx: mpsc::Receiver<BackendCommand>,
    config: AppConfig,
    socket: Option<UdpSocket>,
    quest_rx: watch::Receiver<QuestInputData>,
    skeleton: SkeletonModel,
    t_pose: SkeletonModel,
    fusion: FusionEngine,
    ik_solver: IkSolver,
    recorder: Option<Recorder>,
    osc_sender: Option<OscSender>,
    packet_count: u64,
    udp_buf: [u8; 1024],
    trackers: HashMap<u8, TrackerState>,
    tracker_packet_counts: HashMap<u8, u32>,
    last_tps_update: std::time::Instant,
    tick_rate: Interval,
    serial_tx: Sender<(PacketData, ConnectionType)>,
    serial_rx: Receiver<(PacketData, ConnectionType)>,
    bp_stats: Arc<BackpressStats>,
    serial_stop_tx: Option<watch::Sender<bool>>,
    serial_running_flag: Arc<AtomicBool>,
    serial_status_shared: Arc<Mutex<Option<String>>>,
    net_trackers: HashMap<u8, crate::net::tracker::Tracker>,
    ik_smoothness_weight: f32,
    prop_leg: f32,
    prop_arm: f32,
    prop_spine: f32,
    leg_ratio: f32,
    floor_offset: f32,
    pending_shake_bone: Option<u8>,
    /// Shared with BLE task: tracker_id → EKF quat to sync back when link is stable
    sync_quats: SyncQuatMap,
    /// Per-tracker consecutive lost packet counter (resets on any good packet)
    tracker_consec_lost: HashMap<u8, u32>,
    /// Per-tracker consecutive good packet counter (resets on any lost packet)
    tracker_consec_good: HashMap<u8, u32>,
    config_dirty: bool,
    last_config_save: Option<std::time::Instant>,
    /// Latest BLE status line, shown on the page; a change publishes a snapshot.
    ble_status_shared: Arc<Mutex<Option<String>>>,
    published_ble_status: Option<String>,
    /// Outcome of the last leg calibration, for the page (see WsSnapshot).
    leg_calibration_result: Option<String>,
    /// Why recording could not start or stopped by itself (see WsSnapshot).
    recorder_error: Option<String>,
    /// Why the last OSC target could not be used (see WsSnapshot).
    osc_error: Option<String>,
}

impl BackendRuntime {
    async fn new(
        shared_skel: Arc<RwLock<SkeletonModel>>,
        tx: mpsc::Sender<GuiUpdate>,
        cmd_rx: mpsc::Receiver<BackendCommand>,
        config: AppConfig,
        socket: Option<UdpSocket>,
        quest_rx: watch::Receiver<QuestInputData>,
    ) -> Self {
        let mut skeleton = match shared_skel.read() {
            Ok(skeleton) => skeleton.clone(),
            Err(e) => {
                error!("shared skeleton read poisoned: {}", e);
                SkeletonModel::new_humanoid()
            }
        };

        let t_pose = skeleton.clone();
        let mut fusion = FusionEngine::new();
        let ik_solver = IkSolver::new();
        let (osc_sender, osc_error) = match OscSender::new(&config.osc_ip, config.osc_port).await {
            Ok(sender) => (Some(sender), None),
            Err(e) => {
                error!("OSC sender init failed: {}", e);
                (None, Some(format!("{}:{} ({})", config.osc_ip, config.osc_port, e)))
            }
        };

        fusion.drift_correction = config.drift_correction;
        fusion.smoothing_min_cutoff = config.smoothing_min_cutoff;
        fusion.smoothing_beta = config.smoothing_beta;
        fusion.set_trajectory_integration_mode(config.trajectory_integration_mode);
        fusion.set_zupt_enabled(config.zupt_enabled);
        fusion.set_zupt_params(
            config.zupt_window_size,
            config.zupt_accel_var_threshold,
            config.zupt_gyro_threshold,
        );

        skeleton.adjust_proportions(config.prop_leg, config.prop_arm, config.prop_spine);
        fusion.assigner.unassigned.extend(config.unassigned_trackers.iter().copied());
        for (tracker_id, bone_id) in &config.tracker_assignments {
            fusion.assigner.set_assignment(*tracker_id, *bone_id);
        }

        let (serial_tx, serial_rx) = bounded::<(PacketData, ConnectionType)>(256);

        Self {
            shared_skel,
            tx,
            cmd_rx,
            socket,
            quest_rx,
            skeleton,
            t_pose,
            fusion,
            ik_solver,
            recorder: None,
            osc_sender,
            packet_count: 0,
            udp_buf: [0u8; 1024],
            trackers: HashMap::new(),
            tracker_packet_counts: HashMap::new(),
            last_tps_update: std::time::Instant::now(),
            tick_rate: interval(Duration::from_millis(10)),
            serial_tx,
            serial_rx,
            bp_stats: Arc::new(BackpressStats::new()),
            serial_stop_tx: None,
            serial_running_flag: Arc::new(AtomicBool::new(false)),
            serial_status_shared: Arc::new(Mutex::new(None)),
            net_trackers: HashMap::new(),
            ik_smoothness_weight: config.ik_smoothness,
            prop_leg: config.prop_leg,
            prop_arm: config.prop_arm,
            prop_spine: config.prop_spine,
            leg_ratio: config.leg_ratio,
            floor_offset: config.floor_offset,
            pending_shake_bone: None,
            sync_quats: Arc::new(Mutex::new(HashMap::new())),
            tracker_consec_lost: HashMap::new(),
            tracker_consec_good: HashMap::new(),
            config_dirty: false,
            last_config_save: None,
            ble_status_shared: Arc::new(Mutex::new(None)),
            published_ble_status: None,
            leg_calibration_result: None,
            recorder_error: None,
            osc_error,
            config,
        }
    }

    /// Record a settings change; run_loop writes config.json shortly after.
    fn mark_config_changed(&mut self) {
        self.config_dirty = true;
    }

    fn save_config_if_due(&mut self) {
        if !self.config_dirty
            || self.last_config_save.is_some_and(|at| at.elapsed() < CONFIG_SAVE_INTERVAL)
        {
            return;
        }
        self.config.save();
        self.config_dirty = false;
        self.last_config_save = Some(std::time::Instant::now());
    }

    fn current_ble_status(&self) -> Option<String> {
        self.ble_status_shared.lock().ok().and_then(|status| status.clone())
    }

    /// True once per BLE status change, so idle pages still see it.
    fn ble_status_changed(&mut self) -> bool {
        let status = self.current_ble_status();
        if status == self.published_ble_status {
            return false;
        }
        self.published_ble_status = status;
        true
    }

    /// Copy the assignments of connected trackers into the saved config.
    fn persist_assignments(&mut self) {
        for tracker_id in self.net_trackers.keys() {
            if let Some(bone_id) = self.fusion.assigner.get_bone_id(*tracker_id) {
                self.config.tracker_assignments.insert(*tracker_id, bone_id);
            }
        }
        self.sync_unassigned_config();
        self.mark_config_changed();
    }

    fn sync_unassigned_config(&mut self) {
        let mut unassigned: Vec<u8> = self.fusion.assigner.unassigned.iter().copied().collect();
        unassigned.sort();
        self.config.unassigned_trackers = unassigned;
    }

    async fn run_loop(&mut self) {
        info!("Aetherpose backend running");

        loop {
            let mut snapshot_dirty = false;
            let received_any = self.ingest_udp_packets() | self.ingest_serial_packets();
            let quest_dirty = self.quest_rx.has_changed().unwrap_or(false);

            if self.handle_commands().await {
                snapshot_dirty = true;
            }
            self.save_config_if_due();
            if self.ble_status_changed() {
                snapshot_dirty = true;
            }

            self.run_pose_pipeline().await;
            self.tick_rate.tick().await;
            self.refresh_tracker_tps();

            if received_any || snapshot_dirty || quest_dirty {
                self.publish_snapshot();
            }
        }
    }
}
