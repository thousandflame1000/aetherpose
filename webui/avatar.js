// Round results and stop reasons stay English codes: round history stores
// them and some mark a completed round. People see them in Chinese.
window.aetherReasonText = (() => {
  const names = {"Time's up":'時間到','Round ended':'中途結束','Pose data expired':'姿態資料過期','Pose source changed':'資料來源改變',
    'Pose disconnected':'姿態服務斷線','Game changed':'切換了遊戲','Switched to Combat':'切換到對打','Training ended':'結束訓練',
    'Tab hidden':'頁面切到背景','Scene changed. Round stopped.':'場景改變，回合停止',
    'Reach area blocked — move scene objects away':'伸手範圍被擋住，請移開場景物件',
    'Enemy down.':'擊倒對手','Player down.':'你被擊倒','Decision win.':'判定勝利','Time.':'時間到','Round reset.':'回合重設',
    'Round stopped.':'回合停止','Pose connection lost. Round stopped.':'姿態服務斷線，回合停止',
    'Pose data expired. Round stopped.':'姿態資料過期，回合停止','Position reset. Round stopped.':'位置重設，回合停止',
    'Tab hidden. Round stopped.':'頁面切到背景，回合停止','Pose source changed. Round stopped.':'資料來源改變，回合停止',
    'Body calibration. Round stopped.':'開始身體校正，回合停止','Body calibration required. Round stopped.':'身體校正失效，回合停止',
    'Display lost':'3D 畫面中斷','Display lost. Round stopped.':'3D 畫面中斷，回合停止'};
  return reason => names[reason] ?? reason;
})();

