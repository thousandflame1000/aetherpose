// Aetherpose page: Combat mode switch, training circuits, favourites and the game library.
// Classic script: top-level names are shared with the other page scripts,
// which index.html loads in order (scene, pose, games, backend, trackers, settings, library, main).

function setCombatMode(on) {
  if (on === combatMode) return;
  combatMode = on;
  if (on && poseCircuit) { poseCircuit=null; renderPoseCircuit(); }
  // Activity selection changes rules/HUD only: never swap the visible world,
  // relocate the body, or replace the user's camera view.
  if (on && game.state === 'playing') endGame('Switched to Combat');
  document.body.classList.toggle('combat-mode', on);
  AetherCombat.setActive(on);
  updateGameLibrary();
  // A round this switch ended is in the history; its results card would only cover the new activity.
  dismissRoundResult();
}
let poseCircuit=null;
const customCircuitKey='aetherpose.custom-circuit.v1';
function loadCustomCircuit() {
  try {
    const saved=JSON.parse(localStorage.getItem(customCircuitKey));
    if (Array.isArray(saved) && saved.length===3 && saved.every(mode=>typeof mode==='string' && Object.hasOwn(poseGameNames,mode))) return saved;
  } catch (_) {}
  return ['reach','squat','highfive'];
}
const poseCircuits={upper:['clap','shoulder','highfive'],lower:['squat','march','balance'],mixed:['reach','dodge','cross'],custom:loadCustomCircuit()};
const lastTrainingKey='aetherpose.last-training.v1';
function loadLastTrainingReport() {
  try {
    const raw=localStorage.getItem(lastTrainingKey);
    if (!raw || raw.length>65536) return null;
    const saved=JSON.parse(raw),time=value=>Number.isSafeInteger(value)&&value>0;
    if (!saved || saved.version!==1 || saved.completed!==true || typeof saved.preset!=='string' || !Object.hasOwn(poseCircuits,saved.preset) ||
      !time(saved.startedAt) || !time(saved.finishedAt) || saved.finishedAt<saved.startedAt ||
      !Array.isArray(saved.plan) || saved.plan.length!==3 || !saved.plan.every(mode=>typeof mode==='string'&&Object.hasOwn(poseGameNames,mode)) ||
      !Array.isArray(saved.rounds) || saved.rounds.length!==3 || !saved.rounds.every((round,index)=>round && round.mode===saved.plan[index] &&
        Number.isSafeInteger(round.score) && round.score>=0 && typeof round.source==='string' && /^(demo:0|live:6|mixed:[1-6])$/.test(round.source) &&
        round.seconds===GAME_DURATION_S && time(round.at) && round.at>=saved.startedAt && round.at<=saved.finishedAt)) return null;
    return {version:1,completed:true,preset:saved.preset,startedAt:saved.startedAt,finishedAt:saved.finishedAt,plan:saved.plan.slice(),
      rounds:saved.rounds.map(({mode,score,source,seconds,at})=>({mode,score,source,seconds,at}))};
  } catch (_) { return null; }
}
let lastTrainingReport=loadLastTrainingReport();
function renderLastTrainingReport() {
  document.getElementById('last-training-export').disabled=!lastTrainingReport;
  document.getElementById('last-training-status').textContent=lastTrainingReport?
    `上次完成：${new Date(lastTrainingReport.finishedAt).toLocaleString()} · ${lastTrainingReport.plan.map(mode=>poseGameNames[mode]).join(' → ')}`:'';
}
function showCustomCircuit() {
  document.getElementById('custom-circuit-controls').hidden=document.getElementById('pose-circuit').value!=='custom';
}
function saveCustomCircuit() {
  const modes=[0,1,2].map(index=>document.getElementById(`custom-circuit-${index}`).value);
  if (!modes.every(mode=>Object.hasOwn(poseGameNames,mode))) return;
  poseCircuits.custom=modes;
  try {
    localStorage.setItem(customCircuitKey,JSON.stringify(modes));
    document.getElementById('custom-circuit-status').textContent='已儲存自訂三關，下次開始訓練時套用。';
  } catch (_) { document.getElementById('custom-circuit-status').textContent='本次可使用此組合；瀏覽器無法保存。'; }
}
function buildCustomCircuit() {
  for (let index=0;index<3;index++) {
    const select=document.getElementById(`custom-circuit-${index}`);
    for (const [mode,name] of Object.entries(poseGameNames)) {
      const option=document.createElement('option'); option.value=mode; option.textContent=name; select.add(option);
    }
    select.value=poseCircuits.custom[index];
  }
  showCustomCircuit();
}
function renderPoseCircuit() {
  const next=document.getElementById('circuit-next'),stop=document.getElementById('circuit-stop'),status=document.getElementById('circuit-status');
  document.getElementById('circuit-hud').hidden=!poseCircuit;
  document.getElementById('circuit-hud-next').hidden=!poseCircuit?.waiting;
  document.getElementById('circuit-export').hidden=!poseCircuit?.finished;
  document.getElementById('circuit-hud-export').hidden=!poseCircuit?.finished;
  document.getElementById('circuit-hud-status').textContent=!poseCircuit?'':poseCircuit.finished?`訓練完成 · ${poseCircuit.modes.length} / ${poseCircuit.modes.length} 關`:
    `訓練 ${poseCircuit.index+1} / ${poseCircuit.modes.length} · ${poseGameNames[poseCircuit.modes[poseCircuit.index]]}`+
    (poseCircuit.waiting?` → 下一關 ${poseGameNames[poseCircuit.modes[poseCircuit.index+1]]}`:'');
  next.hidden=!poseCircuit?.waiting; stop.hidden=!poseCircuit;
  if (!poseCircuit) { status.textContent='每關 60 秒。'; return; }
  if (poseCircuit.finished) { status.textContent=`訓練完成！${poseCircuit.results.map(result=>`${poseGameNames[result.mode]} ${result.score} 分`).join(' · ')}`; return; }
  status.textContent=`第 ${poseCircuit.index+1} / ${poseCircuit.modes.length} 關 · ${poseGameNames[poseCircuit.modes[poseCircuit.index]]} · 已完成 ${poseCircuit.results.length} 關`+
    (poseCircuit.waiting?'；準備好後按「開始下一關」。':'；本關中斷可按「開始」重試。');
}
function startPoseCircuit() {
  const modes=poseCircuits[document.getElementById('pose-circuit').value];
  if (!modes) return;
  poseCircuit=null;
  chooseGame(modes[0]);
  poseCircuit={preset:document.getElementById('pose-circuit').value,startedAt:Date.now(),modes:modes.slice(),index:0,results:[],waiting:false,finished:false};
  renderPoseCircuit(); startGame();
}
function completePoseCircuitRound(completed) {
  if (!poseCircuit || poseCircuit.finished || poseCircuit.waiting || game.mode!==poseCircuit.modes[poseCircuit.index]) return;
  if (completed) {
    poseCircuit.results.push({mode:game.mode,score:game.score,source:game.source.signature,seconds:GAME_DURATION_S,at:Date.now()});
    poseCircuit.finished=poseCircuit.index===poseCircuit.modes.length-1;
    if (poseCircuit.finished) poseCircuit.finishedAt=Date.now();
    if (poseCircuit.finished) {
      lastTrainingReport=poseCircuitReport();
      try { localStorage.setItem(lastTrainingKey,JSON.stringify(lastTrainingReport)); } catch (_) {}
      renderLastTrainingReport();
    }
    poseCircuit.waiting=!poseCircuit.finished;
  }
  renderPoseCircuit();
}
function nextPoseCircuitRound() {
  if (!poseCircuit?.waiting || game.state==='playing') return;
  poseCircuit.index++; poseCircuit.waiting=false;
  chooseGame(poseCircuit.modes[poseCircuit.index]); renderPoseCircuit(); startGame();
}
function stopPoseCircuit() {
  poseCircuit=null; renderPoseCircuit();
  if (game.state==='playing') endGame('Training ended');
}
function poseCircuitReport() {
  if (!poseCircuit?.finished) return null;
  return {version:1,completed:true,preset:poseCircuit.preset,startedAt:poseCircuit.startedAt,finishedAt:poseCircuit.finishedAt,
    plan:poseCircuit.modes.slice(),rounds:poseCircuit.results.map(round=>({...round}))};
}
function exportPoseCircuit() {
  return downloadTrainingReport(poseCircuitReport());
}
function exportLastTrainingReport() {
  return downloadTrainingReport(lastTrainingReport);
}
function downloadTrainingReport(report) {
  if (!report) return false;
  const blob=new Blob([JSON.stringify(report,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob);
  const link=document.createElement('a'); link.href=url; link.download=`aetherpose-training-${report.finishedAt}.json`;
  document.body.appendChild(link);
  try { link.click(); } finally { link.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000); }
  return true;
}
const gameFavoriteKey='aetherpose.game-favorites.v1';
function loadGameFavorites() {
  try {
    const saved=JSON.parse(localStorage.getItem(gameFavoriteKey));
    return new Set(Array.isArray(saved)?saved.filter(mode=>typeof mode==='string' && (mode==='combat' || Object.hasOwn(poseGameNames,mode))):[]);
  } catch (_) { return new Set(); }
}
let gameFavorites=loadGameFavorites();
function toggleGameFavorite() {
  const selected=combatMode?'combat':document.getElementById('game-mode').value;
  if (gameFavorites.has(selected)) gameFavorites.delete(selected);
  else gameFavorites.add(selected);
  try { localStorage.setItem(gameFavoriteKey,JSON.stringify([...gameFavorites])); } catch (_) {}
  updateGameLibrary(); filterGameLibrary();
}
function updateGameLibrary() {
  const selected=combatMode?'combat':document.getElementById('game-mode').value;
  const instructions={
    reach:'伸手碰觸黃色目標，連續快速命中可以累積連擊。',
    squat:'先直立校準，再降低身體並保持 0.5 秒；站直後才能計算下一次深蹲。',
    balance:'依提示抬起左腳或右腳，保持軀幹直立 1.5 秒；得分後換腳。',
    dodge:'依黃色提示向左或向右傾身，保持 0.4 秒；回到中央後再換方向。',
    sky:'雙手抬過頭頂，靠近高空目標並保持 0.35 秒；放下雙手後再接下一個。',
    clap:'先在胸前打開雙臂，再合掌保持 0.2 秒；再次打開雙臂即可準備下一拍。',
    march:'依提示交替抬膝與抬腳，保持 0.3 秒；兩腳落地後再換邊。',
    star:'雙臂伸直、保持肩膀高度 0.8 秒；雙手降到胸口以下後再開始。',
    cross:'右手碰抬起的左膝，再換左手碰右膝，保持 0.3 秒；每次站回原位並放開。',
    guard:'雙手分別放在頭部兩側，直立保持 0.8 秒；雙手降到胸口以下後再開始。',
    shoulder:'雙手交叉碰到對側肩膀，保持直立 0.6 秒；兩手都離開肩膀後才能再得分。',
    highfive:'依提示以左手或右手碰高處目標，保持 0.3 秒；另一手留在肩膀以下。得分後放下該手，再換邊。',
    bow:'先直立校準，再向前彎身保持 0.6 秒；保持雙腳同高，站回直立後再做下一次。',
    combat:'按「開始回合」開始。打中亮起的部位；對手出招時護頭、蹲下或側身。'
  };
  const guide=document.getElementById('game-guide');
  guide.textContent=`${selected==='combat'?'Aether Combat':poseGameNames[selected]} · ${selected==='combat'?'90':'60'} 秒\n${instructions[selected]}`;
  const favorite=gameFavorites.has(selected), favoriteButton=document.getElementById('game-favorite-btn');
  favoriteButton.textContent=favorite?'★ 取消收藏':'☆ 收藏目前遊戲';
  favoriteButton.setAttribute('aria-pressed',String(favorite));
  // Best scores are kept per input source (demo, mixed, live): show the ones for the current input.
  const signature=aetherPoseSource(bridgeStatus).signature;
  document.querySelectorAll('[data-game-choice]').forEach(button=>{
    const best=button.querySelector('.game-card-best'), score=poseRecords[`${button.dataset.gameChoice}:${signature}`];
    if (best) best.textContent=score?`最佳 ${score}`:'';
    if (best && button.dataset.gameChoice==='combat') {
      const difficulty=document.getElementById('combat-difficulty').value,levelBest=combatDifficultyBest(difficulty,signature);
      best.textContent=levelBest?`${{easy:'練習',normal:'標準',hard:'挑戰'}[difficulty]}最佳 ${levelBest}`:score?`全部難度最佳 ${score}`:'';
    }
    const active=button.dataset.gameChoice===selected;
    button.setAttribute('aria-pressed',String(active));
    button.style.borderColor=active?'var(--accent)':'';
    button.style.background=active?'rgba(96,165,250,.16)':'';
    const title=button.querySelector('strong');
    title.textContent=`${gameFavorites.has(button.dataset.gameChoice)?'★ ':''}${button.dataset.gameChoice==='combat'?'Aether Combat':poseGameNames[button.dataset.gameChoice]}`;
  });
}
function chooseGame(mode) {
  if (mode==='combat') selectTab('combat');
  else if (Object.hasOwn(poseGameNames,mode)) {
    if (combatMode) selectTab('games');
    document.getElementById('game-mode').value=mode;
    changePoseGame();
  }
  updateGameLibrary();
}
function selectRecordedGame(mode) {
  if (mode!=='combat' && !Object.hasOwn(poseGameNames,mode)) return;
  document.getElementById('game-search').value='';
  document.getElementById('game-favorites-only').checked=false;
  filterGameLibrary(); chooseGame(mode);
  // Combat has its own tab; a Pose game is shown in the library.
  if (mode==='combat') setFocusMode(false); else openGameLibrary();
}
function openGameLibrary() {
  setFocusMode(false);
  selectTab('games');
  const library=document.getElementById('game-library');
  library.open=true;
  library.scrollIntoView({block:'start',behavior:'smooth'});
}
// One stick-figure pictogram per game (inline SVG, 40×44), so the library shows
// the move, not just its name. Points override the standing figure; `dot` marks a target.
const GAME_FIGURE_BASE={head:[20,7],neck:[20,13],pelvis:[20,26],lElbow:[14,19],lHand:[12,25],rElbow:[26,19],rHand:[28,25],
  lKnee:[16,34],lFoot:[15,42],rKnee:[24,34],rFoot:[25,42]};
const GAME_FIGURES={
  reach:{rElbow:[27,11],rHand:[33,5],dot:[36,3]},
  squat:{head:[20,13],neck:[20,19],pelvis:[20,30],lKnee:[12,32],rKnee:[28,32],lElbow:[13,22],lHand:[7,22],rElbow:[27,22],rHand:[33,22]},
  balance:{rKnee:[28,28],rFoot:[26,35],lElbow:[11,14],lHand:[4,14],rElbow:[29,14],rHand:[36,14]},
  dodge:{head:[11,9],neck:[14,15],lElbow:[9,21],lHand:[8,27],rElbow:[20,21],rHand:[24,26],arrow:[[8,4],[2,4]]},
  sky:{lElbow:[12,5],lHand:[16,-1],rElbow:[28,5],rHand:[24,-1],dot:[20,-2]},
  clap:{lElbow:[12,18],lHand:[19,20],rElbow:[28,18],rHand:[21,20],burst:[20,20]},
  march:{lKnee:[14,27],lFoot:[16,34],rElbow:[26,17],rHand:[28,11],lElbow:[14,20],lHand:[13,26]},
  star:{lElbow:[11,13],lHand:[3,13],rElbow:[29,13],rHand:[37,13]},
  cross:{lKnee:[15,27],lFoot:[17,34],rElbow:[25,22],rHand:[17,27],dot:[15,27]},
  guard:{lElbow:[12,16],lHand:[15,7],rElbow:[28,16],rHand:[25,7]},
  shoulder:{lElbow:[17,22],lHand:[25,14],rElbow:[23,22],rHand:[15,14]},
  highfive:{rElbow:[28,9],rHand:[32,3],dot:[35,2]},
  bow:{head:[34,13],neck:[30,16],lElbow:[29,24],lHand:[30,31],rElbow:[31,24],rHand:[32,31],lKnee:[19,34],lFoot:[18,42],rKnee:[21,34],rFoot:[22,42]},
  combat:{rElbow:[28,15],rHand:[36,13],lElbow:[14,17],lHand:[17,10],lKnee:[14,34],lFoot:[10,42],rKnee:[26,34],rFoot:[30,42],burst:[37,13]},
};
function gamePictogram(mode) {
  const f={...GAME_FIGURE_BASE,...GAME_FIGURES[mode]};
  const line=(a,b)=>`<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}"/>`;
  const limbs=[[f.neck,f.pelvis],[f.neck,f.lElbow],[f.lElbow,f.lHand],[f.neck,f.rElbow],[f.rElbow,f.rHand],
    [f.pelvis,f.lKnee],[f.lKnee,f.lFoot],[f.pelvis,f.rKnee],[f.rKnee,f.rFoot]].map(([a,b])=>line(a,b)).join('');
  const dot=f.dot?`<circle cx="${f.dot[0]}" cy="${f.dot[1]}" r="2.6" fill="var(--amber)" stroke="none"/>`:'';
  const burst=f.burst?[[-4,-4],[4,-4],[-4,4],[4,4]].map(([dx,dy])=>`<line x1="${f.burst[0]+dx*.5}" y1="${f.burst[1]+dy*.5}" x2="${f.burst[0]+dx}" y2="${f.burst[1]+dy}" stroke="var(--amber)" stroke-width="1.6"/>`).join(''):'';
  const arrow=f.arrow?`<path d="M${f.arrow[0][0]} ${f.arrow[0][1]}H${f.arrow[1][0]}m3 -3l-3 3l3 3" stroke="var(--amber)" stroke-width="1.6" fill="none"/>`:'';
  return `<svg class="game-figure" viewBox="-2 -6 44 51" aria-hidden="true"><g stroke="currentColor" stroke-width="3" stroke-linecap="round" fill="none">${limbs}</g>`+
    `<circle cx="${f.head[0]}" cy="${f.head[1]}" r="3.8" fill="currentColor"/>${dot}${burst}${arrow}</svg>`;
}
function buildGameLibrary() {
  const descriptions={reach:'伸手碰觸目標',squat:'深蹲節奏',balance:'單腳平衡',dodge:'左右閃避',sky:'雙手接高空目標',clap:'拍手節奏',march:'交替抬膝',star:'展臂保持',cross:'對側手碰膝',guard:'雙手防守',shoulder:'雙手碰肩',highfive:'交替擊掌',bow:'前傾節奏',combat:'與機器人對戰'};
  for (const [mode,name] of Object.entries({...poseGameNames,combat:'Aether Combat'})) {
    const button=document.createElement('button');
    button.className='btn'; button.type='button'; button.dataset.gameChoice=mode;
    button.classList.add('game-card');
    const text=document.createElement('span'); text.className='game-card-text';
    const title=document.createElement('strong'); title.textContent=name;
    const description=document.createElement('span'); description.textContent=descriptions[mode];
    description.style.cssText='display:block;font-size:11px;color:var(--text-dim)';
    text.append(title,description);
    const best=document.createElement('span'); best.className='game-card-best'; text.append(best);
    button.insertAdjacentHTML('beforeend',gamePictogram(mode)); button.append(text);
    button.addEventListener('click',()=>chooseGame(mode));
    document.getElementById('game-library-list').append(button);
  }
  updateGameLibrary();
  filterGameLibrary();
}
function filterGameLibrary() {
  const query=document.getElementById('game-search').value.trim().toLocaleLowerCase();
  let matches=0;
  document.querySelectorAll('[data-game-choice]').forEach(button=>{
    const match=button.textContent.toLocaleLowerCase().includes(query) &&
      (!document.getElementById('game-favorites-only').checked || gameFavorites.has(button.dataset.gameChoice));
    button.hidden=!match;
    if (match) matches++;
  });
  const total=Object.keys(poseGameNames).length+1;
  document.getElementById('game-search-status').textContent=matches===total?'':matches?`${matches} / ${total} 個遊戲`:
    document.getElementById('game-favorites-only').checked?'沒有符合的收藏；取消「只顯示收藏」可查看全部遊戲。':'沒有符合的遊戲，請換個關鍵字。';
}
