// Aetherpose page: shared constants, the Three.js scene, camera views and the render loop.
// Classic script: top-level names are shared with the other page scripts,
// which index.html loads in order (scene, pose, games, backend, trackers, settings, library, main).

// ── constants (bone ids mirror src/app/types.rs) ──────────────────────────
const WS_URL = 'ws://127.0.0.1:9009/ws';
const BONE_NAMES = {0:'骨盆',1:'腰',2:'胸口',3:'頸',4:'頭',
  10:'左大腿',11:'左小腿',12:'左腳',
  20:'右大腿',21:'右小腿',22:'右腳',
  30:'左肩',31:'左上臂',32:'左前臂',33:'左手',
  40:'右肩',41:'右上臂',42:'右前臂',43:'右手'};
const LEFT_BONE_IDS  = new Set([10,11,12,30,31,32,33]);
const RIGHT_BONE_IDS = new Set([20,21,22,40,41,42,43]);

// TransPose (neural-net mesh/joints) bridge — a separate headless Python
// process (mesh_bridge.py), not the Rust backend. See that file for why.
const MESH_WS_URL = 'ws://127.0.0.1:9010/';
const SMPL_L_HAND = 22, SMPL_R_HAND = 23;
const TP_OFFSET = new THREE.Vector3(1.1, 0.97, 0);

// ── Three.js scene ─────────────────────────────────────────────────────────
const canvas = document.getElementById('scene-canvas');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.outputEncoding=THREE.sRGBEncoding;
renderer.toneMapping=THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure=1.1;
renderer.shadowMap.enabled=true;
renderer.shadowMap.type=THREE.PCFSoftShadowMap;
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));

const scene = new THREE.Scene();
// The training hall around the arena (environment.js) also sets the background and fog.
const sceneEnvironment = createAetherEnvironment(scene, renderer);
const poseScene = new THREE.Group();
scene.add(poseScene);

const camera = new THREE.PerspectiveCamera(60, 1, 0.05, 100);
camera.position.set(0, 1.4, 3.6);

const controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0.9, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.maxDistance = 12;
controls.minDistance = 0.8;
const avatar = createAetherAvatar(scene);
// The player always occupies the same arena slot, in every activity.
avatar.setMode(true);
const AetherCombat = createAetherCombat({ scene, camera, avatar, onRoundStart:()=>flashRoundSplash('開始！'),
  onRoundEnd:entry=>finishCombatRound(entry) });
