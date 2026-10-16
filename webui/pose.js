// Aetherpose page: backend IK skeleton lines, debug overlay, the pose service link and body calibration.
// Classic script: top-level names are shared with the other page scripts,
// which index.html loads in order (scene, pose, games, backend, trackers, settings, library, main).

// ── IK skeleton (driven by the Rust backend's "bones" snapshot field) ─────
let skelLines = null;
function boneColor(bid) {
  if (LEFT_BONE_IDS.has(bid))  return [0.0, 0.78, 0.78];
  if (RIGHT_BONE_IDS.has(bid)) return [1.0, 0.69, 0.35];
  return [0.78, 0.82, 0.86];
}
function updateSkeleton(bones) {
  if (!bones || !bones.length) return;
  const idx = {};
  const pts = bones.map((b, i) => { idx[b.id] = i; return new THREE.Vector3(b.pos[0], b.pos[1], b.pos[2]); });
  const positions = [], colors = [];
  for (const b of bones) {
    if (b.parent_id == null || !(b.parent_id in idx)) continue;
    const p1 = pts[idx[b.parent_id]], p2 = pts[idx[b.id]];
    positions.push(p1.x, p1.y, p1.z, p2.x, p2.y, p2.z);
    const c = boneColor(b.id);
    colors.push(...c, ...c);
  }
  if (!positions.length) return;
  if (skelLines) { poseScene.remove(skelLines); skelLines.geometry.dispose(); skelLines.material.dispose(); }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  const mat = new THREE.LineBasicMaterial({ vertexColors: true, linewidth: 2 });
  skelLines = new THREE.LineSegments(geo, mat);
  skelLines.visible=document.getElementById('debug-view').checked;
  poseScene.add(skelLines);
}
function setCollisionDebug(on) {
  scenePhysics.setDebug(on);
  document.getElementById('collision-legend').hidden=!on;
  document.getElementById('physics-status').hidden=!on;
}
function setDebugView(on) {
  document.body.classList.toggle('debug-view',Boolean(on));  // also reveals the performance numbers
  avatar.setDebug(on);
  AetherCombat.setDebug(on);
  if (skelLines) skelLines.visible=Boolean(on);
}

function tpStatusDisplay(status) {
  const source = aetherPoseSource(status);
  return [source.label,source.kind==='error' ? '#f0576b' : source.kind==='live' ? '#3ecf8e' :
    source.kind==='demo' ? '#8db4ff' : '#e0aa4c'];
}

// One mesh_bridge connection feeds both this control view and Combat mode.
// mesh_bridge sends JSON: the mesh's faces and skinning data once, then each
// pose's joints and joint rotations, from which the page skins the mesh.
let meshWs = null;
let lastJointVersion = null;
let bridgeStatus = '';
let lastDroppedInputFrames = null, inputOverloadUntil = 0;
function connectMeshBridge() {
  meshWs = new WebSocket(MESH_WS_URL);
  meshWs.onopen = () => {
    lastDroppedInputFrames=null; inputOverloadUntil=0;
    AetherCombat.onMeshOpen();
    reportPageVisibility();
  };
  meshWs.onmessage = (e) => {
    try {
      const m = JSON.parse(e.data);
      if (m.status) {
        if (aetherCalibrationIssue(m.status) && game.state==='playing')
          endGame('Body calibration required. Round stopped.');
        if (game.state === 'playing') trackPoseSource(aetherPoseSource(m.status));
        if (aetherPoseSource(bridgeStatus).signature !== aetherPoseSource(m.status).signature) scenePhysics.reset(avatar.root);
        if (aetherPoseSource(m.status).kind === 'error' && aetherPoseSource(bridgeStatus).kind !== 'error')
          showPanelNotice('姿態模型有問題：' + m.status.replace(/^(Error|Infer err):\s*/, '') + '（詳見 logs/mesh_bridge.err.log）', 20);
        bridgeStatus = m.status;
        renderSetupSteps();
        AetherCombat.onStatus(m.status);
        const [text, color] = tpStatusDisplay(m.status);
        const el = document.getElementById('tp-status'), uncalibrated = m.status.includes('uncalibrated');
        el.textContent = text + (uncalibrated ? ' · 未校正' : '');
        el.style.color = uncalibrated ? '#e0aa4c' : color; el.title = m.status;
      }
      if (m.runtime && typeof m.runtime.device==='string' && [m.runtime.pose_fps,m.runtime.frame_ms].every(value=>Number.isFinite(value)&&value>=0)) {
        const dropped=m.runtime.dropped_input_frames;
        if (Number.isSafeInteger(dropped) && dropped>=0) {
          if (lastDroppedInputFrames!==null && dropped>lastDroppedInputFrames) inputOverloadUntil=performance.now()+2000;
          else if (lastDroppedInputFrames!==null && dropped<lastDroppedInputFrames) inputOverloadUntil=0;
          lastDroppedInputFrames=dropped;
        }
        const performance_=document.getElementById('pose-performance'), slow=m.runtime.pose_fps<SLOW_POSE_FPS;
        const overloaded=performance.now()<inputOverloadUntil;
        // Players get the warning in words; the debug overlay keeps the timings.
        performance_.textContent=overloaded && !document.body.classList.contains('debug-view') ?
          '姿態推論跟不上，部分動作更新已略過。' : slow && !document.body.classList.contains('debug-view') ?
          `姿態更新偏慢：每秒 ${m.runtime.pose_fps.toFixed(1)} 個姿態` :
          `${m.runtime.device.toUpperCase()} · 每秒 ${m.runtime.pose_fps.toFixed(1)} 個姿態 · 姿態 ${m.runtime.frame_ms.toFixed(1)} ms`;
        // Games judge holds and fast moves from successive poses: say when they come too slowly.
        performance_.style.color=slow||overloaded?'var(--amber)':''; performance_.classList.toggle('slow',slow||overloaded);
        performance_.title=overloaded?'推論服務處理不及，輸入佇列已略過部分資料，遊戲的動作判定可能不準。請降低其他程式的 CPU 負載。':
          slow?'姿態更新太慢，遊戲的動作判定可能不準：關掉其他耗 CPU 的程式，或在有 NVIDIA 顯示卡的電腦上使用 CUDA。':'';
      }
      if (m.calibration) renderBodyCalibration(m.calibration);
      if (m.faces) AetherCombat.onFaces(m.faces);
      if (m.skin) AetherCombat.onSkin(m.skin);
      if (m.joints && (m.joints_version == null || m.joints_version !== lastJointVersion)) {
        const accepted = AetherCombat.onJoints(m.joints);
        if (accepted) {
          lastJointVersion = m.joints_version;
          if (m.pose && AetherCombat.onPose(m.pose)) finishBootSplash();
          if (!combatMode) updateGame(avatar.joints);
        }
      }

    } catch (err) { console.warn('mesh_bridge packet failed', err); }
  };
  meshWs.onclose = () => {
    lastJointVersion = null;
    document.getElementById('pose-performance').textContent='';
    AetherCombat.onMeshClose();
    const status = document.getElementById('tp-status');
    status.textContent = '姿態服務已斷線'; status.style.color = '#f0576b';
    status.title = '姿態服務（mesh_bridge，連接埠 9010）沒有回應，每 2 秒重試。請用 run.ps1 啟動服務；錯誤記錄在 logs/mesh_bridge.err.log。';
    // The last status no longer describes anything: forget it until the service is back.
    bridgeStatus = ''; renderSetupSteps();
    if (game.state === 'playing') endGame('Pose disconnected');
    setTimeout(connectMeshBridge, 2000);
  };
  meshWs.onerror = () => meshWs.close();
}
// The pose service infers only for a page someone can see: a background tab says so.
function reportPageVisibility() { sendToBridge({ cmd: 'visibility', visible: !document.hidden }); }
function sendToBridge(msg) {
  if (!meshWs || meshWs.readyState !== WebSocket.OPEN) return false;
  meshWs.send(JSON.stringify(msg));
  return true;
}
AetherCombat.setSender(sendToBridge);

