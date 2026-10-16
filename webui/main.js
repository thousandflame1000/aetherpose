// Aetherpose page: focus mode, full screen, tabs and start-up. Loaded last.
// Classic script: top-level names are shared with the other page scripts,
// which index.html loads in order (scene, pose, games, backend, trackers, settings, library, main).

function setFocusMode(on) {
  document.body.classList.toggle('focus-mode',Boolean(on));
  const button=document.getElementById('focus-btn');
  button.textContent=on?'顯示面板':'隱藏面板';
  button.setAttribute('aria-pressed',String(Boolean(on)));
  resizeRenderer();
}
async function toggleFullscreen() {
  const status=document.getElementById('display-status');
  status.textContent='';
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen();
    else status.textContent='無法使用全螢幕，可以用「隱藏面板」放大場景。';
  } catch (_) { status.textContent='無法使用全螢幕，可以用「隱藏面板」放大場景。'; }
}
document.addEventListener('fullscreenchange',()=>{
  document.getElementById('fullscreen-btn').textContent=document.fullscreenElement?'離開全螢幕':'全螢幕';
  resizeRenderer();
});
document.addEventListener('keydown',event=>{
  // Esc closes the results card first, then leaves the hidden-panel view.
  if (event.key==='Escape' && document.getElementById('game-result').style.display==='block') { dismissRoundResult(); return; }
  if (event.key==='Escape' && !document.fullscreenElement) setFocusMode(false);
  if (event.defaultPrevented || event.repeat || event.isComposing || event.altKey) return;
  if (event.target instanceof Element && event.target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"])')) return;
  if (!document.getElementById('scene-assets').open || !sceneAssets.model || document.body.classList.contains('focus-mode')) return;
  const key=event.key.toLowerCase();
  if ((event.ctrlKey || event.metaKey) && key==='z') {
    if (sceneMoveTool.dragging) { sceneAssets.endMove(); sceneMoveTool.dragging=false; }
    const applied=event.shiftKey?sceneAssets.redo():sceneAssets.undo();
    if (applied) event.preventDefault();
  } else if (!event.ctrlKey && !event.metaKey && !event.shiftKey && document.getElementById('scene-move-tool').checked) {
    const mode={w:'translate',e:'rotate',r:'scale'}[key];
    if (mode) { setSceneToolMode(mode); event.preventDefault(); }
  }
});
// Engineering pages sit behind "進階" so the everyday tabs stay in front.
const ADVANCED_TABS = ['mon', 'body', 'sys'];
let currentTab = 'cal', lastAdvancedTab = 'mon';
function toggleAdvancedTabs() {
  selectTab(ADVANCED_TABS.includes(currentTab) ? 'cal' : lastAdvancedTab);
}
function selectTab(name) {
  if (name === 'games') updateGameLibrary();  // best scores follow the current input source
  const advanced = ADVANCED_TABS.includes(name);
  currentTab = name;
  if (advanced) lastAdvancedTab = name;
  document.getElementById('subtabbar').hidden = !advanced;
  const toggle = document.getElementById('advanced-toggle');
  toggle.classList.toggle('active', advanced);
  toggle.setAttribute('aria-expanded', String(advanced));
  document.querySelectorAll('.tab').forEach(t => {
    const selected = t.dataset.tab === name;
    t.classList.toggle('active', selected);
    t.setAttribute('aria-selected', String(selected));
  });
  document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.id === 'page-' + name));
  document.getElementById('content').scrollTop = 0;
  setCombatMode(name === 'combat');
  try { sessionStorage.setItem(TAB_STORAGE_KEY, name); } catch {}  // a reload reopens this tab
}
const TAB_STORAGE_KEY = 'aetherpose-tab';
document.querySelectorAll('.tab').forEach(tabEl => {
  tabEl.setAttribute('role', 'tab');
  tabEl.setAttribute('aria-selected', String(tabEl.classList.contains('active')));
  tabEl.tabIndex = 0;
  tabEl.addEventListener('click', () => selectTab(tabEl.dataset.tab));
  tabEl.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectTab(tabEl.dataset.tab); }
    else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      // Arrow keys move along the same row of tabs and wrap around (WAI-ARIA tabs pattern).
      const row = [...tabEl.parentElement.querySelectorAll('.tab')];
      const next = row[(row.indexOf(tabEl) + (e.key === 'ArrowRight' ? 1 : -1) + row.length) % row.length];
      e.preventDefault(); selectTab(next.dataset.tab); next.focus();
    }
  });
});
document.addEventListener('visibilitychange', () => {
  reportPageVisibility();
  AetherCombat.setSuspended(document.hidden);
  if (document.hidden && game.state === 'playing') endGame('Tab hidden');
});

// ── Init ───────────────────────────────────────────────────────────────────
const initialSceneSettings=loadSceneSettings();
loadSoundSetting();
buildGameLibrary();
fillShakeBones();
buildCustomCircuit();
renderLastTrainingReport();
applySceneSettings(initialSceneSettings.quality,initialSceneSettings.brightness);
resizeRenderer();
animate();
connect();
connectMeshBridge();
renderToolState();
refreshFirmwareMag().then(pollTool);  // also resumes the display of a run started before a reload
warnSoftwareRendering();
function finishBootSplash() {
  const splash=document.getElementById('boot-splash');
  if (!splash || splash.classList.contains('done')) return;
  splash.classList.add('done'); setTimeout(()=>splash.remove(),700);
}
setTimeout(finishBootSplash,4000);
// Accept old bookmarks and run.ps1 -Combat, then normalize to the single
// application URL. Otherwise a reload reopens the tab this browser tab was on.
if (location.hash === '#combat') {
  selectTab('combat');
  history.replaceState(null, '', location.pathname + location.search);
} else {
  let savedTab = null;
  try { savedTab = sessionStorage.getItem(TAB_STORAGE_KEY); } catch {}
  if (savedTab && savedTab !== 'cal' && document.querySelector(`.tab[data-tab="${CSS.escape(savedTab)}"]`)) selectTab(savedTab);
}
