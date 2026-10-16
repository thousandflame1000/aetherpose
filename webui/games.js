// Aetherpose page: pose games — targets, records, sound, the round flow and each game's judgement.
// Classic script: top-level names are shared with the other page scripts,
// which index.html loads in order (scene, pose, games, backend, trackers, settings, library, main).

// ── Reach-target mini-game — pure IMU interaction, no mouse/keyboard ──────
// A timed round: reach out with a tracked hand (real or demo-playback) to
// pop targets before they expire. Consecutive hits within COMBO_WINDOW
// build a score multiplier; missing that window resets it.
const N_TARGETS       = 3;
const HIT_RADIUS      = 0.16;
const GAME_DURATION_S = 60;
const SLOW_POSE_FPS = 15;
const DEMO_CALIBRATION_HINT_MS = 6000;
const COMBO_WINDOW_MS = 1800;
const TARGET_SPAN   = new THREE.Vector3(0.45, 0.30, 0.35);

const targetMeshes = [];
const targetGeo = new THREE.SphereGeometry(0.06, 16, 16);
const targetMat = new THREE.MeshBasicMaterial({ color: 0xffd64c });

function spawnTargetPos(avoid = []) {
  const hip = avatar.joints ? avatar.joints[0] : [0,0,0];
  const center = avatar.root.localToWorld(new THREE.Vector3(hip[0],hip[1]+.28,hip[2]));
  let position;
  const clear=point=>avoid.every(hand=>hand.distanceTo(point)>HIT_RADIUS*2) && !scenePhysics.pointBlocked(point,.07);
  for (let attempt=0; attempt<32; attempt++) {
    position = new THREE.Vector3(
      center.x + (Math.random()*2-1) * TARGET_SPAN.x,
      center.y + (Math.random()*2-1) * TARGET_SPAN.y,
      center.z + (Math.random()*2-1) * TARGET_SPAN.z,
    );
    if (clear(position)) return position;
  }
  // A bounded fallback stays inside the reach volume even if randomness keeps
  // selecting a blocked point. Never walk targets arbitrarily far away.
  for (const x of [-1,-.5,0,.5,1]) for (const y of [-1,0,1]) for (const z of [-1,0,1]) {
    position=new THREE.Vector3(center.x+x*TARGET_SPAN.x,center.y+y*TARGET_SPAN.y,center.z+z*TARGET_SPAN.z);
    if (clear(position)) return position;
  }
  return null;
}
for (let i = 0; i < N_TARGETS; i++) {
  const m = new THREE.Mesh(targetGeo, targetMat);
  m.visible = false;
  const position=spawnTargetPos(); if (position) m.position.copy(position);
  poseScene.add(m);
  targetMeshes.push(m);
}

