// Runs against the real page and Three.js with a controlled pose/clock/socket.
(async () => {
  const checks = [];
  const assert = (ok, name) => { if (!ok) throw Error(name); checks.push(name); };
  const $ = id => document.getElementById(id);
  const tick = seconds => {
    window.testClock += seconds * 1000;
    avatar.tick(seconds, performance.now() / 1000);
    AetherCombat.tick(performance.now() / 1000);
  };
  const joints = () => [
    [0,0,0],[-.09,-.08,0],[.09,-.08,0],[0,.12,0],[-.09,-.45,0],[.09,-.45,0],
    [0,.28,0],[-.09,-.86,0],[.09,-.86,0],[0,.4,0],[-.09,-.9,.12],[.09,-.9,.12],
    [0,.54,0],[-.15,.42,0],[.15,.42,0],[0,.68,0],[-.22,.4,0],[.22,.4,0],
    [-.4,.27,0],[.4,.27,0],[-.58,.15,0],[.58,.15,0],[-.64,.15,0],[.64,.15,0]
  ];
  const packet = data => meshWs.onmessage({data: JSON.stringify(data)});
  // The pose service sends a skin once and joint rotations with each pose; the page skins the mesh.
  // A test skin binds every vertex to the root, so an identity pose gives back the template.
  const SMPL_PARENTS = [-1,0,0,0,1,2,3,4,5,6,7,8,9,9,9,12,13,14,16,17,18,19,20,21];
  const testSkin = template => ({template, joints: Array(72).fill(0), parents: SMPL_PARENTS,
    bones: Array(template.length / 3 * 4).fill(0), weights: Array.from({length: template.length / 3 * 4}, (_, i) => i % 4 ? 0 : 1)});
  const posed = (root = [1,0,0,0,1,0,0,0,1], translation = [0,0,0]) =>
    ({rotations: [...root, ...Array.from({length: 23 * 9}, (_, i) => [1,0,0,0,1,0,0,0,1][i % 9])], translation});
  const meshPacket = (template, version) => packet({skin: testSkin(template), joints: joints(), joints_version: version, pose: posed()});
  try {
    assert(window.testErrors.length === 0, 'page initializes without errors');
    assert(document.querySelectorAll('canvas').length === 1, 'one canvas');
    assert(window.testRafRequests === 1, 'one animation loop');
    const originalCamera = camera.position.clone();
    const applicationUrl=location.href;
    const root = avatar.root;
    assert($('game-library').open && document.querySelectorAll('[data-game-choice]').length===14,'all fourteen game choices visible on entry');
    assert($('page-cal').classList.contains('active') && !$('page-cal').contains($('game-library')) && $('page-games').contains($('game-library')),
      'setup comes first; the game library has its own tab');
    selectTab('games');
    $('game-search').value='深蹲'; $('game-search').dispatchEvent(new Event('input'));
    assert(document.querySelectorAll('[data-game-choice]:not([hidden])').length===1 && !document.querySelector('[data-game-choice="squat"]').hidden,'Chinese game search finds squat');
    assert(document.querySelector('[data-game-choice="reach"]').getClientRects().length===0 && document.querySelector('[data-game-choice="squat"]').getClientRects().length>0,'search filters rendered cards in the real browser');
    $('game-search').value='  COMBAT  '; filterGameLibrary();
    assert(document.querySelectorAll('[data-game-choice]:not([hidden])').length===1 && !document.querySelector('[data-game-choice="combat"]').hidden,'game search ignores case and surrounding spaces');
    $('game-search').value='<script>'; filterGameLibrary();
    assert(document.querySelectorAll('[data-game-choice]:not([hidden])').length===0 && $('game-search-status').textContent.includes('沒有符合'),'unmatched search has a safe empty result message');
    $('game-search').value=''; filterGameLibrary();
    assert($('game-search-status').textContent==='','the game count is shown only while a filter hides games');
    const recordsBeforeCards=poseRecords;
    poseRecords={...poseRecords,[`squat:${aetherPoseSource(bridgeStatus).signature}`]:12};
    updateGameLibrary();
    assert(document.querySelector('[data-game-choice="squat"] .game-card-best').textContent==='最佳 12' &&
      !document.querySelector('[data-game-choice="balance"] .game-card-best').textContent && !document.querySelector('[data-game-choice="combat"] .game-card-best').textContent,
      'library cards show the best score for the current input source');
    poseRecords=recordsBeforeCards; updateGameLibrary();
    const confirmBeforeClear=window.confirm, historyBeforeClear=roundHistory, recordsBeforeClear=poseRecords;
    roundHistory=[{mode:'reach',score:3,source:'demo:0',completed:true,reason:"Time's up",seconds:60,at:Date.now()}];
    poseRecords={'reach:demo:0':3};
    window.confirm=()=>false;
    assert(!askClearRoundHistory() && roundHistory.length===1 && !askClearBestScores() && poseRecords['reach:demo:0']===3,
      'clearing history or best scores needs a confirmation');
    window.confirm=()=>true;
    assert(askClearBestScores() && !Object.keys(poseRecords).length && roundHistory.length===1 && $('panel-notice-text').textContent==='已清除最佳成績。',
      'best scores can be cleared without touching the history');
    assert(askClearRoundHistory() && !roundHistory.length, 'confirmed history clearing empties it');
    window.confirm=confirmBeforeClear; roundHistory=historyBeforeClear; poseRecords=recordsBeforeClear; hidePanelNotice(); renderRoundHistory(); updateGameLibrary();
    assert(document.querySelectorAll('[data-game-choice]:not([hidden])').length===14 && game.state!=='playing','clearing search restores choices without starting a game');
    selectTab('combat'); openGameLibrary();
    assert(!combatMode && $('page-games').classList.contains('active') && $('game-library').getClientRects().length>0 && $('content').scrollTop>=0,
      'the Games button opens the library from Combat');
    for (const mode of Object.keys(poseGameNames)) {
      document.querySelector(`[data-game-choice="${mode}"]`).click();
      assert(!combatMode && $('game-mode').value===mode && $('game-btn').textContent===`開始 ${poseGameNames[mode]}` && game.state!=='playing',`library selects ${mode} without starting unavailable tracking`);
      assert(document.querySelector(`[data-game-choice="${mode}"]`).getAttribute('aria-pressed')==='true',`${mode} library selection marked`);
      assert($('game-guide').textContent.includes(poseGameNames[mode]) && $('game-guide').textContent.includes('60 秒'),`${mode} has a matching guide and duration`);
    }
    document.querySelector('[data-game-choice="combat"]').click();
    assert(combatMode && document.querySelector('[data-game-choice="combat"]').getAttribute('aria-pressed')==='true','library selects Combat in the shared scene');
    assert($('game-guide').textContent.includes('90 秒') && $('game-guide').textContent.includes('開始回合'),'Combat guide matches its round controls');
    $('game-library').open=false; setFocusMode(true); openGameLibrary();
    assert($('game-library').open && !document.body.classList.contains('focus-mode'),'Games button reveals library from focus mode');
    chooseGame('reach');
    const favoriteSaved=localStorage.getItem(gameFavoriteKey);
    gameFavorites=new Set(); updateGameLibrary();
    $('game-favorites-only').checked=true; filterGameLibrary();
    assert(document.querySelectorAll('[data-game-choice]:not([hidden])').length===0 && $('game-search-status').textContent.includes('收藏'),'empty favorites explain how to restore all games');
    $('game-favorite-btn').click();
    assert(loadGameFavorites().has('reach') && $('game-favorite-btn').getAttribute('aria-pressed')==='true' && document.querySelectorAll('[data-game-choice]:not([hidden])').length===1,'favorite action saves the selected game and updates filter');
    chooseGame('combat'); $('game-favorite-btn').click();
    assert(loadGameFavorites().has('combat') && document.querySelectorAll('[data-game-choice]:not([hidden])').length===2,'Combat can be saved with Pose favorites');
    $('game-search').value='Reach'; filterGameLibrary();
    assert(document.querySelectorAll('[data-game-choice]:not([hidden])').length===1,'search combines with favorites filter');
    chooseGame('reach'); $('game-favorite-btn').click();
    assert(!loadGameFavorites().has('reach') && document.querySelectorAll('[data-game-choice]:not([hidden])').length===0,'removing a favorite updates filtered results');
    localStorage.setItem(gameFavoriteKey,JSON.stringify(['combat','combat','bad',null,{}]));
    assert(loadGameFavorites().size===1 && loadGameFavorites().has('combat'),'stored favorites reject unknown IDs and remove duplicates');
    localStorage.setItem(gameFavoriteKey,'broken');
    assert(loadGameFavorites().size===0,'corrupt favorites do not break the game library');
    if (favoriteSaved===null) localStorage.removeItem(gameFavoriteKey); else localStorage.setItem(gameFavoriteKey,favoriteSaved);
    gameFavorites=loadGameFavorites(); $('game-search').value=''; $('game-favorites-only').checked=false;
    updateGameLibrary(); filterGameLibrary();
    const navigationHistory=roundHistory;
    roundHistory=[{mode:'shoulder',score:2,source:'demo:0',completed:true,reason:'Time up',seconds:60,at:Date.now()},
      {mode:'combat',score:3,source:'demo:0',completed:false,reason:'Round ended',seconds:12,at:Date.now()}];
    renderRoundHistory();
    $('game-search').value='no matching game'; $('game-favorites-only').checked=true; filterGameLibrary();
    setFocusMode(true); $('game-library').open=false;
    document.querySelector('[data-history-game="shoulder"]').click();
    assert(!combatMode && $('game-mode').value==='shoulder' && game.state!=='playing','history selects its Pose game without automatically starting');
    assert($('game-library').open && !document.body.classList.contains('focus-mode') && $('game-search').value==='' && !$('game-favorites-only').checked,'history reveals the selected game even with hidden panel and filters');
    const navigationCamera=camera.position.clone();
    document.querySelector('[data-history-game="combat"]').click();
    assert(combatMode && avatar.root===root && camera.position.equals(navigationCamera) && location.href===applicationUrl,'history opens Combat while preserving the shared world and URL');
    assert(roundHistory.length===2 && roundHistory[0].score===2,'history navigation preserves original results');
    roundHistory=navigationHistory; renderRoundHistory(); chooseGame('reach');
    const fitBodyPosition=avatar.root.position.clone();
    setFollowPose(true); $('scene-fit-all').click();
    assert($('scene-view').value==='custom' && !followPose && camera.position.distanceTo(controls.target)>0,'Fit all frames the visible world and disables automatic following');
    assert(avatar.root.position.equals(fitBodyPosition) && game.state!=='playing' && location.href===applicationUrl,'Fit all preserves body, activity and URL');
    camera.updateMatrixWorld(true);
    assert(camera.position.distanceTo(controls.target)<10, 'Fit all frames the arena, not the whole training hall');
    const hall=scene.getObjectByName('aether-hall');
    assert(hall && hall.getObjectByName('arena-screen') && !scenePhysics.colliders.some(collider=>{let node=collider;while(node){if(node===hall)return true;node=node.parent;}return false;}),
      'the training hall surrounds the arena without adding colliders');
    const fitEnvironment=new THREE.Box3().setFromObject(scene.getObjectByName('aether-environment'));
    for (const x of [fitEnvironment.min.x,fitEnvironment.max.x]) for (const y of [fitEnvironment.min.y,fitEnvironment.max.y]) for (const z of [fitEnvironment.min.z,fitEnvironment.max.z]) {
      const projected=new THREE.Vector3(x,y,z).project(camera);
      assert(Math.abs(projected.x)<=1 && Math.abs(projected.y)<=1 && projected.z>=-1 && projected.z<=1,'Fit all keeps environment corners inside viewport');
    }
    const fitCamera=camera.position.clone();
    assert(!frameSceneBounds(new THREE.Box3()) && camera.position.equals(fitCamera),'empty scene bounds do not change the camera');
    setSceneView('front');
    const bookmarkPrevious=localStorage.getItem(cameraBookmarkKey);
    setSceneView('side'); const bookmarkPosition=camera.position.clone(),bookmarkTarget=controls.target.clone();
    $('camera-bookmark-save').click(); setSceneView('front'); setFollowPose(true);
    $('camera-bookmark-restore').click();
    assert(camera.position.distanceTo(bookmarkPosition)<1e-6 && controls.target.distanceTo(bookmarkTarget)<1e-6 && !followPose && $('scene-view').value==='custom','saved camera bookmark restores view and stops following');
    assert(avatar.root===root && avatar.root.position.equals(fitBodyPosition) && game.state!=='playing','camera bookmark preserves shared avatar and activity');
    localStorage.setItem(cameraBookmarkKey,JSON.stringify({version:1,position:[0,0,0],target:[0,0,0]}));
    assert(!restoreCameraBookmark() && camera.position.distanceTo(bookmarkPosition)<1e-6,'zero-distance bookmark cannot corrupt camera');
    localStorage.setItem(cameraBookmarkKey,JSON.stringify({version:1,position:[999,0,0],target:[0,0,0]}));
    assert(readCameraBookmark()===null,'out-of-range bookmark is rejected');
    localStorage.setItem(cameraBookmarkKey,'broken');
    assert(!restoreCameraBookmark() && $('camera-bookmark-status').textContent.includes('儲存視角'),'corrupt bookmark provides recoverable status');
    if(bookmarkPrevious===null) localStorage.removeItem(cameraBookmarkKey); else localStorage.setItem(cameraBookmarkKey,bookmarkPrevious);
    setSceneView('front');
    for (let i=0; i<20; i++) { selectTab('combat'); tick(.016); selectTab('cal'); }
    assert(camera.position.distanceTo(originalCamera) < 1e-6, 'camera restored after 20 switches');
    assert(location.href===applicationUrl, 'pose and combat switches preserve the exact application URL');
    assert(avatar.root === root && root.parent === scene, 'one avatar remains in shared scene');
    assert(window.testRafRequests === 1, 'switching creates no extra animation loops');
    selectTab('combat'); $('start-btn').click();
    assert($('start-btn').textContent === '開始回合', 'missing pose cannot start round');
    selectTab('cal'); startGame();
    assert(game.state!=='playing' && $('pose-game-cue').textContent.includes('完整的最新姿態'), 'pose games explain unavailable tracking');
    selectTab('combat');
    packet({joints: joints(), joints_version: 1}); tick(.016);
    assert(root.visible, 'fresh pose visible');
    const skeleton = root.getObjectByName('aether-skeleton');
    const skelGeometry = skeleton.geometry;
    packet({joints: joints(), joints_version: 2});
    assert(root.getObjectByName('aether-skeleton').geometry === skelGeometry, 'skeleton buffers reused');
    $('start-btn').click();
    assert($('start-btn').textContent === '重新開始', 'fresh pose starts round');
    $('reset-btn').click();
    assert($('start-btn').textContent === '開始回合' && $('round-time').textContent === '90', 'reset restores controls and timer');
    $('start-btn').click(); selectTab('cal');
    assert($('start-btn').textContent === '開始回合', 'leaving activity stops round');
    selectTab('combat');
    packet({faces: [[0,1,2]]});
    meshPacket([0,0,0,.2,0,0,0,.3,0], 'mesh-1'); tick(.016);
    const body = root.getObjectByName('aether-body');
    assert(!!body && root.children.filter(o => o.name === 'aether-body').length === 1, 'one body mesh');
    selectTab('cal'); selectTab('combat');
    assert(root.getObjectByName('aether-body') === body, 'same mesh used by control and combat');
    assert(root.position.x === -.55 && root.scale.x === .96, 'arena uses avatar transform');
    selectTab('cal');
    assert(root.position.x === avatar.combatX && root.position.y === .97*.96 && root.scale.x === .96, 'all activities preserve the arena avatar transform');
    assert(scene.getObjectByName('combat-world').visible && poseScene.visible, 'arena and pose objects are simultaneously visible');
    avatar.tick(.016,performance.now()/1000);
    assert(!skeleton.visible, 'loaded body hides duplicate skeleton by default');
    updateSkeleton([{id:0,parent_id:null,pos:[0,1,0]},{id:1,parent_id:0,pos:[0,1.5,0]}]);
    assert(!skelLines.visible, 'calibration hides backend debug skeleton by default');
    $('debug-view').checked=true; setDebugView(true); avatar.tick(.016,performance.now()/1000);
    assert(skeleton.visible && skelLines.visible, 'debug control enables diagnostic skeletons');
    $('debug-view').checked=false; setDebugView(false); avatar.tick(.016,performance.now()/1000);
    assert(!skeleton.visible && !skelLines.visible && scene.getObjectByName('combat-world').visible, 'hiding overlays keeps the unified arena visible');
    const controlFoot = root.localToWorld(new THREE.Vector3(...avatar.joints[10]));
    assert(controlFoot.y >= 0 && controlFoot.y < .2, 'control avatar stands on shared floor');
    selectTab('combat');
    const before = Array.from(body.geometry.attributes.position.array);
    assert(!avatar.onVertsFlat(Float32Array.from([NaN,0,0])), 'nonfinite mesh rejected');
    assert(!avatar.onVertsFlat(Float32Array.from([0,0,0])), 'undersized mesh rejected');
    assert(!avatar.onFaces([[0,1,-1]]) && !avatar.onFaces([[0,1,.5]]), 'invalid topology rejected');
    assert(!AetherCombat.onJoints([[0,0,0]]), 'partial skeleton rejected');
    const bad = joints(); bad[22][0] = NaN;
    assert(!AetherCombat.onJoints(bad), 'nonfinite pose rejected');
    assert(before.every((v,i) => v === body.geometry.attributes.position.array[i]), 'bad packets preserve geometry');
    packet({faces: [[0,2,1]]});
    assert(!root.getObjectByName('aether-body'), 'new topology retires old mesh');
    meshPacket([0,0,0,.2,0,0,0,.3,0,.1,.1,.1], 'mesh-2'); tick(.016);
    assert(root.getObjectByName('aether-body').geometry.attributes.position.count === 4, 'new vertex count recreates buffers');
    const pelvisVerts = Float32Array.from([0,0,0,.2,0,0,0,.3,0]);
    meshPacket([...pelvisVerts], 'mesh-3'); tick(.016);
    assert(root.getObjectByName('aether-body').geometry.attributes.position.array.every((v,i)=>v===pelvisVerts[i]),
      'the mesh uses the same coordinates as the skeleton');
    // Root turned 90 degrees about Y and moved 0.1 m along x: (x, y, z) -> (z + .1, y, -x).
    packet({joints: joints(), joints_version: 'mesh-4', pose: posed([0,0,1,0,1,0,-1,0,0], [.1,0,0])});
    avatar.tick(1, performance.now()/1000);
    const turnedBody = root.getObjectByName('aether-body').geometry.attributes.position.array;
    assert([.1,0,0, .1,0,-.2, .1,.3,0].every((v,i)=>Math.abs(turnedBody[i]-v)<1e-6), 'the page skins the body mesh from each pose\'s rotations');
    assert(!AetherCombat.onPose({rotations: [1,0,0], translation: [0,0,0]}) && !AetherCombat.onSkin({template: [0,0,0]}),
      'malformed pose or skin is refused');
    assert(!avatar.onFaces([[0,1,4294967296]]), 'overflowing mesh index rejected');
    packet({joints: joints(), joints_version: 3}); $('start-btn').click();
    for (let i=0;i<6;i++) { tick(1); packet({joints: joints(), joints_version: 3}); }
    avatar.tick(0,performance.now()/1000);
    assert(!root.visible && $('start-btn').textContent === '開始回合', 'cached heartbeat cannot keep pose or round alive');
    packet({joints: joints(), joints_version: 4}); tick(.016); $('start-btn').click();
    assert($('start-btn').textContent === '重新開始', 'new pose recovers after expiry');
    AetherCombat.stopRound('Body calibration. Round stopped.');
    assert($('start-btn').textContent === '開始回合' && document.body.textContent.includes('開始身體校正，回合停止'),
      'body calibration stops a combat round with its reason');
    meshWs.onclose();
    assert(!root.visible && $('start-btn').textContent === '開始回合', 'disconnect hides avatar and stops round');
    assert($('tp-status').textContent==='姿態服務已斷線' && $('tp-status').title.includes('run.ps1') && bridgeStatus==='',
      'a pose service disconnect says how to recover and forgets the old status');
    packet({joints: joints(), joints_version: 4}); tick(.016); $('start-btn').click();
    assert($('start-btn').textContent === '重新開始', 'reconnection accepts repeated initial version');
    tick(91); packet({joints: joints(), joints_version: 5}); tick(.016);
    assert($('start-btn').textContent === '開始回合', 'expired round stays stopped');
    $('reset-btn').click();
    assert($('round-time').textContent === '90', 'reset works after expiry');
    const random = Math.random;
    Math.random = () => .4; // body target, body attack
    packet({joints: joints(), joints_version: 6}); $('start-btn').click();
    const windup = joints();
    windup[22] = [.45,.23,-.16]; windup[20] = [.2,.23,-.16];
    tick(.4); packet({joints: windup, joints_version: 7});
    tick(.04);
    const punch = joints();
    punch[22] = [.85,.23,-.16]; punch[20] = [.6,.23,-.16];
    packet({joints: punch, joints_version: 8});
    assert(+$('enemy-hp-text').textContent < 100, 'moving hand collider damages enemy on current pose');
    assert(scene.getObjectByName('aether-opponent').userData.animation==='No', 'opponent reacts to a landed strike');
    const directionalHp=+$('enemy-hp-text').textContent;
    tick(.4); packet({joints:punch,joints_version:71});
    const returningHand=punch.map(point=>point.slice()); returningHand[22][0]=.7; returningHand[20][0]=.45;
    tick(.04); packet({joints:returningHand,joints_version:72});
    assert(+$('enemy-hp-text').textContent===directionalHp,'retracting a hand cannot create another punch');
    tick(.4); packet({joints:punch,joints_version:73});
    const movingTorso=punch.map(point=>point.slice());
    for(const joint of [3,6,9,12,13,14,15,16,17,18,19,20,21,22,23]) movingTorso[joint][0]+=.12;
    tick(.04); packet({joints:movingTorso,joints_version:74});
    assert(+$('enemy-hp-text').textContent===directionalHp,'moving the chest and hand together does not manufacture a punch');
    tick(.4); packet({joints:joints(),joints_version:75});
    const invalidArmSample=punch.map(point=>point.slice()); invalidArmSample[9][0]=-.08;
    tick(.04); packet({joints:invalidArmSample,joints_version:76});
    assert(+$('enemy-hp-text').textContent===directionalHp,'invalid hand sample cannot borrow chest velocity to create a punch');
    const hp = +$('enemy-hp-text').textContent;
    let blockedAttackChecks=0;
    AetherCombat.setPhysics({segmentBlocked(){blockedAttackChecks++;return true;}});
    tick(.4); packet({joints:windup,joints_version:80}); tick(.04); packet({joints:punch,joints_version:81});
    assert(blockedAttackChecks>0 && +$('enemy-hp-text').textContent===hp, 'combat obstruction rejects a strike that intersects enemy hitbox');
    AetherCombat.setPhysics({segmentBlocked(from,to,radius=0){return radius===0;}});
    tick(.4); packet({joints:windup,joints_version:811}); tick(.04); packet({joints:punch,joints_version:812});
    assert(+$('enemy-hp-text').textContent===hp && $('event-feed').textContent.includes('命中路徑'),'blocked opponent contact is reported as scene obstruction instead of an ordinary miss');
    AetherCombat.setPhysics(scenePhysics);
    let sweptAttackPath;
    AetherCombat.setPhysics({segmentBlocked(from,to){
      const distance=from.distanceTo(to);
      if (distance>.37 && distance<.40) { sweptAttackPath={from:from.clone(),to:to.clone()}; return true; }
      return false;
    }});
    tick(.4); packet({joints:windup,joints_version:82}); tick(.04); packet({joints:punch,joints_version:83});
    const expectedSweepStart=avatar.root.localToWorld(new THREE.Vector3(...windup[22]));
    const expectedSweepEnd=avatar.root.localToWorld(new THREE.Vector3(...punch[22]));
    assert(sweptAttackPath && sweptAttackPath.from.distanceTo(expectedSweepStart)<1e-6 && sweptAttackPath.to.distanceTo(expectedSweepEnd)<1e-6 && +$('enemy-hp-text').textContent===hp, 'swept limb path obstruction prevents damage even when final hitbox intersects opponent');
    AetherCombat.setPhysics(scenePhysics);
    const strikeWall=new THREE.Mesh(new THREE.BoxGeometry(.015,.15,.15));
    strikeWall.position.copy(expectedSweepStart).lerp(expectedSweepEnd,.5);
    scene.add(strikeWall); scenePhysics.addCollider(strikeWall);
    tick(.4); packet({joints:windup,joints_version:84}); tick(.04); packet({joints:punch,joints_version:85});
    assert(+$('enemy-hp-text').textContent===hp && $('event-feed').textContent.includes('場景擋住了手腳的動作'), 'actual thin scene mesh blocks fast hand movement between pose samples');
    scenePhysics.removeCollider(strikeWall); scene.remove(strikeWall); strikeWall.geometry.dispose(); strikeWall.material.dispose();
    const teleported = joints(); teleported[22] = [3,.23,-.16];
    tick(.4); packet({joints: teleported, joints_version: 9});
    assert(+$('enemy-hp-text').textContent === hp, 'teleport cannot create a strike');
    $('reset-btn').click();
    packet({joints: joints(), joints_version: 10}); $('start-btn').click();
    assert(scene.getObjectByName('aether-opponent').userData.animation==='Idle', 'new round restores idle opponent animation');
    assert(!$('combat-target-progress').hidden && $('combat-target-progress').value>4 && $('target-window').textContent.includes('目標剩餘'),'combat target displays fresh remaining-time budget');
    const facingMarker=scene.getObjectByName('combat-target-marker');
    assert(facingMarker.position.x<-.15 && Math.abs(facingMarker.position.x)<.21,'combat marker offsets toward player while remaining close to original hit zone');
    tick(2.7); packet({joints: joints(), joints_version: 11});
    assert(scene.getObjectByName('aether-opponent').userData.ai.phase==='windup' && $('incoming-window').textContent.includes('蓄力'), 'enemy attack warns before committing punch');
    assert($('combat-target-progress').value<2 && scene.getObjectByName('combat-target-marker').material.color.getHex()===0xf5bd48,'target timer decreases and all prompted zones use gold marker');
    const incomingProgress=$('combat-attack-progress').value;
    assert(!$('combat-attack-progress').hidden && $('incoming-window').textContent.includes('秒') && $('incoming-window').textContent.includes('雙手防守'),'incoming telegraph provides countdown and suitable defense');
    tick(.7); packet({joints:joints(),joints_version:111});
    assert(scene.getObjectByName('aether-opponent').userData.animation==='Punch' && scene.getObjectByName('aether-opponent').userData.ai.phase==='strike','enemy punch animation starts during strike phase');
    assert($('combat-attack-progress').value>incomingProgress,'telegraph progress advances toward enemy impact');
    tick(.4); packet({joints: joints(), joints_version: 12});
    assert(+$('player-hp-text').textContent < 100, 'undefended attack damages player');
    const learningBrain=scene.getObjectByName('aether-opponent').userData.ai;
    assert(learningBrain.landed.body===1,'enemy learns which attack penetrated player defense');
    assert($('combat-attack-progress').hidden && $('combat-attack-progress').value===0,'resolved attack clears telegraph progress');
    const hitWorldPosition=avatar.root.localToWorld(new THREE.Vector3(...avatar.joints[9]));
    const hitSparks=scene.getObjectByName('combat-world').children.filter(object=>object.name==='combat-impact' && object.material.color.getHex()===0xf25c66);
    assert(hitSparks.length===14 && hitSparks.every(object=>object.position.distanceTo(hitWorldPosition)<.1), 'enemy hit effects follow constrained body world position');
    tick(3.5); packet({joints:joints(),joints_version:121});
    assert(Math.abs(learningBrain.weights.body-.54)<1e-6 && learningBrain.weights.high===1,'successful attack gains preference while repetition penalty preserves variety');
    $('reset-btn').click(); packet({joints:joints(),joints_version:101});
    let blockedEnemyChecks=0;
    AetherCombat.setPhysics({segmentBlocked(){blockedEnemyChecks++;return true;}});
    $('start-btn').click(); tick(2.7); packet({joints:joints(),joints_version:102});
    tick(1.1); packet({joints:joints(),joints_version:103});
    assert(blockedEnemyChecks>0 && +$('player-hp-text').textContent===100 && $('event-feed').textContent.includes('場景擋住了攻擊'), 'solid scene obstruction blocks enemy damage without requiring guard');
    assert(scene.getObjectByName('aether-opponent').userData.ai.phase==='cover' && $('incoming-zone').textContent==='無','enemy waits instead of starting an attack when every route is blocked');
    assert($('target-zone').textContent==='場景遮擋' && $('combat-target-progress').hidden && !scene.getObjectByName('combat-target-marker').visible,'fully obstructed combat hides impossible target and explains the scene problem');
    assert(!$('combat-target-routes').hidden && $('combat-target-routes').textContent.includes('所有目標'),'fully obstructed combat explains unavailable routes');
    AetherCombat.setPhysics({segmentBlocked(origin,destination){return destination.y<1.3;}});
    tick(.3); packet({joints:joints(),joints_version:1031}); tick(.016);
    assert($('target-zone').textContent==='頭' && !$('combat-target-progress').hidden && scene.getObjectByName('combat-target-marker').visible,'combat target selection recovers using unobstructed head zone');
    assert($('combat-target-routes').textContent==='可攻擊：頭','partial obstruction lists only available attack zones');
    assert($('combat-target-progress').value>4,'restored target receives a fresh difficulty-specific time budget');
    assert($('incoming-window').textContent.includes('路徑被擋'),'incoming panel distinguishes scenery obstruction from a pending attack');
    AetherCombat.setPhysics({segmentBlocked(origin){return origin.y<1.3;}});
    $('reset-btn').click(); packet({joints:joints(),joints_version:104}); $('start-btn').click();
    tick(2.7); packet({joints:joints(),joints_version:105});
    const routeBrain=scene.getObjectByName('aether-opponent').userData.ai;
    assert(routeBrain.lastType==='high' && routeBrain.weights.body===0 && routeBrain.weights.flank===0,'enemy selects an unobstructed high attack when torso routes are covered');
    AetherCombat.setPhysics({segmentBlocked(){return true;}});
    tick(1.1); packet({joints:joints(),joints_version:106});
    assert(+$('player-hp-text').textContent===100,'cover introduced after enemy windup still prevents damage');
    AetherCombat.setPhysics(scenePhysics);
    $('reset-btn').click(); packet({joints:joints(),joints_version:107}); $('start-btn').click();
    const originalPlayerX=root.position.x; root.position.x-=3; root.updateMatrixWorld(true);
    window.testClock+=2700; AetherCombat.tick(performance.now()/1000);
    assert(routeBrain.phase==='distance' && $('incoming-zone').textContent==='無' && Object.values(routeBrain.routes).every(reason=>reason==='distance'),'enemy does not wind up attacks against an out-of-range player');
    assert($('incoming-window').textContent.includes('進入攻擊範圍'),'incoming panel identifies an out-of-range enemy');
    root.position.x=originalPlayerX; root.updateMatrixWorld(true);
    $('reset-btn').click(); packet({joints:joints(),joints_version:108}); $('start-btn').click();
    tick(2.7); packet({joints:joints(),joints_version:109});
    root.position.x-=3; root.updateMatrixWorld(true);
    window.testClock+=1100; AetherCombat.tick(performance.now()/1000);
    assert(+$('player-hp-text').textContent===100 && $('event-feed').textContent.includes('超出攻擊距離'),'moving out of range during windup prevents remote damage');
    root.position.x=originalPlayerX; root.updateMatrixWorld(true);
    $('reset-btn').click();
    const guard = joints(); guard[22] = [-.12,.64,0]; guard[23] = [.12,.64,0];
    const oneSidedGuard=guard.map(point=>point.slice()); oneSidedGuard[23]=[-.16,.64,0];
    packet({joints:oneSidedGuard,joints_version:130});
    assert(!$('tag-guard').classList.contains('on'),'two hands on the same side cannot count as full guard');
    packet({status:'Streaming #13 DEBUG mask=test live 0/6',joints: guard, joints_version: 13}); $('start-btn').click();
    assert($('tag-guard').classList.contains('on'),'separated hands beside both sides of head form guard');
    const turnedGuard=guard.map(point=>new THREE.Vector3(...point).applyAxisAngle(new THREE.Vector3(0,1,0),Math.PI/2).toArray());
    packet({joints:turnedGuard,joints_version:131});
    assert($('tag-guard').classList.contains('on'),'guard coverage follows shoulder orientation after turning');
    packet({joints:guard,joints_version:132});
    Math.random=()=>0;
    tick(2.7); packet({joints: guard, joints_version: 14});
    const adaptiveBrain=scene.getObjectByName('aether-opponent').userData.ai;
    assert(adaptiveBrain.weights.flank>adaptiveBrain.weights.high && adaptiveBrain.weights.flank>adaptiveBrain.weights.body,'enemy favors flank against held guard');
    tick(1.1); packet({joints: guard, joints_version: 15});
    assert(+$('player-hp-text').textContent === 100, 'guard blocks body attack');
    assert(adaptiveBrain.defended.high===1,'enemy remembers a successfully defended high attack');
    assert(adaptiveBrain.counterUntil>performance.now()/1000 && $('incoming-window').textContent.includes('+25%') && scene.getObjectByName('aether-opponent').userData.animation==='No','successful defense opens a visible counter window and staggers enemy animation');
    const counterSetup=windup.map(point=>point.slice());
    const counterPunch=punch.map(point=>point.slice());
    const counterEnemyHp=+$('enemy-hp-text').textContent;
    tick(.1); packet({joints:counterSetup,joints_version:148});
    tick(.04); packet({joints:counterPunch,joints_version:149});
    assert(+$('enemy-hp-text').textContent<counterEnemyHp && $('event-feed').textContent.includes('反擊命中'),'target hit inside counter window receives counterattack feedback and damage');
    tick(.81); packet({joints:guard,joints_version:150});
    assert(!$('incoming-window').textContent.includes('+25%'),'counter bonus indicator expires after its window');
    assert($('incoming-window').textContent.includes('恢復中') && $('incoming-window').textContent.includes('秒'),'expired counter window shows remaining enemy recovery time');
    tick(3); packet({joints:guard,joints_version:151});
    assert(adaptiveBrain.weights.high<.5,'enemy reduces repeated attacks that were defended');
    AetherCombat.stopRound('Round ended');
    assert($('game-result').style.display==='block' && $('game-result').textContent.includes('防守 1') && $('game-result').textContent.includes('反擊 1') && $('game-result').textContent.includes('正確目標 1'),'finished round summarizes actual defenses counterattacks and correct target hits');
    assert(roundHistory[0].difficulty==='normal' && roundHistory[0].combatStats.defenses===1 && roundHistory[0].combatStats.counters===1 && loadRoundHistory()[0].combatStats.counters===1,'combat performance and round difficulty survive history storage');
    assert(roundHistory[0].combatBreakdown.defended.high===1 && loadRoundHistory()[0].combatBreakdown.defended.high===1,'per-attack defensive breakdown survives history storage');
    assert($('game-result').querySelector('.result-performance')?.textContent.includes('防守 1') && $('game-result').textContent.includes('練習建議'),'combat results dialog presents performance and coaching immediately');
    const singleRoundClick=HTMLAnchorElement.prototype.click; let singleRoundDownload=null;
    HTMLAnchorElement.prototype.click=function(){singleRoundDownload={name:this.download,url:this.href};};
    $('game-result').querySelector('[data-result-export]').click(); HTMLAnchorElement.prototype.click=singleRoundClick;
    const singleRoundReport=await (await fetch(singleRoundDownload.url)).json();
    assert(singleRoundReport.version===1 && singleRoundReport.rounds.length===1 && singleRoundReport.rounds[0].combatStats.counters===1 && singleRoundReport.rounds[0].difficulty==='normal','result export contains only current round with performance and difficulty');
    assert(singleRoundDownload.name.startsWith('aetherpose-combat-') && $('game-result').style.display==='block','single-round export preserves result dialog');
    HTMLAnchorElement.prototype.click=function(){singleRoundDownload={name:this.download,url:this.href};};
    $('history-list').querySelector('[data-history-export="combat"]').click(); HTMLAnchorElement.prototype.click=singleRoundClick;
    const historySingleReport=await (await fetch(singleRoundDownload.url)).json();
    assert(historySingleReport.rounds.length===1 && historySingleReport.rounds[0].at===roundHistory[0].at && historySingleReport.rounds[0].combatBreakdown.defended.high===1,'history row exports the exact saved combat round and breakdown');
    assert($('history-list').textContent.includes('難度：標準') && $('history-list').textContent.includes('反擊 1'),'history renders saved combat difficulty and performance');
    assert($('game-result').textContent.includes('練習建議') && $('history-list').textContent.includes('練習建議'),'round summary and saved history include coaching advice');
    const adviceBase={attempts:8,hits:7,targets:6,blocked:0,defenses:3,received:0,counters:1,bestCombo:4};
    assert(aetherCombatAdvice({...adviceBase,blocked:4}).includes('障礙'),'coaching prioritizes frequent scene obstruction');
    assert(aetherCombatAdvice({...adviceBase,received:5}).includes('來襲提示'),'coaching recognizes missed defenses');
    assert(aetherCombatAdvice({...adviceBase,hits:2,targets:1}).includes('有效距離'),'coaching recognizes low contact accuracy');
    assert(aetherCombatAdvice({...adviceBase,targets:1}).includes('目標部位'),'coaching distinguishes contact from correct targeting');
    assert(aetherCombatAdvice({...adviceBase,counters:0}).includes('0.8 秒'),'coaching recognizes unused counter opportunities');
    assert(aetherCombatAdvice(adviceBase).includes('更高難度'),'coaching suggests harder play only for consistent performance');
    const weakStats={...adviceBase,received:3};
    const flankBreakdown={received:{high:0,body:0,flank:3},defended:{high:2,body:1,flank:0}};
    assert(aetherCombatAdvice(weakStats,flankBreakdown).includes('側身閃避'),'coaching identifies missed flank defenses even with successful guards elsewhere');
    assert(aetherCombatDrill(weakStats,flankBreakdown)==='dodge' && aetherCombatDrill({...adviceBase,hits:2,targets:1})==='reach','coaching maps defense and aiming weaknesses to matching Pose drills');
    assert(aetherCombatDrill({...adviceBase,blocked:4})===null,'scenery obstruction does not produce an unrelated movement drill');
    assert(aetherCombatBreakdown(weakStats,{...flankBreakdown,received:{high:0,body:0,flank:99}})===null,'per-attack breakdown rejects totals inconsistent with round statistics');
    const invalidStatsHistory=normalizeCombatHistory({...roundHistory[0],difficulty:'unknown',combatStats:{...roundHistory[0].combatStats,hits:999999}});
    assert(!invalidStatsHistory.combatStats && !invalidStatsHistory.difficulty && invalidStatsHistory.score===roundHistory[0].score,'invalid combat extras are dropped without losing the round');
    $('reset-btn').click(); packet({joints:joints(),joints_version:201}); $('start-btn').click();
    assert(adaptiveBrain.lastType===null && Object.values(adaptiveBrain.defended).every(value=>value===0),'new round clears learned enemy defense history');
    assert(Object.values(adaptiveBrain.landed).every(value=>value===0),'new round clears learned player weaknesses');
    assert($('game-result').style.display==='none','new round clears previous result summary');
    tick(2.7); packet({joints:joints(),joints_version:202});
    tick(.1); packet({joints:windup,joints_version:203});
    tick(.04); packet({joints:punch,joints_version:204});
    assert(adaptiveBrain.phase==='stagger' && $('incoming-zone').textContent==='無' && +$('enemy-hp-text').textContent<100,'a landed counterstrike interrupts enemy windup');
    assert($('incoming-window').textContent.includes('失衡中'),'counterstrike interruption exposes enemy stagger window');
    tick(1.05); packet({joints:joints(),joints_version:205});
    assert(+$('player-hp-text').textContent===100,'interrupted windup cannot deal delayed damage');
    AetherCombat.stopRound('Round ended');
    assert($('game-result').textContent.includes('受擊 0') && $('game-result').textContent.includes('防守 0'),'interrupting windup does not count as an incoming hit or defense');
    const aiCrouch=joints(); aiCrouch[15][1]=.15; aiCrouch[9][1]=-.1; aiCrouch[0][1]=-.2;
    $('reset-btn').click(); packet({joints:aiCrouch,joints_version:206}); $('start-btn').click();
    tick(2.7); packet({joints:aiCrouch,joints_version:207});
    assert(adaptiveBrain.weights.body>adaptiveBrain.weights.high,'enemy favors body attacks against a crouched player');
    const shortStanding=joints().map(point=>point.map(value=>value*.7));
    packet({joints:shortStanding,joints_version:2071});
    assert(!$('tag-crouch').classList.contains('on'),'shorter standing body is not misclassified as crouching');
    const shortCrouch=aiCrouch.map(point=>point.map(value=>value*.7));
    packet({joints:shortCrouch,joints_version:2072});
    assert($('tag-crouch').classList.contains('on'),'proportional height drop still recognizes crouch for smaller body');
    const aiLean=joints(); aiLean[15][0]=.4;
    $('reset-btn').click(); packet({joints:aiLean,joints_version:208}); $('start-btn').click();
    tick(2.7); packet({joints:aiLean,joints_version:209});
    assert(adaptiveBrain.weights.flank<adaptiveBrain.weights.body,'enemy avoids predictable flank attacks against sideways evasion');
    $('reset-btn').click(); $('combat-difficulty').value='easy'; $('combat-difficulty').dispatchEvent(new Event('change'));
    packet({joints:joints(),joints_version:210}); $('start-btn').click();
    tick(2.7); packet({joints:joints(),joints_version:211});
    assert(adaptiveBrain.difficulty==='easy' && Math.abs(adaptiveBrain.windupSeconds-1.45)<1e-6,'practice difficulty gives longer attack warning');
    assert($('combat-target-progress').max===6 && $('combat-target-progress').value>3,'practice difficulty gives longer target acquisition budget');
    $('combat-difficulty').value='hard'; $('combat-difficulty').dispatchEvent(new Event('change'));
    assert(adaptiveBrain.difficulty==='easy' && localStorage.getItem('aetherpose.combat-difficulty.v1')==='hard','difficulty preference persists but does not alter active round');
    assert($('combat-target-progress').max===6,'changing difficulty does not shrink active target window');
    $('reset-btn').click(); packet({joints:joints(),joints_version:212}); $('start-btn').click();
    tick(2.7); packet({joints:joints(),joints_version:213});
    assert(adaptiveBrain.difficulty==='hard' && Math.abs(adaptiveBrain.windupSeconds-.85)<1e-6,'challenge difficulty applies on next round with readable warning');
    assert($('combat-target-progress').max===3.2 && $('combat-target-progress').value<1,'challenge difficulty uses shorter target acquisition budget');
    tick(.9); packet({joints:joints(),joints_version:214});
    const chainFirst=adaptiveBrain.lastType;
    assert(adaptiveBrain.chainPending && +$('player-hp-text').textContent<100,'hard enemy can prepare a followup only after landing first attack');
    tick(.7); packet({joints:joints(),joints_version:215});
    assert(adaptiveBrain.followup && adaptiveBrain.lastType!==chainFirst && $('incoming-zone').textContent.includes('連招') && adaptiveBrain.windupSeconds>=.75,'followup changes attack type and retains a readable telegraph');
    tick(.9); packet({joints:joints(),joints_version:216});
    assert(!adaptiveBrain.chainPending && $('incoming-zone').textContent==='無','enemy chain stops after its second hit');
    $('reset-btn').click(); packet({joints:joints(),joints_version:217}); $('start-btn').click();
    tick(2.7); packet({joints:joints(),joints_version:218}); tick(.9); packet({joints:joints(),joints_version:219});
    assert(adaptiveBrain.chainPending,'hard enemy prepares new eligible chain');
    tick(.1); packet({joints:windup,joints_version:220}); tick(.04); packet({joints:punch,joints_version:221});
    assert(!adaptiveBrain.chainPending && adaptiveBrain.phase==='stagger','landed player strike cancels pending followup during recovery');
    $('combat-difficulty').value='normal'; $('combat-difficulty').dispatchEvent(new Event('change'));
    $('reset-btn').click();
    packet({joints: joints(), joints_version: 16}); $('start-btn').click();
    window.testClock += 91000;
    packet({joints: joints(), joints_version: 17}); tick(.016);
    assert($('round-time').textContent === '0' && $('incoming-zone').textContent === '無',
      'timeout finishes before enemy can attack again');
    assert($('combat-target-progress').hidden && $('combat-target-progress').value===0,'finished combat clears target timer');
    assert(scene.getObjectByName('aether-opponent').userData.animation==='Yes', 'timed result triggers opponent response');
    Math.random = random;
    $('reset-btn').click();
    packet({joints: joints(), joints_version: 18}); $('start-btn').click();
    AetherCombat.setSuspended(true);
    assert($('start-btn').textContent === '開始回合', 'background tab stops round');
    $('start-btn').click();
    assert($('start-btn').textContent === '開始回合', 'background tab cannot start round');
    AetherCombat.setSuspended(false); $('start-btn').click();
    $('recenter-btn').click();
    assert($('start-btn').textContent === '開始回合' &&
      JSON.parse(meshWs.sent[meshWs.sent.length - 1]).cmd === 'reset_origin', 'recenter sends command and stops round');
    packet({status: 'Streaming #1 LIVE 6/6', joints: joints(), joints_version: 19}); tick(.016);
    assert($('ws-state').textContent === '即時動作捕捉', 'live source labeled');
    $('start-btn').click();
    tick(2.7); packet({status:'Streaming #1 LIVE 6/6',joints:joints(),joints_version:191});
    const liveEndsAt=+$('round-time').textContent;
    packet({status: 'Streaming #2 DEBUG mask=test live 0/6', joints: joints(), joints_version: 20}); tick(.016);
    assert($('start-btn').textContent === '重新開始' && $('event-feed').textContent.includes('追蹤中斷'),
      'a tracker dropping out freezes the combat round instead of ending it');
    const pausedAttackProgress=$('combat-attack-progress').value;
    assert(scene.getObjectByName('aether-opponent').userData.animationPaused && !$('combat-attack-progress').hidden,'tracking interruption pauses enemy animation during active telegraph');
    tick(1);
    assert($('combat-attack-progress').value===pausedAttackProgress && scene.getObjectByName('aether-opponent').userData.ai.phase==='windup','tracking interruption cannot advance attack phase or countdown');
    packet({status: 'Streaming #2 LIVE 6/6', joints: joints(), joints_version: 21}); tick(.016);
    assert(!scene.getObjectByName('aether-opponent').userData.animationPaused && $('combat-attack-progress').value<pausedAttackProgress+.1,'resumed tracking resumes animation without jumping to impact');
    assert($('start-btn').textContent === '重新開始' && $('event-feed').textContent.includes('追蹤恢復') && +$('round-time').textContent>=liveEndsAt-1,
      'a source that comes back within the grace period continues the round without losing time');
    packet({status: 'Streaming #2 DEBUG mask=test live 0/6', joints: joints(), joints_version: 22}); tick(.016); tick(1.6);
    assert($('start-btn').textContent === '開始回合' && $('ws-state').textContent === '示範資料',
      'switch from live to demo stops round and labels source');
    $('reset-btn').click(); packet({status:'Streaming #3 LIVE 6/6',joints:windup,joints_version:230}); $('start-btn').click();
    tick(.04); packet({status:'Streaming #3 DEBUG mask=test live 0/6',joints:punch,joints_version:231});
    tick(.04); packet({status:'Streaming #3 LIVE 6/6',joints:windup,joints_version:232});
    tick(.04); packet({joints:punch,joints_version:233});
    assert(+$('enemy-hp-text').textContent<100,'unaccepted punch during tracking pause does not consume recovered attack cooldown');
    const prePauseHp=+$('enemy-hp-text').textContent;
    packet({status:'Streaming #3 DEBUG mask=test live 0/6',joints:punch,joints_version:234});
    tick(.5); packet({status:'Streaming #3 LIVE 6/6',joints:windup,joints_version:235});
    tick(.16); packet({joints:punch,joints_version:236});
    assert(+$('enemy-hp-text').textContent===prePauseHp,'accepted punch cooldown freezes with the round instead of expiring during tracking pause');
    AetherCombat.stopRound('Round ended'); packet({status:'Streaming #4 DEBUG mask=test live 0/6',joints:joints(),joints_version:237});
    $('start-btn').click();
    assert($('event-feed').textContent.includes('示範資料'), 'demo round explicitly labeled');
    const distance = $('combat-distance'); distance.value='1.5'; distance.dispatchEvent(new Event('input'));
    assert($('start-btn').textContent === '開始回合' && $('combat-distance-value').textContent === '1.50 m',
      'distance adjustment stops round and updates control');
    distance.value='1.1'; distance.dispatchEvent(new Event('input'));
    $('reset-btn').click();
    const calTab = document.querySelector('[data-tab="cal"]');
    calTab.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
    assert(!combatMode && calTab.getAttribute('aria-selected') === 'true', 'keyboard can switch tabs');
    const translated = joints().map(p=>[p[0]+2,p[1],p[2]-.7]);
    packet({joints: translated, joints_version: 21});
    setFollowPose(true);
    const focus = root.localToWorld(new THREE.Vector3(...avatar.joints[0]));
    const oldDistance = focus.distanceTo(controls.target);
    followAvatar(1);
    assert(focus.distanceTo(controls.target) < oldDistance*.01, 'control camera follows moving avatar');
    controls.dispatchEvent({type:'start'});
    assert(!followPose && $('follow-btn').getAttribute('aria-pressed')==='false', 'manual orbit releases automatic follow');
    selectTab('combat');
    const arenaHip = root.localToWorld(new THREE.Vector3(...avatar.joints[0]));
    assert(Math.abs(arenaHip.x-avatar.combatX)<1e-6 && Math.abs(arenaHip.z)<1e-6,
      'entering arena centers current pose without recreating avatar');
    packet({joints: translated.map(p=>[p[0]+.4,p[1],p[2]+.2]), joints_version: 22});
    const movedHip = root.localToWorld(new THREE.Vector3(...avatar.joints[0]));
    assert(Math.abs(movedHip.x-avatar.combatX)<1e-6 && Math.abs(movedHip.z)<1e-6,
      'root drift stays in player arena position');
    packet({status:'Infer err: test'}); $('start-btn').click();
    assert($('start-btn').textContent === '開始回合' && $('ws-state').textContent === '推論錯誤',
      'inference error blocks round and displays status');
    assert(!$('panel-notice').hidden && $('panel-notice').textContent.includes('姿態模型有問題：test') &&
      $('panel-notice').textContent.includes('mesh_bridge.err.log'), 'a pose model error is explained at the top of the panel');
    assert(!$('setup-error').hidden && $('setup-error').textContent.includes('test') && $('setup-error').textContent.includes('mesh_bridge.err.log'),
      'a pose model error stays explained in the setup checklist');
    assert(getComputedStyle($('scene-notice')).display==='none', 'the scene copy of a notice stays hidden while the panel is shown');
    setFocusMode(true);
    assert(getComputedStyle($('scene-notice')).display==='block' && $('scene-notice').textContent.includes('姿態模型有問題'),
      'with the panel hidden, notices appear over the scene');
    $('scene-notice').click();
    assert($('panel-notice').hidden && $('scene-notice').hidden, 'clicking the scene notice closes it');
    setFocusMode(false);
    showPanelNotice('姿態模型有問題：test', 20);
    $('panel-notice-close').click();
    assert(!softwareRendererName(), 'a hardware WebGL renderer is not flagged as software');
    const glContext=renderer.getContext(), realGetParameter=glContext.getParameter;
    glContext.getParameter=function(parameter) {
      const info=this.getExtension('WEBGL_debug_renderer_info');
      return info && parameter===info.UNMASKED_RENDERER_WEBGL ? 'ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)' :
        realGetParameter.call(this,parameter);
    };
    assert(warnSoftwareRendering() && $('panel-notice-text').textContent.includes('硬體加速關閉'), 'software WebGL (SwiftShader) is detected and explained');
    const previousAppearance=localStorage.getItem(sceneSettingsKey);
    localStorage.removeItem(sceneSettingsKey);
    assert(loadSceneSettings().quality==='low', 'first use with software rendering defaults to low quality to preserve pose CPU time');
    localStorage.setItem(sceneSettingsKey,JSON.stringify({quality:'high',brightness:1.3}));
    assert(loadSceneSettings().quality==='high', 'an explicit saved quality overrides the software-renderer default');
    if (previousAppearance===null) localStorage.removeItem(sceneSettingsKey);
    else localStorage.setItem(sceneSettingsKey,previousAppearance);
    delete glContext.getParameter; hidePanelNotice();
    assert($('panel-notice').hidden && getComputedStyle($('panel-notice')).display==='none', 'a notice can be closed before it times out');
    packet({status:'Streaming #3 DEBUG mask=test live 0/6'}); tick(.016);
    $('start-btn').click();
    packet({status:'Streaming #4 DEBUG mask=test live 5/6'}); tick(.016); tick(1.6);
    assert($('ws-state').textContent==='混合輸入（即時 5/6）' && $('tp-status').textContent==='混合輸入（即時 5/6）' &&
      $('start-btn').textContent==='開始回合', 'partial live input has shared label and stops previous source round');
    $('start-btn').click();
    assert($('event-feed').textContent.includes('即時與示範資料混合'), 'mixed-input round explicitly labeled');
    packet({status:'Streaming #5 DEBUG mask=test live 4/6'}); tick(.016); tick(1.6);
    assert($('start-btn').textContent==='開始回合', 'losing a live slot stops mixed-input round');
    packet({status:'Streaming #6 DEBUG mask=test live 0/6'}); tick(.016);
    assert($('subtabbar').hidden && $('advanced-toggle').getAttribute('aria-expanded')==='false', 'the advanced pages start folded away');
    $('advanced-toggle').click();
    assert(!$('subtabbar').hidden && $('page-mon').classList.contains('active') && $('advanced-toggle').classList.contains('active'),
      '"進階" opens the monitor page with its own tab row');
    selectTab('body'); selectTab('games'); $('advanced-toggle').click();
    assert($('page-body').classList.contains('active'), '"進階" returns to the last advanced page');
    $('advanced-toggle').click();
    assert($('page-cal').classList.contains('active') && $('subtabbar').hidden, 'pressing "進階" again goes back to the setup page');
    selectTab('sys'); const savedTab=sessionStorage.getItem(TAB_STORAGE_KEY); selectTab('cal');
    assert(savedTab==='sys' && sessionStorage.getItem(TAB_STORAGE_KEY)==='cal', 'the current tab is remembered for a reload');
    const trackers = {
      76:{id:76,assigned_bone:null,last_update_ms:0,connection_type:'BLE',battery:80,tps:30,received_packets:100,lost_packets:0,rssi:-42},
      77:{id:77,assigned_bone:42,last_update_ms:1200,connection_type:'BLE',battery:70,tps:0,received_packets:100,lost_packets:0,rssi:-50}
    };
    updateTrackers(trackers);
    assert($('tracker-count').textContent==='即時 1 / 已知 2', 'tracker count distinguishes stale input');
    assert(document.querySelector('#cal-trackers [data-tracker-id="76"] .conn').textContent==='藍牙 / 即時' &&
      document.querySelector('#cal-trackers [data-tracker-id="77"] .conn').textContent==='藍牙 / 未更新', 'connection types are shown in words');
    assert(document.querySelector('#mon-trackers [data-tracker-id="76"] .axes-link').getAttribute('href')==='imu_axes.html?id=76',
      'monitor row links to the tracker axes page');
    const boneSelect=document.querySelector('#cal-trackers [data-tracker-id="76"] select');
    assert(boneSelect.value==='', 'unassigned tracker does not display Hip assignment');
    boneSelect.focus(); boneSelect.value='33'; boneSelect.dispatchEvent(new Event('change'));
    assert(JSON.parse(ws.sent[ws.sent.length-1]).AssignTracker.join(',')==='76,33', 'stable calibration selector sends assignment');
    boneSelect.value=''; boneSelect.dispatchEvent(new Event('change'));
    assert(JSON.parse(ws.sent.at(-1)).UnassignTracker===76, 'choosing 未指派 takes the bone away');
    boneSelect.value='33';
    updateTrackers({...trackers,76:{...trackers[76],assigned_bone:32}});
    assert(document.activeElement===boneSelect && boneSelect.value==='33' &&
      document.querySelector('#cal-trackers [data-tracker-id="76"] select')===boneSelect,
      'snapshot refresh preserves active calibration selection');
    $('follow-btn').focus(); updateTrackers({...trackers,76:{...trackers[76],assigned_bone:33}});
    assert(boneSelect.value==='33', 'assignment confirmation updates existing row');
    assert([...boneSelect.querySelectorAll('optgroup')].map(g=>g.children.length).join()==='6,13' &&
      boneSelect.querySelector('optgroup').firstElementChild.textContent==='頭', 'the bone menu separates the six avatar parts from IK-only parts');
    assert(!document.querySelector('#cal-trackers [data-tracker-id="76"] .ik-only').hidden &&
      document.querySelector('#cal-trackers [data-tracker-id="77"] .ik-only').hidden, 'a tracker on an IK-only part says the avatar does not use it');
    updateTrackers({...trackers,76:{...trackers[76],assigned_bone:32}}); $('panel-notice').hidden=true;
    assignBone('76','42');
    assert(JSON.parse(ws.sent.at(-1)).AssignTracker.join(',')==='76,42' && !$('panel-notice').hidden &&
      $('panel-notice-text').textContent==='右前臂原本是追蹤器 77，它改為左前臂（兩顆交換）。', 'taking a bone from another tracker says they swap');
    $('panel-notice').hidden=true; updateTrackers({...trackers,76:{...trackers[76],assigned_bone:33}});
    $('panel-notice').hidden=true;
    setStatus(true); const yawSent=ws.sent.length; updateTrackers({...trackers,76:{...trackers[76],assigned_bone:33,last_update_ms:5000}});
    assert(trackerAction('ResetYaw','x',true)===false && ws.sent.length===yawSent && $('panel-notice-text').textContent.startsWith('沒有連線中的追蹤器'),
      'resetting yaw without live trackers says there is nothing to reset');
    updateTrackers({...trackers,76:{...trackers[76],assigned_bone:33}});
    assert(trackerAction('ResetYaw','已重設航向：IK 骨架以目前的朝向為正前方。',true) && JSON.parse(ws.sent.at(-1))==='ResetYaw' &&
      !$('panel-notice').hidden && $('panel-notice-text').textContent.startsWith('已重設航向'), 'IK-only tracker actions confirm what they did');
    $('panel-notice').hidden=true;
    const realConfirm=window.confirm, sentCount=ws.sent.length; let question='';
    window.confirm=text=>{question=text; return false;};
    assert(autoAssign()===false && ws.sent.length===sentCount && question.includes('覆蓋目前 2 顆'), 'Auto Assign asks before replacing assignments');
    window.confirm=()=>true;
    assert(autoAssign()===true && JSON.parse(ws.sent.at(-1))==='AutoAssign', 'a confirmed Auto Assign is sent');
    window.confirm=realConfirm;
    window.testClock+=600; refreshTrackers(performance.now()/1000);
    assert($('tracker-count').textContent==='即時 0 / 已知 2' &&
      document.querySelector('#mon-trackers [data-tracker-id="76"]').classList.contains('stale'),
      'tracker age advances when backend snapshots stop');
    updateTrackers({76:trackers[76]});
    assert(!document.querySelector('[data-tracker-id="77"]') &&
      document.querySelector('#cal-trackers [data-tracker-id="76"] select')===boneSelect,
      'removed tracker leaves other calibration rows intact');
    const settings={ik_smoothness:.3,prop_leg:1.2,prop_arm:.9,prop_spine:1.1,drift_correction:.25,smoothing_min_cutoff:1.5,
      smoothing_beta:4,trajectory_integration_mode:'euler',osc_ip:'192.168.0.5',osc_port:9100,zupt_enabled:false,zupt_window_size:12,
      zupt_accel_var_threshold:.001,zupt_gyro_threshold:.03,serial_enabled:false,serial_port:null,serial_baud:115200};
    const backendSnapshot=(n,s)=>onMessage({type:'Snapshot',data:{packet_count:n,trackers:{76:trackers[76]},bones:[],settings:s}});
    backendSnapshot(1,settings);
    assert($('s-leg').value==='1.2' && $('v-leg').textContent==='1.20' && $('s-cutoff').value==='1.5' &&
      $('traj-euler').classList.contains('primary') && !$('traj-rk4').classList.contains('primary') &&
      $('osc-ip').value==='192.168.0.5' && $('osc-port').value==='9100' && !$('zupt-en').checked,
      'controls show the backend saved settings');
    const pktBeforeBurst=$('pkt').textContent;
    const packetMutations=new MutationObserver(()=>{});
    packetMutations.observe($('pkt'),{childList:true,characterData:true,subtree:true});
    for(let n=2;n<=101;n++) onMessage({type:'Snapshot',data:{packet_count:n,trackers:{76:{...trackers[76],last_sequence:n}},bones:[],settings}});
    assert($('pkt').textContent===pktBeforeBurst && packetMutations.takeRecords().length===0,
      'a burst of tracker packets does not rebuild the panel for each packet');
    assert(liveTrackers().some(tracker=>tracker.last_sequence===101),
      'freshness and assignment queries receive the newest tracker state before panel rendering');
    window.testClock+=100;
    await new Promise(resolve=>setTimeout(resolve,120));
    assert($('pkt').textContent==='101 個封包', 'the final packet in a burst is rendered even if streaming stops');
    packetMutations.disconnect();
    backendSnapshot(102,settings); // queued final packet must not survive disconnect
    setStatus(false);
    await new Promise(resolve=>setTimeout(resolve,120));
    assert(!$('cal-trackers [data-tracker-id="76"]') && $('status-text').textContent==='未連線',
      'disconnect cancels pending panel work instead of restoring disconnected trackers');
    setStatus(true); backendSnapshot(103,settings);
    const ageSnapshot=n=>onMessage({type:'Snapshot',data:{packet_count:n,trackers:{76:trackers[76]},bones:[],settings,headset_age_ms:0}});
    ageSnapshot(104); ageSnapshot(105);
    window.testClock+=600;
    await new Promise(resolve=>setTimeout(resolve,120));
    assert(!headsetLive() && document.querySelector('#cal-trackers [data-tracker-id="76"]').classList.contains('stale'),
      'deferred rendering preserves observation age instead of reviving expired tracker or headset data');
    backendSnapshot(106,settings);
    onMessage({type:'Snapshot',data:{packet_count:107,trackers:{76:{...trackers[76],connection_type:'Serial'}},bones:[],settings}});
    assert(document.querySelector('#cal-trackers [data-tracker-id="76"] .conn').textContent.includes('USB'),
      'a tracker transport change is rendered immediately without waiting for the panel interval');
    backendSnapshot(108,settings);
    $('s-arm').value='1.3'; sendProp();
    const sentProps=JSON.parse(ws.sent[ws.sent.length-1]).SetProportions;
    assert(sentProps.leg===1.2 && sentProps.spine===1.1 && sentProps.arm===1.3, 'one slider change keeps the other saved proportions');
    assert($('s-leg').getAttribute('aria-label')==='腿' && $('osc-port').getAttribute('aria-label')==='埠' &&
      [...document.querySelectorAll('.slider-row input, .row input')].every(input=>input.getAttribute('aria-label') || input.labels.length),
      'every settings control has an accessible name');
    const overflowing=[];
    for (const tab of ['cal','mon','body','sys','games']) {
      selectTab(tab);
      for (const card of document.querySelectorAll(`#page-${tab} .card`)) {
        const box=card.getBoundingClientRect();
        for (const control of card.querySelectorAll('button, input, select')) {
          const r=control.getBoundingClientRect();
          if (r.width && (r.right>box.right+.5 || r.left<box.left-.5)) overflowing.push(`${tab}:${control.id||control.textContent.trim()}`);
        }
      }
    }
    selectTab('cal');
    assert(!overflowing.length, 'no control sticks out of its card: '+overflowing.join(', '));
    const cue=$('pose-game-cue'), cueText=cue.textContent; cue.textContent='伸手碰觸黃色目標。';
    const cueBox=cue.getBoundingClientRect();
    const toolbarClash=['view-toolbar','scene-toolbar'].filter(id=>{
      const r=$(id).getBoundingClientRect();
      return r.height>50 || (r.top<cueBox.bottom && r.bottom>cueBox.top && r.left<cueBox.right && r.right>cueBox.left);
    });
    cue.textContent=cueText;
    assert(!toolbarClash.length, 'scene toolbars stay on one row and clear of the game cue: '+toolbarClash.join(', '));
    const tabKey=(tab,key)=>document.querySelector(`.tab[data-tab="${tab}"]`).dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true}));
    tabKey('cal','ArrowRight');
    const arrowedRight=currentTab==='games' && document.activeElement===document.querySelector('.tab[data-tab="games"]');
    tabKey('games','ArrowLeft'); tabKey('cal','ArrowLeft');
    assert(arrowedRight && currentTab==='combat', 'arrow keys move between the main tabs and wrap around');
    selectTab('cal');
    const confirmBody=window.confirm, bodySent=ws.sent.length;
    window.confirm=()=>false; assert(resetBodySettings()===false && ws.sent.length===bodySent, 'Body defaults are restored only after confirming');
    window.confirm=()=>true; assert(resetBodySettings()===true, 'confirmed Body defaults are sent');
    const restored=ws.sent.slice(bodySent).map(text=>JSON.parse(text));
    assert(restored.length===6 && restored[1].SetProportions.leg===1 && restored[2].SetSmoothingParams.min_cutoff===3 &&
      restored[5].SetTrajectoryIntegrationMode==='rk4', 'Body defaults match the backend defaults');
    window.confirm=confirmBody;
    $('osc-ip').value='10.0.0.2'; backendSnapshot(2,settings);
    assert($('osc-ip').value==='10.0.0.2', 'snapshot keeps an unapplied field edit');
    backendSnapshot(3,{...settings,osc_ip:'10.0.0.2'}); backendSnapshot(4,{...settings,osc_ip:'10.0.0.9'});
    assert($('osc-ip').value==='10.0.0.9', 'applied field follows later backend changes');
    $('rec-file').value=' session '; startRecording();
    const recording=JSON.parse(ws.sent.at(-1)).SetRecorderConfig;
    assert(recording.enabled===true && recording.filename==='session.csv' && recording.batch_size===128 && recording.flush_interval_ms===500,
      'Start records with the entered name, made a CSV file');
    const sentBefore=ws.sent.length; $('rec-file').value='takes?1';
    assert(startRecording()===false && ws.sent.length===sentBefore && $('rec-error').textContent.startsWith('檔名不能包含'),
      'a file name Windows cannot use is refused before it is sent');
    const recSent=ws.sent.length; $('rec-file').value='take'; $('rec-batch').value='-5';
    assert(startRecording()===false && ws.sent.length===recSent && $('rec-error').textContent.startsWith('批次要是'),
      'a negative batch size is refused instead of silently dropping the command');
    $('rec-batch').value='128';
    $('rec-file').value=''; startRecording();
    assert(JSON.parse(ws.sent.at(-1)).SetRecorderConfig.filename===null, 'an empty name lets the backend pick a dated file');
    const slotTrackers=Object.fromEntries([4,2,32,42,11,21].map((bone,i)=>[60+i,{...trackers[76],id:60+i,assigned_bone:bone}]));
    onMessage({type:'Snapshot',data:{packet_count:7,trackers:{60:slotTrackers[60]},bones:[],settings}});
    assert(document.querySelector('[data-step="connect"]').classList.contains('done') &&
      document.querySelector('[data-step="assign"]').classList.contains('current') &&
      document.querySelector('[data-step="assign"] .step-text').textContent.includes('胸口、左前臂、右前臂、左小腿、右小腿') &&
      $('setup-summary').textContent==='完成 1 / 3', 'the setup checklist names the body parts still missing a tracker');
    onMessage({type:'Snapshot',data:{packet_count:8,trackers:slotTrackers,bones:[],settings}});
    packet({status:'Streaming #8 LIVE 6/6 · 6 uncalibrated'});
    assert(document.querySelector('[data-step="calibrate"]').classList.contains('current') && $('setup-summary').textContent==='完成 2 / 3',
      'uncalibrated live input points to body calibration');
    packet({status:'Streaming #9 LIVE 6/6'});
    assert($('setup-summary').textContent==='全部就緒' && document.querySelector('[data-step="play"]').classList.contains('current') &&
      getComputedStyle(document.querySelector('[data-step="connect"]')).display==='none' &&
      getComputedStyle(document.querySelector('[data-step="play"]')).display!=='none', 'a calibrated live setup collapses to "go play"');
    packet({status:'Streaming #6 DEBUG mask=test live 0/6'});
    $('panel-notice').hidden=true;
    updateTrackers({76:{...trackers[76],assigned_bone:4,battery:12}});
    assert($('tracker-count').textContent==='即時 1 / 已知 1 · 低電量 1' && !$('panel-notice').hidden &&
      $('panel-notice-text').textContent.startsWith('追蹤器 76（頭）電量剩 12%') &&
      document.querySelector('#mon-trackers [data-tracker-id="76"] [data-metric="battery"]').style.color==='var(--red)',
      'a low battery is flagged on the tracker card, the monitor row and once in a notice');
    updateTrackers({76:{...trackers[76],assigned_bone:4,battery:12,rssi:-86,received_packets:100,lost_packets:9}});
    const monRow=document.querySelector('#mon-trackers [data-tracker-id="76"]');
    assert(monRow.querySelector('[data-metric="rssi"]').style.color==='var(--amber)' && monRow.querySelector('[data-metric="loss"]').title.includes('卡頓'),
      'weak signal and heavy packet loss are marked on the monitor row');
    updateTrackers({76:{...trackers[76],assigned_bone:4,battery:12}});
    assert(!monRow.querySelector('[data-metric="rssi"]').style.color && !monRow.querySelector('[data-metric="loss"]').style.color, 'a good link is not marked');
    $('panel-notice').hidden=true; updateTrackers({76:{...trackers[76],assigned_bone:4,battery:11}});
    assert($('panel-notice').hidden, 'the low battery notice is not repeated while the battery stays low');
    updateTrackers({76:{...trackers[76],battery:90}}); updateTrackers({76:{...trackers[76],battery:14}});
    assert(!$('panel-notice').hidden, 'a recharged tracker is warned again when it runs low');
    $('panel-notice').hidden=true;
    const oscSent=ws.sent.length; $('panel-notice').hidden=true;
    $('osc-ip').value='localhost'; $('osc-port').value='9000';
    assert(applyOsc()===false && ws.sent.length===oscSent && $('panel-notice-text').textContent.startsWith('OSC 沒有套用'), 'an OSC target the backend cannot parse is refused');
    $('osc-ip').value=' 192.168.0.20 '; $('osc-port').value='9000';
    assert(applyOsc()===true && JSON.parse(ws.sent.at(-1)).SetOscTarget.join()==='192.168.0.20,9000', 'a valid OSC target is sent trimmed');
    $('zupt-win').value='0';
    assert(applyZupt()===false && $('panel-notice-text').textContent.startsWith('ZUPT 沒有套用'), 'a zero ZUPT window is refused');
    $('zupt-win').value='8'; $('zupt-accel').value='abc';
    assert(applyZupt()===false, 'a ZUPT threshold must be a number');
    $('zupt-accel').value='0.0005';
    assert(applyZupt()===true && JSON.parse(ws.sent.at(-1)).SetZuptParams.window_size===8 && $('panel-notice-text').textContent.startsWith('已套用 ZUPT'),
      'valid ZUPT values are sent and confirmed');
    $('ser-en').checked=true; $('ser-port').value=' ';
    assert(applySerial()===false && $('panel-notice-text').textContent.startsWith('序列埠沒有套用'), 'enabling serial input needs a port name');
    $('ser-en').checked=false; $('ser-port').value='COM3'; $('panel-notice').hidden=true;
    onMessage({type:'Snapshot',data:{packet_count:8,trackers:{76:trackers[76]},bones:[],settings,osc_active:true,osc_error:null}});
    assert($('osc-status').textContent==='正在送到 192.168.0.5:9100。', 'the OSC card says where data goes');
    onMessage({type:'Snapshot',data:{packet_count:8,trackers:{76:trackers[76]},bones:[],settings,osc_active:true,osc_error:'10.0.0.300:9000 (invalid IP address syntax)'}});
    assert($('osc-status').textContent.startsWith('無法改用 10.0.0.300:9000') && $('osc-status').textContent.endsWith('仍送到 192.168.0.5:9100。'),
      'a refused OSC target keeps the working one and says so');
    onMessage({type:'Snapshot',data:{packet_count:8,trackers:{76:trackers[76]},bones:[],settings,osc_active:false,osc_error:'x:1 (bad)'}});
    assert($('osc-status').textContent.startsWith('OSC 沒有輸出'), 'no OSC output is reported');
    $('panel-notice').hidden=true;
    onMessage({type:'Snapshot',data:{packet_count:8,trackers:{76:trackers[76]},bones:[],settings,config_warning:'expected value at line 3 column 5|config.json.bad'}});
    assert(!$('panel-notice').hidden && $('panel-notice-text').textContent.includes('config.json.bad') && $('panel-notice-text').textContent.includes('line 3'),
      'an unreadable config.json is explained with its backup');
    $('panel-notice').hidden=true;
    onMessage({type:'Snapshot',data:{packet_count:9,trackers:{76:trackers[76]},bones:[],settings,config_warning:'expected value at line 3 column 5|config.json.bad'}});
    assert($('panel-notice').hidden, 'the config warning is shown once');
    assert([...$('shake-bone').options].slice(0,6).map(o=>o.text).join()==='頭,胸口,左前臂,右前臂,左小腿,右小腿', 'shake-assign lists the six TransPose parts first');
    $('shake-bone').value='32';
    assert(startShakeAssign() && JSON.parse(ws.sent.at(-1)).StartShakeAssign===32, 'shake-assign asks the backend for the chosen part');
    onMessage({type:'Snapshot',data:{packet_count:8,trackers:{76:trackers[76]},bones:[],settings,pending_shake_bone:32}});
    assert($('shake-status').textContent.includes('左前臂') && $('shake-start').disabled && !$('shake-cancel').hidden, 'a pending shake-assign says what to shake');
    onMessage({type:'Snapshot',data:{packet_count:9,trackers:{76:{...trackers[76],assigned_bone:32}},bones:[],settings,pending_shake_bone:null}});
    assert($('shake-status').textContent==='已指派：追蹤器 76 → 左前臂。' && !$('shake-start').disabled && $('shake-cancel').hidden,
      'a shaken tracker is reported once assigned');
    const systemSnapshot=extra=>onMessage({type:'Snapshot',data:{packet_count:8,trackers:{76:trackers[76]},bones:[],settings,...extra}});
    systemSnapshot({is_recording:true,recorder_filename:'recordings/session.csv',recorder_dropped_count:0,recorder_write_errors:2});
    assert($('rec-start').disabled && !$('rec-stop').disabled && $('rec-text').textContent.includes('寫入錯誤 2 次'),
      'recording disables Start and reports write errors');
    systemSnapshot({is_recording:false,recorder_error:'write:disk full'});
    assert(!$('rec-start').disabled && $('rec-stop').disabled && $('rec-text').textContent==='待機 · 上次存成 recordings/session.csv' &&
      $('rec-error').textContent==='寫入失敗，已停止錄製：disk full', 'a recording stopped by an error says why and where it was saved');
    assert($('ser-status').textContent==='序列埠未啟用。', 'disabled serial input says so');
    systemSnapshot({settings:{...settings,serial_enabled:true,serial_port:'COM5'},serial_running:true,serial_status_msg:'reconnect_scheduled:COM5:3'});
    assert($('ser-status').textContent==='正在重新連接 COM5（第 3 次）。' && !$('rec-error').textContent, 'serial events are shown in words');
    const bleSnapshot=status=>onMessage({type:'Snapshot',data:{packet_count:5,trackers:{76:trackers[76]},bones:[],settings,ble_status:status}});
    bleSnapshot('ble_unavailable:no Bluetooth adapter');
    assert($('ble-status').textContent.startsWith('藍牙無法使用（no Bluetooth adapter）') && $('ble-status').title==='ble_unavailable:no Bluetooth adapter',
      'backend Bluetooth problems are shown on the calibration tab');
    bleSnapshot('ble_connected:09:08:1D:BE:BF:4C');
    assert($('ble-status').textContent==='藍牙：追蹤器已連線。' && !$('ble-status').style.color, 'Bluetooth events read as plain status');
    assert(BONE_NAMES[42]==='右前臂' && Object.values(BONE_NAMES).every(name=>/[一-鿿]/.test(name)), 'every bone name is shown in Chinese');
    const legTrackers={10:{...trackers[76],id:10,assigned_bone:10},11:{...trackers[76],id:11,assigned_bone:11}};
    const legSnapshot=extra=>onMessage({type:'Snapshot',data:{packet_count:6,trackers:legTrackers,bones:[],settings,...extra}});
    setStatus(true); legSnapshot({});
    assert($('leg-start').disabled && $('leg-stop').disabled && $('leg-status').textContent==='需要頭戴裝置才能校正。' &&
      $('headset-status').textContent.startsWith('頭戴裝置：未連線'), 'leg calibration names the missing headset');
    legSnapshot({headset_age_ms:20});
    assert(!$('leg-start').disabled && $('leg-status').textContent==='' && $('headset-status').textContent==='頭戴裝置：已連線',
      'a live headset with left thigh and shin trackers enables leg calibration');
    window.testClock+=600; refreshTrackers(performance.now()/1000);
    assert($('leg-start').disabled && $('headset-status').textContent.startsWith('頭戴裝置：未連線'),
      'a headset that stops sending is shown as disconnected');
    legSnapshot({headset_age_ms:0,leg_calibrating:true,leg_calibration_samples:5});
    assert($('leg-start').disabled && !$('leg-stop').disabled && $('leg-status').textContent.includes('已收集 5 筆'),
      'a running leg calibration shows its progress and allows Stop');
    legSnapshot({headset_age_ms:0,leg_calibration_result:'small_swing:0.080'});
    assert($('leg-status').textContent.includes('8 公分') && !$('leg-start').disabled && $('leg-stop').disabled, 'a shallow squat is explained');
    legSnapshot({headset_age_ms:0,leg_calibration_result:'done:1.050',trackers:{10:legTrackers[10]}});
    assert($('leg-status').textContent==='完成，腿長比例 1.050。 需要左小腿追蹤器才能校正。', 'the result stays with the remaining requirement');
    legSnapshot({leg_calibration_result:'no_samples'});
    assert($('leg-status').textContent==='需要頭戴裝置才能校正。', 'a failure caused by a missing requirement names only the requirement');
    legSnapshot({leg_ratio:.9});
    assert($('leg-reset').disabled && $('leg-ratio').textContent==='比例 0.900', 'the default leg ratio has nothing to reset');
    legSnapshot({leg_ratio:1.25});
    const legConfirm=window.confirm, legSent=ws.sent.length;
    window.confirm=()=>false;
    assert(!$('leg-reset').disabled && resetLegRatio()===false && ws.sent.length===legSent, 'resetting the leg ratio asks first');
    window.confirm=()=>true;
    assert(resetLegRatio()===true && JSON.stringify(JSON.parse(ws.sent.at(-1)))==='{"SetLegRatio":0.9}', 'a confirmed reset sends the default ratio');
    window.confirm=legConfirm;
    legSnapshot({leg_ratio:1.25,leg_calibrating:true});
    assert($('leg-reset').disabled, 'no reset while a leg calibration runs');
    bleSnapshot(null);
    assert($('ble-status').textContent==='', 'no Bluetooth status before the backend reports one');
    const liveStatus='Streaming #8 LIVE 6/6 · 6 uncalibrated';
    packet({status:liveStatus,calibration:{phase:'idle',message:'Not calibrated.',seconds_left:0}});
    assert($('body-cal-start').disabled && $('body-cal-status').textContent.includes('胸口或頭部'),
      'body calibration explains that it needs a live chest or head tracker');
    const chest={id:31,assigned_bone:2,last_update_ms:0,connection_type:'Ble'};
    onMessage({type:'Snapshot',data:{packet_count:6,trackers:{31:chest,76:trackers[76]},bones:[],settings}});
    packet({status:liveStatus,calibration:{phase:'idle',message:'Not calibrated.',seconds_left:0}});
    assert($('body-cal-status').textContent.startsWith('即時追蹤器尚未校正') && !$('body-cal-start').disabled &&
      $('body-cal-cancel').disabled, 'uncalibrated live tracking asks for body calibration');
    assert($('tp-status').textContent==='即時動作捕捉 · 未校正', 'the pose source label warns about uncalibrated input');
    packet({joints: joints(), joints_version: 900}); tick(.016); selectTab('cal'); startGame();
    assert(game.state!=='playing' && $('pose-game-cue').textContent.includes('尚未校正'),
      'uncalibrated live input cannot start a pose round');
    selectTab('combat'); $('start-btn').click();
    assert($('start-btn').textContent==='開始回合' && $('event-feed').textContent.includes('尚未校正'),
      'uncalibrated live input cannot start Combat');
    selectTab('cal');
    packet({status:'Streaming #8 DEBUG mask=test live 2/6 · 2 uncalibrated'}); startGame();
    assert(game.state!=='playing' && $('pose-game-cue').textContent.includes('尚未校正'),
      'mixed uncalibrated trackers also require body calibration');
    packet({status:'Streaming #8 LIVE 6/6'}); startGame();
    assert(game.state==='playing', 'calibrated live input can start a pose round');
    startBodyCalibration();
    assert(JSON.parse(meshWs.sent.at(-1)).cmd==='calibrate_body', 'Calibrate body asks the pose service to start');
    assert(game.state==='over' && $('game-result').textContent.includes('開始身體校正') && $('game-result').textContent.includes('未完成'),
      'body calibration ends a running round as unfinished');
    startGame();
    assert(game.state!=='playing' && $('pose-game-cue').textContent.includes('等待姿態服務回應'),
      'a pending calibration request blocks pose rounds before the reply arrives');
    selectTab('combat'); $('start-btn').click();
    assert($('start-btn').textContent==='開始回合' && $('event-feed').textContent.includes('等待姿態服務回應'),
      'a pending calibration request blocks Combat before the reply arrives');
    selectTab('cal');
    packet({status:liveStatus,calibration:{phase:'tpose',message:'Hold the T-pose still…',seconds_left:1.2}});
    startGame();
    assert(game.state!=='playing' && $('pose-game-cue').textContent.includes('校正進行中'),
      'a pose round cannot start during body calibration');
    assert($('body-cal-status').textContent==='Hold the T-pose still… 2 s' && $('body-cal-start').disabled && !$('body-cal-cancel').disabled,
      'calibration shows the current step and its countdown');
    const backendSent=ws.sent.length;
    packet({status:liveStatus,calibration:{phase:'bow_ready',message:'Bow forward.',seconds_left:3}});
    assert(ws.sent.length===backendSent+1 && JSON.parse(ws.sent.at(-1))==='ResetMounting', 'the same T-pose resets the backend IK mounting');
    packet({status:'Streaming #9 LIVE 6/6',calibration:{phase:'bow',message:'Hold the bow still…',seconds_left:1}});
    assert(ws.sent.length===backendSent+1, 'mounting is reset once per calibration');
    cancelBodyCalibration();
    assert(JSON.parse(meshWs.sent.at(-1)).cmd==='cancel_body_calibration', 'Cancel stops the calibration');
    document.dispatchEvent(new Event('visibilitychange'));
    const visibility=JSON.parse(meshWs.sent.at(-1));
    assert(visibility.cmd==='visibility' && visibility.visible===!document.hidden, 'the page tells the pose service whether it can be seen');
    packet({status:'Streaming #9 LIVE 6/6',calibration:{phase:'done',message:'Calibrated 6 trackers.',seconds_left:0}});
    assert($('body-cal-status').textContent==='Calibrated 6 trackers.' && !$('body-cal-start').disabled, 'finished calibration is reported');
    startGame();
    packet({status:'Streaming #9 LIVE 6/6',calibration:{phase:'tpose_ready',message:'Remote calibration',seconds_left:3}});
    assert(game.state==='over' && $('game-result').textContent.includes('開始身體校正') && $('game-result').textContent.includes('未完成'),
      'remote body calibration stops a pose round before calibration motion scores');
    packet({calibration:{phase:'done',message:'Calibrated 6 trackers.',seconds_left:0}});
    selectTab('combat'); $('start-btn').click();
    packet({calibration:{phase:'tpose_ready',message:'Remote calibration',seconds_left:3}});
    assert($('start-btn').textContent==='開始回合' && $('game-result').textContent.includes('開始身體校正'),
      'remote body calibration stops Combat too');
    $('start-btn').click();
    assert($('start-btn').textContent==='開始回合' && $('event-feed').textContent.includes('校正進行中'),
      'Combat cannot restart while calibration runs');
    packet({calibration:{phase:'done',message:'Calibrated 6 trackers.',seconds_left:0}});
    $('start-btn').click();
    packet({status:liveStatus});
    assert($('start-btn').textContent==='開始回合' && $('game-result').textContent.includes('校正失效') && $('game-result').textContent.includes('未完成'),
      'invalidated live calibration stops Combat without a completed score');
    selectTab('cal'); packet({status:'Streaming #9 LIVE 6/6'}); startGame();
    packet({status:liveStatus});
    assert(game.state==='over' && $('game-result').textContent.includes('校正失效') && $('game-result').textContent.includes('未完成'),
      'invalidated live calibration stops pose games without a completed score');
    packet({status:'Streaming #6 DEBUG mask=test live 0/6'});
    onMessage({type:'Snapshot',data:{packet_count:7,trackers:{76:trackers[76]},bones:[],settings}});
    assert(firmwareMag===null && $('mag-start').disabled && $('mag-status').textContent.includes('run.ps1'),
      'local tools are disabled without the page server API');
    const realFetch=window.fetch, toolCalls=[];
    window.fetch=async (url,options={})=>{
      toolCalls.push({url,method:options.method||'GET',header:options.headers?.['X-Aetherpose'],body:options.body});
      const reply=(data,status=200)=>({ok:status<300,status,json:async()=>data});
      if(url==='api/calibrations') return reply({trackers:{76:{date:'2026-10-12',note:''},43:{date:null,note:''}}});
      if(url==='api/tool/start') return reply({running:true,kind:'calibrate',tracker_id:76,lines:[],progress:'',exit_code:null},202);
      if(url==='api/tool') return reply({running:false,kind:'calibrate',tracker_id:76,lines:['Connected','擬合結果：磁場 45.0 uT'],progress:'',exit_code:0,cancelled:false});
      throw Error('unexpected '+url);
    };
    await refreshFirmwareMag();
    assert(document.querySelector('#mon-trackers [data-tracker-id="76"] [data-metric="mag"]').textContent==='磁力計已校正' &&
      [...$('mag-tracker').options].map(o=>o.value).join()==='43,76' && $('mag-tracker').options[0].text.includes('未連線') &&
      $('mag-tracker').value==='76' && !$('mag-start').disabled && $('mag-cancel').disabled,
      'monitor lists firmware magnetometer entries and enables local tools');
    $('mag-tracker').value='43'; renderToolState();
    assert($('mag-start').disabled && $('mag-start').title.includes('傳送資料') && $('mag-status').textContent.includes('傳送資料') &&
      !$('mag-flash-only').disabled,
      'recording needs a streaming tracker; Flash only does not');
    $('mag-tracker').value='76'; renderToolState();
    renderToolState({running:true,kind:'calibrate',tracker_id:76,lines:['Connected'],progress:'  31 samples',exit_code:null});
    assert($('mag-start').disabled && !$('mag-cancel').disabled && $('mag-status').textContent.includes('追蹤器 76') &&
      $('mag-log').textContent==='Connected\n  31 samples', 'a running tool shows live progress and allows cancel only');
    $('mag-tracker').value='76'; $('mag-flash').checked=false;
    renderToolState({running:false,exit_code:null,lines:[],progress:''});
    await startTool('calibrate');
    await new Promise(resolve=>setTimeout(resolve,0));
    const startCall=toolCalls.find(call=>call.url==='api/tool/start');
    assert(startCall.method==='POST' && startCall.header==='1' && JSON.parse(startCall.body).id===76 && JSON.parse(startCall.body).flash===false,
      'calibration request carries the tracker, the flash choice and the page header');
    assert($('mag-status').textContent==='完成。' && $('mag-log').textContent.includes('擬合結果：磁場 45.0 uT') && !$('mag-start').disabled,
      'finished calibration shows its output and re-enables the tools');
    window.fetch=realFetch; firmwareMag=null; toolState=null;
    setStatus(false);
    assert($('leg-start').disabled && $('leg-stop').disabled && $('leg-status').textContent==='後端沒有連線。', 'leg calibration needs the backend');
    assert(!document.querySelector('[data-tracker-id]') && $('tracker-count').textContent==='', 'disconnect clears obsolete tracker rows');
    assert($('no-trackers').textContent.startsWith('後端沒有連線') && $('no-trackers-mon').textContent.startsWith('後端沒有連線'),
      'without the backend the tracker lists say what is missing');
    ws.readyState=3; const notSent=cmd('AutoAssign');
    assert(!notSent && !$('panel-notice').hidden && $('panel-notice').textContent.includes('沒有連線'), 'an action while disconnected says it was not sent');
    ws.readyState=1; $('panel-notice').hidden=true;
    selectTab('cal');
    packet({status:'Streaming #7 DEBUG mask=test live 0/6',joints:joints(),joints_version:23});
    startGame();
    assert(game.state==='playing', 'reach activity uses same fresh avatar input');
    const beforePauseDeadline=game.deadline;
    $('game-pause').click();
    window.testClock+=2000;
    updateGame(avatar.joints); updateReachClock(performance.now());
    assert(game.paused && game.score===0 && game.timeLeft===60 && targetMeshes.every(m=>!m.visible), 'pause freezes clock, targets and scoring');
    $('game-pause').click();
    assert(!game.paused && game.deadline===beforePauseDeadline+2000 && targetMeshes.every(m=>m.visible) && $('game-pause').textContent==='暫停', 'resume restores targets and extends deadline by pause duration');
    targetMeshes.forEach((m,i)=>m.position.set(100+i,100,100));
    targetMeshes[0].position.copy(root.localToWorld(new THREE.Vector3(...avatar.joints[22])));
    const loopCount=window.testRafRequests;
    packet({joints:joints(),joints_version:24});
    assert(game.score===1 && !!poseScene.getObjectByName('reach-hit-effect') && window.testRafRequests===loopCount,
      'reach hit effect runs in shared animation loop');
    window.testClock+=400; updateReachEffects(performance.now()/1000);
    assert(!poseScene.getObjectByName('reach-hit-effect'), 'shared loop cleans completed reach effects');
    targetMeshes.forEach((mesh,index)=>mesh.position.set(100+index,100,100));
    const obstructedHand=root.localToWorld(new THREE.Vector3(...avatar.joints[22]));
    targetMeshes[0].position.copy(obstructedHand).add(new THREE.Vector3(.145,0,0));
    const reachWall=new THREE.Mesh(new THREE.BoxGeometry(.01,.2,.2),new THREE.MeshBasicMaterial());
    reachWall.position.copy(obstructedHand).add(new THREE.Vector3(.02,0,0));
    scene.add(reachWall); scenePhysics.addCollider(reachWall);
    const blockedReachScore=game.score;
    assert(!scenePhysics.pointBlocked(targetMeshes[0].position,.07),'obstructed reach target remains outside obstacle');
    updateGame(avatar.joints);
    assert(game.score===blockedReachScore && game.combo===0 && $('pose-game-cue').textContent.includes('擋住'),'Reach cannot score through a scene mesh and clears combo');
    scenePhysics.stats.enabled=false; updateGame(avatar.joints);
    assert(game.score===blockedReachScore+1,'Reach hand-path obstruction respects disabled scene collisions');
    scenePhysics.stats.enabled=true;
    targetMeshes[0].position.copy(obstructedHand).add(new THREE.Vector3(.145,0,0));
    game.combo=0; game.lastHitAt=-Infinity;
    scenePhysics.removeCollider(reachWall); scene.remove(reachWall); reachWall.geometry.dispose(); reachWall.material.dispose();
    updateGame(avatar.joints);
    assert(game.score===blockedReachScore+2 && !$('pose-game-cue').textContent.includes('擋住'),'Reach resumes with a new combo after obstruction removal');
    const savedRandom=Math.random;
    Math.random=()=>.5;
    const fixedHand=new THREE.Vector3(TP_OFFSET.x,1.25,TP_OFFSET.z).add(new THREE.Vector3(...avatar.joints[0]));
    const replacement=spawnTargetPos([fixedHand]);
    Math.random=savedRandom;
    assert(replacement.distanceTo(fixedHand)>HIT_RADIUS*2, 'replacement avoids held hand even with identical random positions');
    const previousScore=game.score;
    game.deadline=performance.now()-1;
    targetMeshes[0].position.copy(root.localToWorld(new THREE.Vector3(...avatar.joints[22])));
    updateGame(avatar.joints);
    assert(game.state==='over' && game.score===previousScore && game.timeLeft===0, 'reach deadline prevents late scoring');
    startGame();
    assert(game.lastHitAt===-Infinity && game.score===0 && game.combo===0, 'reach restart clears previous combo timing');
    const reachDeadline=game.deadline, reachSource=bridgeStatus;
    packet({status:'Streaming #8 DEBUG mask=test live 1/6'});
    assert(game.state==='playing' && $('game-time').textContent==='等待追蹤' && $('pose-game-cue').textContent.includes('追蹤中斷'),
      'a pose source change first waits for the tracker');
    window.testClock+=800; packet({status:reachSource});
    assert(game.state==='playing' && Math.abs(game.deadline-reachDeadline-800)<1 && $('pose-game-cue').textContent.includes('追蹤恢復'),
      'a pose round continues when the source comes back, without losing the wait');
    packet({status:'Streaming #8 DEBUG mask=test live 1/6'}); window.testClock+=1600; updateReachClock(performance.now());
    assert(game.state==='over' && $('game-result').textContent.includes('資料來源改變'),
      'reach source change stops round with correct reason');
    packet({status:'Infer err: test'}); startGame();
    assert(game.state!=='playing', 'inference error blocks reach activity too');
    assert($('pose-game-cue').textContent.includes('姿態推論錯誤'), 'pose games explain inference failure');
    meshWs.readyState=3; startGame();
    assert(game.state!=='playing' && $('pose-game-cue').textContent.startsWith('姿態服務沒有連線'),
      'pose games explain a missing pose service');
    meshWs.readyState=1;
    packet({status:'Streaming #9 DEBUG mask=test live 0/6',joints:joints(),joints_version:25});
    $('game-mode').value='squat'; changePoseGame(); startGame();
    assert(game.mode==='squat' && targetMeshes.every(m=>!m.visible), 'squat starts in shared scene without reach targets');
    assert($('library-start').disabled && $('library-start').textContent==='開始 Squat Rhythm', 'the library start button follows the game and is off during a round');
    assert(!$('pose-ready').hidden && $('game-time').textContent==='校準中', 'calibration shows readiness bar instead of running countdown');
    window.testClock+=100; updateGame(avatar.joints);
    assert(game.source.kind==='demo' && !$('pose-game-cue').textContent.includes('示範資料'), 'no demo hint while calibration has just started');
    const calibrationSince=game.calibrationSince; game.calibrationSince-=DEMO_CALIBRATION_HINT_MS+1;
    window.testClock+=100; updateGame(avatar.joints);
    assert($('pose-game-cue').textContent.includes('示範資料的動作不會停下來'), 'a calibration stuck on demo data says why');
    game.calibrationSince=calibrationSince; game.readyHold=0; game.readyHeight=null;
    const initialDeadline=game.deadline;
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(avatar.joints); }
    assert(!game.calibrating && game.deadline>initialDeadline && game.timeLeft===60, 'standing calibration completes before timed round');
    assert($('pose-ready').hidden && $('game-time').textContent==='60 秒', 'completed calibration hides readiness bar and reveals full round time');
    const bowPose=avatar.joints.map(p=>p.slice()); bowPose[15][1]-=.25;
    for(let i=0;i<6;i++) { window.testClock+=100; updateGame(bowPose); }
    assert(game.score===0, 'head lowering alone is not a squat');
    const squatPose=avatar.joints.map(p=>p.slice()); squatPose[15][1]-=.25; squatPose[0][1]-=.2;
    for(let i=0;i<6;i++) { window.testClock+=100; updateGame(squatPose); }
    assert(game.score===1 && game.phase==='stand', 'squat hold scores one repetition');
    for(let i=0;i<6;i++) { window.testClock+=100; updateGame(squatPose); }
    assert(game.score===1, 'held squat cannot score repeatedly');
    window.testClock+=100; updateGame(avatar.joints);
    for(let i=0;i<6;i++) { window.testClock+=100; updateGame(squatPose); }
    assert(game.score===2, 'standing rearms squat repetition');
    $('game-mode').value='balance'; changePoseGame(); startGame();
    const unreadyPose=avatar.joints.map(p=>p.slice()); unreadyPose[10][1]+=.2;
    for(let i=0;i<12;i++) { window.testClock+=100; updateGame(unreadyPose); }
    updateReachClock(performance.now());
    assert(game.calibrating && game.score===0 && game.timeLeft===60, 'raised foot cannot calibrate or consume round time');
    assert($('pose-game-cue').textContent.includes('雙腳要踩平'), 'calibration explains unlevel feet');
    for(let i=0;i<2;i++) { window.testClock+=100; updateGame(avatar.joints); }
    AetherCombat.onJoints(avatar.joints);
    $('game-pause').click();
    assert($('game-time').textContent==='已暫停' && !$('pose-ready').hidden, 'paused calibration displays paused state');
    $('game-pause').click();
    assert($('pose-ready').value===0 && $('game-time').textContent==='校準中', 'resuming calibration resets readiness progress');
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(avatar.joints); }
    assert(!game.calibrating, 'balance uses stable standing calibration');
    const balancePose=avatar.joints.map(p=>p.slice());
    balancePose[15][0]=balancePose[0][0]; balancePose[15][2]=balancePose[0][2];
    balancePose[10][1]=balancePose[11][1]+.2;
    for(let i=0;i<16;i++) { window.testClock+=100; updateGame(balancePose); }
    assert(game.score===1 && game.foot===11, 'balance hold scores then prompts other foot');
    for(let i=0;i<16;i++) { window.testClock+=100; updateGame(balancePose); }
    assert(game.score===1, 'wrong foot cannot score balance prompt');
    balancePose[11][1]=balancePose[10][1]+.2;
    window.testClock+=1000; updateGame(balancePose);
    assert(game.hold===0, 'sample gap cannot count as balance hold');
    for(let i=0;i<16;i++) { window.testClock+=100; updateGame(balancePose); }
    assert(game.score===2 && game.foot===10, 'balance alternates left and right');
    $('game-stop').click();
    assert(game.state==='over' && $('game-stop').style.display==='none' && $('game-result').textContent.includes('中途結束'), 'manual stop ends challenge and restores controls');
    packet({status:'Streaming #10 DEBUG mask=test live 0/6',joints:joints(),joints_version:26});
    $('game-mode').value='dodge'; changePoseGame(); startGame();
    assert(game.mode==='dodge' && game.calibrating, 'dodge shares standing calibration');
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(avatar.joints); }
    const leftDodge=avatar.joints.map(p=>p.slice()); leftDodge[15][0]-=.22; leftDodge[9][0]-=.11;
    const rightDodge=avatar.joints.map(p=>p.slice()); rightDodge[15][0]+=.22; rightDodge[9][0]+=.11;
    for(let i=0;i<5;i++) { window.testClock+=100; updateGame(rightDodge); }
    assert(game.score===0 && targetMeshes[0].visible, 'dodge cue rejects wrong direction');
    const headOnly=avatar.joints.map(p=>p.slice()); headOnly[15][0]-=.22;
    for(let i=0;i<5;i++) { window.testClock+=100; updateGame(headOnly); }
    assert(game.score===0, 'head turn alone does not count as torso dodge');
    for(let i=0;i<5;i++) { window.testClock+=100; updateGame(leftDodge); }
    assert(game.score===1 && game.needsCenter && game.dodgeSide===1 && !targetMeshes[0].visible, 'left dodge scores and prompts neutral reset');
    for(let i=0;i<5;i++) { window.testClock+=100; updateGame(rightDodge); }
    assert(game.score===1, 'switching directly to opposite lean cannot bypass center');
    window.testClock+=100; updateGame(avatar.joints);
    for(let i=0;i<5;i++) { window.testClock+=100; updateGame(rightDodge); }
    assert(game.score===2 && game.dodgeSide===-1, 'neutral rearm allows alternating dodge score');
    packet({status:'Streaming #12 DEBUG mask=test live 0/6',joints:joints(),joints_version:27});
    $('game-mode').value='sky'; changePoseGame(); startGame();
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(avatar.joints); }
    assert(game.mode==='sky' && !game.calibrating, 'sky catch uses shared standing calibration');
    game.hold=.3; $('game-pause').click(); window.testClock+=100;
    $('game-pause').click();
    assert(game.hold===0 && game.sampleAt===performance.now(), 'resume discards partial gesture hold');
    const raised=avatar.joints.map(p=>p.slice());
    raised[22]=[-.12,raised[15][1]+.25,0]; raised[23]=[.12,raised[15][1]+.25,0];
    const single=raised.map(p=>p.slice()); single[23]=avatar.joints[23].slice();
    for(let i=0;i<5;i++) { window.testClock+=100; updateGame(single); }
    assert(game.score===0 && targetMeshes[0].visible, 'single hand cannot catch two-hand target');
    for(let i=0;i<5;i++) { window.testClock+=100; updateGame(raised); }
    assert(game.score===1 && game.needsLower && !targetMeshes[0].visible, 'two raised hands catch overhead target');
    for(let i=0;i<5;i++) { window.testClock+=100; updateGame(raised); }
    assert(game.score===1, 'holding raised hands cannot farm sky catch scores');
    window.testClock+=100; updateGame(avatar.joints);
    for(let i=0;i<5;i++) { window.testClock+=100; updateGame(raised); }
    assert(game.score===2 && game.needsLower, 'lowering both hands rearms sky catch');
    $('game-sound').checked=false; $('game-sound').dispatchEvent(new Event('change'));
    $('game-sound').checked=true; loadSoundSetting();
    assert(!$('game-sound').checked, 'a muted sound setting is remembered across reloads');
    const previousAudio=audioCtx; $('game-sound').checked=false; beep(500);
    packet({status:'Streaming #13 DEBUG mask=test live 0/6',joints:joints(),joints_version:28});
    $('game-mode').value='clap'; changePoseGame(); startGame();
    const openClap=avatar.joints.map(p=>p.slice());
    openClap[22]=[openClap[9][0]-.35,openClap[9][1],openClap[9][2]];
    openClap[23]=[openClap[9][0]+.35,openClap[9][1],openClap[9][2]];
    const closedClap=openClap.map(p=>p.slice());
    closedClap[22][0]=closedClap[9][0]-.04; closedClap[23][0]=closedClap[9][0]+.04;
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(closedClap); }
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(closedClap); }
    assert(game.score===0 && !game.clapOpened, 'clap cannot start from hands already together');
    window.testClock+=100; updateGame(openClap);
    for(let i=0;i<3;i++) { window.testClock+=100; updateGame(closedClap); }
    assert(game.score===1 && !game.clapOpened, 'chest-height open-close gesture scores clap');
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(closedClap); }
    assert(game.score===1, 'held clap cannot repeatedly score');
    window.testClock+=100; updateGame(openClap);
    const lowClap=closedClap.map(p=>p.slice()); lowClap[22][1]-=.5; lowClap[23][1]-=.5;
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(lowClap); }
    assert(game.score===1, 'hands together below chest cannot count as clap');
    window.testClock+=1000; updateGame(closedClap);
    assert(game.hold===0, 'clap sample gap discards hold');
    for(let i=0;i<3;i++) { window.testClock+=100; updateGame(closedClap); }
    assert(game.score===2, 'opening arms rearms another clap');
    packet({status:'Streaming #14 DEBUG mask=test live 0/6',joints:joints(),joints_version:29});
    $('game-mode').value='march'; changePoseGame(); startGame();
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(avatar.joints); }
    const leftStep=avatar.joints.map(p=>p.slice()); leftStep[4][1]+=.2; leftStep[10][1]+=.12;
    const rightStep=avatar.joints.map(p=>p.slice()); rightStep[5][1]+=.2; rightStep[11][1]+=.12;
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(rightStep); }
    assert(game.score===0 && game.foot===10, 'march rejects wrong-side knee lift');
    const kneeOnly=leftStep.map(p=>p.slice()); kneeOnly[10][1]=avatar.joints[10][1];
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(kneeOnly); }
    assert(game.score===0, 'march requires both knee and foot lift');
    const droppedFoot=avatar.joints.map(p=>p.slice()); droppedFoot[11][1]-=.2;
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(droppedFoot); }
    assert(game.score===0, 'lowering the other foot cannot fake a knee lift');
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(leftStep); }
    assert(game.score===1 && game.foot===11 && game.marchNeutral, 'march scores left step and prompts right');
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(rightStep); }
    assert(game.score===1, 'march requires both feet down before changing sides');
    window.testClock+=100; updateGame(avatar.joints);
    window.testClock+=1000; updateGame(rightStep);
    assert(game.hold===0, 'march sample gap cannot accumulate hold');
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(rightStep); }
    assert(game.score===2 && game.foot===10, 'march alternates after neutral stance');
    packet({status:'Streaming #15 DEBUG mask=test live 0/6',joints:joints(),joints_version:30});
    $('game-mode').value='star'; changePoseGame(); startGame();
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(avatar.joints); }
    const starPose=avatar.joints.map(point=>point.slice());
    starPose[16]=[-.2,.42,0]; starPose[18]=[-.5,.42,0]; starPose[22]=[-.8,.42,0];
    starPose[17]=[.2,.42,0]; starPose[19]=[.5,.42,0]; starPose[23]=[.8,.42,0];
    const singleStar=starPose.map(point=>point.slice()); singleStar[23]=avatar.joints[23].slice();
    for(let i=0;i<9;i++) { window.testClock+=100; updateGame(singleStar); }
    assert(game.score===0, 'star hold requires both arms at shoulder height');
    const bentStar=starPose.map(point=>point.slice()); bentStar[18][1]+=.4;
    for(let i=0;i<9;i++) { window.testClock+=100; updateGame(bentStar); }
    assert(game.score===0, 'star hold rejects bent arm even with extended hand position');
    for(let i=0;i<9;i++) { window.testClock+=100; updateGame(starPose); }
    assert(game.score===1 && game.starLower && targetMeshes.every(target=>!target.visible), 'straight level arms score star hold and hide cues');
    for(let i=0;i<9;i++) { window.testClock+=100; updateGame(starPose); }
    assert(game.score===1, 'held star pose cannot repeatedly score');
    window.testClock+=100; updateGame(avatar.joints);
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(starPose); }
    window.testClock+=1000; updateGame(starPose);
    assert(game.hold===0, 'star hold sample gap resets partial hold');
    for(let i=0;i<9;i++) { window.testClock+=100; updateGame(starPose); }
    assert(game.score===2, 'lowering both hands rearms another star hold');
    packet({status:'Streaming #16 DEBUG mask=test live 0/6',joints:joints(),joints_version:31});
    $('game-mode').value='cross'; changePoseGame(); startGame();
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(avatar.joints); }
    const leftCross=avatar.joints.map(point=>point.slice());
    leftCross[4][1]+=.18; leftCross[10][1]+=.1; leftCross[23]=leftCross[4].slice();
    const rightCross=avatar.joints.map(point=>point.slice());
    rightCross[5][1]+=.18; rightCross[11][1]+=.1; rightCross[22]=rightCross[5].slice();
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(rightCross); }
    assert(game.score===0 && game.foot===10, 'cross knee rejects unprompted side');
    const sameSideCross=leftCross.map(point=>point.slice()); sameSideCross[23]=avatar.joints[23].slice(); sameSideCross[22]=leftCross[4].slice();
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(sameSideCross); }
    assert(game.score===0, 'cross knee requires opposite hand');
    const unraisedCross=avatar.joints.map(point=>point.slice()); unraisedCross[23]=unraisedCross[4].slice();
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(unraisedCross); }
    assert(game.score===0, 'cross knee requires raised knee and foot');
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(leftCross); }
    assert(game.score===1 && game.foot===11 && game.crossNeutral && !targetMeshes[0].visible, 'cross knee scores left knee touched by right hand');
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(rightCross); }
    assert(game.score===1, 'cross knee requires neutral release before alternating');
    window.testClock+=100; updateGame(avatar.joints);
    for(let i=0;i<2;i++) { window.testClock+=100; updateGame(rightCross); }
    window.testClock+=1000; updateGame(rightCross);
    assert(game.hold===0, 'cross knee rejects accumulation across pose update gaps');
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(rightCross); }
    assert(game.score===2 && game.foot===10, 'cross knee alternates after neutral stance');
    const crossBody=avatar.root, crossCamera=camera.position.clone();
    game.deadline=performance.now(); updateReachClock(performance.now());
    assert(poseRecords['cross:demo:0']===2 && roundHistory.some(entry=>entry.mode==='cross' && entry.completed) && avatar.root===crossBody && camera.position.equals(crossCamera), 'cross knee records completed round without changing shared avatar or camera');
    packet({status:'Streaming #17 DEBUG mask=test live 0/6',joints:joints(),joints_version:32});
    $('game-mode').value='guard'; changePoseGame(); startGame();
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(avatar.joints); }
    const drillGuard=avatar.joints.map(point=>point.slice());
    drillGuard[22]=[-.12,.64,0]; drillGuard[23]=[.12,.64,0];
    const oneHandGuard=drillGuard.map(point=>point.slice()); oneHandGuard[23]=avatar.joints[23].slice();
    for(let i=0;i<9;i++) { window.testClock+=100; updateGame(oneHandGuard); }
    assert(game.score===0, 'guard drill requires both hands near head');
    const sameSideGuard=drillGuard.map(point=>point.slice()); sameSideGuard[23]=[-.3,.64,0];
    for(let i=0;i<9;i++) { window.testClock+=100; updateGame(sameSideGuard); }
    assert(game.score===0, 'guard drill requires hands on opposite sides of head');
    const leaningGuard=drillGuard.map(point=>point.slice()); leaningGuard[15][0]+=.35;
    for(let i=0;i<9;i++) { window.testClock+=100; updateGame(leaningGuard); }
    assert(game.score===0, 'guard drill rejects uncentered torso');
    for(let i=0;i<9;i++) { window.testClock+=100; updateGame(drillGuard); }
    assert(game.score===1 && game.guardLower && targetMeshes.every(target=>!target.visible), 'guard drill scores stable two-handed guard');
    for(let i=0;i<9;i++) { window.testClock+=100; updateGame(drillGuard); }
    assert(game.score===1, 'continuous guard cannot repeatedly score');
    window.testClock+=100; updateGame(avatar.joints);
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(drillGuard); }
    window.testClock+=1000; updateGame(drillGuard);
    assert(game.hold===0, 'guard drill resets hold after sample gap');
    for(let i=0;i<9;i++) { window.testClock+=100; updateGame(drillGuard); }
    assert(game.score===2, 'lowering both hands rearms guard drill');
    game.deadline=performance.now(); updateReachClock(performance.now());
    assert(poseRecords['guard:demo:0']===2 && roundHistory.some(entry=>entry.mode==='guard' && entry.completed), 'guard drill stores best score and completed history');
    packet({status:'Streaming #18 DEBUG mask=test live 0/6',joints:joints(),joints_version:33});
    chooseGame('shoulder'); startGame();
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(avatar.joints); }
    assert(!game.calibrating && game.score===0,'shoulder tap requires standing calibration');
    const shoulderPose=avatar.joints.map(point=>point.slice());
    shoulderPose[22]=shoulderPose[17].slice(); shoulderPose[23]=shoulderPose[16].slice();
    const sameShoulder=avatar.joints.map(point=>point.slice());
    sameShoulder[22]=sameShoulder[16].slice(); sameShoulder[23]=sameShoulder[17].slice();
    for(let i=0;i<7;i++) { window.testClock+=100; updateGame(sameShoulder); }
    assert(game.score===0,'shoulder tap rejects touching the same-side shoulders');
    const singleShoulder=shoulderPose.map(point=>point.slice()); singleShoulder[23]=avatar.joints[23].slice();
    for(let i=0;i<7;i++) { window.testClock+=100; updateGame(singleShoulder); }
    assert(game.score===0,'shoulder tap requires both opposite hands');
    for(let i=0;i<6;i++) { window.testClock+=100; updateGame(shoulderPose); }
    assert(game.score===1 && game.shoulderRelease,'shoulder tap scores a complete hold');
    for(let i=0;i<7;i++) { window.testClock+=100; updateGame(shoulderPose); }
    assert(game.score===1,'shoulder tap cannot repeatedly score while held');
    window.testClock+=100; updateGame(singleShoulder);
    assert(game.shoulderRelease,'rearming requires releasing both hands');
    window.testClock+=100; updateGame(avatar.joints);
    for(let i=0;i<3;i++) { window.testClock+=100; updateGame(shoulderPose); }
    window.testClock+=1000; updateGame(shoulderPose);
    assert(game.hold===0,'shoulder tap resets partial hold after a sample gap');
    for(let i=0;i<6;i++) { window.testClock+=100; updateGame(shoulderPose); }
    assert(game.score===2,'shoulder tap rearms after both hands release');
    game.deadline=performance.now(); updateReachClock(performance.now());
    assert(poseRecords['shoulder:demo:0']===2 && loadPoseRecords()['shoulder:demo:0']===2 && roundHistory.some(entry=>entry.mode==='shoulder' && entry.completed),'shoulder tap persists best and completed history');
    packet({status:'Streaming #19 DEBUG mask=test live 0/6',joints:joints(),joints_version:34});
    chooseGame('highfive'); startGame();
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(avatar.joints); }
    const highLeft=avatar.joints.map(point=>point.slice()); highLeft[22]=[-.3,.78,0];
    const highRight=avatar.joints.map(point=>point.slice()); highRight[23]=[.3,.78,0];
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(highRight); }
    assert(game.score===0,'high five rejects using the unprompted hand');
    const bothHigh=highLeft.map(point=>point.slice()); bothHigh[23]=highRight[23].slice();
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(bothHigh); }
    assert(game.score===0,'high five requires the other hand below its shoulder');
    const highObstacle=new THREE.Mesh(new THREE.BoxGeometry(.12,.12,.12),new THREE.MeshBasicMaterial());
    highObstacle.position.copy(avatar.root.localToWorld(new THREE.Vector3(-.3,.78,0)));
    scene.add(highObstacle); scenePhysics.addCollider(highObstacle);
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(highLeft); }
    assert(game.score===0 && game.hold===0 && !targetMeshes[0].visible && $('pose-game-cue').textContent.includes('擋住'),'scene obstacle blocks high-five scoring and resets hold');
    scenePhysics.removeCollider(highObstacle); scene.remove(highObstacle); highObstacle.geometry.dispose(); highObstacle.material.dispose();
    for(let i=0;i<3;i++) { window.testClock+=100; updateGame(highLeft); }
    assert(game.score===1 && game.highFiveLower && game.highFiveSide===0,'left high five scores a stable hold');
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(highLeft); }
    assert(game.score===1 && game.highFiveSide===0,'held high five cannot score again or switch sides');
    window.testClock+=100; updateGame(avatar.joints);
    assert(game.highFiveSide===1 && !game.highFiveLower,'lowering prompted hand switches high five side');
    window.testClock+=100; updateGame(highRight); window.testClock+=1000; updateGame(highRight);
    assert(game.hold===0,'high five cannot accumulate hold across sample gaps');
    for(let i=0;i<3;i++) { window.testClock+=100; updateGame(highRight); }
    assert(game.score===2 && game.highFiveSide===1,'right high five scores after rearming');
    game.deadline=performance.now(); updateReachClock(performance.now());
    assert(loadPoseRecords()['highfive:demo:0']===2 && roundHistory.some(entry=>entry.mode==='highfive' && entry.completed),'high five persists best and history');
    const pathHand=new THREE.Vector3(-.5,1.2,0),pathGoal=avatar.root.localToWorld(new THREE.Vector3(-.2,1.2,0));
    const handPathWall=new THREE.Mesh(new THREE.BoxGeometry(.02,.2,.2),new THREE.MeshBasicMaterial());
    handPathWall.position.copy(avatar.root.localToWorld(new THREE.Vector3(-.35,1.2,0)));
    scene.add(handPathWall); scenePhysics.addCollider(handPathWall);
    assert(!scenePhysics.pointBlocked(pathGoal,.08) && poseTargetBlocked(pathGoal,[pathHand]),'hand-to-target path is blocked even when the target itself is clear');
    handPathWall.visible=false;
    assert(!poseTargetBlocked(pathGoal,[pathHand]),'hidden scenery does not block a hand path');
    handPathWall.visible=true; scenePhysics.stats.enabled=false;
    assert(!poseTargetBlocked(pathGoal,[pathHand]),'disabling scene collisions disables pose target obstruction');
    scenePhysics.stats.enabled=true; scenePhysics.removeCollider(handPathWall); scene.remove(handPathWall);
    handPathWall.geometry.dispose(); handPathWall.material.dispose();
    packet({status:'Streaming #20 DEBUG mask=test live 0/6',joints:joints(),joints_version:35});
    chooseGame('sky'); startGame();
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(avatar.joints); }
    const skyBlockedPose=avatar.joints.map(point=>point.slice());
    skyBlockedPose[22]=[-.1,.93,0]; skyBlockedPose[23]=[.1,.93,0];
    const skyObstacle=new THREE.Mesh(new THREE.BoxGeometry(.14,.14,.14),new THREE.MeshBasicMaterial());
    skyObstacle.position.copy(avatar.root.localToWorld(new THREE.Vector3(0,.93,0)));
    scene.add(skyObstacle); scenePhysics.addCollider(skyObstacle);
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(skyBlockedPose); }
    assert(game.score===0 && game.hold===0 && !targetMeshes[0].visible && $('pose-game-cue').textContent.includes('擋住'),'Sky Catch cannot score an obstructed target');
    scenePhysics.removeCollider(skyObstacle); scene.remove(skyObstacle); skyObstacle.geometry.dispose(); skyObstacle.material.dispose();
    for(let i=0;i<4;i++) { window.testClock+=100; updateGame(skyBlockedPose); }
    assert(game.score===1,'Sky Catch resumes scoring after obstacle removal');
    endGame('Round ended');
    packet({status:'Streaming #21 DEBUG mask=test live 0/6',joints:joints(),joints_version:36});
    chooseGame('bow'); startGame();
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(avatar.joints); }
    assert(!game.calibrating && game.standingHeadOffset instanceof THREE.Vector3,'bow captures standing torso baseline after calibration');
    const rhythmBowPose=avatar.joints.map(point=>point.slice()); rhythmBowPose[15][2]=.24; rhythmBowPose[9][2]=.14;
    const headOnlyBow=rhythmBowPose.map(point=>point.slice()); headOnlyBow[9]=avatar.joints[9].slice();
    for(let i=0;i<7;i++) { window.testClock+=100; updateGame(headOnlyBow); }
    assert(game.score===0,'bow requires chest movement as well as head movement');
    const sidewaysBow=rhythmBowPose.map(point=>point.slice()); sidewaysBow[15][0]=.3;
    for(let i=0;i<7;i++) { window.testClock+=100; updateGame(sidewaysBow); }
    assert(game.score===0,'bow rejects sideways leaning');
    const crouchBow=rhythmBowPose.map(point=>point.slice()); crouchBow[0][1]=-.2; crouchBow[15][1]-=.2;
    for(let i=0;i<7;i++) { window.testClock+=100; updateGame(crouchBow); }
    assert(game.score===0,'bow cannot score a crouch');
    for(let i=0;i<6;i++) { window.testClock+=100; updateGame(rhythmBowPose); }
    assert(game.score===1 && game.bowReset,'bow scores stable forward torso movement');
    for(let i=0;i<7;i++) { window.testClock+=100; updateGame(rhythmBowPose); }
    assert(game.score===1,'holding bow cannot score repeatedly');
    window.testClock+=100; updateGame(avatar.joints);
    for(let i=0;i<3;i++) { window.testClock+=100; updateGame(rhythmBowPose); }
    window.testClock+=1000; updateGame(rhythmBowPose);
    assert(game.hold===0,'bow resets hold after tracking sample gap');
    const turnedBow=rhythmBowPose.map(point=>new THREE.Vector3(...point).applyAxisAngle(new THREE.Vector3(0,1,0),Math.PI/2).toArray());
    for(let i=0;i<6;i++) { window.testClock+=100; updateGame(turnedBow); }
    assert(game.score===2,'bow follows body-facing direction after turning');
    game.deadline=performance.now(); updateReachClock(performance.now());
    assert(loadPoseRecords()['bow:demo:0']===2 && roundHistory.some(entry=>entry.mode==='bow' && entry.completed),'bow saves completed score and round history');
    // Real SMPL poses put the body's left at +x when facing +z; the synthetic skeleton
    // above is mirrored. Direction-sensitive games must work for the real one.
    const realHanded=pose=>pose.map(([x,y,z])=>[-x,y,z]);
    packet({joints: joints(), joints_version: 9001}); tick(.016);
    chooseGame('bow'); startGame();
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(realHanded(avatar.joints)); }
    const backwardBow=realHanded(avatar.joints); backwardBow[15][2]=-.24; backwardBow[9][2]=-.14;
    for(let i=0;i<7;i++) { window.testClock+=100; updateGame(backwardBow); }
    assert(game.state==='playing' && game.score===0, 'with real SMPL handedness, bending backwards is not a bow');
    for(let i=0;i<7;i++) { window.testClock+=100; updateGame(realHanded(rhythmBowPose)); }
    assert(game.score===1, 'with real SMPL handedness, bowing forward scores');
    endGame('Round ended');
    chooseGame('dodge'); startGame();
    for(let i=0;i<11;i++) { window.testClock+=100; updateGame(realHanded(avatar.joints)); }
    const ownLeft=realHanded(avatar.joints); ownLeft[15][0]+=.22; ownLeft[9][0]+=.11;  // +x is the body's left
    const ownRight=realHanded(avatar.joints); ownRight[15][0]-=.22; ownRight[9][0]-=.11;
    for(let i=0;i<5;i++) { window.testClock+=100; updateGame(ownRight); }
    assert(game.score===0, 'with real SMPL handedness, leaning right does not answer "向左"');
    for(let i=0;i<5;i++) { window.testClock+=100; updateGame(ownLeft); }
    assert(game.score===1 && game.dodgeSide===1, 'with real SMPL handedness, leaning to the left of the body answers "向左"');
    endGame('Round ended');
    assert(audioCtx===previousAudio, 'muted game sound does not create or replace audio context');
    const audioBefore=audioCtx, RealAudioContext=window.AudioContext;
    let oscillators=0;
    window.AudioContext=class extends RealAudioContext { createOscillator() { oscillators++; return super.createOscillator(); } };
    audioCtx=null; $('game-sound').checked=true; playCue('start');
    assert(audioCtx instanceof RealAudioContext && oscillators===6, 'with sound on, the start cue plays three notes, each with an octave layer');
    audioCtx.close(); audioCtx=audioBefore; window.AudioContext=RealAudioContext;
    $('game-sound').checked=true;
    $('game-mode').value='reach'; changePoseGame();
    assert(game.state==='over' && $('game-btn').textContent==='開始 Reach Targets', 'game switching stops round and updates start label');
    packet({status:'Streaming #10 DEBUG mask=test live 0/6',joints:joints(),joints_version:26});
    poseRecords={}; clearRoundHistory(); startGame(); game.score=7; game.deadline=performance.now(); updateReachClock(performance.now());
    assert(poseRecords['reach:demo:0']===7 && $('game-result').textContent.includes('示範資料') && $('game-result').textContent.includes('最佳 7'),
      'completed round saves best with game and input source');
    assert(getComputedStyle($('game-result')).display==='block' && $('game-result').querySelector('.result-score').textContent.startsWith('7') &&
      !!$('game-result').querySelector('.result-actions .btn.primary'), 'a finished round shows the results card with its score and replay');
    assert(document.activeElement===$('game-result').querySelector('.result-actions .btn.primary'), 'the results card focuses its replay button');
    const sceneBox=$('viewport').getBoundingClientRect(), cardBox=$('game-result').getBoundingClientRect();
    assert(sceneBox.width>=900 ? cardBox.right<sceneBox.left+sceneBox.width/2 : Math.abs(cardBox.left+cardBox.width/2-(sceneBox.left+sceneBox.width/2))<2,
      'the results card docks left on a wide scene (player and robot stay in view) and is centred on a narrow one');
    document.body.classList.add('combat-mode');
    const combatCardBox=$('game-result').getBoundingClientRect();
    document.body.classList.remove('combat-mode');
    assert(Math.abs(combatCardBox.left+combatCardBox.width/2-(sceneBox.left+sceneBox.width/2))<2, 'in Combat the results card stays centred between the HUD panels');
    setFocusMode(true);
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    assert(getComputedStyle($('game-result')).display==='none' && document.body.classList.contains('focus-mode') && !$('game-result').contains(document.activeElement),
      'Esc closes the results card before leaving the hidden-panel view');
    setFocusMode(false);
    showRoundResult({title:'Reach Targets',score:1,sourceLabel:'示範資料',reason:"Time's up",completed:true,best:1,newRecord:false,again:()=>{}});
    selectTab('combat');
    assert(getComputedStyle($('game-result')).display==='none', 'switching to Combat closes the pose results card');
    selectTab('games');
    assert(sceneEnvironment.scoreboard.value==='7' && sceneEnvironment.scoreboard.sub==='完成' && sceneEnvironment.scoreboard.title==='REACH TARGETS',
      'the hall scoreboard shows the final score');
    assert(scene.getObjectByName('aether-opponent').userData.animation==='Dance', 'outside Combat the robot celebrates a finished pose round');
    assert(roundHistory.length===1 && roundHistory[0].completed && roundHistory[0].score===7 && roundHistory[0].seconds===60, 'completed pose round enters history with duration');
    endGame();
    assert(roundHistory.length===1, 'repeated end cannot duplicate round history');
    startGame(); game.score=3; game.deadline=performance.now(); updateReachClock(performance.now());
    assert(poseRecords['reach:demo:0']===7, 'lower score preserves best');
    startGame(); game.score=99; endGame('Round ended');
    assert(poseRecords['reach:demo:0']===7 && $('game-result').textContent.includes('未完成的回合'), 'unfinished round does not replace completed best');
    assert(!roundHistory[0].completed && roundHistory[0].reason==='Round ended', 'interrupted round records its reason');
    packet({status:'Streaming #11 LIVE 6/6'}); startGame(); game.score=2; game.deadline=performance.now(); updateReachClock(performance.now());
    assert(poseRecords['reach:live:6']===2 && poseRecords['reach:demo:0']===7, 'live and demo records remain separate');
    const savedRecords=localStorage.getItem(poseRecordKey);
    localStorage.setItem(poseRecordKey,JSON.stringify({'reach:demo:0':7,'reach:live:6':-4,'bad':10,'squat:mixed:2':'99'}));
    const sanitized=loadPoseRecords();
    assert(Object.keys(sanitized).length===1 && sanitized['reach:demo:0']===7, 'stored records reject invalid values and unknown keys');
    localStorage.setItem(poseRecordKey,'broken json');
    assert(Object.keys(loadPoseRecords()).length===0, 'corrupt stored records do not break game');
    localStorage.setItem(poseRecordKey,savedRecords);
    assert(loadPoseRecords()['reach:demo:0']===7, 'best score reloads from local storage');
    assert(loadRoundHistory().length===4 && loadRoundHistory()[0].source==='live:6', 'round history reloads and retains newest source');
    startGame(); $('game-pause').click(); window.testClock+=2000; $('game-pause').click(); endGame('Round ended');
    assert(roundHistory[0].seconds===0, 'history excludes paused time');
    startGame(); $('game-pause').click(); window.testClock+=6000;
    $('game-pause').click();
    assert(game.state==='over' && $('game-result').textContent.includes('姿態資料過期') && $('game-pause').style.display==='none', 'stale tracking cannot resume paused round');
    for(let i=0;i<55;i++) recordRoundHistory({mode:'combat',score:i,source:'demo:0',completed:false,reason:'Round reset.',seconds:1});
    assert(roundHistory.length===50 && roundHistory[0].score===54 && roundHistory[49].score===5 && $('history-list').children.length===10,
      'history caps storage and keeps newest ten rows visible');
    const historySaved=localStorage.getItem(historyStorageKey);
    localStorage.setItem(historyStorageKey,'broken json');
    assert(loadRoundHistory().length===0, 'corrupt round history is safely ignored');
    localStorage.setItem(historyStorageKey,historySaved);
    const originalClick=HTMLAnchorElement.prototype.click;
    let download;
    HTMLAnchorElement.prototype.click=function(){download={name:this.download,url:this.href};};
    exportRoundHistory(); HTMLAnchorElement.prototype.click=originalClick;
    assert(download.name==='aetherpose-rounds.json' && download.url.startsWith('blob:'), 'export downloads local round history JSON');
    clearRoundHistory();
    assert(roundHistory.length===0 && poseRecords['reach:demo:0']===7 && $('history-list').textContent.includes('還沒有回合紀錄'),
      'clear history preserves best scores');
    packet({status:'Loading model'}); selectTab('combat'); $('start-btn').click();
    assert($('start-btn').textContent==='開始回合', 'loading state blocks combat even with cached pose');
    packet({status:'Streaming #9 DEBUG mask=test live 0/6'}); tick(.016);
    selectTab('combat');
    const lr = document.querySelector('#combat-view .left-stack').getBoundingClientRect();
    const rr = document.querySelector('#combat-view .right-stack').getBoundingClientRect();
    assert(lr.right + 10 <= rr.left, 'HUD columns keep readable gap');
    const combatBox=$('combat-view').getBoundingClientRect();
    const blockingPanels=[...document.querySelectorAll('#combat-view .left-stack .panel, #combat-view .right-stack .panel')].filter(panel=>{
      const r=panel.getBoundingClientRect();
      return r.width && r.right>combatBox.left+combatBox.width*.3 && r.left<combatBox.left+combatBox.width*.7 &&
        r.bottom>combatBox.top+combatBox.height*.25 && r.top<combatBox.top+combatBox.height*.75;
    });
    assert(!blockingPanels.length, 'Combat side panels leave the middle of the scene (player and opponent) clear');
    renderer.render(scene,camera);
    assert(renderer.info.render.calls > 0, 'shared scene renders');
    const gl = renderer.getContext();
    const pixel = new Uint8Array(4);
    gl.readPixels(10,10,1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);
    assert(!gl.isContextLost() && pixel[3] > 0 && pixel[0]+pixel[1]+pixel[2] > 0,
      'WebGL produces visible pixels');
    assert(window.testErrors.length === 0, 'no runtime errors across scenarios');
    const preservedAvatar=avatar.root;
    setSceneView('side');
    assert(Math.abs(camera.position.x-3.6)<1e-5 && Math.abs(camera.position.z)<1e-5 && !followPose, 'side view frames shared world without following body');
    const sideCamera=camera.position.clone(); selectTab('cal'); selectTab('combat');
    assert(camera.position.distanceTo(sideCamera)<1e-6 && avatar.root===preservedAvatar && location.href===applicationUrl, 'camera preset survives activity switching in same world');
    setSceneView('top');
    assert(Math.abs(camera.position.y-5)<1e-5 && $('scene-view').value==='top', 'top view preset works');
    setSceneView('front');
    $('scene-quality').value='low'; $('scene-quality').dispatchEvent(new Event('change'));
    const normalWidth=renderer.domElement.width;
    $('focus-btn').click();
    assert(getComputedStyle($('panel')).display==='none' && renderer.domElement.width>normalWidth, 'focus view expands the actual renderer and hides the panel');
    assert($('focus-btn').getAttribute('aria-pressed')==='true' && avatar.root===preservedAvatar, 'focus view preserves the body and exposes its state');
    const focusCamera=camera.position.clone();
    assert(getComputedStyle($('scene-activity')).display!=='none', 'activity switches appear on the scene while the panel is hidden');
    $('scene-combat-btn').click();
    assert(combatMode && document.body.classList.contains('focus-mode') && camera.position.distanceTo(focusCamera)<1e-6 && location.href===applicationUrl, 'focus toolbar switches activities without moving camera or changing URL');
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));
    assert(getComputedStyle($('panel')).display!=='none' && $('focus-btn').getAttribute('aria-pressed')==='false', 'Escape restores the control panel');
    assert(!renderer.shadowMap.enabled && renderer.getPixelRatio()<=1, 'low quality disables shadows and caps render resolution');
    assert(!scene.getObjectByName('aether-hall-detail').visible, 'low quality hides the hall props and accent lights');
    applySceneSettings('high',1.4);
    assert(renderer.shadowMap.enabled && scene.getObjectByName('arena-key-light').shadow.mapSize.x===2048 && renderer.toneMappingExposure===1.4,
      'high quality upgrades shadows and applies scene brightness');
    assert(avatar.root===preservedAvatar && scene.getObjectByName('combat-world').visible, 'quality changes preserve the shared avatar and world');
    const savedSceneSettings=loadSceneSettings();
    assert(savedSceneSettings.quality==='high' && savedSceneSettings.brightness===1.4, 'appearance settings reload from local storage');
    applySceneSettings('unknown',NaN);
    assert($('scene-quality').value==='balanced' && renderer.toneMappingExposure===1.1, 'invalid appearance input restores safe defaults');
    localStorage.setItem(sceneSettingsKey,'broken json');
    assert(loadSceneSettings().quality==='balanced', 'corrupt scene settings do not block startup');
    applySceneSettings('balanced',1.1);
    assert(Math.abs(camera.position.z-3.6)<1e-5 && $('scene-view').value==='front', 'reset restores front camera view');
    controls.dispatchEvent({type:'start'});
    assert($('scene-view').value==='custom', 'manual orbit marks view as custom');
    setSceneView('front');
    const result = {ok: true, checks};
    const collisionRoot=new THREE.Group(); scene.add(collisionRoot);
    const collisionGeometry=new THREE.BoxGeometry(.4,1,.4);
    assert(!scenePhysics.debugGroup.visible, 'collision diagnostics stay hidden by default');
    assert($('collision-legend').hidden && $('physics-status').hidden, 'collision legend and solver numbers stay hidden by default');
    $('collision-debug').checked=true; $('collision-debug').dispatchEvent(new Event('change'));
    assert(!$('collision-legend').hidden && !$('physics-status').hidden, 'showing collision ranges explains their colours');
    collisionRoot.position.set(0,-.4,1);
    scenePhysics.constrain(collisionRoot,collisionGeometry);
    let constrainedBounds=collisionGeometry.boundingBox.clone().applyMatrix4(collisionRoot.matrixWorld);
    assert(constrainedBounds.min.y>=-.00751 && scenePhysics.stats.contacts>0, 'mesh-derived ground constraint prevents floor penetration');
    scenePhysics.updateDebug(collisionRoot,collisionGeometry);
    const bodyCollisionHelper=scene.getObjectByName('collision-body-bounds');
    assert(scenePhysics.debugGroup.visible && bodyCollisionHelper.box.min.distanceTo(constrainedBounds.min)<1e-6 && bodyCollisionHelper.material.color.getHex()===0xf0576b, 'collision overlay matches constrained body mesh and highlights contact');
    collisionRoot.visible=false; scenePhysics.updateDebug(collisionRoot,collisionGeometry);
    assert(!bodyCollisionHelper.visible, 'collision overlay hides expired body'); collisionRoot.visible=true;
    $('collision-debug').checked=false; $('collision-debug').dispatchEvent(new Event('change'));
    assert(!scenePhysics.debugGroup.visible && scene.getObjectByName('combat-world').visible, 'hiding collision overlays preserves the unified scene');
    scenePhysics.reset(collisionRoot);
    collisionRoot.position.set(0,.7,-2.6);
    scenePhysics.constrain(collisionRoot,collisionGeometry);
    constrainedBounds=collisionGeometry.boundingBox.clone().applyMatrix4(collisionRoot.matrixWorld);
    const wallBounds=new THREE.Box3().setFromObject(scene.getObjectByName('arena-back-wall'));
    assert(!constrainedBounds.intersectsBox(wallBounds), 'body mesh bounds are pushed out of scene wall');
    scenePhysics.reset(collisionRoot);
    collisionRoot.position.set(0,.7,-1.9); scenePhysics.constrain(collisionRoot,collisionGeometry);
    collisionRoot.position.z=-3.3; scenePhysics.constrain(collisionRoot,collisionGeometry);
    assert(collisionRoot.position.z>-2.31 && scenePhysics.stats.sweptContacts===1, 'continuous sweep blocks fast crossing through thin wall');
    scenePhysics.reset(collisionRoot); collisionRoot.position.set(0,.7,-1.9);
    scenePhysics.constrain(collisionRoot,collisionGeometry);
    collisionRoot.position.set(1,.7,-3.3); scenePhysics.constrain(collisionRoot,collisionGeometry);
    assert(collisionRoot.position.z>-2.31 && Math.abs(collisionRoot.position.x-1)<1e-5, 'diagonal collision preserves tangential movement along wall');
    collisionRoot.position.set(1.5,.7,-3.3); scenePhysics.constrain(collisionRoot,collisionGeometry);
    assert(collisionRoot.position.z>-2.31 && Math.abs(collisionRoot.position.x-1.5)<1e-5, 'continued pressure against wall still allows sliding');
    const cornerSolid=new THREE.Mesh(new THREE.BoxGeometry(.2,1,.8));
    cornerSolid.position.set(1.4,.7,-2.1); scene.add(cornerSolid); scenePhysics.colliders.push(cornerSolid);
    scenePhysics.reset(collisionRoot); collisionRoot.position.set(0,.7,-1.9);
    scenePhysics.constrain(collisionRoot,collisionGeometry);
    collisionRoot.position.set(2,.7,-3.3); scenePhysics.constrain(collisionRoot,collisionGeometry);
    const cornerResult=collisionGeometry.boundingBox.clone().applyMatrix4(collisionRoot.matrixWorld);
    assert(!cornerResult.intersectsBox(new THREE.Box3().setFromObject(cornerSolid)) && !cornerResult.intersectsBox(wallBounds), 'iterative sliding resolves a wall and second obstacle in one frame');
    scenePhysics.colliders.pop(); scene.remove(cornerSolid); cornerSolid.geometry.dispose(); cornerSolid.material.dispose();
    scenePhysics.reset(collisionRoot); collisionRoot.position.set(0,.7,-3.3);
    scenePhysics.constrain(collisionRoot,collisionGeometry);
    assert(Math.abs(collisionRoot.position.z+3.3)<1e-6, 'explicit reset permits a new tracking origin without stale sweep');
    scenePhysics.reset(collisionRoot); collisionRoot.position.set(-.5,.9,0);
    scenePhysics.constrain(collisionRoot,collisionGeometry);
    collisionRoot.position.set(1.3,.9,0); scenePhysics.constrain(collisionRoot,collisionGeometry);
    assert(collisionRoot.position.x<.15 && scenePhysics.stats.sweptContacts>0, 'continuous sweep blocks fast traversal through opponent torso proxy');
    scenePhysics.reset(collisionRoot); collisionRoot.position.set(-.5,.9,0);
    scenePhysics.constrain(collisionRoot,collisionGeometry);
    collisionRoot.position.set(1.3,.9,.8); scenePhysics.constrain(collisionRoot,collisionGeometry);
    assert(collisionRoot.position.x<.15 && Math.abs(collisionRoot.position.z-.8)<1e-5, 'opponent collision preserves movement along unblocked direction');
    const movingBot=scene.getObjectByName('aether-opponent'), originalBotPosition=movingBot.position.clone();
    scenePhysics.reset(collisionRoot); movingBot.position.x=-1; collisionRoot.position.set(0,.9,0);
    scenePhysics.constrain(collisionRoot,collisionGeometry);
    movingBot.position.x=1; scenePhysics.constrain(collisionRoot,collisionGeometry);
    assert(collisionRoot.position.x>1.4 && scenePhysics.stats.sweptContacts>0, 'relative sweep catches moving opponent crossing a stationary body');
    scenePhysics.reset(collisionRoot); movingBot.position.x=1; collisionRoot.position.set(0,.9,0);
    scenePhysics.constrain(collisionRoot,collisionGeometry);
    movingBot.position.x=-1; scenePhysics.constrain(collisionRoot,collisionGeometry);
    assert(collisionRoot.position.x< -1.4 && scenePhysics.stats.sweptContacts>0, 'relative sweep pushes body to correct contact side for reverse motion');
    scenePhysics.reset(collisionRoot); movingBot.position.x=-1; collisionRoot.position.set(0,.9,0);
    scenePhysics.constrain(collisionRoot,collisionGeometry);
    movingBot.position.x=1; collisionRoot.position.x=3; scenePhysics.constrain(collisionRoot,collisionGeometry);
    assert(collisionRoot.position.x===3, 'relative sweep permits body moving away faster than opponent');
    movingBot.position.copy(originalBotPosition);
    scenePhysics.reset(collisionRoot);
    const compoundObstacle=new THREE.Group(); compoundObstacle.position.set(0,0,1.2);
    for (const x of [-.7,.7]) {
      const part=new THREE.Mesh(new THREE.BoxGeometry(.25,1.8,.3)); part.position.set(x,.9,0); compoundObstacle.add(part);
    }
    scene.add(compoundObstacle); scenePhysics.addCollider(compoundObstacle);
    const gapPoint=new THREE.Vector3(0,.9,1.2);
    assert(!scenePhysics.pointBlocked(gapPoint,.1) && !scenePhysics.segmentBlocked(new THREE.Vector3(0,.9,.8),new THREE.Vector3(0,.9,1.6)), 'separate meshes leave gap available to targets and attack paths');
    collisionRoot.position.set(0,.9,.6); scenePhysics.constrain(collisionRoot,collisionGeometry);
    collisionRoot.position.z=1.8; scenePhysics.constrain(collisionRoot,collisionGeometry);
    assert(collisionRoot.position.z===1.8 && scenePhysics.stats.sweptContacts===0, 'body continuous sweep can pass through gap between model meshes');
    scenePhysics.reset(collisionRoot); collisionRoot.position.set(.7,.9,.6); scenePhysics.constrain(collisionRoot,collisionGeometry);
    collisionRoot.position.z=1.8; scenePhysics.constrain(collisionRoot,collisionGeometry);
    assert(collisionRoot.position.z<1.2 && scenePhysics.stats.sweptContacts>0 && scenePhysics.pointBlocked(new THREE.Vector3(.7,.9,1.2)), 'individual model mesh still blocks body crossings and targets');
    compoundObstacle.children[1].visible=false;
    assert(!scenePhysics.pointBlocked(new THREE.Vector3(.7,.9,1.2)), 'invisible child mesh contributes no collider');
    scenePhysics.setDebug(true); scenePhysics.updateDebug(collisionRoot,collisionGeometry);
    const compoundHelpers=scenePhysics.debugGroup.children.filter(helper=>helper.userData.collider===compoundObstacle);
    assert(compoundHelpers.length===2 && compoundHelpers.filter(helper=>helper.visible).length===1, 'collision diagnostics show individual visible mesh bounds');
    scenePhysics.setDebug(false); scenePhysics.removeCollider(compoundObstacle); scene.remove(compoundObstacle);
    compoundObstacle.traverse(node=>{if(node.geometry)node.geometry.dispose();if(node.material)node.material.dispose();});
    scenePhysics.reset(collisionRoot);
    const openFrame=new THREE.Mesh(new THREE.BufferGeometry());
    const frameParts=[[-.65,0,.3,2],[.65,0,.3,2],[0,.85,.9,.3],[0,-.85,.9,.3]];
    const framePositions=[];
    for (const [x,y,width,height] of frameParts) {
      const part=new THREE.BoxGeometry(width,height,.15).toNonIndexed();
      part.translate(x,y,0); framePositions.push(...part.attributes.position.array); part.dispose();
    }
    openFrame.geometry.setAttribute('position',new THREE.Float32BufferAttribute(framePositions,3));
    openFrame.position.set(0,1,1.2); openFrame.rotation.y=.25; openFrame.scale.setScalar(.9);
    scene.add(openFrame); scenePhysics.addCollider(openFrame);
    openFrame.updateMatrixWorld(true);
    const frameStart=openFrame.localToWorld(new THREE.Vector3(0,0,-1));
    const frameEnd=openFrame.localToWorld(new THREE.Vector3(0,0,1));
    const frameGap=openFrame.localToWorld(new THREE.Vector3(0,0,0));
    assert(!scenePhysics.pointBlocked(frameGap,.1), 'target sphere can occupy hole inside a single mesh bounding box');
    assert(scenePhysics.pointBlocked(openFrame.localToWorld(new THREE.Vector3(.65,0,0)),.02), 'target center inside closed mesh part is rejected even away from surface');
    assert(scenePhysics.pointBlocked(openFrame.localToWorld(new THREE.Vector3(.45,0,0)),.08) && !scenePhysics.pointBlocked(openFrame.localToWorld(new THREE.Vector3(.35,0,0)),.08), 'sphere surface clearance uses transformed triangle distance near hole edge');
    const openSheet=new THREE.Mesh(new THREE.BufferGeometry());
    openSheet.geometry.setAttribute('position',new THREE.Float32BufferAttribute([-.5,0,-.5,.5,0,-.5,0,1,.5],3));
    openSheet.position.set(0,0,2.1); scene.add(openSheet); scenePhysics.addCollider(openSheet);
    assert(!scenePhysics.pointBlocked(new THREE.Vector3(0,.25,2.1),.01), 'open triangle sheet does not falsely enclose points inside its bounds');
    scenePhysics.removeCollider(openSheet); scene.remove(openSheet); openSheet.geometry.dispose(); openSheet.material.dispose();
    assert(!scenePhysics.segmentBlocked(frameStart,frameEnd) && !scenePhysics.segmentBlocked(frameStart,frameEnd,.03), 'triangle attack ray and swept sphere fit through single-mesh hole');
    const grazeStart=openFrame.localToWorld(new THREE.Vector3(.45,0,-1));
    const grazeEnd=openFrame.localToWorld(new THREE.Vector3(.45,0,1));
    assert(!scenePhysics.segmentBlocked(grazeStart,grazeEnd) && scenePhysics.segmentBlocked(grazeStart,grazeEnd,.06), 'swept sphere catches model edge missed by centerline');
    assert(!scenePhysics.segmentBlocked(openFrame.localToWorld(new THREE.Vector3(.35,0,-1)),openFrame.localToWorld(new THREE.Vector3(.35,0,1)),.06), 'swept sphere with adequate clearance passes hole without broad-phase false block');
    assert(scenePhysics.segmentBlocked(openFrame.localToWorld(new THREE.Vector3(.45,-.3,.12)),openFrame.localToWorld(new THREE.Vector3(.45,.3,.12)),.08), 'parallel sphere sweep detects proximity to triangle edge without plane crossing');
    const stationarySphere=openFrame.localToWorld(new THREE.Vector3(.65,0,0));
    assert(scenePhysics.segmentBlocked(stationarySphere,stationarySphere,.01) && !scenePhysics.segmentBlocked(frameGap,frameGap,.1), 'zero-length swept sphere distinguishes closed volume from hole');
    const frameSolidStart=openFrame.localToWorld(new THREE.Vector3(.65,0,-1));
    const frameSolidEnd=openFrame.localToWorld(new THREE.Vector3(.65,0,1));
    assert(scenePhysics.segmentBlocked(frameSolidStart,frameSolidEnd) && scenePhysics.segmentBlocked(frameSolidEnd,frameSolidStart), 'transformed model triangles block attack rays from both sides');
    assert(!scenePhysics.segmentBlocked(frameSolidStart,frameSolidStart.clone().lerp(frameSolidEnd,.2)), 'triangle collision ignores surface beyond attack endpoint');
    openFrame.visible=false;
    assert(!scenePhysics.segmentBlocked(frameSolidStart,frameSolidEnd), 'triangle attack ray ignores hidden mesh');
    scenePhysics.removeCollider(openFrame); scene.remove(openFrame); openFrame.geometry.dispose(); openFrame.material.dispose();
    const indexedPositions=[];
    for(let i=0;i<100;i++) {
      const part=new THREE.BoxGeometry(.2,.2,.2).toNonIndexed(); part.translate(i*.6,1,1.8);
      indexedPositions.push(...part.attributes.position.array); part.dispose();
    }
    const indexedObstacle=new THREE.Mesh(new THREE.BufferGeometry());
    indexedObstacle.geometry.setAttribute('position',new THREE.Float32BufferAttribute(indexedPositions,3));
    scene.add(indexedObstacle); scenePhysics.addCollider(indexedObstacle);
    assert(scenePhysics.pointBlocked(new THREE.Vector3(0,1,1.8),.02) && scenePhysics.queryStats.totalTriangles===1200 && scenePhysics.queryStats.candidates<60, 'triangle spatial index prunes distant triangles while preserving closed-volume target rejection');
    assert(scenePhysics.segmentBlocked(new THREE.Vector3(0,1,1.4),new THREE.Vector3(0,1,2.2),.04) && scenePhysics.queryStats.candidates<60, 'sphere sweep uses nearby triangle candidates instead of full model scan');
    indexedObstacle.geometry.translate(0,0,1);
    assert(scenePhysics.pointBlocked(new THREE.Vector3(0,1,2.8),.02) && !scenePhysics.pointBlocked(new THREE.Vector3(0,1,1.8),.02), 'geometry updates invalidate spatial index and follow changed triangles');
    scenePhysics.removeCollider(indexedObstacle); scene.remove(indexedObstacle); indexedObstacle.geometry.dispose(); indexedObstacle.material.dispose();
    const originalVertices=Array.from(collisionGeometry.attributes.position.array);
    collisionRoot.position.set(.55,.9,0); scenePhysics.constrain(collisionRoot,collisionGeometry);
    assert(scenePhysics.stats.contacts>0 && originalVertices.every((v,i)=>v===collisionGeometry.attributes.position.array[i]), 'opponent body collision preserves body shape');
    scenePhysics.stats.enabled=false; collisionRoot.position.set(0,-.4,1);
    scenePhysics.constrain(collisionRoot,collisionGeometry);
    assert(collisionRoot.position.y===-.4, 'collision toggle restores unconstrained tracking display');
    scenePhysics.stats.enabled=true; scene.remove(collisionRoot); collisionGeometry.dispose();
    function fixtureGlb(external=false) {
      const vertices=new Float32Array([-.5,0,0,.5,0,0,0,1,0]);
      const document={asset:{version:'2.0'},scene:0,scenes:[{nodes:[0]}],nodes:[{mesh:0}],
        meshes:[{primitives:[{attributes:{POSITION:0}}]}],
        buffers:[{byteLength:vertices.byteLength,...(external?{uri:'https://example.invalid/model.bin'}:{})}],
        bufferViews:[{buffer:0,byteOffset:0,byteLength:vertices.byteLength}],
        accessors:[{bufferView:0,componentType:5126,count:3,type:'VEC3',min:[-.5,0,0],max:[.5,1,0]}]};
      const text=JSON.stringify(document), padding=(4-text.length%4)%4;
      const jsonBytes=new TextEncoder().encode(text+' '.repeat(padding));
      const data=new ArrayBuffer(28+jsonBytes.length+vertices.byteLength), view=new DataView(data);
      view.setUint32(0,0x46546c67,true); view.setUint32(4,2,true); view.setUint32(8,data.byteLength,true);
      view.setUint32(12,jsonBytes.length,true); view.setUint32(16,0x4e4f534a,true);
      new Uint8Array(data,20,jsonBytes.length).set(jsonBytes);
      const offset=20+jsonBytes.length;
      view.setUint32(offset,vertices.byteLength,true); view.setUint32(offset+4,0x004e4942,true);
      new Float32Array(data,offset+8,vertices.length).set(vertices);
      return data;
    }
    const glbData=fixtureGlb();
    await sceneAssets.load({name:'fixture.glb',size:glbData.byteLength,arrayBuffer:async()=>glbData});
    const imported=sceneAssets.model;
    assert(imported && scenePhysics.colliders.includes(imported) && scenePhysics.colliders.length===4 && !$('scene-asset-controls').hidden, 'actual GLB parsing adds a collidable object to the existing scene');
    const importedBounds=new THREE.Box3().setFromObject(imported);
    assert(Math.abs(importedBounds.min.y+.0125)<1e-5 && Math.abs(importedBounds.getSize(new THREE.Vector3()).y-1.2)<1e-5, 'imported model is normalized and placed on shared floor');
    focusSceneObject(); camera.updateMatrixWorld(true);
    const focusCenter=importedBounds.getCenter(new THREE.Vector3());
    assert(controls.target.distanceTo(focusCenter)<1e-6 && $('scene-view').value==='custom' && !followPose && avatar.root===preservedAvatar, 'view selected object frames its center without replacing shared avatar');
    const projectedCorners=[];
    for(const x of [importedBounds.min.x,importedBounds.max.x]) for(const y of [importedBounds.min.y,importedBounds.max.y]) for(const z of [importedBounds.min.z,importedBounds.max.z]) projectedCorners.push(new THREE.Vector3(x,y,z).project(camera));
    assert(projectedCorners.every(point=>Math.abs(point.x)<1 && Math.abs(point.y)<1), 'object camera fit keeps complete model within viewport');
    sceneAssets.place(-1.5,.8);
    sceneAssets.reshape(1.5,90);
    const rotatedAssetBounds=new THREE.Box3().setFromObject(imported);
    assert(Math.abs(rotatedAssetBounds.getSize(new THREE.Vector3()).z-1.8)<1e-5 && Math.abs(rotatedAssetBounds.min.y+.0125)<1e-5,
      'scene object scale and rotation preserve ground contact and update world bounds');
    assert($('scene-asset-scale').value==='1.5' && $('scene-asset-yaw').value==='90' && scenePhysics.colliders.includes(imported), 'scene transform controls stay synchronized with registered collider');
    sceneAssets.reshape(NaN,0);
    assert(imported.scale.x===1.5, 'invalid scene transform cannot corrupt model');
    sceneAssets.resetPlacement();
    assert(imported.scale.x===1 && imported.rotation.y===0 && imported.position.x===1.6 && $('scene-asset-x').value==='1.6', 'reset placement restores position scale and rotation together');
    sceneAssets.place(-1.5,.8);
    assert(imported.position.x===-1.5 && imported.position.z===.8 && avatar.root===preservedAvatar && location.href===applicationUrl, 'scene placement preserves body identity and application URL');
    const importedBodyRoot=new THREE.Group(); importedBodyRoot.position.set(-1.5,.6,.8); scene.add(importedBodyRoot);
    const importedBodyGeometry=new THREE.BoxGeometry(.4,1,.4);
    sceneAssets.reshape(1.5,90);
    scenePhysics.constrain(importedBodyRoot,importedBodyGeometry);
    const importBodyBounds=importedBodyGeometry.boundingBox.clone().applyMatrix4(importedBodyRoot.matrixWorld);
    assert(!importBodyBounds.intersectsBox(new THREE.Box3().setFromObject(imported)), 'rotated scaled GLB participates in actual body collision constraints');
    scenePhysics.reset(importedBodyRoot); importedBodyRoot.position.set(-.5,.6,.8);
    scenePhysics.constrain(importedBodyRoot,importedBodyGeometry);
    importedBodyRoot.position.x=-2.5; scenePhysics.constrain(importedBodyRoot,importedBodyGeometry);
    assert(importedBodyRoot.position.x>-1.301 && scenePhysics.stats.sweptContacts>0, 'continuous sweep blocks fast traversal through rotated imported model');
    scenePhysics.reset(importedBodyRoot); importedBodyRoot.position.set(-.5,3,.8);
    scenePhysics.constrain(importedBodyRoot,importedBodyGeometry);
    importedBodyRoot.position.x=-2.5; scenePhysics.constrain(importedBodyRoot,importedBodyGeometry);
    assert(importedBodyRoot.position.x===-2.5 && scenePhysics.stats.sweptContacts===0, 'continuous collision does not block movement above an obstacle');
    sceneAssets.setFlags(true,false); scenePhysics.reset(importedBodyRoot); importedBodyRoot.position.set(-1.5,.6,.8);
    scenePhysics.constrain(importedBodyRoot,importedBodyGeometry);
    assert(imported.visible && importedBodyRoot.position.x===-1.5 && importedBodyRoot.position.z===.8, 'decorative scene object stays visible without blocking body');
    sceneAssets.setFlags(false,true);
    const cameraBeforeHiddenFocus=camera.position.clone(); focusSceneObject();
    assert(camera.position.distanceTo(cameraBeforeHiddenFocus)<1e-6 && $('scene-asset-status').textContent.includes('請先勾選「顯示」'), 'view hidden object explains visibility without moving camera');
    const hiddenObjectCenter=new THREE.Box3().setFromObject(imported).getCenter(new THREE.Vector3());
    scenePhysics.setDebug(true); scenePhysics.updateDebug(importedBodyRoot,importedBodyGeometry);
    const importedHelper=scenePhysics.debugGroup.children.find(helper=>helper.userData.collider===imported);
    assert(!imported.visible && !scenePhysics.pointBlocked(hiddenObjectCenter,.07) && !importedHelper.visible, 'hidden scene object does not block targets or display collision helper');
    sceneAssets.setFlags(true,true); scenePhysics.setDebug(false);
    assert($('scene-asset-visible').checked && $('scene-asset-solid').checked && scenePhysics.pointBlocked(hiddenObjectCenter,.07), 'reenabling scene object restores collision and synchronized controls');
    scene.remove(importedBodyRoot); importedBodyGeometry.dispose();
    await sceneAssets.load({name:'bad.glb',size:glbData.byteLength,arrayBuffer:async()=>fixtureGlb(true)});
    assert(sceneAssets.model===imported && $('scene-asset-status').textContent.includes('self-contained'), 'external asset references are rejected while preserving current scene object');
    await sceneAssets.load({name:'second.glb',size:glbData.byteLength,arrayBuffer:async()=>glbData});
    const secondImported=sceneAssets.model;
    assert(secondImported!==imported && sceneAssets.models.length===2 && scenePhysics.colliders.includes(imported) && scenePhysics.colliders.length===5, 'adding a scene model preserves existing models and colliders');
    const pickCenter=new THREE.Box3().setFromObject(imported).getCenter(new THREE.Vector3());
    const modelRay=new THREE.Raycaster(pickCenter.clone().add(new THREE.Vector3(3,0,0)),new THREE.Vector3(-1,0,0));
    assert(sceneAssets.pick(modelRay) && sceneAssets.model===imported, 'scene ray picking selects actual rotated imported mesh');
    const selectionFrame=scene.getObjectByName('scene-object-selection');
    $('scene-assets').open=true; sceneAssets.refreshSelectionFrame();
    assert(selectionFrame.visible && selectionFrame.object===imported, 'expanded scene editor shows frame around selected object');
    $('scene-assets').open=false; sceneAssets.refreshSelectionFrame();
    assert(!selectionFrame.visible, 'closing scene editor hides selection frame');
    sceneAssets.setFlags(false,true);
    assert(!sceneAssets.pick(modelRay), 'scene picking ignores hidden imported meshes');
    sceneAssets.setFlags(true,true);
    $('scene-asset-selection').value=String(imported.userData.assetId); $('scene-asset-selection').dispatchEvent(new Event('change'));
    sceneAssets.place(-1,.5);
    assert(sceneAssets.model===imported && imported.position.x===-1 && secondImported.position.x===1.6 && $('scene-asset-scale').value==='1.5', 'object selection restores controls and edits only selected model');
    const priorName=imported.userData.assetName;
    const groundObjectCenter=new THREE.Box3().setFromObject(imported).getCenter(new THREE.Vector3());
    sceneAssets.elevate(1.2);
    assert(imported.position.y===1.1875 && $('scene-asset-height').value==='1.2' && sceneAssets.snapshot()[0].height===1.2, 'height control elevates selected model and updates snapshot');
    assert(!scenePhysics.pointBlocked(groundObjectCenter,.03) && scenePhysics.pointBlocked(groundObjectCenter.clone().add(new THREE.Vector3(0,1.2,0)),.03), 'elevated model collider moves with mesh and leaves previous height clear');
    assert(sceneAssets.undo() && imported.position.y===-.0125 && sceneAssets.redo() && imported.position.y===1.1875, 'object height participates in undo and redo');
    sceneAssets.elevate(Infinity);
    assert(imported.position.y===1.1875, 'invalid height preserves current transform');
    sceneAssets.elevate(9); assert(imported.position.y===2.4875, 'object height clamps to supported scene range');
    sceneAssets.elevate(0);
    $('scene-assets').open=true; $('scene-move-tool').checked=true; syncSceneMoveTool();
    assert(sceneMoveTool.object===imported && sceneMoveTool.visible && sceneMoveTool.parent===scene, 'move tool attaches selected model inside shared scene');
    const editorKey=(key,options={})=>{const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,...options});document.dispatchEvent(event);return event;};
    assert(editorKey('e').defaultPrevented && sceneMoveTool.mode==='rotate' && $('scene-tool-mode').value==='rotate','E shortcut switches scene tool and dropdown');
    assert(editorKey('r').defaultPrevented && sceneMoveTool.mode==='scale','R shortcut selects scale');
    editorKey('w');
    const inputShortcut=new KeyboardEvent('keydown',{key:'e',bubbles:true,cancelable:true}); $('scene-asset-name').dispatchEvent(inputShortcut);
    assert(!inputShortcut.defaultPrevented && sceneMoveTool.mode==='translate','scene shortcut preserves editing in text input');
    editorKey('e',{repeat:true}); editorKey('r',{isComposing:true});
    assert(sceneMoveTool.mode==='translate','repeated and composing keys do not change scene tool');
    const keyboardX=imported.position.x;
    sceneAssets.place(keyboardX+.1,imported.position.z);
    assert(editorKey('z',{ctrlKey:true}).defaultPrevented && Math.abs(imported.position.x-keyboardX)<1e-6,'Ctrl Z undoes selected object edit');
    assert(editorKey('z',{ctrlKey:true,shiftKey:true}).defaultPrevented && Math.abs(imported.position.x-keyboardX-.1)<1e-6,'Ctrl Shift Z redoes selected object edit');
    sceneAssets.undo();
    sceneMoveTool.dispatchEvent({type:'mouseDown'}); sceneMoveTool.dragging=true;
    const moveStart=imported.position.clone();
    imported.position.set(-.7,.4875,.8); sceneMoveTool.dispatchEvent({type:'objectChange'});
    imported.position.set(-.6,.5875,.9); sceneMoveTool.dispatchEvent({type:'objectChange'});
    sceneMoveTool.dispatchEvent({type:'mouseUp'}); sceneMoveTool.dragging=false;
    assert(!followPose && controls.enabled && sceneAssets.undo() && imported.position.distanceTo(moveStart)<1e-6, 'entire scene drag is one undoable transform and orbit resumes after drag');
    assert(sceneAssets.redo() && imported.position.x===-.6 && imported.position.y===.5875 && imported.position.z===.9, 'drag redo restores all three axes');
    sceneAssets.undo();
    $('scene-tool-mode').value='rotate'; $('scene-tool-mode').dispatchEvent(new Event('change'));
    assert(sceneMoveTool.mode==='rotate' && !sceneMoveTool.showX && sceneMoveTool.showY && !sceneMoveTool.showZ,'rotation tool exposes only horizontal rotation');
    const snapBefore=imported.position.clone(),snapBeforeYaw=imported.rotation.y;
    $('scene-tool-snap').checked=true; $('scene-tool-snap').dispatchEvent(new Event('change'));
    assert(sceneMoveTool.translationSnap===.1 && Math.abs(sceneMoveTool.rotationSnap-Math.PI/12)<1e-9,'scene snap configures ten-centimeter movement and fifteen-degree rotation');
    assert(imported.position.equals(snapBefore) && imported.rotation.y===snapBeforeYaw,'enabling snapping preserves current object transform');
    $('scene-tool-snap').checked=false; $('scene-tool-snap').dispatchEvent(new Event('change'));
    assert(sceneMoveTool.translationSnap===null && sceneMoveTool.rotationSnap===null,'disabling snapping restores free movement and rotation');
    const rotateBefore=imported.rotation.y;
    sceneMoveTool.dispatchEvent({type:'mouseDown'}); sceneMoveTool.dragging=true;
    imported.quaternion.setFromAxisAngle(new THREE.Vector3(0,1,0),THREE.MathUtils.degToRad(120));
    sceneMoveTool.dispatchEvent({type:'objectChange'});
    imported.quaternion.setFromAxisAngle(new THREE.Vector3(0,1,0),THREE.MathUtils.degToRad(200));
    sceneMoveTool.dispatchEvent({type:'objectChange'});
    sceneMoveTool.dispatchEvent({type:'mouseUp'}); sceneMoveTool.dragging=false;
    assert(Math.abs(THREE.MathUtils.radToDeg(imported.rotation.y)+160)<1e-6 && imported.rotation.x===0 && imported.rotation.z===0,'rotation drag normalizes yaw past 180 degrees without tilting');
    assert(sceneAssets.snapshot()[0].yaw>=-180 && sceneAssets.snapshot()[0].yaw<=180 && $('scene-asset-yaw').value==='-160','rotation drag stays compatible with saved scene and slider');
    assert(sceneAssets.undo() && Math.abs(imported.rotation.y-rotateBefore)<1e-6 && sceneAssets.redo() && Math.abs(THREE.MathUtils.radToDeg(imported.rotation.y)+160)<1e-6,'entire rotation drag is one undoable edit');
    sceneAssets.undo();
    $('scene-tool-mode').value='translate'; $('scene-tool-mode').dispatchEvent(new Event('change'));
    assert(sceneMoveTool.mode==='translate' && sceneMoveTool.showX && sceneMoveTool.showZ && controls.enabled,'switching back restores movement axes and orbit controls');
    $('scene-tool-mode').value='scale'; $('scene-tool-mode').dispatchEvent(new Event('change'));
    const scaleBefore=imported.scale.x;
    sceneMoveTool.dispatchEvent({type:'mouseDown'}); sceneMoveTool.dragging=true; sceneMoveTool.axis='Y';
    imported.scale.y=1.75; sceneMoveTool.dispatchEvent({type:'objectChange'});
    assert(imported.scale.x===1.75 && imported.scale.z===1.75 && $('scene-asset-scale').value==='1.75','scale drag preserves proportions and synchronizes slider');
    imported.scale.y=5; sceneMoveTool.dispatchEvent({type:'objectChange'});
    assert(imported.scale.x===2 && imported.scale.y===2 && imported.scale.z===2,'scale drag clamps all axes to supported size');
    sceneMoveTool.dispatchEvent({type:'mouseUp'}); sceneMoveTool.dragging=false;
    assert(sceneAssets.undo() && imported.scale.x===scaleBefore && sceneAssets.redo() && imported.scale.x===2,'entire scale drag has one undo and redo');
    sceneAssets.undo();
    setSceneToolSnap(true); assert(sceneMoveTool.scaleSnap===.05,'scale snap uses supported five-hundredths step'); setSceneToolSnap(false);
    $('scene-tool-mode').value='translate'; $('scene-tool-mode').dispatchEvent(new Event('change'));
    sceneAssets.beginMove(); imported.position.set(9,9,-9); sceneAssets.updateMove(); sceneAssets.endMove();
    assert(imported.position.x===2 && imported.position.y===2.4875 && imported.position.z===-2, 'scene drag clamps model to supported placement bounds');
    sceneAssets.undo(); $('scene-move-tool').checked=false; syncSceneMoveTool(); $('scene-assets').open=false;
    assert(!sceneMoveTool.visible && !sceneMoveTool.object, 'disabled move tool detaches cleanly without extra scene');
    const closedMode=sceneMoveTool.mode;
    assert(!editorKey('e').defaultPrevented && sceneMoveTool.mode===closedMode,'closed scene editor does not intercept tool shortcuts');
    $('scene-assets').open=true; $('scene-move-tool').checked=true; syncSceneMoveTool();
    sceneMoveTool.dispatchEvent({type:'mouseDown'}); sceneMoveTool.dragging=true;
    $('scene-assets').open=false; syncSceneMoveTool();
    assert(!sceneMoveTool.dragging && !sceneMoveTool.object && controls.enabled, 'closing editor during drag ends movement and restores orbit controls');
    $('scene-move-tool').checked=false;
    sceneAssets.rename('Undo test'); sceneAssets.setFlags(false,false);
    assert(sceneAssets.undo() && imported.visible && imported.userData.collisionEnabled && imported.userData.assetName==='Undo test', 'undo restores collision and visibility independently from earlier rename');
    assert(sceneAssets.undo() && imported.userData.assetName===priorName && sceneAssets.redo() && imported.userData.assetName==='Undo test', 'name edits undo and redo synchronize object identity');
    sceneAssets.rename(priorName);
    assert(!sceneAssets.redo() && $('scene-asset-redo').disabled, 'new edit discards obsolete redo branch');
    const priorYaw=imported.rotation.y;
    sceneAssets.resetPlacement();
    assert(sceneAssets.undo() && imported.position.x===-1 && imported.position.z===.5 && imported.scale.x===1.5 && imported.rotation.y===priorYaw, 'reset placement undoes as one complete transform');
    sceneAssets.select(secondImported.userData.assetId);
    assert(!sceneAssets.undo() && $('scene-asset-undo').disabled && secondImported.position.x===1.6, 'new model has separate empty edit history');
    sceneAssets.select(imported.userData.assetId);
    sceneAssets.setFlags(false,false);
    assert(await sceneAssets.duplicate(), 'selected scene object can be duplicated');
    const duplicateImported=sceneAssets.model;
    assert(duplicateImported!==imported && sceneAssets.models.length===3 && duplicateImported.position.x===-.5 && duplicateImported.scale.x===1.5 && duplicateImported.rotation.y===imported.rotation.y && !duplicateImported.visible && duplicateImported.userData.collisionEnabled===false, 'duplicate preserves transform and flags with an offset and separate identity');
    let sourceGeometry,duplicateGeometry;
    imported.traverse(node=>{if(node.isMesh)sourceGeometry=node.geometry;});
    duplicateImported.traverse(node=>{if(node.isMesh)duplicateGeometry=node.geometry;});
    assert(sourceGeometry!==duplicateGeometry && scenePhysics.colliders.includes(duplicateImported), 'duplicate owns independent mesh resources and collider');
    sceneAssets.clear(); sceneAssets.select(imported.userData.assetId); sceneAssets.setFlags(true,true);
    const pendingDuplicate=sceneAssets.duplicate(); sceneAssets.place(-.9,.5);
    assert(!await pendingDuplicate && sceneAssets.models.length===2 && sceneAssets.model===imported && imported.position.x===-.9, 'editing during duplication cancels late copy and preserves latest scene');
    sceneAssets.select(secondImported.userData.assetId); sceneAssets.clear();
    assert(sceneAssets.model===imported && sceneAssets.models.length===1 && !scenePhysics.colliders.includes(secondImported) && scenePhysics.colliders.includes(imported), 'removing selected model preserves other scene models');
    sceneAssets.clear();
    assert(!sceneAssets.model && !scenePhysics.colliders.includes(imported) && scenePhysics.colliders.length===3 && $('scene-asset-controls').hidden, 'removing imported scene object releases collider and restores controls');
    let finishRead;
    const pendingImport=sceneAssets.load({name:'late.glb',size:glbData.byteLength,arrayBuffer:()=>new Promise(resolve=>finishRead=resolve)});
    sceneAssets.clear(); finishRead(glbData); await pendingImport;
    assert(!sceneAssets.model && scenePhysics.colliders.length===3, 'clearing scene cancels a pending import without a late model appearing');
    const originalFetch=window.fetch; let libraryFetches=0;
    window.fetch=async url=>{libraryFetches++;assert(url==='assets/lantern/Lantern.glb','scene library fetch uses bundled asset URL');return {ok:true,arrayBuffer:async()=>glbData};};
    await sceneAssets.loadBuiltin('lantern');
    assert(sceneAssets.models.length===1 && sceneAssets.model.userData.assetName==='木燈籠' && scenePhysics.colliders.includes(sceneAssets.model), 'scene library loads through existing editable model and collider pipeline');
    await sceneAssets.loadBuiltin('unknown');
    assert(libraryFetches===1 && sceneAssets.models.length===1, 'scene library rejects unlisted model without fetching or changing scene');
    window.fetch=async()=>({ok:false}); await sceneAssets.loadBuiltin('robot');
    assert(sceneAssets.models.length===1 && $('scene-asset-status').textContent.includes('無法載入'), 'failed library asset request preserves current scene');
    let finishLibraryFetch;
    window.fetch=()=>new Promise(resolve=>finishLibraryFetch=resolve);
    const pendingLibrary=sceneAssets.loadBuiltin('robot'); sceneAssets.clearAll();
    finishLibraryFetch({ok:true,arrayBuffer:async()=>glbData}); await pendingLibrary;
    assert(sceneAssets.models.length===0, 'clearing scene cancels delayed library request without late model appearing');
    window.fetch=originalFetch;
    for(let i=0;i<8;i++) await sceneAssets.load({name:`object-${i}.glb`,size:glbData.byteLength,arrayBuffer:async()=>glbData});
    let overflowRead=false;
    await sceneAssets.load({name:'overflow.glb',size:glbData.byteLength,arrayBuffer:async()=>{overflowRead=true;return glbData;}});
    assert(sceneAssets.models.length===8 && !overflowRead && $('scene-asset-status').textContent.includes('最多 8 個'), 'scene capacity rejects excess models before allocating asset buffers');
    let capacityFetch=false; window.fetch=async()=>{capacityFetch=true;return {ok:true,arrayBuffer:async()=>glbData};};
    await sceneAssets.loadBuiltin('lantern'); window.fetch=originalFetch;
    assert(!capacityFetch && sceneAssets.models.length===8, 'scene library honors object capacity before downloading model');
    assert(!await sceneAssets.duplicate() && sceneAssets.models.length===8, 'duplication respects scene capacity without changing existing models');
    sceneAssets.place(-.8,.4); sceneAssets.reshape(1.25,35);
    $('scene-asset-name').value='  Training pillar  '; $('scene-asset-name').dispatchEvent(new Event('change'));
    assert(sceneAssets.model.userData.assetName==='Training pillar' && $('scene-asset-selection').selectedOptions[0].textContent==='Training pillar', 'renaming object updates selection without changing collider identity');
    sceneAssets.rename('   ');
    assert(sceneAssets.model.userData.assetName==='Training pillar', 'empty object name preserves current name');
    sceneAssets.setFlags(false,false);
    sceneAssets.elevate(.75);
    const savedSceneEntries=sceneAssets.snapshot();
    assert(savedSceneEntries.length===8 && savedSceneEntries[7].data===glbData, 'scene snapshot retains actual GLB buffers and placements');
    const portableScene=await sceneStorage.packageScene().arrayBuffer();
    const portableEntries=sceneStorage.unpackScene(portableScene);
    assert(portableEntries.length===8 && portableEntries[7].name==='Training pillar' && portableEntries[7].height===.75 && portableEntries[7].scale===1.25 && !portableEntries[7].visible && !portableEntries[7].solid && new Uint8Array(portableEntries[7].data).every((byte,index)=>byte===new Uint8Array(glbData)[index]), 'portable scene roundtrip retains embedded GLB bytes and all object settings');
    HTMLAnchorElement.prototype.click=function(){download={name:this.download,url:this.href};};
    const sceneExported=sceneStorage.exportFile(); HTMLAnchorElement.prototype.click=originalClick;
    assert(sceneExported && download.name==='aetherpose.aetherscene' && download.url.startsWith('blob:'), 'scene export downloads a portable scene file');
    const invalidPortable=portableScene.slice(0); new DataView(invalidPortable).setUint32(4,2,true);
    assert(!await sceneStorage.importFile({size:invalidPortable.byteLength,arrayBuffer:async()=>invalidPortable}) && sceneAssets.models.length===8, 'unsupported scene file preserves current objects');
    let finishSceneRead;
    const pendingSceneImport=sceneStorage.importFile({size:portableScene.byteLength,arrayBuffer:()=>new Promise(resolve=>finishSceneRead=resolve)});
    sceneAssets.place(-.7,.4); finishSceneRead(portableScene);
    assert(!await pendingSceneImport && sceneAssets.model.position.x===-.7, 'scene file import cancels when user edits while reading');
    sceneAssets.place(-.8,.4);
    sceneAssets.clearAll();
    assert(sceneAssets.models.length===0 && scenePhysics.colliders.length===3 && $('scene-asset-selection').disabled && scenePhysics.debugGroup.children.length===5, 'clear all removes models colliders and imported diagnostic helpers');
    assert(await sceneAssets.restore(savedSceneEntries), 'saved scene reloads its retained GLB buffers');
    assert(sceneAssets.models.length===8 && scenePhysics.colliders.length===11 && sceneAssets.model.position.x===-.8 && sceneAssets.model.scale.x===1.25 && Math.abs(THREE.MathUtils.radToDeg(sceneAssets.model.rotation.y)-35)<1e-5, 'restored scene retains every model placement and collider');
    assert(!sceneAssets.model.visible && sceneAssets.model.userData.collisionEnabled===false && !$('scene-asset-solid').checked, 'saved scene restores object visibility and collision state');
    assert(sceneAssets.model.userData.assetName==='Training pillar' && $('scene-asset-name').value==='Training pillar', 'scene restore preserves custom object names');
    assert(sceneAssets.model.position.y===.7375 && $('scene-asset-height').value==='0.75', 'scene restore retains model height and synchronized editor control');
    const retainedScene=sceneAssets.model;
    const brokenScene=sceneAssets.snapshot(); brokenScene[1]={...brokenScene[1],x:99};
    assert(!await sceneAssets.restore(brokenScene) && sceneAssets.model===retainedScene && sceneAssets.models.length===8, 'invalid restore preserves current scene after disposing staged assets');
    const pendingSceneRestore=sceneAssets.restore(savedSceneEntries);
    sceneAssets.place(.3,-.5);
    assert(!await pendingSceneRestore && sceneAssets.model===retainedScene && retainedScene.position.x===.3 && scenePhysics.colliders.length===11, 'scene edit cancels pending restore and preserves latest placement');
    assert(await sceneStorage.importFile({size:portableScene.byteLength,arrayBuffer:async()=>portableScene}) && sceneAssets.models.length===8 && sceneAssets.model.position.x===-.8 && sceneAssets.model.userData.assetName==='Training pillar', 'valid portable scene atomically replaces current objects and restores placement');
    const truncatedPortable=portableScene.slice(0,portableScene.byteLength-1);
    assert(!await sceneStorage.importFile({size:truncatedPortable.byteLength,arrayBuffer:async()=>truncatedPortable}) && sceneAssets.models.length===8, 'truncated scene file cannot partially replace scene');
    const invalidHeightScene=sceneAssets.snapshot(); invalidHeightScene[0].height=-1;
    const heightRetainedModel=sceneAssets.model;
    assert(!await sceneAssets.restore(invalidHeightScene) && sceneAssets.model===heightRetainedModel, 'invalid saved height preserves current scene');
    const legacyHeightScene=sceneAssets.snapshot(); for(const entry of legacyHeightScene)delete entry.height;
    assert(await sceneAssets.restore(legacyHeightScene) && sceneAssets.models.every(object=>object.position.y===-.0125), 'legacy scene without heights restores models on floor');
    packet({status:'Streaming #20 DEBUG mask=test live 0/6',joints:joints(),joints_version:120});
    selectTab('cal'); $('game-mode').value='cross'; changePoseGame(); startGame();
    sceneAssets.rename('Round edit check'); sceneAssets.select(sceneAssets.model.userData.assetId); sceneAssets.elevate(0);
    assert(game.state==='playing', 'selection rename and unchanged transform preserve active pose round');
    sceneAssets.elevate(.5);
    assert(game.state==='over' && $('game-result').textContent.includes('場景改變') && roundHistory.some(entry=>entry.mode==='cross' && !entry.completed && entry.reason.includes('Scene changed')), 'physical scene edit stops pose game and records unfinished round');
    selectTab('combat'); $('start-btn').click();
    sceneAssets.elevate(.75);
    assert($('start-btn').textContent==='開始回合' && $('event-feed').textContent.includes('場景改變') && roundHistory.some(entry=>entry.mode==='combat' && !entry.completed && entry.reason.includes('Scene changed')), 'physical scene edit stops combat before edited collision can affect scoring');
    selectTab('cal'); $('game-mode').value='reach'; changePoseGame();
    $('game-mode').value='cross'; changePoseGame(); startGame();
    $('scene-collisions').checked=false; $('scene-collisions').dispatchEvent(new Event('change'));
    assert(game.state==='over' && !scenePhysics.stats.enabled, 'changing collision enforcement stops active round');
    $('scene-collisions').checked=true; $('scene-collisions').dispatchEvent(new Event('change'));
    $('game-mode').value='reach'; changePoseGame();
    sceneAssets.clearAll();
    const packetAvatar=createAetherAvatar(scene); packetAvatar.setMode(true); packetAvatar.setPhysics(scenePhysics);
    packetAvatar.onFaces([[0,1,2]]);
    packetAvatar.onVertsFlat(Float32Array.from([0,-2,0, .1,-1.9,0, 0,-1.8,.1]));
    const rawPacketJoints=joints(); packetAvatar.onJoints(rawPacketJoints);
    const packetBody=packetAvatar.root.getObjectByName('aether-body');
    const packetBodyBounds=packetBody.geometry.boundingBox.clone().applyMatrix4(packetAvatar.root.matrixWorld);
    assert(packetBodyBounds.min.y>=-.00751 && packetAvatar.root.position.y>.97*.96, 'incoming pose is collision constrained before next animation frame');
    const packetHandWorld=packetAvatar.root.localToWorld(new THREE.Vector3(...packetAvatar.joints[22]));
    assert(packetHandWorld.y>rawPacketJoints[22][1]+.97*.96 && packetAvatar.joints[22][1]===rawPacketJoints[22][1], 'gameplay world joints share collision correction without altering raw tracked pose');
    const packetCorrectedPosition=packetAvatar.root.position.clone();
    packetAvatar.tick(.016,performance.now()/1000);
    assert(packetAvatar.root.position.distanceTo(packetCorrectedPosition)<1e-6, 'frame update preserves packet-time collision corrected position');
    packetAvatar.disconnect(); scene.remove(packetAvatar.root);
    packetAvatar.root.traverse(object=>{ if(object.geometry)object.geometry.dispose(); if(object.material)object.material.dispose(); });
    assert(scenePhysics.pointBlocked(new THREE.Vector3(0,1,-2.6),.07) && !scenePhysics.pointBlocked(new THREE.Vector3(0,1,1),.07), 'target clearance distinguishes wall interior from open space');
    assert(scenePhysics.segmentBlocked(new THREE.Vector3(0,1,-2),new THREE.Vector3(0,1,-3)) && !scenePhysics.segmentBlocked(new THREE.Vector3(0,1,0),new THREE.Vector3(0,1,1)), 'attack segment clearance blocks walls and permits open attack paths');
    packet({runtime:{device:'cuda:0',pose_fps:30,frame_ms:8.5,mesh_ms:4.2}});
    assert($('pose-performance').textContent.includes('CUDA:0') && $('pose-performance').textContent.includes('每秒 30.0 個姿態'), 'pose performance displays actual device and update rate from bridge');
    const validPerformance=$('pose-performance').textContent;
    packet({runtime:{device:'cpu',pose_fps:-1,frame_ms:0,mesh_ms:0}});
    assert($('pose-performance').textContent===validPerformance, 'invalid runtime metrics cannot replace valid performance display');
    assert(!$('pose-performance').style.color && getComputedStyle($('pose-performance')).display==='none', 'a normal pose rate is not flagged and its numbers stay out of the way');
    packet({runtime:{device:'cpu',pose_fps:8.4,frame_ms:104,mesh_ms:6.8}});
    assert($('pose-performance').style.color==='var(--amber)' && $('pose-performance').title.includes('動作判定可能不準') &&
      getComputedStyle($('pose-performance')).display!=='none', 'a slow pose rate is flagged and shown');
    assert($('pose-performance').textContent==='姿態更新偏慢：每秒 8.4 個姿態', 'a slow pose rate is reported in words, without timings');
    packet({runtime:{device:'cuda:0',pose_fps:30,frame_ms:8.5,mesh_ms:4.2}});
    packet({runtime:{device:'cpu',pose_fps:30,frame_ms:30,dropped_input_frames:100}});
    assert(!$('pose-performance').classList.contains('slow'), 'historical input drops on first connection do not claim a current overload');
    packet({runtime:{device:'cpu',pose_fps:30,frame_ms:30,dropped_input_frames:101}});
    assert($('pose-performance').classList.contains('slow') && $('pose-performance').textContent.includes('部分動作更新已略過') &&
      getComputedStyle($('pose-performance')).display!=='none', 'new input drops remain visible even when the latest output rate is normal');
    packet({runtime:{device:'cpu',pose_fps:30,frame_ms:30,dropped_input_frames:0}});
    assert(!$('pose-performance').classList.contains('slow'), 'service counter reset clears the old overload warning');
    selectTab('cal'); packet({status:'Streaming #99 DEBUG mask=test live 0/6',joints:joints(),joints_version:99});
    const reachCenter=avatar.root.localToWorld(new THREE.Vector3(avatar.joints[0][0],avatar.joints[0][1]+.28,avatar.joints[0][2]));
    const reachBlocker=new THREE.Mesh(new THREE.BoxGeometry(.3,.3,.3)); reachBlocker.position.copy(reachCenter);
    scene.add(reachBlocker); scenePhysics.addCollider(reachBlocker);
    const originalRandom=Math.random; Math.random=()=>.5;
    const clearSpawn=spawnTargetPos();
    assert(clearSpawn && !scenePhysics.pointBlocked(clearSpawn,.07) && Math.abs(clearSpawn.x-reachCenter.x)<=TARGET_SPAN.x+1e-6 && Math.abs(clearSpawn.y-reachCenter.y)<=TARGET_SPAN.y+1e-6, 'bounded target fallback avoids scene obstacle without moving beyond reach volume');
    reachBlocker.geometry.dispose(); reachBlocker.geometry=new THREE.BoxGeometry(3,3,3); scenePhysics.resetAll();
    assert(spawnTargetPos()===null, 'fully blocked reach volume returns no unreachable target');
    $('game-mode').value='reach'; changePoseGame(); startGame();
    assert(game.state==='over' && targetMeshes.every(target=>!target.visible) && $('game-result').textContent.includes('伸手範圍被擋住'), 'blocked scene ends reach startup with visible explanation and no hidden target');
    Math.random=originalRandom; scenePhysics.removeCollider(reachBlocker); scene.remove(reachBlocker);
    reachBlocker.geometry.dispose(); reachBlocker.material.dispose();
    const previousHistory=roundHistory; roundHistory=[];
    recordRoundHistory({mode:'star',score:9,source:'live:6',completed:true,reason:'Time expired',seconds:60});
    recordRoundHistory({mode:'star',score:2,source:'demo:0',completed:false,reason:'Round ended',seconds:3});
    const combatRecords=poseRecords; poseRecords={};
    finishCombatRound({mode:'combat',score:4,source:'mixed:2',completed:true,reason:'Enemy down.',seconds:12});
    assert(poseRecords['combat:mixed:2']===4 && $('game-result').textContent.includes('最佳 4') && $('game-result').textContent.includes('新紀錄') &&
      document.querySelector('[data-game-choice="combat"] .game-card-best').textContent==='',
      'a finished Combat round keeps its best per input source and says so on the results card');
    finishCombatRound({mode:'combat',score:9,source:'mixed:2',completed:false,reason:'Round stopped.',seconds:3});
    assert(poseRecords['combat:mixed:2']===4 && !$('game-result').textContent.includes('最佳'), 'an unfinished Combat round does not set a best');
    const difficultyBestHistory=roundHistory.slice();
    finishCombatRound({mode:'combat',score:120,source:'demo:0',completed:true,reason:'Time.',seconds:90,difficulty:'easy'});
    finishCombatRound({mode:'combat',score:30,source:'demo:0',completed:true,reason:'Time.',seconds:90,difficulty:'hard'});
    assert(combatDifficultyBest('easy','demo:0')===120 && combatDifficultyBest('hard','demo:0')===30 && $('game-result').textContent.includes('最佳 30'),'Combat best scores separate difficulty without a practice score overriding challenge');
    assert(loadCombatDifficultyRecords()['hard:demo:0']===30 && poseRecords['combat:demo:0']===120,'difficulty records persist while aggregate legacy best remains available');
    finishCombatRound({mode:'combat',score:999,source:'demo:0',completed:false,reason:'Round ended',seconds:1,difficulty:'hard'});
    assert(combatDifficultyBest('hard','demo:0')===30,'unfinished round cannot overwrite difficulty best');
    saveCombatDifficultyBest('hard','live:6',12);
    assert(combatDifficultyBest('hard','live:6')===12 && combatDifficultyBest('hard','demo:0')===30,'difficulty best scores remain separate by tracking source');
    const scoreRecordsBeforeClear={...poseRecords},difficultyRecordsBeforeClear={...combatDifficultyRecords};
    clearBestScores();
    assert(!Object.keys(combatDifficultyRecords).length && localStorage.getItem(combatDifficultyRecordKey)===null,'clearing best scores also clears per-difficulty Combat records');
    poseRecords=scoreRecordsBeforeClear; combatDifficultyRecords=difficultyRecordsBeforeClear;
    localStorage.setItem(poseRecordKey,JSON.stringify(poseRecords)); localStorage.setItem(combatDifficultyRecordKey,JSON.stringify(combatDifficultyRecords)); updateGameLibrary();
    roundHistory=difficultyBestHistory; renderRoundHistory();
    poseRecords=combatRecords; dismissRoundResult(); roundHistory.splice(0,1);  // keep the finished round the filters below expect
    $('history-mode').value='all'; $('history-source').value='all'; renderRoundHistory();
    assert($('history-matches').textContent==='', 'unfiltered history has no match count');
    $('history-mode').value='star'; $('history-source').value='live'; renderRoundHistory();
    assert($('history-list').children.length===1 && $('history-list').textContent.includes('9 分') && $('history-matches').textContent.startsWith('符合 1 場 / 共 3 場'), 'history filters combine game and actual tracking source');
    $('history-source').value='mixed'; renderRoundHistory();
    assert($('history-list').textContent.includes('沒有符合篩選條件') && roundHistory.length===3, 'empty history filter preserves stored rounds');
    $('history-mode').value='all'; renderRoundHistory();
    assert($('history-list').children.length===1 && $('history-list').textContent.includes('混合 2/6'), 'mixed source filter includes partial live tracking');
    roundHistory=previousHistory; $('history-source').value='all'; renderRoundHistory();
    localStorage.setItem(historyStorageKey,JSON.stringify(roundHistory));
    const difficultyHistory=roundHistory;
    roundHistory=[{mode:'combat',score:3,source:'demo:0',completed:true,reason:'Time.',seconds:90,at:Date.now(),difficulty:'hard'},
      {mode:'combat',score:5,source:'live:6',completed:true,reason:'Time.',seconds:90,at:Date.now(),difficulty:'normal'},
      {mode:'combat',score:2,source:'demo:0',completed:false,reason:'Round ended',seconds:8,at:Date.now()}];
    $('history-mode').value='combat'; $('history-source').value='all'; $('history-difficulty').value='hard'; renderRoundHistory();
    assert($('history-list').children.length===1 && $('history-list').textContent.includes('難度：挑戰'),'history filters combat rounds by recorded difficulty');
    $('history-source').value='live'; renderRoundHistory();
    assert($('history-list').textContent.includes('沒有符合'),'source and combat difficulty filters combine');
    $('history-source').value='all'; $('history-difficulty').value='unknown'; renderRoundHistory();
    assert($('history-list').children.length===1 && $('history-list').textContent.includes('2 分'),'unknown difficulty filter preserves legacy combat records');
    $('history-mode').value='star'; renderRoundHistory();
    assert($('history-difficulty-controls').hidden && $('history-difficulty').value==='all','Pose history clears and hides unrelated difficulty filter');
    const aggregateBase={attempts:10,hits:8,targets:6,blocked:0,defenses:2,received:1,counters:1,bestCombo:4};
    roundHistory=[{...roundHistory[0],combatStats:aggregateBase},
      {...roundHistory[1],combatStats:{...aggregateBase,attempts:2,hits:1,targets:1,counters:0,bestCombo:2}},
      {...roundHistory[2],combatStats:aggregateBase}];
    $('history-mode').value='combat'; $('history-difficulty').value='all'; renderRoundHistory();
    assert(!$('history-combat-summary').hidden && $('history-combat-summary').textContent.includes('命中 9/12（75%）'),'combat history computes weighted contact rate across completed rounds');
    assert(combatHistoryTotals(roundHistory).rounds===2 && combatHistoryTotals(roundHistory).bestCombo===4,'combat history excludes interrupted rounds and keeps maximum combo');
    $('history-difficulty').value='hard'; renderRoundHistory();
    assert($('history-combat-summary').textContent.includes('命中 8/10（80%）'),'combat totals respect recorded difficulty filter');
    $('history-source').value='live'; renderRoundHistory();
    assert($('history-combat-summary').hidden,'empty source and difficulty combination hides combat totals');
    $('history-source').value='all'; $('history-difficulty').value='all';
    roundHistory=[{...roundHistory[0],combatStats:{...aggregateBase,received:3},combatBreakdown:{received:{high:0,body:0,flank:3},defended:{high:2,body:0,flank:0}}}];
    renderRoundHistory(); const drillCamera=camera.position.clone(),drillBody=avatar.root;
    document.querySelector('[data-history-drill="dodge"]').click();
    assert(!combatMode && $('game-mode').value==='dodge' && game.state!=='playing','history coaching opens recommended Pose drill without auto-starting');
    assert(camera.position.equals(drillCamera) && avatar.root===drillBody && location.href===applicationUrl && roundHistory.length===1,'recommended drill preserves shared world and original history');
    showRoundResult({title:'Aether Combat',score:3,sourceLabel:'示範資料',reason:'Round ended',completed:false,best:null,newRecord:false,again:()=>{},details:['練習雙手防守'],practiceMode:'guard'});
    document.querySelector('[data-result-drill="guard"]').click();
    assert($('game-mode').value==='guard' && game.state!=='playing' && $('game-result').style.display==='none','results dialog practice action selects drill and clears result overlay without starting');
    roundHistory=difficultyHistory; $('history-mode').value='all'; renderRoundHistory();
    selectTab('cal'); packet({status:'Streaming #100 DEBUG mask=test live 0/6',joints:joints(),joints_version:1000});
    $('pose-circuit').value='upper'; $('circuit-start').click();
    assert(poseCircuit && game.state==='playing' && game.mode==='clap' && poseCircuit.index===0,'upper circuit starts its first pose game');
    assert(poseCircuitReport()===null && !exportPoseCircuit() && $('circuit-export').hidden && $('circuit-hud-export').hidden,'unfinished circuit cannot export a completed report');
    endGame('Round ended');
    assert(poseCircuit.results.length===0 && !poseCircuit.waiting && poseCircuit.index===0,'interrupted circuit round does not advance or count as completed');
    startGame();
    const circuitCamera=camera.position.clone(),circuitBody=avatar.root;
    for (let stage=0;stage<3;stage++) {
      assert(game.mode===['clap','shoulder','highfive'][stage] && game.state==='playing','circuit stage selects correct game rules');
      game.calibrating=false; game.score=stage+1; game.deadline=performance.now(); updateReachClock(performance.now());
      assert(poseCircuit.results.length===stage+1 && poseCircuit.results[stage].score===stage+1,'circuit records each completed round once');
      endGame(); assert(poseCircuit.results.length===stage+1,'repeated end cannot duplicate circuit completion');
      if(stage<2) {
        assert(!$('circuit-next').hidden && game.state==='over','next circuit stage waits for user readiness');
        setFocusMode(true);
        assert($('circuit-hud').getClientRects().length>0 && !$('circuit-hud-next').hidden && $('circuit-hud-status').textContent.includes(poseGameNames[poseCircuit.modes[stage+1]]),'training HUD exposes next stage while panel is hidden');
        $('circuit-hud-next').click(); setFocusMode(false);
      }
    }
    assert(poseCircuit.finished && $('circuit-next').hidden && $('circuit-status').textContent.includes('訓練完成'),'last circuit round displays completion summary');
    const trainingReport=poseCircuitReport();
    assert(trainingReport.version===1 && trainingReport.completed && trainingReport.preset==='upper' && trainingReport.plan.join(',')==='clap,shoulder,highfive' && trainingReport.rounds.every((round,index)=>round.score===index+1 && round.source==='demo:0' && round.seconds===60 && round.at>=trainingReport.startedAt),'completed training report preserves per-game scores source and timestamps');
    trainingReport.rounds[0].score=999;
    assert(poseCircuit.results[0].score===1,'training report is independent of active results');
    HTMLAnchorElement.prototype.click=function(){download={name:this.download,url:this.href};};
    const trainingExported=exportPoseCircuit(); HTMLAnchorElement.prototype.click=originalClick;
    assert(trainingExported && download.name.startsWith('aetherpose-training-') && download.name.endsWith('.json') && !$('circuit-export').hidden && !$('circuit-hud-export').hidden,'completed circuit exports named JSON from panel or scene HUD');
    assert(loadLastTrainingReport()?.rounds[0].score===1 && !$('last-training-export').disabled,'completed training is saved for later export');
    assert(avatar.root===circuitBody && camera.position.equals(circuitCamera) && location.href===applicationUrl,'circuit preserves shared world camera and URL');
    $('circuit-stop').click(); assert(!poseCircuit && $('circuit-stop').hidden,'ending circuit clears training controls');
    assert($('circuit-hud').hidden,'ending training removes scene HUD');
    HTMLAnchorElement.prototype.click=function(){download={name:this.download,url:this.href};};
    const previousTrainingExport=exportLastTrainingReport(); HTMLAnchorElement.prototype.click=originalClick;
    assert(previousTrainingExport && !poseCircuit && download.name.startsWith('aetherpose-training-'),'previous report can export after leaving training');
    const persistedTraining=localStorage.getItem(lastTrainingKey);
    const invalidTraining=JSON.parse(persistedTraining); invalidTraining.rounds[0].source='bad';
    localStorage.setItem(lastTrainingKey,JSON.stringify(invalidTraining));
    assert(loadLastTrainingReport()===null,'stored training report rejects invalid tracking source');
    invalidTraining.rounds[0].source='demo:0'; invalidTraining.plan[0]='combat';
    localStorage.setItem(lastTrainingKey,JSON.stringify(invalidTraining));
    assert(loadLastTrainingReport()===null,'stored report rejects mismatched or unsupported stages');
    localStorage.setItem(lastTrainingKey,'broken'); assert(loadLastTrainingReport()===null,'corrupt training report is safely ignored');
    localStorage.setItem(lastTrainingKey,persistedTraining);
    lastTrainingReport=loadLastTrainingReport(); renderLastTrainingReport();
    assert(lastTrainingReport.rounds.length===3 && $('last-training-status').textContent.includes('Clap Pulse'),'completed report reloads independently of current training');
    $('pose-circuit').value='lower'; startPoseCircuit(); chooseGame('reach');
    assert(!poseCircuit,'choosing a different game exits circuit');
    $('pose-circuit').value='mixed'; startPoseCircuit(); selectTab('combat');
    assert(!poseCircuit && game.state!=='playing','switching to Combat exits circuit and stops pose round');
    selectTab('cal'); startPoseCircuit(); stopPoseCircuit();
    assert(game.state==='over' && !poseCircuit && roundHistory[0].reason==='Training ended','manual circuit stop records unfinished round');
    const savedCustomCircuit=localStorage.getItem(customCircuitKey);
    $('pose-circuit').value='custom'; $('pose-circuit').dispatchEvent(new Event('change'));
    assert(!$('custom-circuit-controls').hidden && [0,1,2].every(index=>$(`custom-circuit-${index}`).options.length===13),'custom circuit exposes all Pose games in three stages');
    ['star','sky','guard'].forEach((mode,index)=>{$(`custom-circuit-${index}`).value=mode;}); saveCustomCircuit();
    assert(loadCustomCircuit().join(',')==='star,sky,guard','custom circuit persists ordered game choices');
    startPoseCircuit();
    assert(game.mode==='star' && poseCircuit.modes.join(',')==='star,sky,guard','custom circuit starts selected sequence');
    $('custom-circuit-0').value='clap'; saveCustomCircuit();
    assert(poseCircuit.modes[0]==='star' && poseCircuits.custom[0]==='clap','editing custom plan does not alter active training sequence');
    stopPoseCircuit();
    localStorage.setItem(customCircuitKey,JSON.stringify(['reach','combat','sky']));
    assert(loadCustomCircuit().join(',')==='reach,squat,highfive','stored custom circuit rejects unsupported modes');
    localStorage.setItem(customCircuitKey,'broken');
    assert(loadCustomCircuit().length===3,'corrupt custom circuit falls back to usable defaults');
    if(savedCustomCircuit===null) localStorage.removeItem(customCircuitKey); else localStorage.setItem(customCircuitKey,savedCustomCircuit);
    poseCircuits.custom=loadCustomCircuit();
    $('pose-circuit').value='upper'; showCustomCircuit();
    assert($('custom-circuit-controls').hidden,'preset circuit hides custom editing controls');
    const captureCamera=camera.position.clone(),captureBody=avatar.root,captureLoop=window.testRafRequests;
    document.body.dataset.captureStage='capture';
    const scenePng=await captureSceneImage();
    document.body.dataset.captureStage='bytes';
    const pngBytes=new Uint8Array(await scenePng.arrayBuffer());
    assert(scenePng.type==='image/png' && scenePng.size>1000 && [...pngBytes.slice(0,8)].join(',')==='137,80,78,71,13,10,26,10','scene capture produces a real PNG from WebGL');
    const pngHeader=new DataView(pngBytes.buffer);
    assert(pngHeader.getUint32(16)===canvas.width && pngHeader.getUint32(20)===canvas.height,'scene PNG uses current rendered resolution');
    HTMLAnchorElement.prototype.click=function(){download={name:this.download,url:this.href};};
    const originalCaptureSceneImage=captureSceneImage; captureSceneImage=()=>Promise.resolve(scenePng);
    document.body.dataset.captureStage='export';
    const imageExported=await exportSceneImage(); HTMLAnchorElement.prototype.click=originalClick;
    captureSceneImage=originalCaptureSceneImage;
    assert(imageExported && download.name.startsWith('aetherpose-scene-') && download.name.endsWith('.png') && !$('scene-image-save').disabled && $('scene-image-status').textContent.includes('PNG'),'scene export downloads named PNG and restores button');
    assert(camera.position.equals(captureCamera) && avatar.root===captureBody && window.testRafRequests===captureLoop && document.querySelectorAll('canvas').length===1,'scene capture preserves camera body and single animation loop');
    selectTab('combat');
    const turned=pose=>pose.map(([x,y,z])=>[z,y,-x]);  // the player stands turned 90 degrees
    const bentForward=joints(); bentForward[15][2]+=.45; bentForward[12][2]+=.3;
    AetherCombat.onJoints(turned(bentForward));
    const forwardCountedAsLean=$('tag-lean').classList.contains('on');
    const leanedSideways=joints(); leanedSideways[15][0]+=.45; leanedSideways[12][0]+=.3;
    AetherCombat.onJoints(turned(leanedSideways));
    assert(!forwardCountedAsLean && $('tag-lean').classList.contains('on'),
      'a Combat side lean follows the body: bending forward while turned is not a dodge, leaning sideways is');
    selectTab('games');
    selectTab('combat'); $('reset-btn').click();
    packet({status:'Streaming #600 DEBUG mask=test live 0/6',joints:joints(),joints_version:6000}); $('start-btn').click();
    tick(.1); const raisedFoot=joints(); raisedFoot[10][1]=-.6;
    packet({joints:raisedFoot,joints_version:6001}); AetherCombat.stopRound('Round ended');
    assert(roundHistory[0].combatStats.attempts===0,'ordinary foot lifting is not counted as a kick attempt');
    const previousKickRandom=Math.random; Math.random=()=>.99;
    $('reset-btn').click(); packet({joints:joints(),joints_version:6002}); $('start-btn').click();
    const kickSetup=joints(); kickSetup[10]=[.5,-.65,-.14]; kickSetup[7]=[.3,-.7,-.14];
    tick(.4); packet({joints:kickSetup,joints_version:6003});
    const kickForward=joints(); kickForward[10]=[.85,-.5,-.14]; kickForward[7]=[.6,-.55,-.14];
    tick(.04); packet({joints:kickForward,joints_version:6004});
    assert(+$('enemy-hp-text').textContent<100,'forward raised-foot kick still damages enemy leg target');
    const kickHp=+$('enemy-hp-text').textContent;
    tick(.7); packet({joints:kickForward,joints_version:6005});
    const kickReturn=kickForward.map(point=>point.slice()); kickReturn[10][0]=.7; kickReturn[7][0]=.45;
    tick(.04); packet({joints:kickReturn,joints_version:6006});
    assert(+$('enemy-hp-text').textContent===kickHp,'retracting foot does not create a second kick');
    AetherCombat.stopRound('Round ended'); Math.random=previousKickRandom; selectTab('cal');
    const loseContext=renderer.getContext().getExtension('WEBGL_lose_context');
    selectTab('games'); dismissRoundResult(); startGame();
    loseContext.loseContext();
    await new Promise(resolve=>setTimeout(resolve,50));
    assert(game.state==='over' && $('game-result').textContent.includes('3D 畫面中斷') && $('panel-notice-text').textContent.includes('正在恢復'),
      'a lost WebGL context ends the round and says the 3D view is recovering');
    loseContext.restoreContext();
    await new Promise(resolve=>setTimeout(resolve,50));
    assert($('panel-notice-text').textContent.includes('已恢復') && !renderer.getContext().isContextLost(), 'a restored WebGL context is announced');
    dismissRoundResult(); renderer.render(scene,camera);
    $('event-feed').textContent = 'Integration checks passed: ' + checks.length;
    document.body.dataset.testResult = JSON.stringify(result);
    if (window.testScreenshotMode) {
      // Headless GPU composition can discard canvas pixels before a native
      // screenshot. Capture the rendered buffer for the static QA frame.
      const frame = new Image();
      frame.src = canvas.toDataURL();
      frame.id = canvas.id;
      canvas.replaceWith(frame);
    }
    window.testNativeRaf(() => {
      renderer.render(scene,camera);
      window.testNativeRaf(() => renderer.render(scene,camera));
    });
  } catch (e) {
    document.body.dataset.testResult = JSON.stringify({ok:false,checks,error:e.stack});
  }
})();