// ── Body calibration (mesh_bridge maps live trackers into the body frame) ──
let bodyCalibrationPhase = 'idle';
const bodyCalibrationActive = phase => ['requested','tpose_ready','tpose','bow_ready','bow'].includes(phase);
function startBodyCalibration() {
  if (meshWs?.readyState !== WebSocket.OPEN) {
    document.getElementById('body-cal-status').textContent = '姿態服務沒有連線。';
    return false;
  }
  // The T-pose and bow would be scored, and the new calibration moves the pose mid-round.
  if (game.state === 'playing') endGame('Body calibration. Round stopped.');
  AetherCombat.stopRound('Body calibration. Round stopped.');
  const sent=sendToBridge({cmd:'calibrate_body'});
  if (sent) renderBodyCalibration({phase:'requested',message:'已送出校正要求，等待姿態服務回應。',seconds_left:0});
  return sent;
}
function cancelBodyCalibration() { sendToBridge({cmd:'cancel_body_calibration'}); }
function renderBodyCalibration(state) {
  if (!state || typeof state.phase !== 'string') return;
  AetherCombat.onCalibration(state);
  // Commands from another page/client must stop scoring too.
  if (bodyCalibrationActive(state.phase) && game.state==='playing')
    endGame('Body calibration. Round stopped.');
  // The T-pose hold just ended: reset the backend IK mounting from the same pose.
  if (bodyCalibrationPhase === 'tpose' && state.phase === 'bow_ready') cmd('ResetMounting');
  bodyCalibrationPhase = state.phase;
  const active = bodyCalibrationActive(state.phase), status = document.getElementById('body-cal-status');
  const torsoLive = liveTrackers().some(t => t.assigned_bone === 2 || t.assigned_bone === 4);
  const start = document.getElementById('body-cal-start');
  start.disabled = active || !torsoLive;
  start.title = torsoLive ? '' : '需要一顆已連線、指派到胸口或頭部的追蹤器。';
  document.getElementById('body-cal-cancel').disabled = !active;
  let text = String(state.message || '');
  if (active && state.seconds_left > 0) text += ' ' + Math.ceil(state.seconds_left) + ' s';
  if (state.phase === 'idle' && bridgeStatus.includes('uncalibrated')) text = '即時追蹤器尚未校正：按「校正身體」之前，人體姿態不正確。';
  if (state.phase === 'idle' && !torsoLive) text = '請連上追蹤器，並把其中一顆指派到胸口或頭部，才能校正。';
  status.textContent = text;
  status.style.color = state.phase === 'failed' || text.startsWith('即時追蹤器尚未校正') ? 'var(--amber)' : state.phase === 'done' ? 'var(--green)' : '';
}
