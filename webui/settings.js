// Aetherpose page: the 骨架 (IK skeleton) and 系統 settings tabs.
// Classic script: top-level names are shared with the other page scripts,
// which index.html loads in order (scene, pose, games, backend, trackers, settings, library, main).

// ── Body / System ──────────────────────────────────────────────────────────
// Shake-assign: the backend gives the chosen part to the next tracker shaken
// hard (over ~2.5 g). The six TransPose parts are listed first.
let shakePendingBone = null;
function fillShakeBones() {
  const select = document.getElementById('shake-bone');
  const order = [...SLOT_BONES, ...Object.keys(BONE_NAMES).map(Number).filter(id => !SLOT_BONES.includes(id))];
  select.replaceChildren(...order.map(id => new Option(BONE_NAMES[id], id)));
}
function startShakeAssign() {
  return cmd({ StartShakeAssign: +document.getElementById('shake-bone').value });
}
function renderShakeAssign(d) {
  const pending = Number.isInteger(d.pending_shake_bone) ? d.pending_shake_bone : null;
  const status = document.getElementById('shake-status');
  if (pending != null) status.textContent = `請用力搖一下要戴在「${BONE_NAMES[pending] ?? pending}」的追蹤器（其他追蹤器先別動）…`;
  else if (shakePendingBone != null) {
    const holder = Object.values(d.trackers || {}).find(t => t && t.assigned_bone === shakePendingBone);
    status.textContent = holder ? `已指派：追蹤器 ${holder.id} → ${BONE_NAMES[shakePendingBone]}。` : '已取消搖動指派。';
  }
  shakePendingBone = pending;
  document.getElementById('shake-start').disabled = pending != null;
  document.getElementById('shake-bone').disabled = pending != null;
  document.getElementById('shake-cancel').hidden = pending == null;
}
const DEFAULT_LEG_RATIO = 0.9;
let legRatio = null;
function updateBody(d) {
  renderShakeAssign(d);
  if (Number.isFinite(d.leg_ratio)) {
    legRatio = d.leg_ratio;
    document.getElementById('leg-ratio').textContent = '比例 ' + d.leg_ratio.toFixed(3);
  }
  setSlider('s-floor', 'v-floor', d.floor_offset);
  applySettings(d.settings);
  headsetAgeMs = Number.isFinite(d.headset_age_ms) && d.headset_age_ms >= 0 ? d.headset_age_ms : null;
  headsetAt = performance.now()/1000;
  legState = {calibrating: d.leg_calibrating === true,
    samples: Number.isInteger(d.leg_calibration_samples) ? d.leg_calibration_samples : 0,
    result: typeof d.leg_calibration_result === 'string' ? d.leg_calibration_result : null};
  renderLegCalibration();
}
function headsetLive() {
  return headsetAgeMs != null && headsetAgeMs + (performance.now()/1000 - headsetAt)*1000 < 500;
}
const LEG_RESULTS = {
  done: ratio => `完成，腿長比例 ${ratio}。`,
  no_samples: () => '沒有收集到資料：校正時需要頭戴裝置，以及左大腿、左小腿的追蹤器都在傳送資料。',
  small_swing: metres => `頭只移動了 ${Math.round(metres*100)} 公分，請蹲得更深（至少 15 公分）再試一次。`,
  unsolvable: () => '站姿和蹲姿的腿部角度太接近，請蹲得更深再試一次。',
  out_of_range: ratio => `算出的比例 ${ratio} 不合理，保留原本的設定。請再試一次。`,
};
function renderLegCalibration() {
  const live = headsetLive(), bones = new Set(liveTrackers().map(t => t.assigned_bone));
  document.getElementById('headset-status').textContent = live ? '頭戴裝置：已連線' : '頭戴裝置：未連線（Quest 姿態送到 UDP 9002）';
  const missing = [!live && '頭戴裝置', !bones.has(10) && '左大腿追蹤器', !bones.has(11) && '左小腿追蹤器'].filter(Boolean);
  document.getElementById('leg-start').disabled = !backendConnected || legState.calibrating || missing.length > 0;
  document.getElementById('leg-stop').disabled = !backendConnected || !legState.calibrating;
  document.getElementById('leg-reset').disabled = !backendConnected || legState.calibrating ||
    legRatio == null || Math.abs(legRatio - DEFAULT_LEG_RATIO) < 5e-4;
  const [code, value] = (legState.result || '').split(':');
  let text;
  if (!backendConnected) text = '後端沒有連線。';
  else if (legState.calibrating) text = `校正中：已收集 ${legState.samples} 筆。站直後慢慢蹲到底再站起來，然後按「停止」。` +
    (missing.length ? `目前缺少${missing.join('、')}，收不到資料。` : '');
  // "No samples" only repeats a missing requirement, which is named instead.
  else text = [!(code === 'no_samples' && missing.length) && LEG_RESULTS[code]?.(value),
    missing.length && `需要${missing.join('、')}才能校正。`].filter(Boolean).join(' ');
  const status = document.getElementById('leg-status');
  if (status.textContent !== text) status.textContent = text;
}
// Controls show the backend's saved settings rather than their HTML defaults,
// so a slider group never sends defaults back over saved values.
function applySettings(s) {
  if (!s || typeof s !== 'object') return;
  setSlider('s-ik', 'v-ik', s.ik_smoothness);
  setSlider('s-leg', 'v-leg', s.prop_leg);
  setSlider('s-arm', 'v-arm', s.prop_arm);
  setSlider('s-spine', 'v-spine', s.prop_spine);
  setSlider('s-cutoff', 'v-cutoff', s.smoothing_min_cutoff);
  setSlider('s-beta', 'v-beta', s.smoothing_beta);
  setSlider('s-drift', 'v-drift', s.drift_correction);
  for (const mode of ['rk4', 'euler']) {
    const button = document.getElementById('traj-' + mode);
    const active = s.trajectory_integration_mode === mode;
    button.classList.toggle('primary', active);
    button.setAttribute('aria-pressed', String(active));
  }
  setField('osc-ip', s.osc_ip);
  setField('osc-port', s.osc_port);
  setField('zupt-en', s.zupt_enabled);
  setField('zupt-win', s.zupt_window_size);
  setField('zupt-accel', s.zupt_accel_var_threshold);
  setField('zupt-gyro', s.zupt_gyro_threshold);
  setField('ser-en', s.serial_enabled);
  setField('ser-port', s.serial_port);
  setField('ser-baud', s.serial_baud);
}
// Fields applied with a button: keep an edit that has not been applied yet.
function setField(id, val) {
  const el = document.getElementById(id);
  if (val == null || !el || document.activeElement === el) return;
  const checkbox = el.type === 'checkbox';
  const current = checkbox ? String(el.checked) : el.value;
  const text = checkbox ? String(Boolean(val)) : String(val);
  if (current !== text && el.dataset.backend !== undefined && current !== el.dataset.backend) return;
  if (checkbox) el.checked = Boolean(val); else el.value = text;
  el.dataset.backend = text;
}
function setSlider(id, vid, val) {
  if (val == null) return;
  const el = document.getElementById(id);
  if (el && document.activeElement !== el) {
    el.value = val;
    document.getElementById(vid).textContent = (+val).toFixed(2);
  }
}
// The backend's latest Bluetooth event (snapshot ble_status), in words.
function bleStatusText(status) {
  if (typeof status !== 'string' || !status) return '';
  const split = status.indexOf(':'), kind = split < 0 ? status : status.slice(0, split), detail = split < 0 ? '' : status.slice(split + 1);
  switch (kind) {
    case 'ble_scanning': return '藍牙：正在搜尋追蹤器。';
    case 'ble_unavailable': return `藍牙無法使用（${detail}）。請在 Windows 設定開啟藍牙，後端會自動重試。`;
    case 'ble_discovered': return '藍牙：找到追蹤器，連線中…';
    case 'ble_connected': return '藍牙：追蹤器已連線。';
    case 'ble_connect_error': return '藍牙：連線失敗，正在重試。';
    case 'ble_subscribe_error': return '藍牙：已連線但無法接收追蹤器資料，會重新連線。';
    case 'ble_disconnected': return '藍牙：有追蹤器斷線，回到範圍內會自動重連。';
    default: return '藍牙：' + status;
  }
}
// An unreadable config.json is replaced by defaults at backend start: say so once.
let configWarningShown = false;
function showConfigWarning(warning) {
  if (typeof warning !== 'string' || !warning || configWarningShown) return;
  configWarningShown = true;
  const split = warning.lastIndexOf('|'), problem = warning.slice(0, split), backup = warning.slice(split + 1);
  showPanelNotice(`config.json 讀不到，後端改用預設設定（${problem}）。` + (backup ?
    `原檔已備份為 ${backup}：修好後改名回 config.json，再用 run.ps1 -Restart 重新啟動。` : '原檔無法備份，請手動檢查 config.json。'), 30);
}
function updateSystem(d) {
  showConfigWarning(d.config_warning);
  const ble = document.getElementById('ble-status');
  ble.textContent = bleStatusText(d.ble_status);
  ble.title = d.ble_status || '';
  ble.style.color = typeof d.ble_status === 'string' && d.ble_status.startsWith('ble_unavailable') ? 'var(--amber)' : '';
  const dot = document.getElementById('rec-dot');
  const status = document.getElementById('rec-status');
  const text = document.getElementById('rec-text');
  if (d.is_recording) {
    status.classList.add('recording');
    if (d.recorder_filename) lastRecordingFile = d.recorder_filename;
    text.textContent = '錄製中' + (d.recorder_filename ? '：' + d.recorder_filename : '') + '（遺失 ' + (d.recorder_dropped_count || 0) + ' 筆' +
      (d.recorder_write_errors ? '，寫入錯誤 ' + d.recorder_write_errors + ' 次' : '') + '）';
  } else {
    status.classList.remove('recording');
    text.textContent = lastRecordingFile ? '待機 · 上次存成 ' + lastRecordingFile : '待機';
  }
  document.getElementById('rec-start').disabled = d.is_recording === true;
  document.getElementById('rec-stop').disabled = d.is_recording !== true;
  const recError = typeof d.recorder_error === 'string' ? d.recorder_error : '', split = recError.indexOf(':');
  document.getElementById('rec-error').textContent = !recError ? '' :
    (RECORDER_ERRORS[recError.slice(0, split)] || '錄製錯誤') + '：' + recError.slice(split + 1);
  document.getElementById('ser-status').textContent = serialStatusText(d);
  const s = d.settings || {}, osc = document.getElementById('osc-status'), target = `${s.osc_ip}:${s.osc_port}`;
  osc.textContent = d.osc_active === false ? `OSC 沒有輸出：${d.osc_error || target + ' 無法使用'}。請改成可用的 IP 與埠。` :
    d.osc_error ? `無法改用 ${d.osc_error}，仍送到 ${target}。` : s.osc_ip ? `正在送到 ${target}。` : '';
  osc.style.color = d.osc_active === false || d.osc_error ? 'var(--amber)' : '';
}
let lastRecordingFile = null;
const RECORDER_ERRORS = {open: '無法建立錄製檔', write: '寫入失敗，已停止錄製'};
const SERIAL_STATUS = {
  opened: ([port]) => `已開啟 ${port}，正在接收資料。`,
  parse_error: ([port, ...error]) => `${port} 收到無法解析的資料：${error.join(':')}`,
  non_utf8: ([port, bytes]) => `${port} 收到非文字資料（${bytes}），請確認鮑率。`,
  error: ([port, ...error]) => `${port} 錯誤：${error.join(':')}`,
  disconnected: ([port]) => `${port} 已中斷，稍後自動重新連線。`,
  reconnect_scheduled: ([port, attempt]) => `正在重新連接 ${port}（第 ${attempt} 次）。`,
};
function serialStatusText(d) {
  if (d.settings?.serial_enabled !== true) return '序列埠未啟用。';
  if (!d.serial_running) return d.settings.serial_port ? '序列埠已停止。' : '請先填入序列埠名稱再套用。';
  const status = typeof d.serial_status_msg === 'string' ? d.serial_status_msg : '';
  if (!status) return '序列埠：啟動中…';
  const [kind, ...rest] = status.split(':');
  return SERIAL_STATUS[kind]?.(rest) ?? '序列埠：' + status;
}