// Combat keeps a best score per input source like the pose games (only finished rounds count).
function finishCombatRound(entry) {
  const normalized=normalizeCombatHistory({...entry,at:Date.now()}),stats=normalized.combatStats;
  const details=stats?[`命中 ${stats.hits}/${stats.attempts}（${stats.attempts?Math.round(stats.hits/stats.attempts*100):0}%） · 正確目標 ${stats.targets}`,
    `防守 ${stats.defenses} · 反擊 ${stats.counters} · 受擊 ${stats.received} · 最高連擊 ${stats.bestCombo}`,
    aetherCombatAdvice(stats,normalized.combatBreakdown)]:[];
  if (normalized.combatBreakdown) details.splice(2,0,['high','body','flank'].map(type=>
    `${{high:'高位',body:'身體',flank:'側面'}[type]}：受擊 ${normalized.combatBreakdown.received[type]}／防守 ${normalized.combatBreakdown.defended[type]}`).join(' · '));
  recordRoundHistory(entry);
  const separateDifficulty=['easy','normal','hard'].includes(entry.difficulty);
  const previousBest=separateDifficulty?combatDifficultyBest(entry.difficulty,entry.source):poseRecords[`combat:${entry.source}`]||0;
  if (entry.completed) {
    flashRoundSplash(aetherReasonText(entry.reason)+'！',true);
    saveBestScore('combat',entry.source,entry.score);
    if (separateDifficulty) saveCombatDifficultyBest(entry.difficulty,entry.source,entry.score);
  }
  sceneEnvironment.setScoreboard({title:'AETHER COMBAT',value:String(entry.score),sub:entry.completed?'完成':'中斷'});
  showRoundResult({title:'Aether Combat',score:entry.score,sourceLabel:sourceLabelOf(entry.source)+(separateDifficulty?` · ${{easy:'練習',normal:'標準',hard:'挑戰'}[entry.difficulty]}`:''),reason:entry.reason,
    details,practiceMode:stats?aetherCombatDrill(stats,normalized.combatBreakdown):null,
    exportRound:()=>exportSingleRound(normalized),
    completed:entry.completed,best:entry.completed?(separateDifficulty?combatDifficultyBest(entry.difficulty,entry.source):poseRecords[`combat:${entry.source}`]||0):null,
    newRecord:entry.completed && entry.score>previousBest && entry.score>0,again:()=>document.getElementById('start-btn').click()});
}
const scenePhysics=createAetherPhysics(scene);
function sceneWorldChanged() {
  if (game.state==='playing') endGame('Scene changed. Round stopped.');
  AetherCombat.onSceneChanged();
}
function setSceneCollisions(enabled) {
  if (typeof enabled!=='boolean' || enabled===scenePhysics.stats.enabled) return;
  scenePhysics.stats.enabled=enabled; scenePhysics.resetAll(); sceneWorldChanged();
}
const sceneAssets=createAetherSceneAssets(scene,scenePhysics,sceneWorldChanged);
const sceneStorage=createAetherSceneStorage(sceneAssets);
const sceneMoveTool=new THREE.TransformControls(camera,canvas);
sceneMoveTool.name='scene-model-move-tool'; sceneMoveTool.setMode('translate'); sceneMoveTool.setSize(.8); scene.add(sceneMoveTool);
let orbitBeforeMove=true;
function setSceneToolMode(mode) {
  if (!['translate','rotate','scale'].includes(mode)) return;
  if (sceneMoveTool.dragging) { sceneAssets.endMove(); sceneMoveTool.dragging=false; }
  sceneMoveTool.setMode(mode); sceneMoveTool.setSpace('world');
  document.getElementById('scene-tool-mode').value=mode;
  sceneMoveTool.showX=mode!=='rotate'; sceneMoveTool.showY=true; sceneMoveTool.showZ=mode!=='rotate';
  sceneMoveTool.axis=null;
}
function setSceneToolSnap(enabled) {
  if (sceneMoveTool.dragging) { sceneAssets.endMove(); sceneMoveTool.dragging=false; }
  sceneMoveTool.setTranslationSnap(enabled?.1:null);
  sceneMoveTool.setRotationSnap(enabled?THREE.MathUtils.degToRad(15):null);
  sceneMoveTool.setScaleSnap(enabled?.05:null);
}
sceneMoveTool.addEventListener('mouseDown',()=>{sceneAssets.beginMove();setFollowPose(false);});
sceneMoveTool.addEventListener('objectChange',()=>sceneAssets.updateMove(sceneMoveTool.mode==='scale'?sceneMoveTool.axis:null));
sceneMoveTool.addEventListener('mouseUp',()=>sceneAssets.endMove());
sceneMoveTool.addEventListener('dragging-changed',event=>{
  if(event.value) {orbitBeforeMove=controls.enabled;controls.enabled=false;}
  else controls.enabled=orbitBeforeMove;
});
function syncSceneMoveTool() {
  const object=sceneAssets.model;
  const show=document.getElementById('scene-move-tool').checked && document.getElementById('scene-assets').open && object && object.visible;
  if (show && sceneMoveTool.object===object) return;
  if (sceneMoveTool.dragging) {sceneAssets.endMove();sceneMoveTool.dragging=false;}
  if(show) sceneMoveTool.attach(object); else sceneMoveTool.detach();
}
document.getElementById('scene-assets').addEventListener('toggle',syncSceneMoveTool);
canvas.addEventListener('dblclick',event=>{
  if (event.button!==0) return;
  const rect=canvas.getBoundingClientRect(); if (!rect.width || !rect.height) return;
  const pointer=new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
  const raycaster=new THREE.Raycaster(); raycaster.setFromCamera(pointer,camera);
  if (sceneAssets.pick(raycaster)) {
    setFocusMode(false); document.getElementById('scene-assets').open=true;
    document.getElementById('scene-assets').scrollIntoView({block:'nearest'});
  }
});
avatar.setPhysics(scenePhysics);
AetherCombat.setPhysics(scenePhysics);
document.getElementById('recenter-btn').addEventListener('click',()=>scenePhysics.reset(avatar.root));
const sceneSettingsKey='aetherpose.scene-settings.v1';
const sceneQualityProfiles={low:{pixelRatio:1,shadows:false,mapSize:512},balanced:{pixelRatio:1.5,shadows:true,mapSize:1024},high:{pixelRatio:2,shadows:true,mapSize:2048}};
function loadSceneSettings() {
  try {
    const data=JSON.parse(localStorage.getItem(sceneSettingsKey)||'null');
    if (data && Object.hasOwn(sceneQualityProfiles,data.quality) && Number.isFinite(data.brightness) && data.brightness>=.7 && data.brightness<=1.6)
      return {quality:data.quality,brightness:data.brightness};
  } catch (_) {}
  // CPU WebGL competes with pose inference. Start without shadows/detail on
  // those devices; an explicitly saved appearance preference still wins.
  return {quality:softwareRendererName()?'low':'balanced',brightness:1.1};
}
function applySceneSettings(quality,brightness) {
  if (!Object.hasOwn(sceneQualityProfiles,quality)) quality='balanced';
  if (!Number.isFinite(brightness)) brightness=1.1;
  brightness=Math.min(1.6,Math.max(.7,brightness));
  const profile=sceneQualityProfiles[quality];
  const pixelRatio=Math.min(window.devicePixelRatio||1,profile.pixelRatio);
  if (renderer.getPixelRatio()!==pixelRatio) renderer.setPixelRatio(pixelRatio);
  if (renderer.shadowMap.enabled!==profile.shadows) {
    renderer.shadowMap.enabled=profile.shadows;
    scene.traverse(object=>{
      if (object.material) for (const material of Array.isArray(object.material)?object.material:[object.material]) material.needsUpdate=true;
    });
  }
  const light=scene.getObjectByName('arena-key-light');
  if (light.shadow.mapSize.x!==profile.mapSize) {
    if (light.shadow.map) { light.shadow.map.dispose(); light.shadow.map=null; }
    light.shadow.mapSize.set(profile.mapSize,profile.mapSize);
  }
  renderer.toneMappingExposure=brightness;
  sceneEnvironment.setQuality(quality);
  document.getElementById('scene-quality').value=quality;
  document.getElementById('scene-brightness').value=brightness;
  document.getElementById('scene-brightness-value').textContent=brightness.toFixed(2);
  try { localStorage.setItem(sceneSettingsKey,JSON.stringify({quality,brightness})); } catch (_) {}
  resizeRenderer();
}


