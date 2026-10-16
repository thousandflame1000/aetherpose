// Aetherpose page: tracker lists, the setup checklist, local tools (webui/server.py) and assignment.
// Classic script: top-level names are shared with the other page scripts,
// which index.html loads in order (scene, pose, games, backend, trackers, settings, library, main).

// ── Trackers ───────────────────────────────────────────────────────────────
function boneOptions(selected) {
  // The avatar (TransPose) uses only the six slot parts; the rest feed the IK skeleton alone.
  const option = id => `<option value="${id}" ${selected != null && +id === selected ? 'selected' : ''}>${BONE_NAMES[id]}</option>`;
  const others = Object.keys(BONE_NAMES).map(Number).filter(id => !SLOT_BONES.includes(id));
  return `<option value="">未指派</option><optgroup label="3D 人體與 IK 骨架">${SLOT_BONES.map(option).join('')}</optgroup>` +
    `<optgroup label="只用於 IK 骨架（OSC、錄製）">${others.map(option).join('')}</optgroup>`;
}
const calibrationRows = new Map();
const monitorRows = new Map();
let trackerSnapshot = {}, trackerSnapshotAt = 0, lastTrackerRenderAt = 0;
// Local tools (webui/server.py); firmwareMag stays null when the page has no such API.
let firmwareMag = null, toolState = null, toolPolling = false;
function refreshTrackers(t) {
  if (t - lastTrackerRenderAt < .2) return;
  updateTrackers(trackerSnapshot,trackerSnapshotAt,true);
  renderLegCalibration();
  lastTrackerRenderAt = t;
}