// Name each control after the label beside it: the labels are spans, not <label>s.
document.querySelectorAll('.slider-row, .row').forEach(row => {
  const label = row.querySelector('.field-label'), control = row.querySelector('input, select');
  if (label && control && !control.hasAttribute('aria-label') && !control.labels?.length)
    control.setAttribute('aria-label', label.textContent.trim());
});
// The backend defaults (AppConfig::default) for every control on the Body tab
// except the leg calibration result.
const BODY_DEFAULTS = [{SetIkSmoothness: 0.5}, {SetProportions: {leg: 1, arm: 1, spine: 1}},
  {SetSmoothingParams: {min_cutoff: 3, beta: 3}}, {SetFloorOffset: 0}, {SetDriftCorrection: 0},
  {SetTrajectoryIntegrationMode: 'rk4'}];
// A leg calibration that went wrong can be undone without redoing it.
function resetLegRatio() {
  if (!confirm(`把腿長比例還原成預設值 ${DEFAULT_LEG_RATIO.toFixed(3)}？`)) return false;
  return cmd({SetLegRatio: DEFAULT_LEG_RATIO});
}
function resetBodySettings() {
  if (!confirm('把這一頁的比例、平滑、濾波、地板、漂移與軌跡設定還原成預設值？腿長校正的結果不變。')) return false;
  return BODY_DEFAULTS.every(command => cmd(command));
}
function sliderVal(el, vid) { document.getElementById(vid).textContent = (+el.value).toFixed(2); }
function sendProp() {
  cmd({ SetProportions: {
    leg:   +document.getElementById('s-leg').value,
    arm:   +document.getElementById('s-arm').value,
    spine: +document.getElementById('s-spine').value,
  }});
}
function sendSmooth() {
  cmd({ SetSmoothingParams: {
    min_cutoff: +document.getElementById('s-cutoff').value,
    beta:       +document.getElementById('s-beta').value,
  }});
}
// Values the backend cannot use are refused here with a reason; a blank or
// mistyped number would otherwise reach it as 0 or null.
const IPV4 = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;
const isInteger = (value, min, max) => /^\d+$/.test(value.trim()) && +value >= min && +value <= max;
function applyOsc() {
  const ip = document.getElementById('osc-ip').value.trim(), port = document.getElementById('osc-port').value;
  if (!IPV4.test(ip) || !isInteger(port, 1, 65535)) {
    showPanelNotice('OSC 沒有套用：IP 要是像 127.0.0.1 的 IPv4 位址，埠要是 1–65535 的整數。', 8);
    return false;
  }
  return cmd({ SetOscTarget: [ip, +port] });
}
function applyZupt() {
  const win = document.getElementById('zupt-win').value, accel = document.getElementById('zupt-accel').value,
    gyro = document.getElementById('zupt-gyro').value;
  const positive = value => value.trim() !== '' && Number.isFinite(+value) && +value > 0;
  if (!isInteger(win, 1, 200) || !positive(accel) || !positive(gyro)) {
    showPanelNotice('ZUPT 沒有套用：視窗要是 1–200 的整數，兩個門檻要是大於 0 的數字。', 8);
    return false;
  }
  if (!cmd({ SetZuptParams: { window_size: +win, accel_var_threshold: +accel, gyro_threshold: +gyro } })) return false;
  showPanelNotice(`已套用 ZUPT：視窗 ${+win}，加速度變異 ${+accel}，陀螺儀門檻 ${+gyro}。`, 4);
  return true;
}
// Records with the fields above. An empty name gets a dated one, so a new
// recording never overwrites an earlier file.
function startRecording() {
  let name = document.getElementById('rec-file').value.trim();
  if (/[<>:"/\\|?*]/.test(name)) {
    document.getElementById('rec-error').textContent = '檔名不能包含 < > : " / \\ | ? * 這些字元。';
    return false;
  }
  if (name && !/\.[a-z0-9]+$/i.test(name)) name += '.csv';
  // Blank uses the backend default; anything else must be a whole number in range.
  const batch = document.getElementById('rec-batch').value, flush = document.getElementById('rec-flush').value;
  if (batch.trim() && !isInteger(batch, 1, 10000) || flush.trim() && !isInteger(flush, 10, 60000)) {
    document.getElementById('rec-error').textContent = '批次要是 1–10000 的整數，寫入間隔要是 10–60000 ms 的整數（留空用預設值）。';
    return false;
  }
  return cmd({ SetRecorderConfig: {
    enabled:           true,
    filename:          name || null,
    batch_size:        batch.trim() ? +batch : null,
    flush_interval_ms: flush.trim() ? +flush : null,
  }});
}
function applySerial() {
  const enabled = document.getElementById('ser-en').checked;
  if (enabled && !document.getElementById('ser-port').value.trim() || !isInteger(document.getElementById('ser-baud').value, 1, 4000000)) {
    showPanelNotice('序列埠沒有套用：啟用時要填埠名稱（例如 COM3），鮑率要是正整數。', 8);
    return false;
  }
  return cmd({ SetSerialConfig: {
    enabled: document.getElementById('ser-en').checked,
    port:    document.getElementById('ser-port').value,
    baud:    +document.getElementById('ser-baud').value,
  }});
}