function resizeRenderer() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  if (canvas.width === Math.floor(w * renderer.getPixelRatio()) && canvas.height === Math.floor(h * renderer.getPixelRatio())) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resizeRenderer);
// Without hardware acceleration the browser draws WebGL on the CPU: the scene stutters and
// the pose service loses the CPU time it needs. main.js warns once at start-up.
function softwareRendererName() {
  try {
    const gl=renderer.getContext(), info=gl.getExtension('WEBGL_debug_renderer_info');
    const name=String(gl.getParameter(info?info.UNMASKED_RENDERER_WEBGL:gl.RENDERER)||'');
    return /swiftshader|llvmpipe|softpipe|software|basic render/i.test(name)?name:'';
  } catch (_) { return ''; }
}
function warnSoftwareRendering() {
  const name=softwareRendererName();
  if (name) showPanelNotice('瀏覽器沒有用顯示卡畫 3D（硬體加速關閉）：畫面會卡，也會拖慢姿態推論。請在瀏覽器設定開啟「可用時使用圖形加速」，再重新開啟瀏覽器。',20);
  return Boolean(name);
}
// A GPU reset (driver update, sleep, too many 3D tabs) loses the WebGL context. three.js restores it
// by itself; until then the picture is frozen, so say so and end a round the player cannot see.
let contextLostTimer=null;
canvas.addEventListener('webglcontextlost',()=>{
  if (game.state==='playing') endGame('Display lost');
  AetherCombat.stopRound('Display lost. Round stopped.');
  showPanelNotice('3D 畫面中斷（顯示卡重設），正在恢復…',60);
  clearTimeout(contextLostTimer);
  contextLostTimer=setTimeout(()=>showPanelNotice('3D 畫面沒有恢復，請重新整理頁面。',600),8000);
});
canvas.addEventListener('webglcontextrestored',()=>{ clearTimeout(contextLostTimer); showPanelNotice('3D 畫面已恢復。',4); });

