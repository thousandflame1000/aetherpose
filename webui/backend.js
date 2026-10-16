// Aetherpose page: the backend WebSocket, panel notices and snapshot dispatch.
// Classic script: top-level names are shared with the other page scripts,
// which index.html loads in order (scene, pose, games, backend, trackers, settings, library, main).

// ── WebSocket (Rust backend) ────────────────────────────────────────────────
let ws = null;
function connect() {
  ws = new WebSocket(WS_URL);
  ws.onopen  = () => setStatus(true);
  ws.onclose = () => { setStatus(false); setTimeout(connect, 2000); };
  ws.onerror = () => ws.close();
  ws.onmessage = (e) => { try { onMessage(JSON.parse(e.data)); } catch(_){} };
}
function cmd(c) {
  if (ws && ws.readyState === 1) { ws.send(JSON.stringify(c)); return true; }
  showPanelNotice('未送出：後端沒有連線。請用 run.ps1 啟動服務，頁面會自動重新連線。');
  return false;
}
// A short message under the panel header, e.g. an action that could not be sent.
let panelNoticeTimer = null;
function showPanelNotice(text, seconds = 5) {
  const notice = document.getElementById('panel-notice');
  const sceneNotice = document.getElementById('scene-notice');
  document.getElementById('panel-notice-text').textContent = text; notice.hidden = false;
  sceneNotice.textContent = text; sceneNotice.hidden = false;
  clearTimeout(panelNoticeTimer);
  panelNoticeTimer = setTimeout(hidePanelNotice, seconds * 1000);
}
function hidePanelNotice() {
  clearTimeout(panelNoticeTimer);
  document.getElementById('panel-notice').hidden = true;
  document.getElementById('scene-notice').hidden = true;
}
document.getElementById('panel-notice-close').addEventListener('click', hidePanelNotice);
document.getElementById('scene-notice').addEventListener('click', hidePanelNotice);
let backendConnected = false;
let pendingBackendSnapshot = null, backendRenderTimer = null;
let lastBackendRenderAt = -Infinity, lastBackendPanelKey = null;
const BACKEND_PANEL_INTERVAL_MS = 100;
// Headset (Quest bridge) pose: the backend ignores it after 500 ms, and the
// page ages the last report the same way when snapshots stop.
let headsetAgeMs = null, headsetAt = 0, legState = {calibrating:false, samples:0, result:null};
function setStatus(ok) {
  backendConnected = ok;
  document.getElementById('status-dot').className = 'dot' + (ok ? ' on' : '');
  document.getElementById('status-text').textContent = ok ? '已連線' : '未連線';
  if (!ok) {
    clearTimeout(backendRenderTimer); backendRenderTimer=null;
    pendingBackendSnapshot=null; lastBackendPanelKey=null; lastBackendRenderAt=-Infinity;
    updateTrackers({});
    headsetAgeMs = null; legState = {calibrating:false, samples:0, result:null};
    renderLegCalibration();
    document.getElementById('ble-status').textContent = '';
    if (skelLines) skelLines.visible = false;
  }
}

function onMessage(msg) {
  if (msg.type !== 'Snapshot') return;
  const d = msg.data;
  const receivedAt=performance.now();
  // Keep freshness and assignment queries at the input rate. Expensive DOM
  // and diagnostic geometry updates only need the newest snapshot at 10 Hz.
  trackerSnapshot=d.trackers||{}; trackerSnapshotAt=receivedAt/1000;
  headsetAgeMs=Number.isFinite(d.headset_age_ms)&&d.headset_age_ms>=0?d.headset_age_ms:null;
  headsetAt=receivedAt/1000;
  const {packet_count,bones,trackers,headset_age_ms,leg_calibration_samples,...panelState}=d;
  const panelKey=JSON.stringify([panelState,headsetAgeMs!==null&&headsetAgeMs<500,
    Object.entries(trackerSnapshot).filter(([,t])=>t&&typeof t==='object')
      .map(([id,t])=>[id,t.assigned_bone,t.connection_type,trackerAge(t)<=500,Number.isFinite(t.battery)&&t.battery<=LOW_BATTERY])]);
  pendingBackendSnapshot={data:d,receivedAt};
  if (panelKey!==lastBackendPanelKey || receivedAt-lastBackendRenderAt>=BACKEND_PANEL_INTERVAL_MS) {
    lastBackendPanelKey=panelKey;
    flushBackendSnapshot();
  } else if (backendRenderTimer===null) {
    backendRenderTimer=setTimeout(flushBackendSnapshot,Math.max(0,BACKEND_PANEL_INTERVAL_MS-(receivedAt-lastBackendRenderAt)));
  }
}
function flushBackendSnapshot() {
  clearTimeout(backendRenderTimer); backendRenderTimer=null;
  const pending=pendingBackendSnapshot;
  pendingBackendSnapshot=null;
  if (!pending) return;
  lastBackendRenderAt=performance.now();
  renderBackendSnapshot(pending.data,pending.receivedAt);
}
function renderBackendSnapshot(d,receivedAt) {
  document.getElementById('pkt').textContent = (d.packet_count || 0).toLocaleString() + ' 個封包';
  updateTrackers(d.trackers || {},receivedAt/1000);
  const age=d.headset_age_ms;
  updateBody({...d,headset_age_ms:Number.isFinite(age)&&age>=0?age+Math.max(0,performance.now()-receivedAt):null});
  updateSystem(d);
  updateSkeleton(d.bones || []);
}