// One source classification for the controls and every activity.
window.aetherCombatBreakdown = (stats,breakdown) => {
  const types=['high','body','flank'];
  if (!stats || !breakdown || !['received','defended'].every(key=>breakdown[key] && !Array.isArray(breakdown[key]) &&
    types.every(type=>Number.isSafeInteger(breakdown[key][type]) && breakdown[key][type]>=0))) return null;
  if(types.reduce((sum,type)=>sum+breakdown.received[type],0)!==stats.received || types.reduce((sum,type)=>sum+breakdown.defended[type],0)!==stats.defenses) return null;
  return Object.fromEntries(['received','defended'].map(key=>[key,Object.fromEntries(types.map(type=>[type,breakdown[key][type]]))]));
};
window.aetherCombatWeakness = (stats,breakdown) => {
  const details=aetherCombatBreakdown(stats,breakdown);
  return details?['high','body','flank'].filter(type=>details.received[type]>=2 && details.received[type]>details.defended[type])
    .sort((a,b)=>(details.received[b]-details.defended[b])-(details.received[a]-details.defended[a]))[0]??null:null;
};
window.aetherCombatDrill = (stats,breakdown=null) => {
  if (!stats || !['attempts','hits','targets','blocked','defenses','received','counters'].every(key=>Number.isSafeInteger(stats[key])&&stats[key]>=0)) return null;
  if(stats.blocked>=2 && stats.blocked/Math.max(1,stats.attempts)>=.25) return null;
  const weak=aetherCombatWeakness(stats,breakdown);
  if(weak) return weak==='flank'?'dodge':'guard';
  if(stats.received>=2 && stats.received>stats.defenses) return 'guard';
  if(stats.attempts>=3 && stats.hits/stats.attempts<.5 || stats.hits>=3 && stats.targets/stats.hits<.5 || stats.defenses>=2 && stats.counters===0) return 'reach';
  return null;
};
window.aetherCombatAdvice = (stats,breakdown=null) => {
  const fields=['attempts','hits','targets','blocked','defenses','received','counters','bestCombo'];
  if (!stats || !fields.every(key=>Number.isSafeInteger(stats[key]) && stats[key]>=0)) return '練習建議：先完成幾次出手與防守，再比較表現。';
  if (stats.blocked>=2 && stats.blocked/Math.max(1,stats.attempts)>=.25) return '練習建議：先繞過場景障礙，再朝目標出手。';
  const weak=aetherCombatWeakness(stats,breakdown);
  if(weak) return {high:'練習建議：高位攻擊漏防較多，先練雙手防守或蹲下。',body:'練習建議：身體攻擊漏防較多，先練雙手防守，蹲下無法擋住身體攻擊。',flank:'練習建議：側面攻擊漏防較多，先練側身閃避，舉手防守無法擋住側擊。'}[weak];
  if (stats.received>=2 && stats.received>stats.defenses) return '練習建議：先看清來襲提示，練習防守或側身，再急著反擊。';
  if (stats.attempts>=3 && stats.hits/stats.attempts<.5) return '練習建議：先靠近有效距離、放慢出手，讓手腳碰到對手。';
  if (stats.hits>=3 && stats.targets/stats.hits<.5) return '練習建議：看準黃色目標部位再出手，避免一直打錯位置。';
  if (stats.defenses>=2 && stats.counters===0) return '練習建議：防住攻擊後，在 0.8 秒空檔內反擊黃色目標。';
  if (stats.attempts>=5 && stats.hits/stats.attempts>=.8 && stats.targets>=3 && stats.received===0) return '練習建議：命中與防守已穩定，下回合可嘗試更高難度。';
  return '練習建議：保持看提示、出手、回到防守的節奏。';
};
window.aetherCalibrationIssue = (status, phase) => {
  if (phase==='requested') return '已送出身體校正要求：等待姿態服務回應後再開始回合。';
  if (['tpose_ready','tpose','bow_ready','bow'].includes(phase))
    return '身體校正進行中：完成校正後再開始回合。';
  const kind=aetherPoseSource(status).kind;
  if ((kind==='live' || kind==='mixed') && status.includes('uncalibrated'))
    return '即時追蹤器尚未校正：請先到「準備」完成「校正身體」，再開始回合。';
  return '';
};
window.aetherPoseSource = status => {
  const text = typeof status === 'string' ? status : '';
  if (text.startsWith('Error') || text.startsWith('Infer err:'))
    return {kind:'error',label:'推論錯誤',signature:'error'};
  if (text.includes('LIVE 6/6'))
    return {kind:'live',label:'即時動作捕捉',signature:'live:6'};
  if (text.includes('DEBUG')) {
    const match = /\blive ([0-6])\/6\b/.exec(text);
    const count = match ? +match[1] : 0;
    return count ? {kind:'mixed',label:`混合輸入（即時 ${count}/6）`,signature:'mixed:'+count} :
      {kind:'demo',label:'示範資料',signature:'demo:0'};
  }
  return {kind:'waiting',label:text.startsWith('Loading') || text.startsWith('Ready') ?
    '初始化中…' : '等待姿態',signature:'waiting'};
};

