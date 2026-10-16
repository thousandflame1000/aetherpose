// Aether Combat: the combat mode of the Aetherpose web UI (index.html).
// The page owns the single mesh_bridge connection and forwards its messages
// here; arena objects live in the shared scene and the page owns rendering.
window.createAetherCombat = ({ scene: sharedScene, camera, avatar, onRoundEnd=()=>{}, onRoundStart=()=>{} }) => {
  const scene = new THREE.Group();
  scene.name = 'combat-world';
  scene.visible = true;
  sharedScene.add(scene);
  const ROUND_SECONDS = 90;
  const SOURCE_GRACE_S = 1.5;  // how long a round waits for a tracker that dropped out
  const SMPL_RENDER_SCALE = 0.96;
  const SMPL_FLOOR_LIFT = 0.97;
  const SMPL_JOINT = {
    hip: 0,
    chest: 9,
    neck: 12,
    head: 15,
    leftShoulder: 16,
    rightShoulder: 17,
    leftAnkle: 7,
    rightAnkle: 8,
    leftWrist: 20,
    rightWrist: 21,
    leftFoot: 10,
    rightFoot: 11,
    leftHand: 22,
    rightHand: 23
  };

  const $ = (id) => document.getElementById(id);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const nowSec = () => performance.now() / 1000;

  const hemi = new THREE.HemisphereLight(0xf1f4fa, 0x20232b, 0.65);
  scene.add(hemi);
  // Soft fill keeps calibration readable from every orbit angle.
  scene.add(new THREE.AmbientLight(0xe9efff, 0.45));
  const key = new THREE.DirectionalLight(0xffffff, 1.0);
  key.name='arena-key-light';
  key.position.set(-1.6, 3.2, 3.5);
  key.castShadow=true;
  key.shadow.mapSize.set(1024,1024);
  key.shadow.camera.left=-3; key.shadow.camera.right=3;
  key.shadow.camera.top=3; key.shadow.camera.bottom=-3;
  key.shadow.camera.near=.1; key.shadow.camera.far=10;
  key.shadow.bias=-.0002; key.shadow.normalBias=.015;
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xa6c6ed, 0.25);
  rim.position.set(3.5, 2.1, -1.4);
  scene.add(rim);

  const arena = new THREE.Group();
  scene.add(arena);

  const floorMat = new THREE.MeshStandardMaterial({ color: 0x263241, roughness: 0.7, metalness: 0.2 });
  floorMat.color.convertSRGBToLinear();
  const floor = new THREE.Mesh(new THREE.CylinderGeometry(2.65, 2.65, 0.045, 96), floorMat);
  floor.position.y = -0.035;
  floor.receiveShadow=true;
  arena.add(floor);

  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(2.65, 0.018, 8, 128),
    new THREE.MeshBasicMaterial({ color: 0x57bcc9, transparent:true, opacity:.55 })
  );
  ring.rotation.x = Math.PI / 2;
  ring.position.y = 0.015;
  arena.add(ring);

  const grid = new THREE.GridHelper(5.1, 18, 0x344053, 0x1b2330);
  grid.name='debug-floor-grid';
  grid.visible=false;
  grid.position.y = 0.004;
  arena.add(grid);

  const playerGroup = avatar.root;
  let latestSmplJoints = null;
  let sendToBridge = null;  // set by the page; sends a JSON command to mesh_bridge
  let active = false;       // simulate/render only while the Combat tab is open
  let suspended = false;
  let physics=null;
  let sourceStatus = '';
  let calibrationPhase = 'idle';
  let poseStateOk = null;

  const enemyGroup = new THREE.Group();
  enemyGroup.name='aether-opponent';
  let botDistance = 1.1;
  enemyGroup.position.x = avatar.combatX + botDistance;
  scene.add(enemyGroup);

  function cylinderBetween(a, b, radius, color) {
    const dir = new THREE.Vector3().subVectors(b, a);
    const len = Math.max(dir.length(), 0.001);
    const geo = new THREE.CylinderGeometry(radius, radius, len, 14);
    const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.62, metalness: 0.1 });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.copy(a).addScaledVector(dir, 0.5);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
    return mesh;
  }

  function buildEnemy() {
    const dark = 0x242c37;
    const armor = 0x5a6a7f;
    enemyGroup.add(cylinderBetween(new THREE.Vector3(0, 0.55, 0), new THREE.Vector3(0, 1.24, 0), 0.17, armor));
    enemyGroup.add(cylinderBetween(new THREE.Vector3(-0.22, 1.13, 0), new THREE.Vector3(-0.48, 0.78, 0.04), 0.055, dark));
    enemyGroup.add(cylinderBetween(new THREE.Vector3(0.22, 1.13, 0), new THREE.Vector3(0.48, 0.78, 0.04), 0.055, dark));
    enemyGroup.add(cylinderBetween(new THREE.Vector3(-0.09, 0.52, 0), new THREE.Vector3(-0.28, 0.12, 0.02), 0.065, dark));
    enemyGroup.add(cylinderBetween(new THREE.Vector3(0.09, 0.52, 0), new THREE.Vector3(0.28, 0.12, 0.02), 0.065, dark));
    const head = new THREE.Mesh(
      new THREE.SphereGeometry(0.18, 24, 16),
      new THREE.MeshStandardMaterial({ color: 0x8899aa, roughness: 0.55 })
    );
    head.position.set(0, 1.48, 0);
    enemyGroup.add(head);

  }
  buildEnemy();
  const fallbackParts=enemyGroup.children.slice();
  let botMixer=null;
  let botModel=null;
  const botActions=new Map();
  let botAction=null;
  let botState='Idle', lastCheerAt=-Infinity;
  function playBotAnimation(name,duration=null) {
    botState=name;
    enemyGroup.userData.animation=name;
    const next=botActions.get(name);
    if (!next) return;
    // Repeated hits/coach events should not pin the same clip to its first frame.
    if (next===botAction && next.isRunning() && name!=='Punch') return;
    if (botModel) botModel.userData.animation=name;
    botModel.userData.animationStarts=(botModel.userData.animationStarts||0)+1;
    if (botAction) botAction.fadeOut(.15);
    next.reset().setEffectiveTimeScale(duration?next.getClip().duration/duration:1).setEffectiveWeight(1);
    next.setLoop(name==='Idle'?THREE.LoopRepeat:THREE.LoopOnce,name==='Idle'?Infinity:1);
    next.clampWhenFinished=name!=='Idle';
    next.fadeIn(.15).play(); botAction=next;
  }
  let botFrameAt=null;
  new THREE.GLTFLoader().load('assets/robot/RobotExpressive.glb',gltf=>{
    const model=gltf.scene;
    botModel=model;
    model.name='aether-opponent-model';
    const bounds=new THREE.Box3().setFromObject(model);
    const height=bounds.max.y-bounds.min.y;
    if (!Number.isFinite(height) || height<=0) return;
    const scale=1.65/height;
    model.scale.setScalar(scale);
    model.position.y=-bounds.min.y*scale;
    model.rotation.y=-.25;
    model.traverse(node=>{
      if (node.isMesh) { node.castShadow=true; node.receiveShadow=true; }
    });
    enemyGroup.add(model);
    for (const part of fallbackParts) {
      enemyGroup.remove(part);
      part.geometry.dispose(); part.material.dispose();
    }
    botMixer=new THREE.AnimationMixer(model);
    for (const clip of gltf.animations) botActions.set(clip.name,botMixer.clipAction(clip));
    botMixer.addEventListener('finished',event=>{
      if (event.action===botAction && botState!=='Death') playBotAnimation('Idle');
    });
    playBotAnimation(botState);
    model.userData.assetLoaded=true;
  },undefined,()=>{
    // The functional fallback remains available if local asset loading fails.
    console.warn('Opponent asset unavailable; using fallback model.');
  });

  const targetMat = new THREE.MeshBasicMaterial({ color: 0xf5bd48, transparent: true, opacity: 0.88 });
  const targetOrb = new THREE.Mesh(new THREE.SphereGeometry(0.105, 24, 16), targetMat);
  targetOrb.name='combat-target-marker';
  targetOrb.visible=false;
  enemyGroup.add(targetOrb);

  const targetRing = new THREE.Mesh(
    new THREE.TorusGeometry(0.17, 0.012, 8, 48),
    new THREE.MeshBasicMaterial({ color: 0xf5bd48, transparent: true, opacity: 0.7 })
  );
  enemyGroup.add(targetRing);
  targetRing.visible=false;

  const attackMat = new THREE.MeshBasicMaterial({ color: 0xf25c66, transparent: true, opacity: 0.0, side: THREE.DoubleSide });
  const attackArc = new THREE.Mesh(new THREE.RingGeometry(0.38, 0.48, 48), attackMat);
  attackArc.position.set(0, 1.05, -0.04);
  enemyGroup.add(attackArc);

  const hitboxDefs = {
    head: {
      type: "sphere",
      center: new THREE.Vector3(0, 1.48, -0.16),
      radius: 0.29,
      attacks: new Set(["punch"])
    },
    body: {
      type: "capsule",
      a: new THREE.Vector3(0, 0.74, -0.15),
      b: new THREE.Vector3(0, 1.22, -0.15),
      radius: 0.28,
      attacks: new Set(["punch"])
    },
    legs: {
      type: "capsule",
      a: new THREE.Vector3(-0.16, 0.16, -0.12),
      b: new THREE.Vector3(0.16, 0.58, -0.12),
      radius: 0.24,
      attacks: new Set(["kick"])
    }
  };

  const hitboxVisuals = new Map();
  const hitboxBaseMat = {
    head: new THREE.MeshBasicMaterial({ color: 0xf5bd48, transparent: true, opacity: 0.12, wireframe: true }),
    body: new THREE.MeshBasicMaterial({ color: 0x32d3c5, transparent: true, opacity: 0.10, wireframe: true }),
    legs: new THREE.MeshBasicMaterial({ color: 0xf25c66, transparent: true, opacity: 0.10, wireframe: true })
  };

  function makeCapsuleVisual(a, b, radius, material) {
    const group = new THREE.Group();
    const dir = new THREE.Vector3().subVectors(b, a);
    const len = Math.max(dir.length(), 0.001);
    const cyl = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, len, 16), material);
    cyl.position.copy(a).addScaledVector(dir, 0.5);
    cyl.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
    const s1 = new THREE.Mesh(new THREE.SphereGeometry(radius, 16, 10), material);
    const s2 = new THREE.Mesh(new THREE.SphereGeometry(radius, 16, 10), material);
    s1.position.copy(a);
    s2.position.copy(b);
    group.add(cyl, s1, s2);
    return group;
  }

  for (const [name, def] of Object.entries(hitboxDefs)) {
    const mat = hitboxBaseMat[name];
    const visual = def.type === "sphere"
      ? new THREE.Mesh(new THREE.SphereGeometry(def.radius, 24, 16), mat)
      : makeCapsuleVisual(def.a, def.b, def.radius, mat);
    if (def.type === "sphere") visual.position.copy(def.center);
    enemyGroup.add(visual);
    hitboxVisuals.set(name, visual);
  }

  const attackColliderDefs = {
    leftHand: {
      baseJoint: SMPL_JOINT.leftWrist,
      tipJoint: SMPL_JOINT.leftHand,
      side: "left",
      kind: "punch",
      size: new THREE.Vector3(0.22, 0.22, 0.34),
      tipOffset: 0.07,
      color: 0xf5bd48
    },
    rightHand: {
      baseJoint: SMPL_JOINT.rightWrist,
      tipJoint: SMPL_JOINT.rightHand,
      side: "right",
      kind: "punch",
      size: new THREE.Vector3(0.22, 0.22, 0.34),
      tipOffset: 0.07,
      color: 0xf5bd48
    },
    leftFoot: {
      baseJoint: SMPL_JOINT.leftAnkle,
      tipJoint: SMPL_JOINT.leftFoot,
      side: "left",
      kind: "kick",
      size: new THREE.Vector3(0.24, 0.16, 0.46),
      tipOffset: 0.08,
      color: 0x32d3c5
    },
    rightFoot: {
      baseJoint: SMPL_JOINT.rightAnkle,
      tipJoint: SMPL_JOINT.rightFoot,
      side: "right",
      kind: "kick",
      size: new THREE.Vector3(0.24, 0.16, 0.46),
      tipOffset: 0.08,
      color: 0x32d3c5
    }
  };

  const attackColliderMeshes = new Map();
  let debugVisible = false;
  for (const visual of hitboxVisuals.values()) visual.visible=false;
  const attackColliderState = new Map();
  const activeColliderUntil = new Map();

  for (const [name, def] of Object.entries(attackColliderDefs)) {
    const mat = new THREE.MeshBasicMaterial({
      color: def.color,
      transparent: true,
      opacity: 0.18,
      wireframe: true
    });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(def.size.x, def.size.y, def.size.z), mat);
    mesh.visible = false;
    scene.add(mesh);
    attackColliderMeshes.set(name, mesh);
  }

  const particles = [];
  const sparkGeo = new THREE.SphereGeometry(0.018, 8, 8);
  const sparkMat = new THREE.MeshBasicMaterial({ color: 0xffdb7a });

  const pose = {
    prev: new Map(),
    vel: new Map(),
    lastAt: 0,
    live: false,
    guard: false,
    crouch: false,
    lean: 0,
    handCooldown: { left: 0, right: 0 },
    kickCooldown: 0
  };

  const game = {
    breakdown:{received:{high:0,body:0,flank:0},defended:{high:0,body:0,flank:0}},
    stats:{attempts:0,hits:0,targets:0,blocked:0,defenses:0,received:0,counters:0,bestCombo:0},
    running: false,
    playerHp: 100,
    enemyHp: 100,
    combo: 0,
    score: 0,
    timeLeft: ROUND_SECONDS,
    roundEndsAt: 0,
    targetZone: "head",
    targetExpiresAt: 0,
    targetAvailable:true,targetCheckAt:0,availableZones:[],
    enemyAttack: null,
    nextEnemyAt: 0,
    lastStrikeAt: 0,
    sourceLostAt: null,
    result: ""
  };

  const targetPositions = {
    head: new THREE.Vector3(0, 1.48, -0.16),
    body: new THREE.Vector3(0, 0.98, -0.18),
    legs: new THREE.Vector3(0, 0.43, -0.14)
  };
  const targetNames = { head: "頭", body: "身體", legs: "腿" };
  const attackNames = { high: "高位攻擊", body: "身體攻擊", flank: "側面攻擊" };
  const difficultyProfiles={easy:{windup:1.45,recovery:2.8,jitter:1.5,adaptation:.35,targetWindow:6},normal:{windup:1.05,recovery:1.9,jitter:1.2,adaptation:1,targetWindow:4.2},hard:{windup:.85,recovery:1.3,jitter:.8,adaptation:1.3,targetWindow:3.2}};
  let enemyDifficulty=difficultyProfiles.normal;
  const difficultySelect=$('combat-difficulty');
  try { const saved=localStorage.getItem('aetherpose.combat-difficulty.v1'); if(Object.hasOwn(difficultyProfiles,saved))difficultySelect.value=saved; } catch (_) {}
  difficultySelect.addEventListener('change',()=>{try {if(Object.hasOwn(difficultyProfiles,difficultySelect.value))localStorage.setItem('aetherpose.combat-difficulty.v1',difficultySelect.value);}catch (_) {}});
  difficultySelect.addEventListener('change',()=>updateGameLibrary());
  const enemyBrain={lastType:null,defended:{high:0,body:0,flank:0},landed:{high:0,body:0,flank:0},weights:null,phase:'idle',counterUntil:0,chainPending:false,followup:false};
  enemyGroup.userData.ai=enemyBrain;
  function enemyAttackUnavailable(type) {
    const destination=smplJointWorld(type==='high'?SMPL_JOINT.head:SMPL_JOINT.chest);
    const origin=enemyGroup.localToWorld(new THREE.Vector3(0,type==='high'?1.48:1.05,0));
    if (!destination) return 'pose';
    if (origin.distanceTo(destination)>1.7) return 'distance';
    return physics && physics.segmentBlocked(origin,destination,.06)?'cover':null;
  }
  function chooseEnemyAttack() {
    const weights={high:1,body:1,flank:1};
    enemyBrain.routes={};
    if (pose.guard) { weights.flank=3.5; weights.high=.5; weights.body=.5; }
    if (pose.crouch) { weights.body*=2.5; weights.high*=.3; }
    if (Math.abs(pose.lean)>.34) { weights.flank*=.25; weights.high*=1.4; weights.body*=1.4; }
    for (const type of Object.keys(weights)) {
      weights[type]=Math.max(.05,1+(weights[type]-1)*enemyDifficulty.adaptation);
      weights[type]/=1+enemyBrain.defended[type]*.6*enemyDifficulty.adaptation;
      weights[type]*=1+enemyBrain.landed[type]*.2*enemyDifficulty.adaptation;
      if(type===enemyBrain.lastType) weights[type]*=.45;
      enemyBrain.routes[type]=enemyAttackUnavailable(type);
      if(enemyBrain.routes[type]) weights[type]=0;
    }
    if (enemyBrain.chainPending && Object.keys(weights).some(type=>type!==enemyBrain.lastType && weights[type]>0)) weights[enemyBrain.lastType]=0;
    enemyBrain.weights={...weights};
    const available=Object.keys(weights).filter(type=>weights[type]>0);
    if (!available.length) return null;
    let roll=Math.random()*available.reduce((sum,type)=>sum+weights[type],0);
    for (const type of available) { roll-=weights[type]; if(roll<=0) return type; }
    return available[available.length-1];
  }
  function smplJointToPlayerLocal(joint) {
    // The shared avatar owns floor lift and scale through its root transform.
    return new THREE.Vector3(...joint);
  }

  function updateSmplJoints(joints) {
    if (!avatar.onJoints(joints)) return false;
    const t = nowSec();
    latestSmplJoints = avatar.joints;
    pose.lastAt = t;
    updateSmplVelocity(joints, t);
    if (active && !suspended) {
      updateAttackColliderMeshes(t);
      detectSmplActions(t);
    }
    return true;
  }

  function smplIsFresh(t = nowSec()) {
    return avatar.fresh(t);
  }

  function smplJointWorld(smplIndex) {
    if (!latestSmplJoints || smplIndex >= latestSmplJoints.length) return null;
    return playerGroup.localToWorld(smplJointToPlayerLocal(latestSmplJoints[smplIndex]));
  }

  const BOX_FORWARD_AXIS = new THREE.Vector3(0, 0, 1);

  function attackColliderPose(def, t) {
    if (!smplIsFresh(t)) return null;
    const base = smplJointWorld(def.baseJoint);
    const tip = smplJointWorld(def.tipJoint);
    if (!base || !tip) return null;

    const direction = tip.clone().sub(base);
    if (direction.lengthSq() < 1e-6) return null;
    direction.normalize();

    return {
      center: tip.clone().addScaledVector(direction, def.tipOffset || 0),
      quaternion: new THREE.Quaternion().setFromUnitVectors(BOX_FORWARD_AXIS, direction),
      halfSize: def.size.clone().multiplyScalar(0.5)
    };
  }

  function onMeshOpen() {
    setFeed("姿態服務已連線。");
  }

  function onMeshClose() {
    $("tag-smpl").classList.remove("on");
    avatar.disconnect();
    latestSmplJoints = null;
    pose.prev.clear();
    pose.vel.clear();
    clearSmplPoseState();
    setPoseState(false);
    if (game.running) finishRound("Pose connection lost. Round stopped.");
  }

  function smplJointLocal(smplIndex) {
    if (!latestSmplJoints || smplIndex >= latestSmplJoints.length) return null;
    const joint = latestSmplJoints[smplIndex];
    return new THREE.Vector3(joint[0] * SMPL_RENDER_SCALE,
      (joint[1] + SMPL_FLOOR_LIFT) * SMPL_RENDER_SCALE, joint[2] * SMPL_RENDER_SCALE);
  }

  function smplVelocity(smplIndex) {
    return pose.vel.get(smplIndex) || new THREE.Vector3();
  }

  function setActionTags(live) {
    $("tag-guard").classList.toggle("on", live && pose.guard);
    $("tag-crouch").classList.toggle("on", live && pose.crouch);
    $("tag-lean").classList.toggle("on", live && Math.abs(pose.lean) > 0.32);
    $("tag-live").classList.toggle("on", live);
  }

  function clearSmplPoseState() {
    pose.live = false;
    pose.guard = false;
    pose.crouch = false;
    pose.lean = 0;
    setActionTags(false);
  }

  function updateSmplVelocity(joints, t) {
    for (let i = 0; i < joints.length; i++) {
      const point = new THREE.Vector3(...joints[i]).sub(new THREE.Vector3(...joints[0])).multiplyScalar(SMPL_RENDER_SCALE);
      const prev = pose.prev.get(i);
      const elapsed = prev ? t - prev.t : 0;
      let path=null;
      if (prev && elapsed > 0 && elapsed < 0.25 && point.distanceTo(prev.p) < 0.6) {
        pose.vel.set(i, point.clone().sub(prev.p).divideScalar(Math.max(elapsed, 0.016)));
        // Map the previous hip-relative point through the current root so
        // collision correction cannot manufacture a swept limb movement.
        const from=prev.p.clone().divideScalar(SMPL_RENDER_SCALE).add(new THREE.Vector3(...joints[0]));
        path={from:playerGroup.localToWorld(from),to:smplJointWorld(i)};
      } else {
        pose.vel.set(i, new THREE.Vector3());
      }
      pose.prev.set(i, { p: point, t, path });
    }
  }

  function detectSmplActions(t) {
    const head = smplJointLocal(SMPL_JOINT.head);
    const chest = smplJointLocal(SMPL_JOINT.chest);
    const hip = smplJointLocal(SMPL_JOINT.hip);
    const lh = smplJointLocal(SMPL_JOINT.leftHand);
    const rh = smplJointLocal(SMPL_JOINT.rightHand);
    const lf = smplJointLocal(SMPL_JOINT.leftFoot);
    const rf = smplJointLocal(SMPL_JOINT.rightFoot);
    if (!head || !chest || !hip || !lh || !rh || !lf || !rf) return;

    const floorY = Math.min(lf.y, rf.y);
    const bodyHeight = Math.max(0.7, head.y - floorY);
    const handsHigh = lh.y > chest.y - 0.07 && rh.y > chest.y - 0.07;
    const handsClose = lh.distanceTo(head) < bodyHeight * 0.34 && rh.distanceTo(head) < bodyHeight * 0.34;

    pose.live = true;
    const torsoChain=[0,3,6,9,12,15];
    const torsoLength=torsoChain.slice(1).reduce((sum,joint,index)=>sum+smplJointLocal(joint).distanceTo(smplJointLocal(torsoChain[index])),0);
    const legLength=([upper,knee,ankle,footJoint])=>Math.abs(smplJointLocal(upper).y-hip.y)+
      smplJointLocal(upper).distanceTo(smplJointLocal(knee))+smplJointLocal(knee).distanceTo(smplJointLocal(ankle))+
      Math.abs(smplJointLocal(ankle).y-smplJointLocal(footJoint).y);
    const standingHeight=clamp(torsoLength+(legLength([1,4,7,10])+legLength([2,5,8,11]))/2,.7,2.4);
    pose.crouch = bodyHeight < standingHeight*.82;
    // Sideways along the body's own shoulder line: measured on x, bending forward counted as a
    // dodge whenever the player did not face exactly +z.
    const ls = smplJointLocal(SMPL_JOINT.leftShoulder), rs = smplJointLocal(SMPL_JOINT.rightShoulder);
    const across = ls && rs ? rs.clone().sub(ls).setY(0) : new THREE.Vector3(1, 0, 0);
    if (across.lengthSq() < 1e-8) across.set(1, 0, 0);
    const sideways = head.clone().sub(hip).setY(0).dot(across.normalize());
    pose.guard=handsHigh && handsClose && lh.distanceTo(rh)>bodyHeight*.08 &&
      lh.clone().sub(head).dot(across)<-bodyHeight*.03 && rh.clone().sub(head).dot(across)>bodyHeight*.03;
    pose.lean = clamp((sideways / bodyHeight) * 2.2, -1, 1);
    setActionTags(true);
    if (!active || suspended || !game.running || game.sourceLostAt!==null) return;

    maybeSmplPunch("left", SMPL_JOINT.leftHand, lh, chest, t);
    maybeSmplPunch("right", SMPL_JOINT.rightHand, rh, chest, t);
    maybeSmplKick("left", SMPL_JOINT.leftFoot, lf, floorY, t);
    maybeSmplKick("right", SMPL_JOINT.rightFoot, rf, floorY, t);
  }

  function maybeSmplPunch(side, jointId, hand, chest, t) {
    if (t < pose.handCooldown[side]) return;
    if (!pose.prev.get(jointId)?.path || !pose.prev.get(SMPL_JOINT.chest)?.path) return;
    if (smplVelocity(jointId).length()<=.95) return;
    const velocity=smplVelocity(jointId).clone().sub(smplVelocity(SMPL_JOINT.chest));
    const speed = velocity.length();
    const reach = hand.distanceTo(chest);
    const outwardSpeed=velocity.dot(hand.clone().sub(chest).normalize());
    const highEnough = hand.y > chest.y - 0.28;
    if (speed > 0.95 && outwardSpeed>.1 && reach > 0.28 && highEnough) {
      pose.handCooldown[side] = t + 0.34;
      handleStrike({ type: "punch", side, power: clamp(speed / 2.0 + reach, 0.65, 2.0) });
    }
  }

  function maybeSmplKick(side, jointId, foot, floorY, t) {
    if (t < pose.kickCooldown) return;
    const velocity=smplVelocity(jointId),speed=velocity.length();
    const hip=smplJointWorld(SMPL_JOINT.hip);
    if (!hip || !pose.prev.get(jointId)?.path) return;
    const toward=enemyGroup.getWorldPosition(new THREE.Vector3()).sub(hip); toward.y=0;
    if (toward.lengthSq()<1e-8) return; toward.normalize();
    const worldVelocity=velocity.clone().applyQuaternion(playerGroup.getWorldQuaternion(new THREE.Quaternion()));
    const forwardSpeed=worldVelocity.dot(toward);
    if (speed > 0.85 && forwardSpeed>.3 && foot.y > floorY + 0.1) {
      pose.kickCooldown = t + 0.68;
      handleStrike({ type: "kick", side, power: clamp(speed / 1.9, 0.65, 2.1) });
    }
  }

  function startRound() {
    const sourceKind = aetherPoseSource(sourceStatus).kind;
    const calibrationIssue=aetherCalibrationIssue(sourceStatus,calibrationPhase);
    if (calibrationIssue) { setFeed(calibrationIssue); return; }
    if (!active || suspended || !smplIsFresh() || sourceKind === 'error' || (sourceStatus && sourceKind === 'waiting')) {
      setFeed("等待最新的姿態，才能開始回合。");
      return;
    }
    resetRound();
    game.stats={attempts:0,hits:0,targets:0,blocked:0,defenses:0,received:0,counters:0,bestCombo:0};
    game.breakdown={received:{high:0,body:0,flank:0},defended:{high:0,body:0,flank:0}};
    game.running = true;
    game.sourceLostAt = null;
    game.roundSource=aetherPoseSource(sourceStatus).signature;
    game.playerHp = 100;
    game.enemyHp = 100;
    game.combo = 0;
    game.score = 0;
    game.timeLeft = ROUND_SECONDS;
    game.roundEndsAt = nowSec() + ROUND_SECONDS;
    game.nextEnemyAt = nowSec() + 2.6;
    const difficulty=Object.hasOwn(difficultyProfiles,difficultySelect.value)?difficultySelect.value:'normal';
    enemyDifficulty=difficultyProfiles[difficulty]; enemyBrain.difficulty=difficulty;
    enemyBrain.lastType=null; enemyBrain.defended={high:0,body:0,flank:0}; enemyBrain.weights=null; enemyBrain.phase='idle';
    enemyBrain.landed={high:0,body:0,flank:0};
    enemyBrain.counterUntil=0;
    enemyBrain.chainPending=false; enemyBrain.followup=false;
    game.enemyAttack = null;
    game.result = "";
    changeTarget();
    const source = aetherPoseSource(sourceStatus).kind;
    setFeed(source === 'demo' ? "回合開始（示範資料）。" :
      source === 'mixed' ? "回合開始（即時與示範資料混合）。" : "回合開始。");
    $("start-btn").textContent = "重新開始";
    updateHud();
    onRoundStart();
  }

  function resetRound() {
    enemyBrain.chainPending=false; enemyBrain.followup=false;
    enemyBrain.phase='idle'; enemyBrain.counterUntil=0;
    if (game.running) reportRound('Round reset.',false);
    playBotAnimation('Idle');
    game.running = false;
    game.playerHp = 100;
    game.enemyHp = 100;
    game.combo = 0;
    game.score = 0;
    game.timeLeft = ROUND_SECONDS;
    game.enemyAttack = null;
    game.targetZone = "head";
    game.result = "";
    attackMat.opacity = 0;
    game.lastStrikeAt = -Infinity;
    pose.handCooldown = { left: 0, right: 0 };
    pose.kickCooldown = 0;
    pose.prev.clear();
    pose.vel.clear();
    activeColliderUntil.clear();
    for (const p of particles) { scene.remove(p.mesh); p.mesh.material.dispose(); }
    particles.length = 0;
    $("start-btn").textContent = "開始回合";
    $("last-move").textContent = "";
    setTargetVisual("head");
    setFeed("回合已重設。");
    updateHud();
  }

  // A tracker dropping out for a moment changes the pose source. The round
  // freezes for up to SOURCE_GRACE_S (no strikes, no attacks, no clock) and
  // continues if the source comes back; updateGame ends it otherwise.
  function trackRoundSource(signature) {
    const t = nowSec();
    if (signature !== game.roundSource) {
      if (game.sourceLostAt != null) return;
      game.sourceLostAt = t;
      setFeed("追蹤中斷，等待恢復…");
    } else if (game.sourceLostAt != null) {
      const frozen = t - game.sourceLostAt;
      game.roundEndsAt += frozen; game.targetExpiresAt += frozen; game.nextEnemyAt += frozen;
      game.targetCheckAt+=frozen;
      game.lastStrikeAt+=frozen;
      pose.handCooldown.left+=frozen; pose.handCooldown.right+=frozen; pose.kickCooldown+=frozen;
      game.targetChangedAt+=frozen;
      if (enemyBrain.counterUntil>t-frozen) enemyBrain.counterUntil+=frozen;
      if (game.enemyAttack) { game.enemyAttack.startedAt += frozen; game.enemyAttack.landsAt += frozen; }
      game.sourceLostAt = null;
      pose.prev.clear(); pose.vel.clear();
      setFeed("追蹤恢復，繼續。");
    }
  }

  function finishRound(result) {
    if (!game.running) return;
    enemyBrain.chainPending=false; enemyBrain.followup=false;
    enemyBrain.phase='idle'; enemyBrain.counterUntil=0;
    game.sourceLostAt = null;
    reportRound(result,['Enemy down.','Player down.','Decision win.','Time.'].includes(result));
    playBotAnimation(result==='Enemy down.'?'Death':result==='Player down.'?'Dance':
      result==='Decision win.'?'No':result==='Time.'?'Yes':'Idle');
    game.running = false;
    game.result = result;
    game.enemyAttack = null;
    attackMat.opacity = 0;
    $("start-btn").textContent = "開始回合";
    setFeed(aetherReasonText(result) + " · 得分 " + game.score);
    game.stats.bestCombo=Math.max(game.stats.bestCombo,game.combo);
    updateHud();
  }
  function reportRound(reason,completed) {
    onRoundEnd({mode:'combat',score:game.score,source:game.roundSource,completed,reason,
      difficulty:enemyBrain.difficulty,combatStats:{...game.stats,bestCombo:Math.max(game.stats.bestCombo,game.combo)},
      combatBreakdown:{received:{...game.breakdown.received},defended:{...game.breakdown.defended}},
      seconds:Math.round(Math.min(ROUND_SECONDS,Math.max(0,nowSec()-game.roundEndsAt+ROUND_SECONDS)))});
  }

  function changeTarget(available=null) {
    const zones = available||["head", "body", "legs"].filter(targetRouteClear);
    game.availableZones=zones;
    game.targetCheckAt=nowSec()+.25;
    game.targetAvailable=zones.length>0;
    if (!zones.length) { targetOrb.visible=false; targetRing.visible=false; return; }
    let next = zones[Math.floor(Math.random() * zones.length)];
    if (next === game.targetZone) next = zones[(zones.indexOf(next) + 1) % zones.length];
    game.targetZone = next;
    game.targetExpiresAt = nowSec() + enemyDifficulty.targetWindow;
    game.targetChangedAt=nowSec();
    setTargetVisual(next);
  }
  function targetRouteClear(zone) {
    const origin=smplJointWorld(zone==='legs'?SMPL_JOINT.hip:SMPL_JOINT.chest);
    const destination=hitboxWorldCenter(hitboxDefs[zone]);
    return Boolean(origin && (!physics || !physics.segmentBlocked(origin,destination)));
  }

  function setTargetVisual(zone) {
    positionTargetMarker(zone);
    const color = 0xf5bd48;
    targetMat.color.setHex(color);
    targetRing.material.color.setHex(color);
    for (const [name, visual] of hitboxVisuals) {
      visual.traverse((node) => {
        if (node.material) node.material.opacity = name === zone ? 0.32 : 0.08;
      });
    }
  }
  function positionTargetMarker(zone) {
    targetOrb.position.copy(targetPositions[zone]);
    if (avatar.fresh()) {
      const direction=enemyGroup.worldToLocal(avatar.root.localToWorld(new THREE.Vector3(...avatar.joints[0]))).sub(targetPositions[zone]);
      direction.y=0;
      if(direction.lengthSq()>.0025) targetOrb.position.addScaledVector(direction.normalize(),.2);
    }
    targetRing.position.copy(targetOrb.position);
  }

  function colliderNameForStrike(strike) {
    if (strike.type === "punch") return strike.side === "left" ? "leftHand" : "rightHand";
    return strike.side === "left" ? "leftFoot" : "rightFoot";
  }

  function boxFromColliderState(state) {
    const min = state.center.clone().sub(state.halfSize);
    const max = state.center.clone().add(state.halfSize);
    return { min, max };
  }

  function colliderLocalPoint(state, point) {
    return point.clone().sub(state.center).applyQuaternion(state.inverseQuaternion);
  }

  function boxIntersectsSphere(state, center, radius) {
    if (state.inverseQuaternion) {
      const localCenter = colliderLocalPoint(state, center);
      const closest = new THREE.Vector3(
        clamp(localCenter.x, -state.halfSize.x, state.halfSize.x),
        clamp(localCenter.y, -state.halfSize.y, state.halfSize.y),
        clamp(localCenter.z, -state.halfSize.z, state.halfSize.z)
      );
      return closest.distanceToSquared(localCenter) <= radius * radius;
    }
    const box = boxFromColliderState(state);
    const closest = new THREE.Vector3(
      clamp(center.x, box.min.x, box.max.x),
      clamp(center.y, box.min.y, box.max.y),
      clamp(center.z, box.min.z, box.max.z)
    );
    return closest.distanceToSquared(center) <= radius * radius;
  }

  function segmentIntersectsAabb(a, b, min, max) {
    const d = b.clone().sub(a);
    let tMin = 0;
    let tMax = 1;
    for (const axis of ["x", "y", "z"]) {
      if (Math.abs(d[axis]) < 1e-6) {
        if (a[axis] < min[axis] || a[axis] > max[axis]) return false;
      } else {
        const inv = 1 / d[axis];
        let t1 = (min[axis] - a[axis]) * inv;
        let t2 = (max[axis] - a[axis]) * inv;
        if (t1 > t2) [t1, t2] = [t2, t1];
        tMin = Math.max(tMin, t1);
        tMax = Math.min(tMax, t2);
        if (tMin > tMax) return false;
      }
    }
    return true;
  }

  function boxIntersectsCapsule(state, a, b, radius) {
    if (state.inverseQuaternion) {
      const localA = colliderLocalPoint(state, a);
      const localB = colliderLocalPoint(state, b);
      const min = state.halfSize.clone().multiplyScalar(-1).subScalar(radius);
      const max = state.halfSize.clone().addScalar(radius);
      return segmentIntersectsAabb(localA, localB, min, max);
    }
    const box = boxFromColliderState(state);
    const expand = new THREE.Vector3(radius, radius, radius);
    return segmentIntersectsAabb(
      a,
      b,
      box.min.clone().sub(expand),
      box.max.clone().add(expand)
    );
  }

  function hitboxWorldCenter(def) {
    if (def.type === "sphere") return enemyGroup.localToWorld(def.center.clone());
    return enemyGroup.localToWorld(def.a.clone().add(def.b).multiplyScalar(0.5));
  }

  function testAttackCollider(strike) {
    const name = colliderNameForStrike(strike);
    const state = attackColliderState.get(name);
    if (!state) return {hit:null,blocked:false};

    let best = null,blocked=false;
    for (const [zone, def] of Object.entries(hitboxDefs)) {
      if (!def.attacks.has(strike.type)) continue;

      let hit = false;
      if (def.type === "sphere") {
        hit = boxIntersectsSphere(state, enemyGroup.localToWorld(def.center.clone()), def.radius);
      } else {
        hit = boxIntersectsCapsule(
          state,
          enemyGroup.localToWorld(def.a.clone()),
          enemyGroup.localToWorld(def.b.clone()),
          def.radius
        );
      }

      if (!hit) continue;

      const center = hitboxWorldCenter(def);
      const origin=smplJointWorld(strike.type==='punch'?SMPL_JOINT.chest:SMPL_JOINT.hip);
      if (physics && origin && physics.segmentBlocked(origin,center)) { blocked=true; continue; }
      const distance = state.center.distanceTo(center);
      if (!best || distance < best.distance) {
        best = { zone, center, distance, colliderName: name };
      }
    }

    return {hit:best,blocked:!best && blocked};
  }

  function flashAttackCollider(name, hit) {
    const mesh = attackColliderMeshes.get(name);
    if (!mesh) return;
    mesh.material.color.setHex(hit ? 0xffffff : 0xf25c66);
    mesh.material.opacity = hit ? 0.7 : 0.42;
    activeColliderUntil.set(name, nowSec() + 0.16);
  }

  function handleStrike(strike) {
    if (!active || !game.running || game.sourceLostAt != null || nowSec() >= game.roundEndsAt || nowSec() - game.lastStrikeAt < 0.12) return;
    game.lastStrikeAt = nowSec();
    game.stats.attempts++;

    const joint=strike.type==='punch'?(strike.side==='left'?SMPL_JOINT.leftHand:SMPL_JOINT.rightHand):
      (strike.side==='left'?SMPL_JOINT.leftFoot:SMPL_JOINT.rightFoot);
    const path=pose.prev.get(joint)?.path;
    if (physics && path && physics.segmentBlocked(path.from,path.to,strike.type==='punch'?.11:.12)) {
      game.stats.blocked++;
      game.combo=0; updateHud();
      setFeed('場景擋住了手腳的動作。');
      return;
    }

    const contact=testAttackCollider(strike),hit=contact.hit;
    const correct = !!hit && game.targetAvailable && hit.zone === game.targetZone;
    if (hit) game.stats.hits++;
    const label = ({ left: "左", right: "右" }[strike.side] || strike.side) + ({ punch: "拳", kick: "踢" }[strike.type] || strike.type);
    $("last-move").textContent = label;
    flashAttackCollider(colliderNameForStrike(strike), !!hit);
    if (contact.blocked) {
      game.stats.blocked++; game.combo=0;
      setFeed('場景擋住了命中路徑。'); updateHud(); return;
    }

    if (correct) {
      game.stats.targets++;
      game.combo = Math.min(game.combo + 1, 12);
      const counter=nowSec()<enemyBrain.counterUntil;
      if(counter) game.stats.counters++;
      const damage = Math.round((6 + strike.power * 6) * (1 + game.combo * 0.08) * (counter?1.25:1));
      game.enemyHp = clamp(game.enemyHp - damage, 0, 100);
      game.score += damage + game.combo;
      setFeed((counter?'反擊命中！':'命中') + targetNames[hit.zone] + "：造成 " + damage + " 傷害。");
      impactAt(hit.center, 0xffdb7a);
      playBlip(360 + game.combo * 35, 0.08);
      changeTarget();
    } else if (hit) {
      game.combo = 0;
      const damage = Math.round(2 + strike.power);
      game.enemyHp = clamp(game.enemyHp - damage, 0, 100);
      setFeed("碰到" + targetNames[hit.zone] + "，但不是目標部位。");
      impactAt(hit.center, 0x9aa5b5);
      playBlip(180, 0.07);
    } else {
      game.combo = 0;
      setFeed("揮空，沒有碰到。");
      playBlip(110, 0.05);
    }

    if (game.enemyHp <= 0) finishRound("Enemy down.");
    else if (hit && game.enemyAttack?.phase!=='strike') {
      if (game.enemyAttack || enemyBrain.chainPending) {
        enemyBrain.chainPending=false;
        game.enemyAttack=null; attackMat.opacity=0; game.nextEnemyAt=nowSec()+1.3; enemyBrain.phase='stagger';
      }
      playBotAnimation('No');
    }
    updateHud();
  }

  function launchEnemyAttack(t) {
    const type=chooseEnemyAttack();
    if (!type) {
      enemyBrain.chainPending=false; enemyBrain.followup=false;
      const covered=Object.values(enemyBrain.routes).includes('cover');
      enemyBrain.phase=covered?'cover':'distance'; game.nextEnemyAt=t+.65;
      setFeed(covered?'場景擋住了攻擊路徑，對手等待空檔。':'距離太遠，對手等待進入攻擊範圍。'); return;
    }
    enemyBrain.lastType=type; enemyBrain.phase='windup';
    const followup=Boolean(enemyBrain.chainPending); enemyBrain.chainPending=false; enemyBrain.followup=followup;
    game.enemyAttack = {
      type,
      followup,
      startedAt: t,
      landsAt: t + Math.max(.75,enemyDifficulty.windup-(game.enemyHp<35?.15:0)),
      phase:'windup',
      resolved: false
    };
    enemyBrain.windupSeconds=game.enemyAttack.landsAt-t;
    setFeed((followup?'連招第二擊 · ':'')+attackNames[type] + "！");
  }

  function resolveEnemyAttack(attack) {
    if (!game.running || attack.resolved) return;
    attack.resolved = true;
    const destination=smplJointWorld(attack.type==='high'?SMPL_JOINT.head:SMPL_JOINT.chest);
    const unavailable=enemyAttackUnavailable(attack.type);
    if (unavailable) {
      setFeed(unavailable==='distance'?'超出攻擊距離，對手揮空。':'場景擋住了攻擊。'); updateHud(); return;
    }
    let defended = false;
    if (attack.type === "high") defended = pose.guard || pose.crouch;
    if (attack.type === "body") defended = pose.guard;
    if (attack.type === "flank") defended = Math.abs(pose.lean) > 0.34;

    if (defended) {
      game.stats.defenses++;
      game.breakdown.defended[attack.type]++;
      attack.defended=true; enemyBrain.counterUntil=nowSec()+.8;
      enemyBrain.defended[attack.type]=Math.min(6,enemyBrain.defended[attack.type]+1);
      enemyBrain.landed[attack.type]=Math.max(0,enemyBrain.landed[attack.type]-1);
      game.combo = Math.min(game.combo + 1, 12);
      setFeed("防禦成功！0.8 秒反擊空檔。");
      playBotAnimation('No',.7);
      if (destination) impactAt(destination.clone(), 0x42d983);
      playBlip(460, 0.05);
    } else {
      attack.landed=true;
      game.stats.received++;
      game.breakdown.received[attack.type]++;
      enemyBrain.defended[attack.type]=Math.max(0,enemyBrain.defended[attack.type]-1);
      enemyBrain.landed[attack.type]=Math.min(6,enemyBrain.landed[attack.type]+1);
      const damage = attack.type === "body" ? 9 : 7;
      game.playerHp = clamp(game.playerHp - damage, 0, 100);
      game.combo = 0;
      setFeed("被擊中：" + damage + " 傷害。");
      if (destination) impactAt(destination.clone(), 0xf25c66);
      playBlip(120, 0.12);
    }

    if (game.playerHp <= 0) finishRound("Player down.");
    updateHud();
  }

  let audioCtx = null;
  function playBlip(freq, dur) {
    if (!document.getElementById('game-sound').checked) return;
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.frequency.value = freq;
      osc.type = "sine";
      gain.gain.setValueAtTime(0.12, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + dur);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + dur);
    } catch (_) {}
  }

  function impactAt(pos, color) {
    for (let i = 0; i < 14; i++) {
      const m = new THREE.Mesh(sparkGeo, sparkMat.clone());
      m.name='combat-impact';
      m.material.color.setHex(color);
      m.position.copy(pos);
      const vel = new THREE.Vector3(
        (Math.random() - 0.5) * 0.8,
        Math.random() * 0.45,
        (Math.random() - 0.5) * 0.8
      );
      scene.add(m);
      particles.push({ mesh: m, vel, life: 0.48 });
    }
  }

  function updateParticles(dt) {
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.life -= dt;
      p.vel.y -= dt * 1.8;
      p.mesh.position.addScaledVector(p.vel, dt);
      p.mesh.material.opacity = clamp(p.life * 2, 0, 1);
      p.mesh.material.transparent = true;
      if (p.life <= 0) {
        scene.remove(p.mesh);
        p.mesh.material.dispose();
        particles.splice(i, 1);
      }
    }
  }

  function setFeed(text) {
    $("event-feed").textContent = text;
  }

  function updateHud() {
    game.stats.bestCombo=Math.max(game.stats.bestCombo,game.combo);
    $("player-hp").style.width = game.playerHp + "%";
    $("enemy-hp").style.width = game.enemyHp + "%";
    $("player-hp-text").textContent = Math.round(game.playerHp);
    $("enemy-hp-text").textContent = Math.round(game.enemyHp);
    $("round-time").textContent = Math.max(0, Math.ceil(game.timeLeft));
    $("combo-readout").textContent = "x" + game.combo;
    $("target-zone").textContent = game.running ? (game.targetAvailable?targetNames[game.targetZone]:'場景遮擋') : "待命";
    const targetRemaining=Math.max(0,game.targetExpiresAt-(game.sourceLostAt??nowSec()));
    $("target-window").textContent = game.running ? (game.targetAvailable?`得分 ${game.score} · 目標剩餘 ${targetRemaining.toFixed(1)} 秒`:'整理場景或重設位置後，可重開回合。') : (game.result ? aetherReasonText(game.result) : "");
    $('combat-target-progress').max=enemyDifficulty.targetWindow;
    $('combat-target-progress').hidden=!game.running || !game.targetAvailable; $('combat-target-progress').value=game.running&&game.targetAvailable?targetRemaining:0;
    $('combat-target-routes').hidden=!game.running || game.availableZones.length===3;
    $('combat-target-routes').textContent=game.availableZones.length?`可攻擊：${game.availableZones.map(zone=>targetNames[zone]).join('、')}`:'所有目標路徑受阻';

    if (game.enemyAttack && !game.enemyAttack.resolved) {
      $("incoming-zone").textContent = (game.enemyAttack.followup?'連招 · ':'')+attackNames[game.enemyAttack.type];
      const attack=game.enemyAttack,remaining=Math.max(0,attack.landsAt-(game.sourceLostAt??nowSec()));
      const defense={high:'雙手防守或蹲下',body:'雙手防守',flank:'側身閃避'}[attack.type];
      $("incoming-window").textContent = `${attack.phase==='windup'?'蓄力中，可搶先打斷':'出招中'} · ${remaining.toFixed(1)} 秒 · ${defense}`;
      $('combat-attack-progress').hidden=false;
      $('combat-attack-progress').value=clamp(1-remaining/(attack.landsAt-attack.startedAt),0,1);
      $("tag-guard").classList.toggle("warn", game.enemyAttack.type === "high" || game.enemyAttack.type === "body");
      $("tag-lean").classList.toggle("warn", game.enemyAttack.type === "flank");
    } else {
      $("incoming-zone").textContent = "無";
      $('combat-attack-progress').hidden=true; $('combat-attack-progress').value=0;
      const clock=game.sourceLostAt??nowSec();
      const labels={idle:'準備下一波',recover:enemyBrain.chainPending?'對手準備連招':'對手恢復中',stagger:'對手失衡中',cover:'攻擊路徑被擋',distance:'等待進入攻擊範圍'};
      const recovery=enemyBrain.phase==='recover'||enemyBrain.phase==='stagger';
      $("incoming-window").textContent = !game.running?'':game.sourceLostAt!==null?'追蹤暫停':clock<enemyBrain.counterUntil?'反擊空檔 · 命中目標傷害 +25%':
        (labels[enemyBrain.phase]||'準備下一波')+(recovery?` · ${Math.max(0,game.nextEnemyAt-clock).toFixed(1)} 秒`:'');
      $("tag-guard").classList.remove("warn");
      $("tag-lean").classList.remove("warn");
    }
  }

  function updateGame(dt, t) {
    if (!game.running) {
      return;
    }
    if (game.sourceLostAt != null) {
      if (t - game.sourceLostAt > SOURCE_GRACE_S) finishRound("Pose source changed. Round stopped.");
      return;
    }

    game.timeLeft = Math.max(0, game.roundEndsAt - t);
    if (game.timeLeft <= 0) {
      finishRound(game.enemyHp < game.playerHp ? "Decision win." : "Time.");
      return;
    }

    if (t>=game.targetCheckAt) {
      game.targetCheckAt=t+.25;
      const zones=['head','body','legs'].filter(targetRouteClear); game.availableZones=zones;
      if (!game.targetAvailable || !zones.includes(game.targetZone)) changeTarget(zones);
    }
    if (game.targetAvailable && t > game.targetExpiresAt) {
      game.combo = 0;
      changeTarget();
    }

    if (!game.enemyAttack && t >= game.nextEnemyAt) {
      launchEnemyAttack(t);
    }

    if (game.enemyAttack) {
      const attack = game.enemyAttack;
      if (attack.phase==='windup' && t>=attack.landsAt-.45) {
        attack.phase='strike'; enemyBrain.phase='strike'; playBotAnimation('Punch',.8);
      }
      const windup = clamp((t - attack.startedAt) / (attack.landsAt - attack.startedAt), 0, 1);
      attackMat.opacity = 0.08 + windup * 0.42;
      attackArc.scale.setScalar(0.85 + windup * 0.55);
      attackArc.rotation.z = attack.type === "flank" ? Math.PI / 2 : 0;
      attackArc.position.y = attack.type === "high" ? 1.32 : attack.type === "body" ? 0.92 : 1.05;
      if (t >= attack.landsAt) {
        resolveEnemyAttack(attack);
        if (!game.running) { attackMat.opacity=0; updateHud(); return; }
        game.enemyAttack = null;
        enemyBrain.phase='recover';
        enemyBrain.chainPending=enemyBrain.difficulty==='hard' && attack.landed===true && !attack.followup && Math.random()<.5;
        game.nextEnemyAt = t + (enemyBrain.chainPending?.65:enemyDifficulty.recovery + Math.random() * enemyDifficulty.jitter + enemyBrain.defended[attack.type]*.12 + (attack.defended?.8:0));
        attackMat.opacity = 0;
      }
    }

    updateHud();
  }

  function updateAttackColliderMeshes(t) {
    for (const [name, def] of Object.entries(attackColliderDefs)) {
      const mesh = attackColliderMeshes.get(name);
      const bound = attackColliderPose(def, t);
      if (!mesh || !bound) {
        if (mesh) mesh.visible = false;
        attackColliderState.delete(name);
        continue;
      }

      mesh.position.copy(bound.center);
      mesh.quaternion.copy(bound.quaternion);
      mesh.visible = debugVisible;

      attackColliderState.set(name, {
        name,
        kind: def.kind,
        side: def.side,
        center: bound.center.clone(),
        halfSize: bound.halfSize,
        quaternion: bound.quaternion.clone(),
        inverseQuaternion: bound.quaternion.clone().invert()
      });

      const active = (activeColliderUntil.get(name) || 0) > t;
      if (!active) {
        mesh.material.color.setHex(def.color);
        mesh.material.opacity = pose.live ? 0.22 : 0.12;
      }
    }
  }

  function updatePoseRender(t) {
    targetOrb.visible=game.running && game.targetAvailable;
    targetRing.visible=game.running && game.targetAvailable;
    const hasSmpl = smplIsFresh(t);
    setPoseState(hasSmpl);
    if (!hasSmpl) {
      clearSmplPoseState();
      if (game.running) finishRound("Pose data expired. Round stopped.");
    }

    updateAttackColliderMeshes(t);
    if (game.running && hasSmpl && game.sourceLostAt===null) positionTargetMarker(game.targetZone);

    const visualClock=game.sourceLostAt??t;
    const changed=game.running?Math.max(0,1-(visualClock-game.targetChangedAt)/.4):0;
    const pulse = 1 + Math.sin(visualClock * 5.6) * 0.08 + changed*.25;
    targetOrb.scale.setScalar(pulse);
    targetRing.scale.setScalar(1.0 + Math.sin(visualClock * 6.2) * 0.13 + changed*.4);
    targetRing.rotation.y += 0.015;
    targetRing.lookAt(camera.position);
  }

  function setPoseState(ok) {
    const source = aetherPoseSource(sourceStatus);
    const demo = source.kind === 'demo' || source.kind === 'mixed';
    const error = source.kind === 'error';
    const label = error ? source.label : !ok ? '等待姿態' : source.kind === 'waiting' ? '姿態就緒' : source.label;
    if (poseStateOk === label) return;
    poseStateOk = label;
    $("tag-smpl").classList.toggle("on", ok);
    $("ws-dot").classList.toggle("on", ok && !error);
    $("ws-dot").classList.toggle("demo", ok && demo);
    $("ws-state").textContent = label;
  }

  $("start-btn").addEventListener("click", startRound);
  $("reset-btn").addEventListener("click", resetRound);
  $("recenter-btn").addEventListener("click", () => {
    if (sendToBridge && sendToBridge({ cmd: "reset_origin" })) {
      if (game.running) finishRound("Position reset. Round stopped.");
      pose.prev.clear();
      pose.vel.clear();
      avatar.disconnect();
      setFeed("玩家位置已重設。");
    } else {
      setFeed("姿態服務沒有連線。");
    }
  });

  let last = nowSec();
  function tick(t) {
    const animationPaused=game.running && game.sourceLostAt!==null;
    enemyGroup.userData.animationPaused=animationPaused;
    const animationDt=botFrameAt===null?0:Math.min(Math.max(t-botFrameAt,0),.1);
    if (botMixer && !animationPaused) botMixer.update(animationDt);
    if (botModel && !animationPaused && botState!=='Death' && avatar.fresh(t)) {
      const player=enemyGroup.worldToLocal(avatar.root.localToWorld(new THREE.Vector3(...avatar.joints[0])));
      const x=player.x-botModel.position.x,z=player.z-botModel.position.z;
      if (Math.hypot(x,z)>.05) {
        const yaw=Math.atan2(x,z),delta=Math.atan2(Math.sin(yaw-botModel.rotation.y),Math.cos(yaw-botModel.rotation.y));
        botModel.rotation.y+=delta*(1-Math.exp(-animationDt*6));
      }
    }
    if (botModel && botMixer) botModel.userData.animationTime=botMixer.time;
    botFrameAt=t;
    // Keep visible pose geometry current even when another activity is selected.
    updatePoseRender(t);
    if (!active || suspended) return;
    const dt = clamp(t - last, 0.001, 0.05);
    last = t;
    updateGame(dt, t);
    updateParticles(dt);
  }

  function setActive(on) {
    if (on === active) return;
    active = on;
    if (on) {
      // Velocities from a stale previous sample would read as a fast strike.
      pose.prev.clear();
      pose.vel.clear();
      last = nowSec();

    } else if (game.running) {
      finishRound("Round stopped.");
    }
  }

  setTargetVisual("head");
  updateHud();

  return {
    setPhysics(value) { physics=value; },
    setDebug(on) {
      debugVisible=Boolean(on);
      grid.visible=debugVisible;
      for (const visual of hitboxVisuals.values()) visual.visible=debugVisible;
      if (!debugVisible) for (const mesh of attackColliderMeshes.values()) mesh.visible=false;
    },
    setActive,
    tick,
    setDistance(distance) {
      if (!Number.isFinite(distance)) return;
      botDistance = clamp(distance, 0.8, 1.8);
      enemyGroup.position.x = avatar.combatX + botDistance;
      resetRound();
      setFeed("對手距離已更新，請重新開始回合。");
    },
    setSuspended(on) {
      suspended = on;
      pose.prev.clear();
      pose.vel.clear();
      if (on && game.running) finishRound("Tab hidden. Round stopped.");
      last = nowSec();
    },
    onStatus(status) {
      if (typeof status !== 'string') return;
      if (sourceStatus && aetherPoseSource(sourceStatus).signature !== aetherPoseSource(status).signature) {
        pose.prev.clear();
        pose.vel.clear();
      }
      sourceStatus = status;
      if (game.running && aetherCalibrationIssue(status))
        finishRound('Body calibration required. Round stopped.');
      if (game.running) trackRoundSource(aetherPoseSource(status).signature);
      setPoseState(smplIsFresh());
    },
    onCalibration(state) {
      calibrationPhase=state.phase;
      if (game.running && aetherCalibrationIssue('',calibrationPhase))
        finishRound('Body calibration. Round stopped.');
    },
    setSender(fn) { sendToBridge = fn; },
    onSceneChanged() {
      pose.prev.clear(); pose.vel.clear();
      if (game.running) finishRound('Scene changed. Round stopped.');
    },
    // Outside a Combat round the robot coaches the pose games: waves at the
    // start, a thumbs-up on a point (at most every 1.2 s), dances at the end.
    cheer(kind) {
      if (game.running) return;
      const now = nowSec();
      if (kind === 'score' && now - lastCheerAt < 1.2) return;
      lastCheerAt = now;
      playBotAnimation({ start: 'Wave', score: 'ThumbsUp', end: 'Dance' }[kind] || 'Idle');
    },
    stopRound(result) {
      pose.prev.clear(); pose.vel.clear();
      if (game.running) finishRound(result);
    },
    onMeshOpen,
    onMeshClose,
    onFaces: avatar.onFaces,
    onJoints: updateSmplJoints,
    onSkin: avatar.onSkin,
    onPose: avatar.onPose,
  };
};