const game = { state: 'idle', score: 0, combo: 0, lastHitAt: 0, timeLeft: GAME_DURATION_S, deadline: 0 };
// Round-end reasons are English codes; avatar.js names them for people.
const reasonText=reason=>aetherReasonText(reason);
const poseGameNames={reach:'Reach Targets',squat:'Squat Rhythm',balance:'Balance Hold',dodge:'Dodge Flow',sky:'Sky Catch',clap:'Clap Pulse',march:'March Step',star:'Star Hold',cross:'Cross Knee',guard:'Guard Drill',shoulder:'Shoulder Tap',highfive:'High Five',bow:'Bow Rhythm'};
const historyStorageKey='aetherpose.round-history.v1';
function normalizeCombatHistory(entry) {
  if (entry.mode!=='combat') return entry;
  const stats=entry.combatStats,keys=['attempts','hits','targets','blocked','defenses','received','counters','bestCombo'];
  const valid=stats && !Array.isArray(stats) && keys.every(key=>Number.isSafeInteger(stats[key]) && stats[key]>=0) &&
    stats.hits<=stats.attempts && stats.targets<=stats.hits && stats.counters<=stats.targets && stats.blocked<=stats.attempts && stats.bestCombo<=12;
  return {...entry,difficulty:['easy','normal','hard'].includes(entry.difficulty)?entry.difficulty:undefined,
    combatStats:valid?Object.fromEntries(keys.map(key=>[key,stats[key]])):undefined,
    combatBreakdown:valid?aetherCombatBreakdown(stats,entry.combatBreakdown)??undefined:undefined};
}
function loadRoundHistory() {
  try {
    const saved=JSON.parse(localStorage.getItem(historyStorageKey)||'[]');
    if (!Array.isArray(saved)) return [];
    return saved.filter(entry=>entry && (entry.mode==='combat' || Object.hasOwn(poseGameNames,entry.mode)) &&
      Number.isSafeInteger(entry.at) && entry.at>0 && Number.isSafeInteger(entry.score) && entry.score>=0 &&
      /^(demo:0|live:6|mixed:[1-6])$/.test(entry.source) && typeof entry.completed==='boolean' &&
      typeof entry.reason==='string' && entry.reason.length<=140 && Number.isFinite(entry.seconds) &&
      entry.seconds>=0 && entry.seconds<=90).slice(0,50).map(normalizeCombatHistory);
  } catch (_) { return []; }
}
let roundHistory=loadRoundHistory();
function combatHistoryTotals(entries) {
  const totals={rounds:0,attempts:0,hits:0,defenses:0,counters:0,received:0,bestCombo:0};
  for (const entry of entries) {
    if (entry.mode!=='combat' || entry.completed!==true) continue;
    const stats=normalizeCombatHistory(entry).combatStats;
    if (!stats) continue;
    totals.rounds++;
    for (const key of ['attempts','hits','defenses','counters','received']) totals[key]+=stats[key];
    totals.bestCombo=Math.max(totals.bestCombo,stats.bestCombo);
  }
  return totals;
}
function renderRoundHistory() {
  const modeSelect=document.getElementById('history-mode');
  if (modeSelect.options.length===1) {
    for (const [mode,name] of Object.entries({combat:'Aether Combat',...poseGameNames})) {
      const option=document.createElement('option'); option.value=mode; option.textContent=name; modeSelect.add(option);
    }
  }
  const source=document.getElementById('history-source').value;
  const difficultySelect=document.getElementById('history-difficulty');
  const combatFilter=modeSelect.value==='all'||modeSelect.value==='combat';
  document.getElementById('history-difficulty-controls').hidden=!combatFilter;
  if (!combatFilter) difficultySelect.value='all';
  const difficulty=difficultySelect.value;
  const filtered=roundHistory.filter(entry=>(modeSelect.value==='all'||entry.mode===modeSelect.value) &&
    (source==='all'||entry.source.startsWith(source+':')) &&
    (difficulty==='all'||entry.mode==='combat' && (difficulty==='unknown'?!['easy','normal','hard'].includes(entry.difficulty):entry.difficulty===difficulty)));
  const filtering=modeSelect.value!=='all' || source!=='all' || difficulty!=='all';
  const totals=combatHistoryTotals(filtered),summary=document.getElementById('history-combat-summary');
  summary.hidden=totals.rounds===0;
  summary.textContent=totals.rounds?`目前篩選 · 有統計的完成對戰 ${totals.rounds} 場 · 命中 ${totals.hits}/${totals.attempts}（${totals.attempts?Math.round(totals.hits/totals.attempts*100):0}%） · 防守 ${totals.defenses} · 反擊 ${totals.counters} · 受擊 ${totals.received} · 最高連擊 ${totals.bestCombo}`:'';
  document.getElementById('history-matches').textContent=[filtering?`符合 ${filtered.length} 場 / 共 ${roundHistory.length} 場`:'',
    filtered.length>10?'顯示最近 10 場':''].filter(Boolean).join(' · ');
  document.getElementById('history-count').textContent=`${roundHistory.length} 場`;
  const list=document.getElementById('history-list'); list.replaceChildren();
  if (!roundHistory.length) { list.textContent='還沒有回合紀錄。'; return; }
  if (!filtered.length) { list.textContent='沒有符合篩選條件的回合。'; return; }
  for (const entry of filtered.slice(0,10)) {
    const row=document.createElement('div');
    const actions=document.createElement('div'); actions.style.cssText='display:flex;flex-wrap:wrap;gap:6px;margin-top:6px';
    row.style.cssText='padding:8px 0;border-bottom:1px solid var(--border);line-height:1.6';
    const source=entry.source==='demo:0'?'示範':entry.source==='live:6'?'即時':`混合 ${entry.source.split(':')[1]}/6`;
    row.textContent=`${entry.mode==='combat'?'Aether Combat':poseGameNames[entry.mode]} · ${entry.score} 分 · ${source} · ${entry.seconds} 秒 · ${entry.completed?'完成':'中斷'} — ${reasonText(entry.reason)} · ${new Date(entry.at).toLocaleString()}`;
    if (entry.mode==='combat') {
      const normalized=normalizeCombatHistory(entry),stats=normalized.combatStats;
      if (stats || normalized.difficulty) {
        const detail=document.createElement('div'); detail.style.cssText='font-size:12px;color:var(--text-dim)';
        detail.textContent=[normalized.difficulty?`難度：${{easy:'練習',normal:'標準',hard:'挑戰'}[normalized.difficulty]}`:'',
          stats?`命中 ${stats.hits}/${stats.attempts}（${stats.attempts?Math.round(stats.hits/stats.attempts*100):0}%） · 防守 ${stats.defenses} · 反擊 ${stats.counters} · 受擊 ${stats.received} · 最高連擊 ${stats.bestCombo}`:''].filter(Boolean).join(' · ');
        row.appendChild(detail);
        if (stats) { const advice=document.createElement('div'); advice.style.fontSize='12px'; advice.textContent=aetherCombatAdvice(stats,normalized.combatBreakdown); row.appendChild(advice); }
        const drill=stats?aetherCombatDrill(stats,normalized.combatBreakdown):null;
        if(drill) {
          const practice=document.createElement('button'); practice.className='btn'; practice.type='button'; practice.dataset.historyDrill=drill;
          practice.textContent={guard:'練習雙手防守',dodge:'練習側身閃避',reach:'練習伸手目標'}[drill];
          practice.addEventListener('click',()=>{selectRecordedGame(drill);dismissRoundResult();}); actions.appendChild(practice);
        }
      }
    }
    const replay=document.createElement('button'); replay.type='button'; replay.className='btn';
    replay.textContent='選回這款遊戲'; replay.dataset.historyGame=entry.mode;
    replay.setAttribute('aria-label',`選回 ${entry.mode==='combat'?'Aether Combat':poseGameNames[entry.mode]}`);
    replay.addEventListener('click',()=>selectRecordedGame(entry.mode));
    const download=document.createElement('button'); download.type='button'; download.className='btn'; download.textContent='匯出本回合';
    download.dataset.historyExport=entry.mode;
    download.setAttribute('aria-label',`匯出 ${entry.mode==='combat'?'Aether Combat':poseGameNames[entry.mode]} 回合紀錄`);
    download.addEventListener('click',()=>exportSingleRound(entry));
    actions.append(replay,download); row.appendChild(actions);
    list.appendChild(row);
  }
}
function recordRoundHistory(entry) {
  if (!/^(demo:0|live:6|mixed:[1-6])$/.test(entry.source)) return;
  roundHistory.unshift(normalizeCombatHistory({...entry,at:Date.now()})); roundHistory=roundHistory.slice(0,50);
  try { localStorage.setItem(historyStorageKey,JSON.stringify(roundHistory)); } catch (_) {}
  renderRoundHistory();
}
function clearRoundHistory() {
  roundHistory=[];
  try { localStorage.removeItem(historyStorageKey); } catch (_) {}
  renderRoundHistory();
}
function clearBestScores() {
  poseRecords={};
  combatDifficultyRecords={};
  try { localStorage.removeItem(combatDifficultyRecordKey); } catch (_) {}
  try { localStorage.removeItem(poseRecordKey); } catch (_) {}
  updateGameLibrary(); renderGameStats();
}
// The buttons ask first: history and best scores live only in this browser and cannot be restored.
function askClearRoundHistory() {
  if (!roundHistory.length) return false;
  if (!confirm(`清除全部 ${roundHistory.length} 場回合紀錄？最佳成績不受影響。`)) return false;
  clearRoundHistory(); return true;
}
function askClearBestScores() {
  const count=Object.keys(poseRecords).length+Object.keys(combatDifficultyRecords).length;
  if (!count) { showPanelNotice('還沒有最佳成績。',4); return false; }
  if (!confirm(`清除 ${count} 項最佳成績？回合紀錄不受影響。`)) return false;
  clearBestScores(); showPanelNotice('已清除最佳成績。',4); return true;
}
function exportRoundHistory() {
  const blob=new Blob([JSON.stringify({version:1,rounds:roundHistory},null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob);
  const link=document.createElement('a'); link.href=url; link.download='aetherpose-rounds.json';
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function exportSingleRound(entry) {
  const round=normalizeCombatHistory(entry);
  const blob=new Blob([JSON.stringify({version:1,rounds:[round]},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob);
  const link=document.createElement('a'); link.href=url; link.download=`aetherpose-${round.mode}-${round.at}.json`;
  document.body.appendChild(link);
  try { link.click(); } finally { link.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000); }
}
renderRoundHistory();
const poseRecordKey='aetherpose.game-records.v1';
// Best scores per game and input source; only these keys are kept.
const RECORD_KEY=/^(reach|squat|balance|dodge|sky|clap|march|star|cross|guard|shoulder|highfive|bow|combat):(demo:0|live:6|mixed:[1-6])$/;
function loadPoseRecords() {
  try {
    const saved=JSON.parse(localStorage.getItem(poseRecordKey)||'{}');
    const records={};
    if (!saved || typeof saved!=='object' || Array.isArray(saved)) return records;
    for (const [key,value] of Object.entries(saved)) {
      if (RECORD_KEY.test(key) &&
          Number.isSafeInteger(value) && value>=0 && value<=1000000) records[key]=value;
    }
    return records;
  } catch (_) { return {}; }
}
let poseRecords=loadPoseRecords();
const combatDifficultyRecordKey='aetherpose.combat-difficulty-records.v1';
function loadCombatDifficultyRecords() {
  try {
    const saved=JSON.parse(localStorage.getItem(combatDifficultyRecordKey)||'{}');
    if (!saved || Array.isArray(saved) || typeof saved!=='object') return {};
    return Object.fromEntries(Object.entries(saved).filter(([key,score])=>/^(easy|normal|hard):(demo:0|live:6|mixed:[1-6])$/.test(key) && Number.isSafeInteger(score)&&score>=0));
  } catch (_) { return {}; }
}
let combatDifficultyRecords=loadCombatDifficultyRecords();
function combatDifficultyBest(difficulty,source) { return combatDifficultyRecords[`${difficulty}:${source}`]||0; }
function saveCombatDifficultyBest(difficulty,source,score) {
  const key=`${difficulty}:${source}`;
  if (!/^(easy|normal|hard):(demo:0|live:6|mixed:[1-6])$/.test(key) || !Number.isSafeInteger(score) || score<0) return;
  combatDifficultyRecords[key]=Math.max(combatDifficultyRecords[key]||0,score);
  try { localStorage.setItem(combatDifficultyRecordKey,JSON.stringify(combatDifficultyRecords)); } catch (_) {}
  updateGameLibrary();
}
function poseBest() { return game.source ? poseRecords[`${game.mode}:${game.source.signature}`]||0 : 0; }  // no source before the first round
function saveBestScore(mode,signature,score) {
  const key=`${mode}:${signature}`;
  if (!RECORD_KEY.test(key)) return;
  poseRecords[key]=Math.max(poseRecords[key]||0,score);
  try { localStorage.setItem(poseRecordKey,JSON.stringify(poseRecords)); } catch (_) {}
  updateGameLibrary();
}
function savePoseBest() { saveBestScore(game.mode,game.source.signature,game.score); }
function changePoseGame() {
  if (game.state==='playing') endGame('Game changed');
  const mode=document.getElementById('game-mode').value;
  if (poseCircuit && mode!==poseCircuit.modes[poseCircuit.index]) { poseCircuit=null; renderPoseCircuit(); }
  updateGameLibrary();
  document.getElementById('game-btn').textContent=`開始 ${poseGameNames[mode]}`;
  document.getElementById('library-start').textContent=`開始 ${poseGameNames[mode]}`;
  document.getElementById('pose-game-cue').textContent=mode==='reach'?'伸手碰觸黃色目標。':
    mode==='squat'?'開始前先站直。下蹲並停一下，再站起來。':
    mode==='balance'?'開始前先站直。抬起提示的那隻腳並保持，軀幹維持直立。':
    mode==='dodge'?'往黃色提示的方向傾身並保持，再回到中間；左右交替。':
    mode==='clap'?'在胸前張開雙臂，再合掌，然後再張開。':
    mode==='march'?'抬起提示的膝蓋和腳並停一下，再雙腳落地；左右交替。':
    mode==='guard'?'雙手放在頭部兩側保持 0.8 秒，再把雙手放到胸口以下。':
    mode==='bow'?'向前彎身保持 0.6 秒，再站直。':
    mode==='highfive'?'用提示的那隻手碰高處的目標，再放下那隻手。':mode==='shoulder'?'雙手交叉碰到對側肩膀保持 0.6 秒，再放開雙手。':
    mode==='cross'?'用右手碰抬起的左膝，再換邊；每次之間先站好並放開。':
    mode==='star'?'雙臂伸直平舉到肩膀高度，再放下雙手準備下一次。':
    '雙手舉過頭接住目標，再放下雙手準備下一次。';
}
let audioCtx = null;
// The sound toggle is remembered in this browser.
const soundSettingKey='aetherpose.sound.v1';
function loadSoundSetting() {
  try { document.getElementById('game-sound').checked=localStorage.getItem(soundSettingKey)!=='off'; } catch (_) {}
}
document.getElementById('game-sound').addEventListener('change',event=>{
  try { localStorage.setItem(soundSettingKey,event.target.checked?'on':'off'); } catch (_) {}
});
const reachEffects = [];

// Game sounds: short tones with a soft attack (no clicks) and a quiet octave
// layer; start and end of a round get a short phrase. Muted means no AudioContext.
function tone(freq, delay, dur, type, level) {
  const at = audioCtx.currentTime + delay;
  const osc = audioCtx.createOscillator(), gain = audioCtx.createGain();
  osc.type = type; osc.frequency.value = freq;
  gain.gain.setValueAtTime(0.0001, at);
  gain.gain.linearRampToValueAtTime(level, at + 0.008);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + dur);
  osc.connect(gain); gain.connect(audioCtx.destination);
  osc.start(at); osc.stop(at + dur + 0.02);
}
function playNotes(notes, step = 0, dur = 0.12) {
  if (!document.getElementById('game-sound').checked) return;
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    notes.forEach((freq, i) => { tone(freq, i * step, dur, 'sine', 0.14); tone(freq * 2, i * step, dur * 0.6, 'triangle', 0.035); });
  } catch (_) {}
}
function beep(freq, dur = 0.12) { playNotes([freq], 0, dur); }
function playCue(kind) {
  playNotes(kind === 'start' ? [523, 659, 784] : [784, 659, 523, 1047], kind === 'start' ? 0.09 : 0.11, kind === 'start' ? 0.16 : 0.22);
}

function hitEffect(pos) {
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(0.02, 0.05, 24),
    new THREE.MeshBasicMaterial({ color: 0xffe08a, side: THREE.DoubleSide, transparent: true, opacity: 0.9 })
  );
  ring.position.copy(pos);
  ring.name = 'reach-hit-effect';
  ring.lookAt(camera.position);
  poseScene.add(ring);
  reachEffects.push({mesh:ring,at:performance.now()/1000});
}
function updateReachEffects(now) {
  for (let i=reachEffects.length-1;i>=0;i--) {
    const effect=reachEffects[i];
    const t=(now-effect.at)/.35;
    if (t>=1 || game.state!=='playing') {
      poseScene.remove(effect.mesh); effect.mesh.geometry.dispose(); effect.mesh.material.dispose();
      reachEffects.splice(i,1);
    } else {
      effect.mesh.scale.setScalar(1+t*6);
      effect.mesh.material.opacity=.9*(1-t);
    }
  }
}

function startGame() {
  if (poseCircuit?.waiting || poseCircuit?.finished) { poseCircuit=null; renderPoseCircuit(); }
  const source=aetherPoseSource(bridgeStatus).kind;
  if (combatMode || document.hidden) return;
  let unavailable='';
  if (meshWs?.readyState !== WebSocket.OPEN) unavailable='姿態服務沒有連線：請用 run.ps1 啟動服務，頁面會自動重新連線。';
  else if (source==='error') unavailable='姿態推論錯誤：'+bridgeStatus.replace(/^(Error|Infer err):\s*/,'');
  else if (bridgeStatus && source==='waiting') unavailable='等待姿態模型與追蹤資料。';
  else if (!avatar.fresh()) unavailable='等待完整的最新姿態，請檢查追蹤連線。';
  else unavailable=aetherCalibrationIssue(bridgeStatus,bodyCalibrationPhase);
  if (unavailable) { document.getElementById('pose-game-cue').textContent=unavailable; return; }
  game.state = 'playing';
  game.paused=false;
  game.mode=document.getElementById('game-mode').value;
  game.source=aetherPoseSource(bridgeStatus);
  const joints=avatar.joints;
  game.standingHeight=joints[15][1]-Math.min(joints[10][1],joints[11][1]);
  game.calibrating=game.mode!=='reach'; game.readyHold=0; game.readyHeight=null; game.calibrationSince=performance.now();
  if (!game.calibrating) flashRoundSplash('開始！');
  game.sourceLostAt=null;
  game.standingHip=joints[0][1]-Math.min(joints[10][1],joints[11][1]);
  game.phase='lower'; game.hold=0; game.sampleAt=performance.now(); game.foot=10;
  game.dodgeSide=-1; game.needsCenter=false;
  game.clapOpened=false;
  game.marchNeutral=false;
  game.starLower=false; game.crossNeutral=false; game.guardLower=false;
  game.shoulderRelease=false;
  game.highFiveSide=0; game.highFiveLower=false;
  game.bowReset=false;
  game.needsLower=false;
  game.score = 0;
  game.combo = 0;
  game.lastHitAt = -Infinity;
  game.timeLeft = GAME_DURATION_S;
  game.deadline = performance.now() + GAME_DURATION_S * 1000;
  updateReachEffects(Infinity);
  for (const m of targetMeshes) {
    m.visible=false;
    if (game.mode==='reach') {
      const position=spawnTargetPos();
      if (!position) { endGame('Reach area blocked — move scene objects away'); return; }
      m.position.copy(position); m.visible=true;
    }
  }
  document.getElementById('pose-game-cue').textContent=game.mode==='reach'?'伸手碰觸黃色目標。':'雙腳踩平、站直 1 秒完成校準。';
  document.getElementById('game-btn').style.display = 'none';
  document.getElementById('library-start').disabled = true;
  document.getElementById('game-stop').style.display = 'inline-block';
  const pauseButton=document.getElementById('game-pause');
  pauseButton.style.display='inline-block'; pauseButton.textContent='暫停'; pauseButton.setAttribute('aria-pressed','false');
  document.getElementById('game-stats').style.display = 'flex';
  document.getElementById('game-result').style.display = 'none';
  renderGameStats();
}

// A tracker dropping out for a moment (Bluetooth) changes the pose source. The
// round freezes for up to SOURCE_GRACE_MS: it continues if the source comes back,
// otherwise it ends. The wait does not cost round time.
const SOURCE_GRACE_MS = 1500;
function trackPoseSource(source) {
  const now = performance.now();
  if (source.signature !== game.source.signature) {
    if (game.sourceLostAt != null) return;
    game.sourceLostAt = now;
    document.getElementById('pose-game-cue').textContent = '追蹤中斷，等待恢復…';
  } else if (game.sourceLostAt != null) {
    if (!game.paused) game.deadline += now - game.sourceLostAt;
    game.sourceLostAt = null; game.hold = 0; game.sampleAt = now; game.readyHold = 0; game.readyHeight = null;
    document.getElementById('pose-game-cue').textContent = '追蹤恢復，繼續。';
  }
  renderGameStats();
}
function updateReachClock(now) {
  if (game.state !== 'playing') return;
  if (game.sourceLostAt != null) {
    if (now - game.sourceLostAt > SOURCE_GRACE_MS) endGame('Pose source changed');
    return;
  }
  if (game.calibrating || game.paused) return;
  const remaining = Math.max(0, Math.ceil((game.deadline-now)/1000));
  if (remaining !== game.timeLeft) { game.timeLeft=remaining; renderGameStats(); }
  if (now >= game.deadline) endGame();
}

// ── round presentation ──────────────────────────────────────────────────
function sourceLabelOf(signature) {
  const [kind,count]=String(signature).split(':');
  return kind==='live'?'即時動作捕捉':kind==='mixed'?`混合輸入（即時 ${count}/6）`:'示範資料';
}
function flashRoundSplash(text, high=false) {
  playCue(text==='開始！'?'start':'end');
  if (text==='開始！') AetherCombat.cheer('start');
  const splash=document.getElementById('round-splash');
  splash.textContent=text; splash.classList.toggle('high',high);
  splash.classList.remove('show'); void splash.offsetWidth; splash.classList.add('show');
}
// The card's text keeps the source, the reason and either "最佳 n" or "未完成的回合".
function showRoundResult({title,score,sourceLabel,reason,completed,best,newRecord,again,details=[],practiceMode=null,exportRound=null}) {
  const card=document.getElementById('game-result');
  const node=(tag,className,text)=>{ const element=document.createElement(tag); if (className) element.className=className; if (text!=null) element.textContent=text; return element; };
  const scoreLine=node('div','result-score',String(score)); scoreLine.append(node('small',null,'分'));
  const children=[node('div','result-kicker',completed?'回合完成':'回合結束'),node('div','result-title',title),scoreLine];
  if (newRecord) children.push(node('div','result-badge','新紀錄！'));
  if (!completed) children.push(node('div','result-badge unfinished','未完成的回合'));
  children.push(node('div','result-meta',[sourceLabel,reasonText(reason),best!=null?`最佳 ${best}`:null].filter(Boolean).join(' · ')));
  if (details.length) {
    const performance=node('div','result-performance');
    for(const text of details) performance.appendChild(node('div',null,text)); children.push(performance);
  }
  const actions=node('div','result-actions');
  const replay=node('button','btn primary','再玩一次'); replay.type='button'; replay.onclick=()=>{ dismissRoundResult(); again(); };
  const browse=node('button','btn','選其他遊戲'); browse.type='button'; browse.onclick=()=>{ dismissRoundResult(); openGameLibrary(); };
  const close=node('button','btn','關閉'); close.type='button'; close.onclick=dismissRoundResult;
  actions.append(replay,browse,close); children.push(actions);
  if(exportRound) { const download=node('button','btn','匯出本回合'); download.type='button'; download.dataset.resultExport='true'; download.onclick=exportRound; actions.appendChild(download); }
  if(practiceMode && Object.hasOwn(poseGameNames,practiceMode)) {
    const practice=node('button','btn','選擇建議練習'); practice.type='button'; practice.dataset.resultDrill=practiceMode;
    practice.onclick=()=>{selectRecordedGame(practiceMode);dismissRoundResult();}; actions.appendChild(practice);
  }
  card.replaceChildren(...children); card.style.display='block';
  replay.focus({preventScroll:true});  // Enter replays, Esc closes (main.js)
}
function dismissRoundResult() {
  const card=document.getElementById('game-result');
  if (card.contains(document.activeElement)) document.activeElement.blur();
  card.style.display='none';
}
document.getElementById('start-btn').addEventListener('click',dismissRoundResult);  // a new Combat round
document.getElementById('reset-btn').addEventListener('click',dismissRoundResult);
// Hold progress: game cues end in "NN%" while a hold fills; show it as a bar.
new MutationObserver(()=>{
  const cue=document.getElementById('pose-game-cue').textContent, bar=document.getElementById('pose-cue-progress');
  const match=/(\d{1,3})%\s*$/.exec(cue);
  bar.hidden=!match || game.state!=='playing' || game.calibrating;
  if (match) bar.firstElementChild.style.width=Math.min(100,+match[1])+'%';
}).observe(document.getElementById('pose-game-cue'),{childList:true,characterData:true,subtree:true});
function endGame(reason="Time's up") {
  if (game.state!=='playing') return;
  game.sourceLostAt=null;
  const completed=reason==="Time's up" && !game.calibrating;
  const previousBest=poseBest();
  const playedAt=game.paused?game.pausedAt:performance.now();
  recordRoundHistory({mode:game.mode,score:game.score,source:game.source.signature,completed,reason,
    seconds:game.calibrating?0:Math.round(Math.min(GAME_DURATION_S,Math.max(0,(playedAt-game.deadline)/1000+GAME_DURATION_S)))});
  if (completed) savePoseBest();
  game.state = 'over';
  updateReachEffects(performance.now()/1000);
  targetMeshes.forEach(m => { m.visible = false; });
  showRoundResult({title:poseGameNames[game.mode],score:game.score,sourceLabel:game.source.label,reason,completed,
    best:completed?poseBest():null,newRecord:completed && game.score>previousBest && game.score>0,
    again:()=>startGame()});
  if (completed) { flashRoundSplash('時間到！',true); AetherCombat.cheer('end'); }
  sceneEnvironment.setScoreboard({title:poseGameNames[game.mode].toUpperCase(),value:String(game.score),sub:completed?'完成':'中斷'});
  const btn = document.getElementById('game-btn');
  btn.textContent = '再玩一次';
  btn.style.display = 'inline-block';
  document.getElementById('library-start').disabled = false;
  document.getElementById('game-stats').style.display = 'none';
  document.getElementById('game-stop').style.display = 'none';
  document.getElementById('game-pause').style.display = 'none';
  completePoseCircuitRound(completed);
  game.paused=false;
  document.getElementById('pose-game-cue').textContent='';
  document.getElementById('pose-ready').hidden=true;
}

function renderGameStats() {
  const score = document.getElementById('game-score');
  if (score.textContent !== String(game.score)) {
    if (game.score > 0) { score.classList.remove('bump'); void score.offsetWidth; score.classList.add('bump'); AetherCombat.cheer('score'); }
    score.textContent = String(game.score);
  }
  document.getElementById('game-combo').textContent = game.combo > 1 ? `${game.combo} 連擊` : '';
  document.getElementById('game-time').textContent = game.sourceLostAt!=null?'等待追蹤':game.paused?'已暫停':game.calibrating?'校準中':`${game.timeLeft} 秒`;
  const readiness=document.getElementById('pose-ready');
  readiness.hidden=game.state!=='playing' || !game.calibrating;
  readiness.value=Math.min(100,Math.round((game.readyHold||0)*100));
  document.getElementById('game-best').textContent=String(poseBest());
  // The hall's scoreboard shows the running round too.
  if (game.state==='playing') sceneEnvironment.setScoreboard({title:poseGameNames[game.mode].toUpperCase(),value:String(game.score),
    sub:game.sourceLostAt!=null?'追蹤中斷…':game.paused?'暫停':game.calibrating?'校準中':`剩 ${game.timeLeft} 秒`});
}

function updateGame(joints) {
  updateReachClock(performance.now());
  if (game.state !== 'playing' || game.paused || game.sourceLostAt != null || joints.length <= SMPL_R_HAND) return;
  const hands = [SMPL_L_HAND, SMPL_R_HAND].map(i =>
    avatar.root.localToWorld(new THREE.Vector3(...joints[i])));
  const now = performance.now();
  if (game.mode!=='reach') { updatePoseChallenge(joints,now); return; }
  let blockedReach=false;
  targetMeshes.forEach(m => {
    if (game.state!=='playing') return;
    if (scenePhysics.pointBlocked(m.position,.07)) {
      const replacement=spawnTargetPos(hands);
      if (!replacement) { endGame('Reach area blocked — move scene objects away'); return; }
      m.position.copy(replacement); return;
    }
    const nearby=hands.filter(hand=>hand.distanceTo(m.position)<HIT_RADIUS);
    const canReach=nearby.some(hand=>!scenePhysics.stats.enabled || !scenePhysics.segmentBlocked(hand,m.position,.06*Math.abs(avatar.root.scale.x)));
    if (nearby.length && !canReach) blockedReach=true;
    if (canReach) {
      hitEffect(m.position);
      game.combo = (now - game.lastHitAt < COMBO_WINDOW_MS) ? game.combo + 1 : 1;
      game.lastHitAt = now;
      game.score += game.combo;
      beep(520 + Math.min(game.combo, 10) * 40);
      const replacement=spawnTargetPos(hands);
      if (!replacement) { endGame('Reach area blocked — move scene objects away'); return; }
      m.position.copy(replacement);
      renderGameStats();
    }
  });
  if (game.state==='playing') {
    if (blockedReach) { game.combo=0; game.lastHitAt=-Infinity; renderGameStats(); }
    document.getElementById('pose-game-cue').textContent=blockedReach?'手的路徑被擋住，請繞過場景物件。':'伸手碰觸黃色目標。';
  }
}

function toggleGamePause() {
  if (game.state!=='playing') return;
  const now=performance.now();
  if (!game.paused) {
    updateReachClock(now);
    if (game.state!=='playing') return;
    game.paused=true; game.pausedAt=now;
    updateReachEffects(Infinity);
    targetMeshes.forEach(m=>m.visible=false);
    document.getElementById('pose-game-cue').textContent='已暫停，準備好後按「繼續」。';
  } else {
    if (!avatar.fresh()) { endGame('Pose data expired'); return; }
    game.deadline+=now-game.pausedAt;
    game.paused=false; game.sampleAt=now; game.hold=0; game.readyHold=0; game.readyHeight=null; game.calibrationSince=now;
    game.combo=0; game.lastHitAt=-Infinity;
    targetMeshes.forEach(m=>m.visible=game.mode==='reach');
    document.getElementById('pose-game-cue').textContent=game.calibrating?'雙腳踩平、站直 1 秒完成校準。':'已繼續，請跟著下一個目標或提示動作。';
    renderGameStats();
  }
  const button=document.getElementById('game-pause');
  renderGameStats();
  button.textContent=game.paused?'繼續':'暫停'; button.setAttribute('aria-pressed',String(game.paused));
}

function updatePoseChallenge(joints,now) {
  const elapsed=now-game.sampleAt;
  game.sampleAt=now;
  const dt=elapsed>0 && elapsed<=250?elapsed/1000:0;
  if (!dt) game.hold=0;
  const floor=Math.min(joints[10][1],joints[11][1]);
  const height=joints[15][1]-floor;
  const hipHeight=joints[0][1]-floor;
  if (game.calibrating) {
    const lean=Math.hypot(joints[15][0]-joints[0][0],joints[15][2]-joints[0][2]);
    const upright=height>.8 && height<2.4 && hipHeight/height>.48 && lean<.2 && Math.abs(joints[10][1]-joints[11][1])<.08;
    const stable=upright && dt>0 && (game.readyHeight===null || Math.abs(height-game.readyHeight)<.03);
    game.readyHold=stable?game.readyHold+dt:0;
    if (!stable || game.readyHeight===null) game.readyHeight=height;
    const reason=height<=.8 || height>=2.4 || hipHeight/height<=.48?'請站直。':
      lean>=.2?'頭部要在骨盆正上方。':Math.abs(joints[10][1]-joints[11][1])>=.08?'雙腳要踩平。':
      !dt?'等待更穩定的姿態更新。':!stable?'保持站立高度穩定。':'保持這個站姿。';
    // Demo playback never stands still, so say why calibration may not finish.
    const demoStuck=game.source?.kind==='demo' && now-game.calibrationSince>DEMO_CALIBRATION_HINT_MS;
    document.getElementById('pose-game-cue').textContent=`${reason}校準 ${Math.min(100,Math.round(game.readyHold*100))}%`+
      (demoStuck?'。示範資料的動作不會停下來，可能無法完成校準；戴上追蹤器再玩。':'');
    if (game.readyHold+1e-6>=1) {
      game.calibrating=false; game.standingHeight=height; game.standingHip=hipHeight;
      flashRoundSplash('開始！');
      game.standingHeadOffset=new THREE.Vector3(...joints[15]).sub(new THREE.Vector3(...joints[0]));
      game.standingChestOffset=new THREE.Vector3(...joints[9]).sub(new THREE.Vector3(...joints[0]));
      game.standingKnees=[joints[4][1]-joints[0][1],joints[5][1]-joints[0][1]];
      game.deadline=now+GAME_DURATION_S*1000; game.hold=0;
      document.getElementById('pose-game-cue').textContent=game.mode==='squat'?'下蹲並保持 0.5 秒。':game.mode==='dodge'?'向左傾身，靠近黃色提示。':game.mode==='sky'?'雙手舉向頭上的目標。':game.mode==='clap'?'在胸前張開雙臂，準備拍手。':game.mode==='march'?'抬起左膝和左腳，停一下。':game.mode==='bow'?'朝提示的方向向前彎身。':game.mode==='highfive'?'用左手碰高處的目標。':game.mode==='shoulder'?'雙手交叉碰到對側肩膀。':game.mode==='guard'?'雙手放在頭部兩側。':game.mode==='cross'?'抬起左膝，用右手碰它。':game.mode==='star'?'雙臂伸直平舉到肩膀高度。':'抬起左腳並保持 1.5 秒。';
    }
    renderGameStats(); return;
  }
  let valid=false;
  if (game.mode==='dodge') { updateDodgeChallenge(joints,dt); return; }
  if (game.mode==='sky') { updateSkyChallenge(joints,dt); return; }
  if (game.mode==='clap') { updateClapChallenge(joints,dt); return; }
  if (game.mode==='march') { updateMarchChallenge(joints,dt); return; }
  if (game.mode==='star') { updateStarChallenge(joints,dt); return; }
  if (game.mode==='cross') { updateCrossChallenge(joints,dt); return; }
  if (game.mode==='guard') { updateGuardChallenge(joints,dt); return; }
  if (game.mode==='shoulder') { updateShoulderChallenge(joints,dt); return; }
  if (game.mode==='highfive') { updateHighFiveChallenge(joints,dt); return; }
  if (game.mode==='bow') { updateBowChallenge(joints,dt); return; }
  if (game.mode==='squat') {
    const lowered=game.standingHeight-height;
    if (game.phase==='stand') {
      if (lowered<.08) { game.phase='lower'; game.hold=0; }
      document.getElementById('pose-game-cue').textContent=game.phase==='stand'?'站直，準備下一次。':'下蹲並保持 0.5 秒。';
      return;
    }
    valid=lowered>=.18 && game.standingHip-hipHeight>=.12 && Math.abs(joints[10][1]-joints[11][1])<.1;
  } else {
    const other=game.foot===10?11:10;
    const lean=Math.hypot(joints[15][0]-joints[0][0],joints[15][2]-joints[0][2]);
    valid=joints[game.foot][1]-joints[other][1]>=.12 && lean<.2;
  }
  game.hold=valid?game.hold+dt:0;
  const required=game.mode==='squat'?.5:1.5;
  document.getElementById('pose-game-cue').textContent=game.mode==='squat'?
    `下蹲保持：${Math.min(100,Math.round(game.hold/required*100))}%`:
    `抬起${game.foot===10?'左':'右'}腳：${Math.min(100,Math.round(game.hold/required*100))}%`;
  if (game.hold+1e-6<required) return;
  game.score++; game.hold=0; beep(680);
  if (game.mode==='squat') { game.phase='stand'; document.getElementById('pose-game-cue').textContent='站直，準備下一次。'; }
  else { game.foot=game.foot===10?11:10; document.getElementById('pose-game-cue').textContent=`抬起${game.foot===10?'左':'右'}腳並保持 1.5 秒。`; }
  renderGameStats();
}
function updateDodgeChallenge(joints,dt) {
  // Lean along the body's own left-right line (left shoulder minus right), so
  // "左" is the player's left whatever the skeleton's handedness; dodgeSide -1 is left.
  const side=new THREE.Vector3(...joints[17]).sub(new THREE.Vector3(...joints[16])); side.y=0;
  if (side.lengthSq()<1e-8) { game.hold=0; return; }
  side.normalize();
  const along=index=>new THREE.Vector3(...joints[index]).sub(new THREE.Vector3(...joints[0])).dot(side);
  const headLean=along(15), chestLean=along(9);
  const cue=targetMeshes[0];
  const direction=game.dodgeSide<0?'左':'右';
  cue.position.copy(avatar.root.localToWorld(new THREE.Vector3(...joints[0]).addScaledVector(side,game.dodgeSide*.4).add(new THREE.Vector3(0,.55,0))));
  cue.visible=!game.needsCenter;
  if (game.needsCenter) {
    game.hold=0;
    if (Math.abs(headLean)<.06 && Math.abs(chestLean)<.04 && dt>0) game.needsCenter=false;
    document.getElementById('pose-game-cue').textContent=game.needsCenter?'先回到中間，再做下一次閃避。':`向${direction}傾身，靠近黃色提示。`;
    return;
  }
  const valid=headLean*game.dodgeSide>=.16 && chestLean*game.dodgeSide>=.08 &&
    Math.abs(joints[10][1]-joints[11][1])<.1;
  game.hold=valid && dt>0?game.hold+dt:0;
  document.getElementById('pose-game-cue').textContent=`向${direction}傾身：${Math.min(100,Math.round(game.hold/.4*100))}%`;
  if (game.hold+1e-6<.4) return;
  hitEffect(cue.position); beep(760); game.score++; game.hold=0;
  game.dodgeSide*=-1; game.needsCenter=true; cue.visible=false;
  document.getElementById('pose-game-cue').textContent='先回到中間，再做下一次閃避。';
  renderGameStats();
}
function updateStarChallenge(joints,dt) {
  const shoulders=[new THREE.Vector3(...joints[16]),new THREE.Vector3(...joints[17])];
  const hands=[new THREE.Vector3(...joints[22]),new THREE.Vector3(...joints[23])];
  const axis=shoulders[1].clone().sub(shoulders[0]); axis.y=0;
  if (axis.lengthSq()<1e-8) { game.hold=0; return; } axis.normalize();
  for(let side=0;side<2;side++) {
    targetMeshes[side].position.copy(avatar.root.localToWorld(shoulders[side].clone().addScaledVector(axis,side===0?-.5:.5)));
    targetMeshes[side].visible=!game.starLower;
  }
  if (game.starLower) {
    game.hold=0;
    if (dt>0 && hands.every(hand=>hand.y<joints[9][1]-.1)) game.starLower=false;
    document.getElementById('pose-game-cue').textContent=game.starLower?'先把雙手放到胸口以下，再做下一次。':'雙臂伸直平舉到肩膀高度。';
    return;
  }
  const extended=hands.every((hand,side)=>{
    const shoulder=shoulders[side], elbow=new THREE.Vector3(...joints[side===0?18:19]);
    const length=shoulder.distanceTo(elbow)+elbow.distanceTo(hand);
    return length>.1 && shoulder.distanceTo(hand)/length>=.85 && Math.abs(hand.y-shoulder.y)<.12 &&
      hand.clone().sub(shoulder).dot(axis)*(side===0?-1:1)>=.35;
  });
  const lean=Math.hypot(joints[15][0]-joints[0][0],joints[15][2]-joints[0][2]);
  game.hold=extended && lean<.2 && dt>0?game.hold+dt:0;
  document.getElementById('pose-game-cue').textContent=`雙臂伸直平舉：${Math.min(100,Math.round(game.hold/.8*100))}%`;
  if(game.hold+1e-6<.8) return;
  game.score++; game.hold=0; game.starLower=true;
  for(let side=0;side<2;side++) { hitEffect(targetMeshes[side].position); targetMeshes[side].visible=false; }
  beep(800); renderGameStats();
  document.getElementById('pose-game-cue').textContent='得分！放下雙手再做下一次。';
}
function updateBowChallenge(joints,dt) {
  const hip=new THREE.Vector3(...joints[0]),head=new THREE.Vector3(...joints[15]);
  const axis=new THREE.Vector3(...joints[17]).sub(new THREE.Vector3(...joints[16])); axis.y=0;
  if (axis.lengthSq()<1e-8) { game.hold=0; targetMeshes[0].visible=false; return; }
  axis.normalize();
  // Forward is where the toes point. A cross product with the shoulder axis
  // depends on the skeleton's handedness and pointed backwards for real SMPL poses.
  const forward=new THREE.Vector3(...joints[10]).sub(new THREE.Vector3(...joints[7]))
    .add(new THREE.Vector3(...joints[11]).sub(new THREE.Vector3(...joints[8]))); forward.y=0;
  if (forward.lengthSq()<1e-8) { game.hold=0; targetMeshes[0].visible=false; return; }
  forward.normalize();
  const headDelta=head.clone().sub(hip).sub(game.standingHeadOffset);
  const chestDelta=new THREE.Vector3(...joints[9]).sub(hip).sub(game.standingChestOffset);
  const headForward=headDelta.dot(forward),chestForward=chestDelta.dot(forward);
  const floor=Math.min(joints[10][1],joints[11][1]);
  const upright=hip.y-floor>game.standingHip-.1 && Math.abs(joints[10][1]-joints[11][1])<.08;
  const cue=targetMeshes[0];
  cue.position.copy(avatar.root.localToWorld(hip.clone().add(game.standingHeadOffset).addScaledVector(forward,.24)));
  cue.visible=!game.bowReset;
  if (game.bowReset) {
    game.hold=0;
    if (dt>0 && upright && Math.abs(headForward)<.07 && Math.abs(chestForward)<.04 && Math.abs(headDelta.dot(axis))<.1) game.bowReset=false;
    document.getElementById('pose-game-cue').textContent=game.bowReset?'先站直，再做下一次鞠躬。':'朝提示的方向向前彎身。';
    return;
  }
  if (scenePhysics.stats.enabled && scenePhysics.pointBlocked(cue.position,.08)) {
    game.hold=0; cue.visible=false; document.getElementById('pose-game-cue').textContent='鞠躬目標被擋住，請移開場景物件。'; return;
  }
  const valid=upright && headForward>=.18 && chestForward>=.08 && Math.abs(headDelta.dot(axis))<.15 && head.y-floor>game.standingHeight-.2;
  game.hold=valid && dt>0?game.hold+dt:0;
  document.getElementById('pose-game-cue').textContent=`向前彎身：${Math.min(100,Math.round(game.hold/.6*100))}%`;
  if (game.hold+1e-6<.6) return;
  game.score++; game.hold=0; game.bowReset=true;
  hitEffect(cue.position); cue.visible=false; beep(720); renderGameStats();
  document.getElementById('pose-game-cue').textContent='得分！先站直再做下一次。';
}
function updateHighFiveChallenge(joints,dt) {
  const side=game.highFiveSide, hand=new THREE.Vector3(...joints[side===0?22:23]);
  const name=side===0?'左':'右', other=side===0?23:22;
  const chest=new THREE.Vector3(...joints[9]);
  if (game.highFiveLower) {
    game.hold=0; targetMeshes[0].visible=false;
    if (dt>0 && hand.y<chest.y-.1) { game.highFiveLower=false; game.highFiveSide=1-side; }
    document.getElementById('pose-game-cue').textContent=`先放下${name}手，再做下一次擊掌。`;
    return;
  }
  const axis=new THREE.Vector3(...joints[17]).sub(new THREE.Vector3(...joints[16])); axis.y=0;
  if (axis.lengthSq()<1e-8) { game.hold=0; targetMeshes[0].visible=false; return; }
  axis.normalize();
  const target=new THREE.Vector3(...joints[15]).addScaledVector(axis,side===0?-.3:.3); target.y+=.1;
  const cue=targetMeshes[0]; cue.position.copy(avatar.root.localToWorld(target.clone()));
  const blocked=poseTargetBlocked(cue.position,[hand]);
  cue.visible=!blocked;
  if (blocked) { game.hold=0; document.getElementById('pose-game-cue').textContent='擊掌目標被擋住，請移開場景物件。'; return; }
  const lean=Math.hypot(joints[15][0]-joints[0][0],joints[15][2]-joints[0][2]);
  const valid=hand.distanceTo(target)<=.16 && joints[other][1]<joints[other===22?16:17][1] && lean<.22;
  game.hold=valid && dt>0?game.hold+dt:0;
  document.getElementById('pose-game-cue').textContent=`用${name}手擊掌：${Math.min(100,Math.round(game.hold/.3*100))}%`;
  if (game.hold+1e-6<.3) return;
  game.score++; game.hold=0; game.highFiveLower=true;
  hitEffect(cue.position); cue.visible=false; beep(900); renderGameStats();
  document.getElementById('pose-game-cue').textContent=`得分！放下${name}手，換另一邊。`;
}
function updateShoulderChallenge(joints,dt) {
  const shoulders=[new THREE.Vector3(...joints[17]),new THREE.Vector3(...joints[16])];
  const hands=[new THREE.Vector3(...joints[22]),new THREE.Vector3(...joints[23])];
  const distances=hands.map((hand,side)=>hand.distanceTo(shoulders[side]));
  for (let side=0;side<2;side++) {
    targetMeshes[side].position.copy(avatar.root.localToWorld(shoulders[side].clone()));
    targetMeshes[side].visible=!game.shoulderRelease;
  }
  if (game.shoulderRelease) {
    game.hold=0;
    if (dt>0 && distances.every(distance=>distance>.28)) game.shoulderRelease=false;
    document.getElementById('pose-game-cue').textContent=game.shoulderRelease?'雙手離開肩膀。':'雙手交叉碰到對側肩膀。';
    return;
  }
  const lean=Math.hypot(joints[15][0]-joints[0][0],joints[15][2]-joints[0][2]);
  const valid=distances.every(distance=>distance<=.16) && shoulders[0].distanceTo(shoulders[1])>.2 && lean<.22;
  game.hold=valid && dt>0?game.hold+dt:0;
  document.getElementById('pose-game-cue').textContent=`雙手碰對側肩膀：${Math.min(100,Math.round(game.hold/.6*100))}%`;
  if (game.hold+1e-6<.6) return;
  game.score++; game.hold=0; game.shoulderRelease=true;
  for (let side=0;side<2;side++) { hitEffect(targetMeshes[side].position); targetMeshes[side].visible=false; }
  beep(760); renderGameStats();
  document.getElementById('pose-game-cue').textContent='得分！雙手放開再做下一次。';
}
function updateGuardChallenge(joints,dt) {
  const head=new THREE.Vector3(...joints[15]), chest=new THREE.Vector3(...joints[9]);
  const hands=[new THREE.Vector3(...joints[22]),new THREE.Vector3(...joints[23])];
  const axis=new THREE.Vector3(...joints[17]).sub(new THREE.Vector3(...joints[16])); axis.y=0;
  if (axis.lengthSq()<1e-8) { game.hold=0; return; } axis.normalize();
  for(let side=0;side<2;side++) {
    targetMeshes[side].position.copy(avatar.root.localToWorld(head.clone().addScaledVector(axis,side===0?-.16:.16).add(new THREE.Vector3(0,-.1,0))));
    targetMeshes[side].visible=!game.guardLower;
  }
  if (game.guardLower) {
    game.hold=0;
    if (dt>0 && hands.every(hand=>hand.y<chest.y-.1)) game.guardLower=false;
    document.getElementById('pose-game-cue').textContent=game.guardLower?'先把雙手放到胸口以下，再做下一次防守。':'雙手放到頭部兩側。';
    return;
  }
  const floor=Math.min(joints[10][1],joints[11][1]), height=head.y-floor;
  const lean=Math.hypot(head.x-joints[0][0],head.z-joints[0][2]);
  const valid=hands.every((hand,side)=>hand.y>chest.y-.07 && hand.distanceTo(head)<height*.34 &&
    hand.clone().sub(head).dot(axis)*(side===0?-1:1)>.05) && hands[0].distanceTo(hands[1])>.12 &&
    lean<.22 && Math.abs(joints[10][1]-joints[11][1])<.08 && joints[0][1]-floor>game.standingHip-.1;
  game.hold=valid && dt>0?game.hold+dt:0;
  document.getElementById('pose-game-cue').textContent=`雙手護住兩側：${Math.min(100,Math.round(game.hold/.8*100))}%`;
  if(game.hold+1e-6<.8) return;
  game.score++; game.hold=0; game.guardLower=true;
  for(let side=0;side<2;side++) { hitEffect(targetMeshes[side].position); targetMeshes[side].visible=false; }
  beep(840); renderGameStats();
  document.getElementById('pose-game-cue').textContent='得分！放下雙手再做下一次。';
}
function updateCrossChallenge(joints,dt) {
  const side=game.foot===10?0:1, kneeId=side===0?4:5, handId=side===0?23:22;
  const otherFoot=side===0?11:10;
  const knee=new THREE.Vector3(...joints[kneeId]), hand=new THREE.Vector3(...joints[handId]);
  const cue=targetMeshes[0]; cue.position.copy(avatar.root.localToWorld(knee.clone())); cue.visible=!game.crossNeutral;
  const direction=side===0?'左':'右', handName=side===0?'右':'左';
  if (game.crossNeutral) {
    game.hold=0;
    const neutral=Math.abs(joints[10][1]-joints[11][1])<.05 &&
      [4,5].every((id,index)=>Math.abs(joints[id][1]-joints[0][1]-game.standingKnees[index])<.07) &&
      new THREE.Vector3(...joints[22]).distanceTo(new THREE.Vector3(...joints[5]))>.28 &&
      new THREE.Vector3(...joints[23]).distanceTo(new THREE.Vector3(...joints[4]))>.28;
    if (neutral && dt>0) game.crossNeutral=false;
    document.getElementById('pose-game-cue').textContent=game.crossNeutral?'雙腳落地站好，手離開膝蓋。':`用${handName}手碰抬起的${direction}膝。`;
    return;
  }
  const floor=Math.min(joints[10][1],joints[11][1]);
  const lean=Math.hypot(joints[15][0]-joints[0][0],joints[15][2]-joints[0][2]);
  const valid=knee.y-joints[0][1]-game.standingKnees[side]>=.12 &&
    joints[game.foot][1]-joints[otherFoot][1]>=.06 && hand.distanceTo(knee)<=.18 &&
    joints[0][1]-floor>game.standingHip-.15 && lean<.3;
  game.hold=valid && dt>0?game.hold+dt:0;
  document.getElementById('pose-game-cue').textContent=`${handName}手碰${direction}膝：${Math.min(100,Math.round(game.hold/.3*100))}%`;
  if (game.hold+1e-6<.3) return;
  hitEffect(cue.position); beep(780); game.score++; game.hold=0; game.foot=otherFoot;
  game.crossNeutral=true; cue.visible=false; renderGameStats();
  document.getElementById('pose-game-cue').textContent='得分！站好放開，再換邊。';
}
function updateMarchChallenge(joints,dt) {
  const floor=Math.min(joints[10][1],joints[11][1]);
  const side=game.foot===10?0:1, other=game.foot===10?11:10;
  const direction=side===0?'左':'右';
  const cue=targetMeshes[0];
  cue.position.copy(avatar.root.localToWorld(new THREE.Vector3(...joints[side===0?4:5]).add(new THREE.Vector3(0,.18,0))));
  cue.visible=!game.marchNeutral;
  if (game.marchNeutral) {
    game.hold=0;
    const neutral=Math.abs(joints[10][1]-joints[11][1])<.05 &&
      Math.abs(joints[4][1]-joints[0][1]-game.standingKnees[0])<.07 && Math.abs(joints[5][1]-joints[0][1]-game.standingKnees[1])<.07;
    if (neutral && dt>0) game.marchNeutral=false;
    document.getElementById('pose-game-cue').textContent=game.marchNeutral?'雙腳落地，再踏下一步。':`抬起${direction}膝和${direction}腳。`;
    return;
  }
  const lean=Math.hypot(joints[15][0]-joints[0][0],joints[15][2]-joints[0][2]);
  const valid=joints[side===0?4:5][1]-joints[0][1]-game.standingKnees[side]>=.16 &&
    joints[game.foot][1]-joints[other][1]>=.08 && lean<.22 && joints[0][1]-floor>game.standingHip-.1;
  game.hold=valid && dt>0?game.hold+dt:0;
  document.getElementById('pose-game-cue').textContent=`抬起${direction}膝：${Math.min(100,Math.round(game.hold/.3*100))}%`;
  if (game.hold+1e-6<.3) return;
  hitEffect(cue.position); beep(720); game.score++; game.hold=0;
  game.foot=other; game.marchNeutral=true; cue.visible=false; renderGameStats();
  document.getElementById('pose-game-cue').textContent='得分！雙腳落地，再換邊。';
}
function updateClapChallenge(joints,dt) {
  const left=new THREE.Vector3(...joints[SMPL_L_HAND]);
  const right=new THREE.Vector3(...joints[SMPL_R_HAND]);
  const chest=new THREE.Vector3(...joints[9]);
  const separation=left.distanceTo(right);
  const raised=Math.abs(left.y-chest.y)<.3 && Math.abs(right.y-chest.y)<.3;
  const cue=targetMeshes[0];
  cue.position.copy(avatar.root.localToWorld(chest.clone()));
  cue.visible=true;
  if (!game.clapOpened) {
    game.hold=0;
    if (dt>0 && raised && separation>.55) game.clapOpened=true;
    document.getElementById('pose-game-cue').textContent=game.clapOpened?'在胸前合掌。':'在胸前張開雙臂，準備拍手。';
    return;
  }
  const valid=raised && separation<.18 && left.distanceTo(chest)<.45 && right.distanceTo(chest)<.45;
  game.hold=valid && dt>0?game.hold+dt:0;
  document.getElementById('pose-game-cue').textContent=`合掌保持：${Math.min(100,Math.round(game.hold/.2*100))}%`;
  if (game.hold+1e-6<.2) return;
  game.score++; game.hold=0; game.clapOpened=false;
  hitEffect(cue.position); beep(920); renderGameStats();
  document.getElementById('pose-game-cue').textContent='得分！張開雙臂再拍下一次。';
}
function poseTargetBlocked(worldTarget,localHands) {
  if (!scenePhysics.stats.enabled) return false;
  if (scenePhysics.pointBlocked(worldTarget,.08)) return true;
  const radius=.06*Math.abs(avatar.root.scale.x);
  return localHands.some(hand=>scenePhysics.segmentBlocked(avatar.root.localToWorld(hand.clone()),worldTarget,radius));
}
function updateSkyChallenge(joints,dt) {
  const head=new THREE.Vector3(...joints[15]);
  const left=new THREE.Vector3(...joints[SMPL_L_HAND]);
  const right=new THREE.Vector3(...joints[SMPL_R_HAND]);
  const cue=targetMeshes[0];
  const goal=head.clone().add(new THREE.Vector3(0,.25,0));
  cue.position.copy(avatar.root.localToWorld(goal.clone()));
  cue.visible=!game.needsLower;
  if (game.needsLower) {
    game.hold=0;
    if (dt>0 && left.y<joints[12][1]-.05 && right.y<joints[12][1]-.05) game.needsLower=false;
    document.getElementById('pose-game-cue').textContent=game.needsLower?'把雙手放到肩膀以下，準備下一次。':'雙手舉向頭上的目標。';
    return;
  }
  if (poseTargetBlocked(cue.position,[left,right])) {
    game.hold=0; cue.visible=false;
    document.getElementById('pose-game-cue').textContent='目標或手的路徑被擋住，請移開場景物件。';
    return;
  }
  const valid=left.y>=head.y+.1 && right.y>=head.y+.1 &&
    left.distanceTo(goal)<.35 && right.distanceTo(goal)<.35;
  game.hold=valid && dt>0?game.hold+dt:0;
  document.getElementById('pose-game-cue').textContent=`雙手接住：${Math.min(100,Math.round(game.hold/.35*100))}%`;
  if (game.hold+1e-6<.35) return;
  hitEffect(cue.position); beep(840); game.score++; game.hold=0;
  game.needsLower=true; cue.visible=false;
  document.getElementById('pose-game-cue').textContent='接住了！把雙手放到肩膀以下，準備下一次。';
  renderGameStats();
}