// One pose, mesh and skeleton for every activity in the shared scene.
window.createAetherAvatar = (scene) => {
  const root = new THREE.Group();
  root.name = 'aether-avatar';
  scene.add(root);
  const bones = [[0,1],[0,2],[0,3],[1,4],[2,5],[3,6],[4,7],[5,8],[6,9],
    [7,10],[8,11],[9,12],[9,13],[9,14],[12,15],[13,16],[14,17],
    [16,18],[17,19],[18,20],[19,21],[20,22],[21,23]];
  const left = new Set([1,4,7,10,13,16,18,20,22]);
  const combatX = -0.55;
  const validPoint = p => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite);
  let mesh = null, skeleton = null, faces = null, maxIndex = -1;
  let target = null, current = null, joints = null;
  let jointAt = -Infinity, meshAt = -Infinity;
  let combatMode = false;
  let physics=null;
  const anchor = new THREE.Vector3();
  const fresh = (t = performance.now() / 1000) => joints !== null && t - jointAt < 5;

  function onFaces(input) {
    if (!Array.isArray(input) || !input.length || !input.every(f =>
      Array.isArray(f) && f.length === 3 && f.every(i => Number.isInteger(i) && i >= 0 && i <= 0xffffffff))) return false;
    const next = Uint32Array.from(input.flat());
    let highest = -1;
    for (const i of next) highest = Math.max(highest, i);
    // A topology change starts a new mesh; never apply indices to old vertices.
    if (faces && faces.length === next.length && faces.every((v, i) => v === next[i])) return true;
    faces = next;
    maxIndex = highest;
    if (mesh) { root.remove(mesh); mesh.geometry.dispose(); mesh.material.dispose(); mesh = null; }
    current = target = null;
    meshAt = -Infinity;
    return true;
  }

  // Outfit: every vertex takes the colour of its nearest bone, worked out once
  // (SMPL's vertex topology is the same in every pose): jersey, shorts, shoes,
  // light limbs and head. A cool rim light keeps the figure readable in the hall.
  const OUTFIT = (() => {
    const colour = hex => new THREE.Color(hex).convertSRGBToLinear();
    const jersey = colour(0x2f62c9), shorts = colour(0x1b2230), skin = colour(0xd2d9e3), shoe = colour(0x262a33);
    return new Map([[jersey, ['0,3','3,6','6,9','9,12','9,13','9,14','13,16','14,17','16,18','17,19']],
      [shorts, ['0,1','0,2','1,4','2,5']], [skin, ['4,7','5,8','12,15','18,20','19,21','20,22','21,23']], [shoe, ['7,10','8,11']]]
      .flatMap(([c, keys]) => keys.map(key => [key, c])));
  })();
  function paintOutfit() {
    if (!mesh || !joints || mesh.userData.outfit) return;
    const positions = mesh.geometry.attributes.position.array, count = positions.length / 3;
    const colours = new Float32Array(count * 3), segment = new THREE.Line3();
    const point = new THREE.Vector3(), closest = new THREE.Vector3();
    const segments = bones.map(([a, b]) => [new THREE.Line3(new THREE.Vector3(...joints[a]), new THREE.Vector3(...joints[b])), OUTFIT.get(`${a},${b}`)]);
    for (let i = 0; i < count; i++) {
      point.fromArray(positions, i * 3);
      let best = Infinity, colour = null;
      for (const [line, c] of segments) {
        const distance = line.closestPointToPoint(point, true, closest).distanceToSquared(point);
        if (distance < best) { best = distance; colour = c; }
      }
      colour.toArray(colours, i * 3);
    }
    mesh.geometry.setAttribute('color', new THREE.BufferAttribute(colours, 3));
    mesh.material.vertexColors = true; mesh.material.color.setRGB(1, 1, 1); mesh.material.needsUpdate = true;
    mesh.userData.outfit = true;
  }
  function addRimLight(material) {
    material.onBeforeCompile = shader => {
      shader.fragmentShader = shader.fragmentShader.replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
        float aetherRim = pow(1.0 - clamp(dot(normal, normalize(vViewPosition)), 0.0, 1.0), 2.5);
        totalEmissiveRadiance += vec3(0.2, 0.55, 0.62) * aetherRim * 0.55;`);
    };
    return material;
  }

  // Meshes come with every pose (about 45 a second): the previous target is refilled for the
  // one after next instead of allocating a new array each time.
  let spare = null;
  function onVertsFlat(input) {
    if (!faces || !input || input.length % 3 || input.length / 3 <= maxIndex ||
      !input.every(Number.isFinite)) return false;
    const next = spare && spare.length === input.length ? spare : new Float32Array(input.length);
    next.set(input);
    if (!next.every(Number.isFinite)) return false;  // beyond float32 range
    spare = target && target.length === next.length ? target : null;
    target = next;
    if (!mesh || current.length !== next.length) {
      if (mesh) { root.remove(mesh); mesh.geometry.dispose(); mesh.material.dispose(); }
      current = next.slice();
      const geo = new THREE.BufferGeometry();
      const attr = new THREE.BufferAttribute(current, 3);
      attr.setUsage(THREE.DynamicDrawUsage);
      geo.setAttribute('position', attr);
      geo.setIndex(new THREE.Uint32BufferAttribute(faces, 1));
      geo.computeVertexNormals();
      mesh = new THREE.Mesh(geo, addRimLight(new THREE.MeshStandardMaterial({
        color: 0xb6bfcd, roughness: 0.62, metalness: 0.05, side: THREE.DoubleSide
      })));
      mesh.castShadow=true;
      mesh.receiveShadow=true;
      mesh.material.color.convertSRGBToLinear();
      mesh.name = 'aether-body';
      mesh.frustumCulled = false;
      root.add(mesh);
      paintOutfit();
    }
    meshAt = performance.now() / 1000;
    return true;
  }

  // The pose service sends the skinning data once; each pose's mesh is then skinned here.
  let skin = null, skinned = null;
  function onSkin(input) {
    skin = smplSkinning.load(input);
    skinned = skin && new Float32Array(skin.count * 3);
    return skin !== null;
  }
  function onPose(input) {
    const verts = skin && input ? smplSkinning.pose(skin, input.rotations, input.translation, skinned) : null;
    return verts !== null && onVertsFlat(verts);
  }

  function onJoints(input) {
    if (!Array.isArray(input) || input.length !== 24 || !input.every(validPoint)) return false;
    joints = input.map(p => p.slice());
    jointAt = performance.now() / 1000;
    paintOutfit();
    if (combatMode) {
      anchor.set(joints[0][0],0,joints[0][2]);
      applyTransform();
    }
    // Packet-time gameplay consumes the root immediately after onJoints.
    // Apply the same mesh constraint here rather than waiting for the next
    // animation frame, which would briefly use an unconstrained transform.
    if (physics && mesh && jointAt-meshAt<5) physics.constrain(root,mesh.geometry);
    const positions = new Float32Array(bones.length * 6);
    const colors = new Float32Array(positions.length);
    bones.forEach(([a,b], i) => {
      positions.set(joints[a], i * 6);
      positions.set(joints[b], i * 6 + 3);
      const c = left.has(b) ? [0,0.78,0.78] : [1,0.69,0.35];
      colors.set(c, i * 6); colors.set(c, i * 6 + 3);
    });
    if (!skeleton) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage));
      geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
      skeleton = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({vertexColors: true,depthTest:false}));
      skeleton.name = 'aether-skeleton';
      skeleton.renderOrder = 2;
      skeleton.frustumCulled = false;
      root.add(skeleton);
    } else {
      skeleton.geometry.attributes.position.array.set(positions);
      skeleton.geometry.attributes.position.needsUpdate = true;
    }
    return true;
  }

  function tick(dt, t) {
    applyTransform();
    root.visible = fresh(t);
    if (physics && !root.visible) physics.reset(root);
    if (mesh) {
      mesh.visible = t - meshAt < 5;
      let changed = false;
      // Ease toward each pose's mesh (about 33 ms behind): smooths the model's jitter between
      // poses without trailing far behind the joints the games use.
      const blend = 1 - Math.exp(-Math.max(0, dt) * 30);
      for (let i = 0; i < current.length; i++) {
        const d = target[i] - current[i];
        if (Math.abs(d) > 0.00001) { current[i] += d * blend; changed = true; }
      }
      if (changed) { mesh.geometry.attributes.position.needsUpdate = true; mesh.geometry.computeVertexNormals(); }
    }
    if (skeleton) skeleton.visible = debugVisible || !mesh || !mesh.visible;
    if (physics && root.visible && mesh && mesh.visible) physics.constrain(root,mesh.geometry);
    if (physics) physics.updateDebug(root,mesh && mesh.visible?mesh.geometry:null);
  }

  let debugVisible = false;

  function applyTransform() {
    const scale = combatMode ? 0.96 : 1;
    root.position.set(combatMode ? combatX - anchor.x * scale : 1.1,
      0.97 * scale, combatMode ? -anchor.z * scale : 0);
    root.scale.setScalar(scale);
    root.updateMatrixWorld(true);
  }
  function setMode(combat) {
    combatMode = combat;
    anchor.set(combat && joints ? joints[0][0] : 0,0,combat && joints ? joints[0][2] : 0);
    applyTransform();
  }
  setMode(false);
  return { root, combatX, fresh, tick, setMode, onFaces, onVertsFlat, onSkin, onPose, onJoints,
    setPhysics(value) { physics=value; },
    setDebug(on) { debugVisible=Boolean(on); },
    get joints() { return joints; },
    disconnect() {
      if (physics) physics.reset(root);
      jointAt = meshAt = -Infinity;
      root.visible = false;
    }
  };
};
