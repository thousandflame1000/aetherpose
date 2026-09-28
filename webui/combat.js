// Aether Combat: the combat mode of the Aetherpose web UI (index.html).
// The page owns the single mesh_bridge connection and forwards its messages
// here; this module keeps its own arena scene and only simulates and renders
// while the Combat tab is open.
window.AetherCombat = (() => {
  const ROUND_SECONDS = 90;
  const SMPL_RENDER_SCALE = 0.96;
  const SMPL_FLOOR_LIFT = 0.97;
  const SMPL_STALE_SECONDS = 5.0;
  const SMPL_MESH_BLEND_FRAMES = 10;
  const SMPL_MESH_SETTLE_EPS = 0.00035;
  const MAX_RENDER_FPS = 30;
  const SMPL_VERT0_MINUS_JOINT0 = new THREE.Vector3(0.05000331, 0.7557691, 0.06511144);
  const SMPL_JOINT = {
    hip: 0,
    chest: 9,
    neck: 12,
    head: 15,
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

  const canvas = $("arena");
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: false,
    powerPreference: "high-performance"
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.outputEncoding = THREE.sRGBEncoding;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x07090d);

  const camera = new THREE.PerspectiveCamera(58, 1, 0.05, 80);
  camera.position.set(0, 1.45, 4.2);
  camera.lookAt(0, 1.0, 0);

  const hemi = new THREE.HemisphereLight(0xbad4ff, 0x17120e, 0.7);
  scene.add(hemi);
  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(-1.6, 3.2, 3.5);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x48d7ff, 0.65);
  rim.position.set(3.5, 2.1, -1.4);
  scene.add(rim);

  const arena = new THREE.Group();
  scene.add(arena);

  const floorMat = new THREE.MeshStandardMaterial({ color: 0x121820, roughness: 0.92, metalness: 0.05 });
  const floor = new THREE.Mesh(new THREE.CylinderGeometry(2.65, 2.65, 0.045, 96), floorMat);
  floor.position.y = -0.035;
  arena.add(floor);

  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(2.65, 0.018, 8, 128),
    new THREE.MeshBasicMaterial({ color: 0x3f5068 })
  );
  ring.rotation.x = Math.PI / 2;
  ring.position.y = 0.015;
  arena.add(ring);

  const grid = new THREE.GridHelper(5.1, 18, 0x344053, 0x1b2330);
  grid.position.y = 0.004;
  arena.add(grid);

  const playerGroup = new THREE.Group();
  playerGroup.position.x = -0.9;
  scene.add(playerGroup);

  let smplMesh = null;
  let smplFaces = null;
  let smplCurrentPositions = null;
  let smplTargetPositions = null;
  let smplPositionAttr = null;
  let smplMeshBlendFrames = 0;
  let latestSmplJoints = null;
  let smplLive = false;
  let smplLastAt = 0;
  let sendToBridge = null;  // set by the page; sends a JSON command to mesh_bridge
  let active = false;       // simulate/render only while the Combat tab is open
  let poseStateOk = null;

  const enemyGroup = new THREE.Group();
  enemyGroup.position.x = 1.0;
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

    const guard = new THREE.Mesh(
      new THREE.TorusGeometry(0.78, 0.012, 6, 96),
      new THREE.MeshBasicMaterial({ color: 0x435066, transparent: true, opacity: 0.7 })
    );
    guard.rotation.x = Math.PI / 2;
    guard.position.y = 0.04;
    enemyGroup.add(guard);
  }
  buildEnemy();

  const targetMat = new THREE.MeshBasicMaterial({ color: 0xf5bd48, transparent: true, opacity: 0.88 });
  const targetOrb = new THREE.Mesh(new THREE.SphereGeometry(0.105, 24, 16), targetMat);
  enemyGroup.add(targetOrb);

  const targetRing = new THREE.Mesh(
    new THREE.TorusGeometry(0.17, 0.012, 8, 48),
    new THREE.MeshBasicMaterial({ color: 0xf5bd48, transparent: true, opacity: 0.7 })
  );
  enemyGroup.add(targetRing);

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
    running: false,
    playerHp: 100,
    enemyHp: 100,
    combo: 0,
    score: 0,
    timeLeft: ROUND_SECONDS,
    roundEndsAt: 0,
    targetZone: "head",
    targetExpiresAt: 0,
    enemyAttack: null,
    nextEnemyAt: 0,
    lastStrikeAt: 0,
    result: ""
  };

  const targetPositions = {
    head: new THREE.Vector3(0, 1.48, -0.16),
    body: new THREE.Vector3(0, 0.98, -0.18),
    legs: new THREE.Vector3(0, 0.43, -0.14)
  };
  const targetNames = { head: "Head", body: "Body", legs: "Legs" };
  const attackNames = { high: "High Strike", body: "Body Shot", flank: "Flank Hit" };
  let renderWidth = 0;
  let renderHeight = 0;

  function resize() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;  // hidden (display: none) while another tab is open
    if (w === renderWidth && h === renderHeight) return;
    renderWidth = w;
    renderHeight = h;
    renderer.setSize(w, h, false);
    camera.aspect = Math.max(w / h, 0.1);
    camera.updateProjectionMatrix();
  }
  window.addEventListener("resize", resize);

  function setSmplFaces(faces) {
    smplFaces = new Uint16Array(faces.length * 3);
    for (let i = 0; i < faces.length; i++) {
      smplFaces[i * 3] = faces[i][0];
      smplFaces[i * 3 + 1] = faces[i][1];
      smplFaces[i * 3 + 2] = faces[i][2];
    }
  }

  function smplJointToPlayerLocal(joint) {
    return new THREE.Vector3(
      joint[0] * SMPL_RENDER_SCALE,
      (joint[1] + SMPL_FLOOR_LIFT) * SMPL_RENDER_SCALE,
      joint[2] * SMPL_RENDER_SCALE
    );
  }

  function fillSmplPositions(verts, out) {
    for (let i = 0; i < verts.length; i++) {
      const vertex = verts[i];
      const offset = i * 3;
      out[offset] = (vertex[0] + SMPL_VERT0_MINUS_JOINT0.x) * SMPL_RENDER_SCALE;
      out[offset + 1] = (vertex[1] + SMPL_VERT0_MINUS_JOINT0.y + SMPL_FLOOR_LIFT) * SMPL_RENDER_SCALE;
      out[offset + 2] = (vertex[2] + SMPL_VERT0_MINUS_JOINT0.z) * SMPL_RENDER_SCALE;
    }
  }

  function fillSmplPositionsFlat(flatVerts, out) {
    for (let i = 0; i < flatVerts.length; i += 3) {
      out[i] = (flatVerts[i] + SMPL_VERT0_MINUS_JOINT0.x) * SMPL_RENDER_SCALE;
      out[i + 1] = (flatVerts[i + 1] + SMPL_VERT0_MINUS_JOINT0.y + SMPL_FLOOR_LIFT) * SMPL_RENDER_SCALE;
      out[i + 2] = (flatVerts[i + 2] + SMPL_VERT0_MINUS_JOINT0.z) * SMPL_RENDER_SCALE;
    }
  }

  function ensureSmplMesh(positionCount) {
    if (!smplCurrentPositions || smplCurrentPositions.length !== positionCount) {
      smplCurrentPositions = new Float32Array(positionCount);
      smplCurrentPositions.set(smplTargetPositions);
    }

    if (!smplMesh) {
      const geo = new THREE.BufferGeometry();
      smplPositionAttr = new THREE.BufferAttribute(smplCurrentPositions, 3);
      smplPositionAttr.setUsage(THREE.DynamicDrawUsage);
      geo.setAttribute("position", smplPositionAttr);
      geo.setIndex(new THREE.Uint16BufferAttribute(smplFaces, 1));
      geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(0, 1, 0), 3.2);
      const mat = new THREE.MeshBasicMaterial({
        color: 0xc7a77a,
        transparent: true,
        opacity: 0.86,
        side: THREE.DoubleSide
      });
      smplMesh = new THREE.Mesh(geo, mat);
      smplMesh.name = "smpl-player-mesh";
      smplMesh.frustumCulled = false;
      playerGroup.add(smplMesh);
    }
  }

  function updateSmplMesh(verts) {
    if (!verts || !verts.length || !smplFaces) return;
    const positionCount = verts.length * 3;
    if (!smplTargetPositions || smplTargetPositions.length !== positionCount) {
      smplTargetPositions = new Float32Array(positionCount);
    }
    fillSmplPositions(verts, smplTargetPositions);
    ensureSmplMesh(positionCount);
    smplMeshBlendFrames = SMPL_MESH_BLEND_FRAMES;
    smplLive = true;
    smplLastAt = nowSec();
  }

  function updateSmplMeshFlat(flatVerts) {
    if (!flatVerts || !flatVerts.length || !smplFaces) return;
    if (!smplTargetPositions || smplTargetPositions.length !== flatVerts.length) {
      smplTargetPositions = new Float32Array(flatVerts.length);
    }
    fillSmplPositionsFlat(flatVerts, smplTargetPositions);
    ensureSmplMesh(flatVerts.length);
    smplMeshBlendFrames = SMPL_MESH_BLEND_FRAMES;

    smplLive = true;
    smplLastAt = nowSec();
  }

  function stepSmplMesh(dt) {
    if (!smplPositionAttr || !smplCurrentPositions || !smplTargetPositions) return;
    if (smplMeshBlendFrames <= 0) return;
    const blend = 1 - Math.exp(-dt * 9);
    let maxDelta = 0;
    for (let i = 0; i < smplCurrentPositions.length; i++) {
      const delta = smplTargetPositions[i] - smplCurrentPositions[i];
      const absDelta = Math.abs(delta);
      if (absDelta > maxDelta) maxDelta = absDelta;
      smplCurrentPositions[i] += delta * blend;
    }
    smplMeshBlendFrames -= 1;
    if (maxDelta < SMPL_MESH_SETTLE_EPS || smplMeshBlendFrames <= 0) {
      smplCurrentPositions.set(smplTargetPositions);
      smplMeshBlendFrames = 0;
    }
    smplPositionAttr.needsUpdate = true;
  }

  function updateSmplJoints(joints) {
    if (!joints || !joints.length) return;
    const t = nowSec();
    latestSmplJoints = joints;
    smplLive = true;
    smplLastAt = t;
    pose.lastAt = t;
    updateSmplVelocity(joints, t);
    detectSmplActions(t);
  }

  function smplIsFresh(t = nowSec()) {
    return smplLive && latestSmplJoints && t - smplLastAt < SMPL_STALE_SECONDS;
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
    setFeed("SMPL bridge connected.");
  }

  function onMeshClose() {
    $("tag-smpl").classList.remove("on");
    smplLive = false;
    clearSmplPoseState();
    setPoseState(false);
  }

  function smplJointLocal(smplIndex) {
    if (!latestSmplJoints || smplIndex >= latestSmplJoints.length) return null;
    return smplJointToPlayerLocal(latestSmplJoints[smplIndex]);
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
      const point = smplJointToPlayerLocal(joints[i]);
      const prev = pose.prev.get(i);
      if (prev) {
        const dt = clamp(t - prev.t, 0.016, 0.18);
        pose.vel.set(i, point.clone().sub(prev.p).divideScalar(dt));
      }
      pose.prev.set(i, { p: point, t });
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
    pose.guard = handsHigh && handsClose;
    pose.crouch = bodyHeight < 1.2;
    pose.lean = clamp(((head.x - hip.x) / bodyHeight) * 2.2, -1, 1);
    setActionTags(true);

    maybeSmplPunch("left", SMPL_JOINT.leftHand, lh, chest, t);
    maybeSmplPunch("right", SMPL_JOINT.rightHand, rh, chest, t);
    maybeSmplKick("left", SMPL_JOINT.leftFoot, lf, floorY, t);
    maybeSmplKick("right", SMPL_JOINT.rightFoot, rf, floorY, t);
  }

  function maybeSmplPunch(side, jointId, hand, chest, t) {
    if (t < pose.handCooldown[side]) return;
    const speed = smplVelocity(jointId).length();
    const reach = hand.distanceTo(chest);
    const highEnough = hand.y > chest.y - 0.28;
    if (speed > 0.95 && reach > 0.28 && highEnough) {
      pose.handCooldown[side] = t + 0.34;
      handleStrike({ type: "punch", side, power: clamp(speed / 2.0 + reach, 0.65, 2.0) });
    }
  }

  function maybeSmplKick(side, jointId, foot, floorY, t) {
    if (t < pose.kickCooldown) return;
    const speed = smplVelocity(jointId).length();
    if (speed > 0.85 && foot.y > floorY + 0.1) {
      pose.kickCooldown = t + 0.68;
      handleStrike({ type: "kick", side, power: clamp(speed / 1.9, 0.65, 2.1) });
    }
  }

  function startRound() {
    game.running = true;
    game.playerHp = 100;
    game.enemyHp = 100;
    game.combo = 0;
    game.score = 0;
    game.timeLeft = ROUND_SECONDS;
    game.roundEndsAt = nowSec() + ROUND_SECONDS;
    game.nextEnemyAt = nowSec() + 2.6;
    game.enemyAttack = null;
    game.result = "";
    changeTarget();
    setFeed("Round live.");
    $("start-btn").textContent = "Restart";
    updateHud();
  }

  function resetRound() {
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
    setFeed("Round reset.");
    updateHud();
  }

  function finishRound(result) {
    game.running = false;
    game.result = result;
    game.enemyAttack = null;
    attackMat.opacity = 0;
    $("start-btn").textContent = "Start Round";
    setFeed(result + " Score " + game.score + ".");
    updateHud();
  }

  function changeTarget() {
    const zones = ["head", "body", "legs"];
    let next = zones[Math.floor(Math.random() * zones.length)];
    if (next === game.targetZone) next = zones[(zones.indexOf(next) + 1) % zones.length];
    game.targetZone = next;
    game.targetExpiresAt = nowSec() + 4.2;
    setTargetVisual(next);
  }

  function setTargetVisual(zone) {
    targetOrb.position.copy(targetPositions[zone]);
    targetRing.position.copy(targetPositions[zone]);
    const color = zone === "head" ? 0xf5bd48 : zone === "body" ? 0x32d3c5 : 0xf25c66;
    targetMat.color.setHex(color);
    targetRing.material.color.setHex(color);
    for (const [name, visual] of hitboxVisuals) {
      visual.traverse((node) => {
        if (node.material) node.material.opacity = name === zone ? 0.32 : 0.08;
      });
    }
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
    if (!state) return null;

    let best = null;
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
      const distance = state.center.distanceTo(center);
      if (!best || distance < best.distance) {
        best = { zone, center, distance, colliderName: name };
      }
    }

    return best;
  }

  function flashAttackCollider(name, hit) {
    const mesh = attackColliderMeshes.get(name);
    if (!mesh) return;
    mesh.material.color.setHex(hit ? 0xffffff : 0xf25c66);
    mesh.material.opacity = hit ? 0.7 : 0.42;
    activeColliderUntil.set(name, nowSec() + 0.16);
  }

  function handleStrike(strike) {
    if (!game.running || nowSec() - game.lastStrikeAt < 0.12) return;
    game.lastStrikeAt = nowSec();

    const hit = testAttackCollider(strike);
    const correct = !!hit && hit.zone === game.targetZone;
    const label = strike.side + " " + strike.type;
    $("last-move").textContent = label;
    flashAttackCollider(colliderNameForStrike(strike), !!hit);

    if (correct) {
      game.combo = Math.min(game.combo + 1, 12);
      const damage = Math.round((6 + strike.power * 6) * (1 + game.combo * 0.08));
      game.enemyHp = clamp(game.enemyHp - damage, 0, 100);
      game.score += damage + game.combo;
      setFeed("Clean " + targetNames[hit.zone].toLowerCase() + " hit: " + damage + " damage.");
      impactAt(hit.center, 0xffdb7a);
      playBlip(360 + game.combo * 35, 0.08);
      changeTarget();
    } else if (hit) {
      game.combo = 0;
      const damage = Math.round(2 + strike.power);
      game.enemyHp = clamp(game.enemyHp - damage, 0, 100);
      setFeed("Collider touched " + targetNames[hit.zone].toLowerCase() + ", wrong target.");
      impactAt(hit.center, 0x9aa5b5);
      playBlip(180, 0.07);
    } else {
      game.combo = 0;
      setFeed("Whiff. No collider contact.");
      playBlip(110, 0.05);
    }

    if (game.enemyHp <= 0) finishRound("Enemy down.");
    updateHud();
  }

  function launchEnemyAttack(t) {
    const types = ["high", "body", "flank"];
    const type = types[Math.floor(Math.random() * types.length)];
    game.enemyAttack = {
      type,
      startedAt: t,
      landsAt: t + 1.05,
      resolved: false
    };
    setFeed(attackNames[type] + ".");
  }

  function resolveEnemyAttack(attack) {
    if (!game.running || attack.resolved) return;
    attack.resolved = true;
    let defended = false;
    if (attack.type === "high") defended = pose.guard || pose.crouch;
    if (attack.type === "body") defended = pose.guard;
    if (attack.type === "flank") defended = Math.abs(pose.lean) > 0.34;

    if (defended) {
      game.combo = Math.min(game.combo + 1, 12);
      setFeed("Defense held.");
      impactAt(new THREE.Vector3(-0.9, 1.1, -0.05), 0x42d983);
      playBlip(460, 0.05);
    } else {
      const damage = attack.type === "body" ? 9 : 7;
      game.playerHp = clamp(game.playerHp - damage, 0, 100);
      game.combo = 0;
      setFeed("Hit taken: " + damage + ".");
      impactAt(new THREE.Vector3(-0.9, 1.15, -0.05), 0xf25c66);
      playBlip(120, 0.12);
    }

    if (game.playerHp <= 0) finishRound("Player down.");
    updateHud();
  }

  let audioCtx = null;
  function playBlip(freq, dur) {
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
        p.mesh.geometry.dispose();
        p.mesh.material.dispose();
        particles.splice(i, 1);
      }
    }
  }

  function setFeed(text) {
    $("event-feed").textContent = text;
  }

  function updateHud() {
    $("player-hp").style.width = game.playerHp + "%";
    $("enemy-hp").style.width = game.enemyHp + "%";
    $("player-hp-text").textContent = Math.round(game.playerHp);
    $("enemy-hp-text").textContent = Math.round(game.enemyHp);
    $("round-time").textContent = Math.max(0, Math.ceil(game.timeLeft));
    $("combo-readout").textContent = "x" + game.combo;
    $("target-zone").textContent = game.running ? targetNames[game.targetZone] : "Standby";
    $("target-window").textContent = game.running ? "Score " + game.score : (game.result || "No round active");

    if (game.enemyAttack && !game.enemyAttack.resolved) {
      $("incoming-zone").textContent = attackNames[game.enemyAttack.type];
      $("incoming-window").textContent = "Landing";
      $("tag-guard").classList.toggle("warn", game.enemyAttack.type === "high" || game.enemyAttack.type === "body");
      $("tag-lean").classList.toggle("warn", game.enemyAttack.type === "flank");
    } else {
      $("incoming-zone").textContent = "Clear";
      $("incoming-window").textContent = game.running ? "Next pressure" : "No pressure";
      $("tag-guard").classList.remove("warn");
      $("tag-lean").classList.remove("warn");
    }
  }

  function updateGame(dt, t) {
    if (!game.running) {
      return;
    }

    game.timeLeft = Math.max(0, game.roundEndsAt - t);
    if (game.timeLeft <= 0) finishRound(game.enemyHp < game.playerHp ? "Decision win." : "Time.");

    if (t > game.targetExpiresAt) {
      game.combo = 0;
      changeTarget();
    }

    if (!game.enemyAttack && t >= game.nextEnemyAt) {
      launchEnemyAttack(t);
    }

    if (game.enemyAttack) {
      const attack = game.enemyAttack;
      const windup = clamp((t - attack.startedAt) / (attack.landsAt - attack.startedAt), 0, 1);
      attackMat.opacity = 0.08 + windup * 0.42;
      attackArc.scale.setScalar(0.85 + windup * 0.55);
      attackArc.rotation.z = attack.type === "flank" ? Math.PI / 2 : 0;
      attackArc.position.y = attack.type === "high" ? 1.32 : attack.type === "body" ? 0.92 : 1.05;
      if (t >= attack.landsAt) {
        resolveEnemyAttack(attack);
        game.enemyAttack = null;
        game.nextEnemyAt = t + 2.1 + Math.random() * 1.4;
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
      mesh.visible = true;

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
    const hasSmpl = smplIsFresh(t);
    if (smplMesh) smplMesh.visible = hasSmpl;
    setPoseState(hasSmpl);
    if (!hasSmpl) {
      clearSmplPoseState();
    }

    updateAttackColliderMeshes(t);

    const pulse = 1 + Math.sin(t * 5.6) * 0.08;
    targetOrb.scale.setScalar(pulse);
    targetRing.scale.setScalar(1.0 + Math.sin(t * 6.2) * 0.13);
    targetRing.rotation.y += 0.015;
    targetRing.lookAt(camera.position);
  }

  function setPoseState(ok) {
    if (poseStateOk === ok) return;
    poseStateOk = ok;
    $("tag-smpl").classList.toggle("on", ok);
    $("ws-dot").classList.toggle("on", ok);
    $("ws-state").textContent = ok ? "SMPL Live" : "SMPL Waiting";
  }

  $("start-btn").addEventListener("click", startRound);
  $("reset-btn").addEventListener("click", resetRound);
  $("recenter-btn").addEventListener("click", () => {
    if (sendToBridge && sendToBridge({ cmd: "reset_origin" })) {
      setFeed("Player position reset.");
    } else {
      setFeed("SMPL bridge not connected.");
    }
  });

  let last = nowSec();
  let lastRenderAt = 0;
  function frame() {
    if (!active) return;
    requestAnimationFrame(frame);
    const t = nowSec();
    if (t - lastRenderAt < 1 / MAX_RENDER_FPS) return;
    lastRenderAt = t;
    resize();
    const dt = clamp(t - last, 0.001, 0.05);
    last = t;
    stepSmplMesh(dt);
    updatePoseRender(t);
    updateGame(dt, t);
    updateParticles(dt);
    renderer.render(scene, camera);
  }

  function setActive(on) {
    if (on === active) return;
    active = on;
    if (on) {
      // Velocities from a stale previous sample would read as a fast strike.
      pose.prev.clear();
      pose.vel.clear();
      last = nowSec();
      frame();
    } else if (game.running) {
      finishRound("Round stopped.");
    }
  }

  resize();
  setTargetVisual("head");
  updateHud();

  return {
    setActive,
    setSender(fn) { sendToBridge = fn; },
    onMeshOpen,
    onMeshClose,
    onFaces: setSmplFaces,
    onJoints(joints) { if (active) updateSmplJoints(joints); },
    onVertsFlat(flat) { if (active) updateSmplMeshFlat(flat); },
    onVerts(verts) { if (active) updateSmplMesh(verts); },
  };
})();