// One animation loop renders both modes in the shared scene.
let combatMode = false;
let lastFrameAt = performance.now() / 1000;
let followPose = true;
function setFollowPose(on) {
  followPose = on;
  document.getElementById('follow-btn').textContent = on ? '跟隨：開' : '跟隨：關';
  document.getElementById('follow-btn').setAttribute('aria-pressed', String(on));
}
controls.addEventListener('start', () => {
  setFollowPose(false);
  document.getElementById('scene-view').value='custom';
});
function setSceneView(view) {
  const positions={front:[0,1.4,3.6],side:[3.6,1.4,0],top:[0,5,.01]};
  if (!positions[view]) return;
  setFollowPose(false);
  controls.reset();
  controls.target.set(0,.9,0);
  camera.position.set(...positions[view]);
  controls.update();
  document.getElementById('scene-view').value=view;
}
function focusSceneObject() {
  const object=sceneAssets.model;
  if (!object) return;
  if (!object.visible) { document.getElementById('scene-asset-status').textContent='請先勾選「顯示」再檢視這個物件。'; return; }
  const bounds=new THREE.Box3().setFromObject(object);
  frameSceneBounds(bounds);
}
function frameSceneBounds(bounds) {
  if (bounds.isEmpty()) return false;
  const center=bounds.getCenter(new THREE.Vector3());
  const radius=bounds.getSize(new THREE.Vector3()).length()/2;
  if (!Number.isFinite(radius)||radius<=0) return false;
  const vertical=THREE.MathUtils.degToRad(camera.fov)/2;
  const horizontal=Math.atan(Math.tan(vertical)*camera.aspect);
  const distance=THREE.MathUtils.clamp(radius/Math.sin(Math.min(vertical,horizontal))*1.2,controls.minDistance,camera.far*.8);
  controls.maxDistance=Math.max(12,distance);
  const direction=camera.position.clone().sub(controls.target).normalize();
  if (direction.lengthSq()<.5) direction.set(0,.2,1).normalize();
  setFollowPose(false); controls.target.copy(center); camera.position.copy(center).addScaledVector(direction,distance);
  controls.update(); document.getElementById('scene-view').value='custom';
  return true;
}
function fitSceneView() {
  const bounds=new THREE.Box3();
  const roots=[avatar.root,scene.getObjectByName('aether-opponent'),scene.getObjectByName('aether-environment'),...sceneAssets.models];
  for (const root of roots) {
    if (!root) continue;
    root.updateWorldMatrix(true,true);
    root.traverse(node=>{
      if (!node.isMesh || !node.geometry) return;
      for (let ancestor=node;ancestor;ancestor=ancestor.parent) if (!ancestor.visible) return;
      if (!node.geometry.boundingBox) node.geometry.computeBoundingBox();
      if (node.geometry.boundingBox) bounds.union(node.geometry.boundingBox.clone().applyMatrix4(node.matrixWorld));
    });
  }
  return frameSceneBounds(bounds);
}
const cameraBookmarkKey='aetherpose.camera-bookmark.v1';
function readCameraBookmark() {
  try {
    const saved=JSON.parse(localStorage.getItem(cameraBookmarkKey));
    const vector=value=>Array.isArray(value) && value.length===3 && value.every(number=>Number.isFinite(number)&&Math.abs(number)<=100);
    if (!saved || saved.version!==1 || !vector(saved.position) || !vector(saved.target)) return null;
    const distance=new THREE.Vector3(...saved.position).distanceTo(new THREE.Vector3(...saved.target));
    return distance>=controls.minDistance && distance<=camera.far*.8?saved:null;
  } catch (_) { return null; }
}
function saveCameraBookmark() {
  const status=document.getElementById('camera-bookmark-status');
  try {
    localStorage.setItem(cameraBookmarkKey,JSON.stringify({version:1,position:camera.position.toArray(),target:controls.target.toArray()}));
    status.textContent='已儲存目前視角。';
  } catch (_) { status.textContent='瀏覽器無法儲存視角。'; }
}
function restoreCameraBookmark() {
  const saved=readCameraBookmark(), status=document.getElementById('camera-bookmark-status');
  if (!saved) { status.textContent='沒有可用的視角書籤，請先按「儲存視角」。'; return false; }
  setFollowPose(false); controls.reset();
  controls.target.fromArray(saved.target); camera.position.fromArray(saved.position);
  controls.maxDistance=Math.max(12,camera.position.distanceTo(controls.target));
  controls.update(); document.getElementById('scene-view').value='custom';
  status.textContent='已還原儲存的視角。'; return true;
}
function captureSceneImage() {
  return new Promise((resolve,reject)=>{
    try {
      // Render and encode in one task, before WebGL clears its buffer. The
      // synchronous encode does not depend on when an async encoder finishes.
      renderer.render(scene,camera);
      const data=atob(canvas.toDataURL('image/png').split(',')[1]||'');
      if (!data) throw Error('PNG capture failed');
      const bytes=new Uint8Array(data.length);
      for (let i=0;i<data.length;i++) bytes[i]=data.charCodeAt(i);
      resolve(new Blob([bytes],{type:'image/png'}));
    } catch(error) { reject(error); }
  });
}
async function exportSceneImage() {
  const button=document.getElementById('scene-image-save'),status=document.getElementById('scene-image-status');
  if (button.disabled) return false;
  button.disabled=true; status.textContent='正在匯出場景…';
  let url=null;
  try {
    const blob=await captureSceneImage(); url=URL.createObjectURL(blob);
    const link=document.createElement('a'); link.href=url;
    link.download=`aetherpose-scene-${new Date().toISOString().replace(/[:.]/g,'-')}.png`;
    document.body.appendChild(link);
    try { link.click(); } finally { link.remove(); }
    status.textContent=`已匯出 ${canvas.width} × ${canvas.height} PNG。`; return true;
  } catch (_) { status.textContent='無法匯出場景，請再試一次。'; return false; }
  finally {
    if (url) { const capturedUrl=url; setTimeout(()=>URL.revokeObjectURL(capturedUrl),1000); }
    button.disabled=false;
  }
}
function followAvatar(dt) {
  if (!followPose || !avatar.fresh()) return;
  const target = avatar.root.localToWorld(new THREE.Vector3(...avatar.joints[0]));
  const delta = target.sub(controls.target).multiplyScalar(1 - Math.exp(-dt * 6));
  controls.target.add(delta);
  camera.position.add(delta);
}
function animate() {
  requestAnimationFrame(animate);
  const t = performance.now() / 1000;
  const dt = Math.min(Math.max(t - lastFrameAt,0),0.1);
  avatar.tick(dt, t);
  if (!animate.physicsStatusAt || t-animate.physicsStatusAt>.5) {
    const s=scenePhysics.stats;
    const q=scenePhysics.queryStats;
    document.getElementById('physics-status').textContent=s.enabled?`${s.backend} · 接觸 ${s.contacts}（連續 ${s.sweptContacts}）· ${s.milliseconds.toFixed(2)} ms · 三角面候選 ${q.candidates}/${q.totalTriangles}${s.unresolved?' · 達到約束上限':''}`:'場景約束已關閉';
    animate.physicsStatusAt=t;
  }
  refreshTrackers(t);
  updateReachClock(t * 1000);
  updateReachEffects(t);
  if (game.state === 'playing' && !avatar.fresh(t)) endGame('Pose data expired');
  lastFrameAt = t;
  AetherCombat.tick(t);
  if (!combatMode) followAvatar(dt);
  controls.update();
  resizeRenderer();
  syncSceneMoveTool();
  renderer.render(scene, camera);
}