// Trackers streaming right now (same 500 ms rule as the tracker list).
function liveTrackers() {
  const elapsed = Math.max(0, (performance.now()/1000 - trackerSnapshotAt) * 1000);
  return Object.values(trackerSnapshot || {}).filter(t => t && typeof t === 'object' && trackerAge(t, elapsed) <= 500);
}
function trackerAge(t, elapsed = 0) {
  const age = 'last_update_ms' in t ? t.last_update_ms : 0;
  return Number.isFinite(age) && age >= 0 ? age + elapsed : Infinity;
}
function trackerRow(container, rows, id, template) {
  let row = rows.get(id);
  if (row) return row;
  row = document.createElement('div');
  row.className = 'tracker';
  row.dataset.trackerId = id;
  row.innerHTML = template;
  if (!rows.size) container.replaceChildren();
  const next = [...rows.keys()].sort((a,b)=>+a-+b).find(key=>+key>+id);
  container.insertBefore(row,next ? rows.get(next) : null);
  rows.set(id,row);
  row.querySelector('.badge').textContent = id;
  return row;
}
function pruneTrackers(container, rows, ids, emptyId) {
  for (const [id,row] of rows) {
    if (!ids.includes(id)) { row.remove(); rows.delete(id); }
  }
  if (!ids.length) {
    let message = container.querySelector('#'+emptyId);
    if (!message) {
      message = document.createElement('div');
      message.id = emptyId;
      container.replaceChildren(message);
    }
    // No trackers can mean the backend is not running at all: say which.
    message.textContent = backendConnected ?
      '還沒有追蹤器連線。' :
      '後端沒有連線。請用 run.ps1 啟動服務，頁面會自動重新連線。';
  }
}
// Low battery: warn once when a tracker reaches LOW_BATTERY, again only after
// it has been charged above LOW_BATTERY_RESET.
const LOW_BATTERY = 15, LOW_BATTERY_RESET = 25, lowBatteryWarned = new Set();
const WEAK_RSSI_DBM = -80, HIGH_LOSS_PERCENT = 5;
function warnLowBattery(trackers, ids) {
  const newlyLow = [];
  for (const id of ids) {
    const battery = trackers[id].battery;
    if (!Number.isFinite(battery)) continue;
    if (battery >= LOW_BATTERY_RESET) lowBatteryWarned.delete(id);
    else if (battery <= LOW_BATTERY && !lowBatteryWarned.has(id)) { lowBatteryWarned.add(id); newlyLow.push(id); }
  }
  if (newlyLow.length) showPanelNotice(newlyLow.map(id => `追蹤器 ${id}（${BONE_NAMES[trackers[id].assigned_bone] ?? '未指派'}）電量剩 ${Math.round(trackers[id].battery)}%`).join('；') +
    '，請盡快充電，電量耗盡會中斷追蹤。', 10);
}
// The backend sends its ConnectionType names (Ble, Udp, Serial, Unknown).
const CONNECTION_NAMES = {ble: '藍牙', udp: 'Wi-Fi', serial: 'USB', unknown: '未知'};
// First-use checklist: connect trackers, assign the six TransPose slots,
// calibrate the body, then play. Missing slots are filled with demo data.
const SLOT_BONES = [4, 2, 32, 42, 11, 21];
function renderSetupSteps() {
  const live = liveTrackers(), bones = new Set(live.map(t => t.assigned_bone));
  const missing = SLOT_BONES.filter(id => !bones.has(id)).map(id => BONE_NAMES[id]);
  const source = aetherPoseSource(bridgeStatus).kind;
  const steps = [
    ['connect', live.length > 0, live.length ? `已連上 ${live.length} 顆追蹤器。` :
      backendConnected ? '打開追蹤器，等它們透過藍牙連上。' : '後端沒有連線：請用 run.ps1 啟動服務。'],
    ['assign', missing.length === 0, missing.length ? `把追蹤器指派到 6 個部位，還缺：${missing.join('、')}。缺的部位用示範資料補。` :
      '6 個部位都已指派。'],
    ['calibrate', (source === 'live' || source === 'mixed') && !bridgeStatus.includes('uncalibrated'),
      (source === 'live' || source === 'mixed') && !bridgeStatus.includes('uncalibrated') ? '身體已校正。' : '戴好後按下方「校正身體」。'],
  ];
  const current = steps.findIndex(([, done]) => !done);
  steps.forEach(([name, done, text], index) => {
    const item = document.querySelector(`#setup-steps [data-step="${name}"]`);
    item.classList.toggle('done', done); item.classList.toggle('current', index === current);
    item.querySelector('.step-mark').textContent = done ? '✓' : String(index + 1);
    item.querySelector('.step-text').textContent = text;
  });
  document.querySelector('#setup-steps [data-step="play"]').classList.toggle('current', current < 0);
  document.getElementById('setup-steps').classList.toggle('all-done', current < 0);
  const doneCount = steps.filter(([, done]) => done).length;
  document.getElementById('setup-summary').textContent = current < 0 ? '全部就緒' : `完成 ${doneCount} / 3`;
  // A pose model error blocks every step after the trackers: keep its reason here.
  const error = document.getElementById('setup-error');
  error.hidden = source !== 'error';
  error.textContent = source === 'error' ? '姿態模型有問題，人體與遊戲都無法使用：' +
    bridgeStatus.replace(/^(Error|Infer err):\s*/, '') + '（詳見 logs/mesh_bridge.err.log）' : '';
}
function updateTrackers(trackers, receivedAt = performance.now()/1000, ageOnly = false) {
  if (!trackers || typeof trackers !== 'object') trackers = {};
  if (!ageOnly) { trackerSnapshot = trackers; trackerSnapshotAt = receivedAt; }
  const elapsed = Math.max(0,(performance.now()/1000-receivedAt)*1000);
  const ids = Object.keys(trackers).filter(id=> {
    const t = trackers[id];
    return Number.isInteger(+id) && +id>=0 && +id<=255 && t && typeof t==='object';
  }).sort((a,b)=>a-b);
  const live = ids.filter(id=>trackerAge(trackers[id],elapsed)<=500).length;
  const lowBattery = ids.filter(id=>Number.isFinite(trackers[id].battery) && trackers[id].battery<=LOW_BATTERY);
  document.getElementById('tracker-count').textContent = ids.length ?
    `即時 ${live} / 已知 ${ids.length}` + (lowBattery.length ? ` · 低電量 ${lowBattery.length}` : '') : '';
  if (!ageOnly) warnLowBattery(trackers, ids);
  const calEl = document.getElementById('cal-trackers');
  const monEl = document.getElementById('mon-trackers');
  pruneTrackers(calEl,calibrationRows,ids,'no-trackers');
  pruneTrackers(monEl,monitorRows,ids,'no-trackers-mon');
  for (const id of ids) {
    const t = trackers[id];
    const age = trackerAge(t,elapsed);
    const stale = age>500;
    const connection = (CONNECTION_NAMES[String(t.connection_type).toLowerCase()] ?? t.connection_type ?? '未知') + (stale ? ' / 未更新' : ' / 即時');
    const cal = trackerRow(calEl,calibrationRows,id,`
      <div class="tracker-top"><div class="badge"></div>
        <div class="tracker-id-col"><span class="conn"></span><span class="ik-only" hidden
          title="3D 人體只用頭、胸口、左右前臂、左右小腿這 6 個部位；這個部位只影響 IK 骨架（OSC 與錄製）。">只用於 IK 骨架</span></div>
        <select aria-label="指派的骨頭"></select></div>`);
    const select = cal.querySelector('select');
    if (!select.options.length) {
      select.innerHTML = boneOptions(null);
      select.setAttribute('aria-label','追蹤器 '+id+' 指派的骨頭');
      select.addEventListener('change',()=>assignBone(+id,select.value));
    }
    // The backend supports assigning a bone, not individually unassigning one.
    // Keep the empty option as a placeholder rather than offering a no-op.
    select.options[0].disabled = t.assigned_bone != null;
    if (document.activeElement !== select) select.value = t.assigned_bone == null ? '' : String(t.assigned_bone);
    cal.querySelector('.conn').textContent = connection;
    cal.querySelector('.ik-only').hidden = t.assigned_bone == null || SLOT_BONES.includes(t.assigned_bone);
    cal.classList.toggle('stale',stale);
    cal.title = Number.isFinite(age) ? '上次更新：'+Math.round(age)+' ms 前' : '沒有更新時間';

    const mon = trackerRow(monEl,monitorRows,id,`
      <div class="tracker-top"><div class="badge"></div>
        <div class="tracker-id-col"><span class="bone-name"></span><span class="conn"></span></div>
        <div class="batt-track" style="margin-left:auto"><div class="batt-fill"></div></div></div>
      <div class="tracker-metrics"><span data-metric="rate"></span><span data-metric="loss"></span>
        <span data-metric="rssi"></span><span data-metric="battery"></span><span data-metric="age"></span>
        <span data-metric="mag"></span><a class="axes-link" target="_blank" rel="noopener">三軸 ↗</a></div>`);
    const magMetric = mon.querySelector('[data-metric="mag"]'), magEntry = firmwareMag?.[id];
    magMetric.textContent = firmwareMag == null ? '' : magEntry ? '磁力計已校正' : '磁力計未校正';
    magMetric.title = firmwareMag == null ? '' : magEntry ?
      `韌體校正表裡有它的磁力計校正值${magEntry.date ? '（' + magEntry.date + '）' : ''}，燒錄後生效` :
      '韌體校正表裡沒有它的磁力計校正值：航向只靠陀螺儀，會漂移';
    const axesLink = mon.querySelector('.axes-link');
    if (!axesLink.getAttribute('href')) {
      axesLink.href = 'imu_axes.html?id=' + encodeURIComponent(id);
      axesLink.title = '開啟追蹤器 ' + id + ' 的韌體原始方向（X/Y/Z 軸、與參考姿態比對）';
    }
    mon.querySelector('.bone-name').textContent = (BONE_NAMES[t.assigned_bone] ?? '未指派') + (t.stationary ? ' / 靜止' : '');
    mon.querySelector('.conn').textContent = connection;
    mon.classList.toggle('stale',stale);
    const battery = Number.isFinite(t.battery) ? Math.min(100,Math.max(0,t.battery)) : null;
    const fill = mon.querySelector('.batt-fill');
    fill.style.width = (battery ?? 0)+'%';
    fill.style.background = battery>40 ? 'var(--green)' : battery>15 ? 'var(--amber)' : 'var(--red)';
    const metrics = {
      rate:Number.isFinite(t.tps) ? t.tps+' 次/秒' : '- 次/秒',
      loss:Number.isFinite(t.lost_packets) && Number.isFinite(t.received_packets) ?
        '遺失 '+(100*t.lost_packets/Math.max(t.received_packets,1)).toFixed(1)+'%' : '遺失 -',
      rssi:Number.isFinite(t.rssi) ? t.rssi+' dBm' : '- dBm',
      battery:battery == null ? '電量 -' : '電量 '+Math.round(battery)+'%',
      age:Number.isFinite(age) ? Math.round(age)+' ms 前' : '更新時間不明'
    };
    for (const [name,value] of Object.entries(metrics)) mon.querySelector('[data-metric="'+name+'"]').textContent=value;
    mon.querySelector('[data-metric="battery"]').style.color = battery != null && battery <= LOW_BATTERY ? 'var(--red)' : '';
    // Weak signal and heavy packet loss are what make tracking stutter: mark them.
    const lossRate = Number.isFinite(t.lost_packets) && Number.isFinite(t.received_packets) ? 100*t.lost_packets/Math.max(t.received_packets,1) : 0;
    const rssiMetric = mon.querySelector('[data-metric="rssi"]'), lossMetric = mon.querySelector('[data-metric="loss"]');
    const weak = Number.isFinite(t.rssi) && t.rssi <= WEAK_RSSI_DBM, lossy = lossRate > HIGH_LOSS_PERCENT;
    rssiMetric.style.color = weak ? 'var(--amber)' : '';
    rssiMetric.title = weak ? '訊號弱：讓追蹤器靠近電腦，或減少身體與牆壁的遮擋。' : '';
    lossMetric.style.color = lossy ? 'var(--amber)' : '';
    lossMetric.title = lossy ? '封包遺失偏高：動作會卡頓。通常是訊號弱或附近干擾太多。' : '';
  }
  renderMagTrackers(ids);
  renderSetupSteps();
}

// ── Local tools (webui/server.py) ──────────────────────────────────────────
const toolHeaders = {'Content-Type':'application/json','X-Aetherpose':'1'};
function renderMagTrackers(ids) {
  const select = document.getElementById('mag-tracker');
  const choices = [...new Set([...ids, ...Object.keys(firmwareMag || {})])].sort((a,b)=>a-b);
  if (document.activeElement !== select && select.dataset.ids !== choices.join(',')) {
    const current = select.value;
    select.replaceChildren(...choices.map(id => new Option('追蹤器 ' + id + (ids.includes(id) ? '' : '（未連線）'), id)));
    select.dataset.ids = choices.join(',');
    if (choices.includes(current)) select.value = current;
  }
  renderToolState();
}
function renderToolState(state) {
  if (state) toolState = state;
  const available = firmwareMag != null, running = Boolean(toolState?.running);
  const chosenId = document.getElementById('mag-tracker').value, chosen = chosenId !== '';
  const streaming = liveTrackers().some(t => String(t.id) === chosenId);
  const start = document.getElementById('mag-start');
  start.disabled = !available || running || !chosen || !streaming;
  start.title = chosen && !streaming ? '錄製需要這顆追蹤器正在連線並傳送資料；「只燒錄」不需要。' : '';
  document.getElementById('mag-flash-only').disabled = !available || running || !chosen;
  document.getElementById('mag-cancel').disabled = !available || !running;
  const status = document.getElementById('mag-status');
  if (!available) status.textContent = '本機工具需要用 run.ps1 啟動的頁面伺服器。';
  else if (!toolState || toolState.exit_code == null && !running) status.textContent = chosen && !streaming ?
    '要錄製，這顆追蹤器必須連線並正在傳送資料；「只燒錄」只需要 USB。' : chosen ? '' : '沒有可選的追蹤器：連上追蹤器後就能選。';
  else if (running) status.textContent = `${toolState.kind === 'flash' ? '正在燒錄' : '正在校正'}追蹤器 ${toolState.tracker_id}…`;
  else status.textContent = toolState.cancelled ? '已取消。' : toolState.exit_code === 0 ? '完成。' :
    `已停止（結束代碼 ${toolState.exit_code}），請看下方輸出。`;
  const log = document.getElementById('mag-log'), text = [...(toolState?.lines || []), toolState?.progress].filter(Boolean).join('\n');
  log.hidden = !text;
  if (log.textContent !== text) { log.textContent = text; log.scrollTop = log.scrollHeight; }
}
let firmwareMagRequest = 0;
async function refreshFirmwareMag() {
  const request = ++firmwareMagRequest;
  let entries = null;
  try {
    const response = await fetch('api/calibrations', {cache:'no-store'});
    if (!response.ok) throw Error('HTTP ' + response.status);
    const data = await response.json();
    entries = data && typeof data.trackers === 'object' && data.trackers ? data.trackers : {};
  } catch {}
  if (request !== firmwareMagRequest) return;  // a later refresh already answered
  firmwareMag = entries;
  updateTrackers(trackerSnapshot, trackerSnapshotAt, true);
}
async function pollTool() {
  if (toolPolling || firmwareMag == null) return;
  toolPolling = true;
  try {
    for (;;) {
      const response = await fetch('api/tool', {cache:'no-store'});
      if (!response.ok) break;
      const state = await response.json();
      renderToolState(state);
      if (!state.running) { if (state.exit_code != null) refreshFirmwareMag(); break; }
      await new Promise(resolve => setTimeout(resolve, 500));
    }
  } catch {} finally { toolPolling = false; }
}
async function startTool(kind) {
  const id = Number(document.getElementById('mag-tracker').value), status = document.getElementById('mag-status');
  if (!Number.isInteger(id)) return;
  try {
    const response = await fetch('api/tool/start', {method:'POST', headers:toolHeaders,
      body:JSON.stringify({kind, id, flash:document.getElementById('mag-flash').checked})});
    const data = await response.json();
    if (!response.ok) { status.textContent = data.error || '請求失敗（' + response.status + '）'; return; }
    renderToolState(data);
    pollTool();
  } catch (err) { status.textContent = '連不到頁面伺服器：' + err.message; }
}
async function cancelTool() {
  try { await fetch('api/tool/cancel', {method:'POST', headers:toolHeaders, body:'{}'}); } catch {}
  pollTool();
}
// These change only the IK skeleton, which the avatar does not show: confirm them.
function trackerAction(command, done, needsTrackers = false) {
  if (needsTrackers && backendConnected && !liveTrackers().length) {
    showPanelNotice('沒有連線中的追蹤器，沒有東西可以重設。', 5);
    return false;
  }
  if (!cmd(command)) return false;
  showPanelNotice(done, 4);
  return true;
}
// Auto Assign replaces every assignment, so ask first when there are some.
function autoAssign() {
  const assigned = Object.values(trackerSnapshot || {}).filter(t => t && t.assigned_bone != null).length;
  if (assigned && !confirm(`依 ID 順序重新指派所有已連線的追蹤器，會覆蓋目前 ${assigned} 顆的指派。要繼續嗎？`)) return false;
  return cmd('AutoAssign');
}
function assignBone(trackerId, boneId) {
  if (boneId === '') { cmd({ UnassignTracker: +trackerId }); return; }  // stays without a bone until assigned again
  if (!cmd({ AssignTracker: [trackerId, +boneId] })) return;
  // The backend gives a bone to one tracker only: the one holding it takes this tracker's old bone.
  const trackers = Object.values(trackerSnapshot || {}), previous = trackerSnapshot?.[trackerId]?.assigned_bone;
  const holder = trackers.find(t => t && String(t.id) !== String(trackerId) && t.assigned_bone === +boneId);
  if (holder) showPanelNotice(`${BONE_NAMES[+boneId]}原本是追蹤器 ${holder.id}，它改為` +
    (previous != null && previous !== +boneId ? `${BONE_NAMES[previous] ?? previous}（兩顆交換）。` : '未指派。'), 8);
}
