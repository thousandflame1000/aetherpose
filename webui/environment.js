// Training hall around the arena. Built from primitives and canvas textures,
// so it needs no downloaded assets. Purely decoration: nothing here is a
// collider, and "fit all" frames the arena, not the hall. The props and accent
// lights are hidden at the "low" quality setting.
window.createAetherEnvironment = (scene, renderer) => {
  const hall = new THREE.Group(); hall.name = 'aether-hall'; scene.add(hall);
  const detail = new THREE.Group(); detail.name = 'aether-hall-detail'; hall.add(detail);
  const anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
  const HALF = 15, HEIGHT = 7.5, FLOOR_Y = -0.06;

  scene.background = new THREE.Color(0x0e131b);
  scene.fog = new THREE.FogExp2(0x0e131b, 0.024);

  // ── helpers ─────────────────────────────────────────────────────────────
  let seed = 7;
  const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  function texture(width, height, draw, repeat = [1, 1]) {
    const canvas = document.createElement('canvas');
    canvas.width = width; canvas.height = height;
    draw(canvas.getContext('2d'), width, height);
    const map = new THREE.CanvasTexture(canvas);
    map.encoding = THREE.sRGBEncoding;
    map.anisotropy = anisotropy;
    if (repeat[0] !== 1 || repeat[1] !== 1) {
      map.wrapS = map.wrapT = THREE.RepeatWrapping;
      map.repeat.set(...repeat);
    }
    return map;
  }
  // Identical materials are shared, so mergeStatic can combine their meshes.
  const materials = new Map();
  function cached(kind, color, options, create) {
    const key = kind + color + JSON.stringify(options, (name, value) => value && value.isTexture ? value.uuid : value);
    if (!materials.has(key)) materials.set(key, create());
    return materials.get(key);
  }
  function standard(color, options = {}) {
    return cached('standard', color, options, () => {
      const material = new THREE.MeshStandardMaterial({ color, roughness: 0.8, metalness: 0, ...options });
      material.color.convertSRGBToLinear();
      if (options.emissive !== undefined) material.emissive.convertSRGBToLinear();
      return material;
    });
  }
  function glow(color, options = {}) {
    return cached('basic', color, options, () => {
      const material = new THREE.MeshBasicMaterial({ color, ...options });
      material.color.convertSRGBToLinear();
      return material;
    });
  }
  // Static, unnamed meshes of `group` that share a material become one mesh
  // (the hall would otherwise cost ~75 extra draw calls). Child groups listed
  // in `skip` are merged separately so they can still be hidden on their own.
  function mergeStatic(group, skip = []) {
    group.updateMatrixWorld(true);
    const inverse = new THREE.Matrix4().copy(group.matrixWorld).invert();
    const buckets = new Map();
    (function collect(node) {
      for (const child of [...node.children]) {
        if (skip.includes(child)) continue;
        if (child.isMesh && !child.isInstancedMesh && !child.name) {
          if (!buckets.has(child.material)) buckets.set(child.material, []);
          buckets.get(child.material).push(child);
        } else collect(child);
      }
    })(group);
    const point = new THREE.Vector3(), normal = new THREE.Vector3();
    for (const [material, meshes] of buckets) {
      if (meshes.length < 2) continue;
      const positions = [], normals = [], uvs = [], indices = [];
      for (const object of meshes) {
        const geometry = object.geometry, matrix = new THREE.Matrix4().multiplyMatrices(inverse, object.matrixWorld);
        const normalMatrix = new THREE.Matrix3().getNormalMatrix(matrix), offset = positions.length / 3;
        const position = geometry.attributes.position, normalAttribute = geometry.attributes.normal, uv = geometry.attributes.uv;
        for (let i = 0; i < position.count; i++) {
          point.fromBufferAttribute(position, i).applyMatrix4(matrix); positions.push(point.x, point.y, point.z);
          normal.fromBufferAttribute(normalAttribute, i).applyMatrix3(normalMatrix).normalize(); normals.push(normal.x, normal.y, normal.z);
          uvs.push(uv ? uv.getX(i) : 0, uv ? uv.getY(i) : 0);
        }
        if (geometry.index) for (let i = 0; i < geometry.index.count; i++) indices.push(geometry.index.getX(i) + offset);
        else for (let i = 0; i < position.count; i++) indices.push(i + offset);
        object.parent.remove(object); geometry.dispose();
      }
      const merged = new THREE.BufferGeometry();
      merged.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      merged.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
      merged.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
      merged.setIndex(indices);
      group.add(new THREE.Mesh(merged, material));
    }
  }
  function mesh(geometry, material, position, parent = hall, rotation) {
    const object = new THREE.Mesh(geometry, material);
    object.position.set(...position);
    if (rotation) object.rotation.set(...rotation);
    parent.add(object);
    return object;
  }
  // Centred text, shrunk until it fits `fit` pixels (92 % of the canvas width by default).
  function brandText(context, text, x, y, size, color, weight = 800, spacing = 0.12, fit = context.canvas.width * 0.92) {
    for (;;) {
      context.font = `${weight} ${size}px "Segoe UI", "Microsoft JhengHei UI", sans-serif`;
      if ('letterSpacing' in context) context.letterSpacing = `${Math.round(size * spacing)}px`;
      if (context.measureText(text).width <= fit || size <= 12) break;
      size = Math.floor(size * 0.94);
    }
    context.fillStyle = color;
    context.textAlign = 'center'; context.textBaseline = 'middle';
    context.fillText(text, x, y);
    if ('letterSpacing' in context) context.letterSpacing = '0px';
  }

  // ── textures ────────────────────────────────────────────────────────────
  const floorMap = texture(1024, 1024, (c, w, h) => {
    c.fillStyle = '#3a2d22'; c.fillRect(0, 0, w, h);
    const row = 64;
    for (let y = 0; y < h; y += row) {
      let x = -random() * 300;
      while (x < w) {
        const length = 220 + random() * 260, shade = 34 + random() * 22;
        c.fillStyle = `rgb(${shade + 22},${shade + 8},${shade - 6})`;
        c.fillRect(x, y, length, row);
        for (let i = 0; i < 6; i++) {  // grain
          c.fillStyle = `rgba(20,12,6,${0.05 + random() * 0.07})`;
          c.fillRect(x, y + random() * row, length, 1 + random() * 2);
        }
        c.fillStyle = 'rgba(10,6,3,.55)'; c.fillRect(x, y, 2, row);
        x += length;
      }
      c.fillStyle = 'rgba(10,6,3,.6)'; c.fillRect(0, y, w, 2);
    }
  }, [7, 7]);
  const wallMap = texture(512, 512, (c, w, h) => {
    const gradient = c.createLinearGradient(0, 0, 0, h);
    gradient.addColorStop(0, '#202a38'); gradient.addColorStop(1, '#161d28');
    c.fillStyle = gradient; c.fillRect(0, 0, w, h);
    c.fillStyle = 'rgba(0,0,0,.35)';
    for (let x = 0; x < w; x += 128) c.fillRect(x, 0, 3, h);
    c.fillStyle = 'rgba(255,255,255,.035)';
    for (let x = 0; x < w; x += 128) c.fillRect(x + 3, 0, 2, h);
  }, [10, 1]);
  const windowMap = texture(512, 384, (c, w, h) => {
    const sky = c.createLinearGradient(0, 0, 0, h);
    sky.addColorStop(0, '#16284a'); sky.addColorStop(0.55, '#3d4f7a'); sky.addColorStop(0.82, '#c9785a'); sky.addColorStop(1, '#e8a868');
    c.fillStyle = sky; c.fillRect(0, 0, w, h);
    c.fillStyle = '#121a2a';  // distant skyline
    let x = 0;
    while (x < w) {
      const width = 18 + random() * 40, height = 30 + random() * 90;
      c.fillRect(x, h - height, width, height);
      c.fillStyle = 'rgba(255,214,140,.55)';
      for (let i = 0; i < 4; i++) c.fillRect(x + 4 + random() * (width - 8), h - height + 6 + random() * (height - 12), 3, 3);
      c.fillStyle = '#121a2a';
      x += width + 2;
    }
    c.fillStyle = '#0b0f16';  // mullions
    c.fillRect(0, 0, w, 10); c.fillRect(0, h - 10, w, 10); c.fillRect(0, 0, 10, h); c.fillRect(w - 10, 0, 10, h);
    c.fillRect(w / 2 - 5, 0, 10, h); c.fillRect(0, h / 2 - 4, w, 8);
  });
  const screenMap = texture(1024, 360, (c, w, h) => {
    const back = c.createLinearGradient(0, 0, w, h);
    back.addColorStop(0, '#0b1a2c'); back.addColorStop(1, '#10243a');
    c.fillStyle = back; c.fillRect(0, 0, w, h);
    c.strokeStyle = 'rgba(87,188,201,.16)'; c.lineWidth = 2;
    for (let x = -h; x < w; x += 46) { c.beginPath(); c.moveTo(x, h); c.lineTo(x + h, 0); c.stroke(); }
    c.fillStyle = '#57bcc9'; c.fillRect(0, h - 10, w, 10); c.fillRect(0, 0, w, 4);
    brandText(c, 'AETHERPOSE', w / 2, h * 0.5, 118, '#eaf6ff');
  });
  const bannerMap = texture(256, 768, (c, w, h) => {
    c.fillStyle = '#1b3b52'; c.fillRect(0, 0, w, h);
    c.fillStyle = '#57bcc9'; c.fillRect(0, 0, w, 14); c.fillRect(0, h - 40, w, 40);
  });
  // The scoreboard is redrawn by the page: the current game and score during a round.
  let scoreboardState = { title: '準備就緒', value: '', sub: '' };
  function drawScoreboard(c, w, h) {
    c.fillStyle = '#05080d'; c.fillRect(0, 0, w, h);
    c.fillStyle = '#f0a742'; c.fillRect(0, 0, w, 6);
    const { title, value, sub } = scoreboardState;
    if (value) {
      brandText(c, title, w / 2, h * 0.2, 34, '#9fb4cc', 700, 0.1);
      brandText(c, value, w / 2, h * 0.55, 120, '#f0a742', 900, 0.02);
      brandText(c, sub, w / 2, h * 0.86, 30, '#3ecf8e', 700, 0.1);
    } else {
      brandText(c, title, w / 2, sub ? h * 0.36 : h * 0.5, 86, '#3ecf8e', 800, 0.18);
      if (sub) brandText(c, sub, w / 2, h * 0.72, 30, '#9fb4cc', 600, 0.1);
    }
  }
  const scoreboardMap = texture(512, 288, drawScoreboard);
  const matMap = texture(1024, 1024, (c, w, h) => {
    const cx = w / 2, cy = h / 2, r = w / 2;
    c.clearRect(0, 0, w, h);
    c.strokeStyle = 'rgba(87,188,201,.55)'; c.lineWidth = 10;
    c.beginPath(); c.arc(cx, cy, r * 0.94, 0, Math.PI * 2); c.stroke();
    c.strokeStyle = 'rgba(87,188,201,.22)'; c.lineWidth = 4;
    for (const k of [0.62, 0.3]) { c.beginPath(); c.arc(cx, cy, r * k, 0, Math.PI * 2); c.stroke(); }
    c.setLineDash([18, 14]); c.beginPath(); c.moveTo(cx, cy - r * 0.9); c.lineTo(cx, cy + r * 0.9); c.stroke(); c.setLineDash([]);
  });

  // ── hall shell ──────────────────────────────────────────────────────────
  const floor = mesh(new THREE.PlaneGeometry(HALF * 2, HALF * 2),
    standard(0xffffff, { map: floorMap, roughness: 0.62 }), [0, FLOOR_Y, 0], hall, [-Math.PI / 2, 0, 0]);
  floor.name = 'hall-floor'; floor.receiveShadow = true;
  const wallMaterial = standard(0xffffff, { map: wallMap, roughness: 0.9 });
  const wainscot = standard(0x10151d, { roughness: 0.7, metalness: 0.2 });
  for (const [x, z, yaw] of [[0, -HALF, 0], [0, HALF, Math.PI], [-HALF, 0, Math.PI / 2], [HALF, 0, -Math.PI / 2]]) {
    const wall = new THREE.Group(); wall.position.set(x, 0, z); wall.rotation.y = yaw; hall.add(wall);
    mesh(new THREE.PlaneGeometry(HALF * 2, HEIGHT), wallMaterial, [0, HEIGHT / 2 + FLOOR_Y, 0], wall);
    mesh(new THREE.BoxGeometry(HALF * 2, 1.1, 0.08), wainscot, [0, 0.5, 0.04], wall);
    mesh(new THREE.BoxGeometry(HALF * 2, 0.05, 0.05), glow(0x57bcc9), [0, 1.08, 0.09], wall);
    for (let i = -3; i <= 3; i++) {  // pilasters
      mesh(new THREE.BoxGeometry(0.5, HEIGHT, 0.3), wainscot, [i * 4.3, HEIGHT / 2 + FLOOR_Y, 0.15], wall);
    }
  }
  // Windows on the far and side walls, banners above them.
  const windowMaterial = glow(0xffffff, { map: windowMap });
  for (let i = -2; i <= 2; i++) {
    if (i) mesh(new THREE.PlaneGeometry(3.4, 2.5), windowMaterial, [i * 4.3 - Math.sign(i) * 2.15, 3.6, -HALF + 0.31]);
  }
  for (const side of [-1, 1]) {
    for (const z of [-6.45, -2.15, 2.15, 6.45]) {  // between the pilasters
      mesh(new THREE.PlaneGeometry(3.4, 2.5), windowMaterial, [side * (HALF - 0.31), 3.6, z], hall, [0, -side * Math.PI / 2, 0]);
    }
  }
  const bannerMaterial = standard(0xffffff, { map: bannerMap, roughness: 0.85, side: THREE.DoubleSide });
  for (const x of [-10.5, -7.5, 7.5, 10.5]) mesh(new THREE.PlaneGeometry(1.1, 3.3), bannerMaterial, [x, 5.0, -10]);

  // Ceiling: slab, steel beams and rows of light strips.
  mesh(new THREE.PlaneGeometry(HALF * 2, HALF * 2), standard(0x0b0f15, { roughness: 1 }),
    [0, HEIGHT + FLOOR_Y, 0], hall, [Math.PI / 2, 0, 0]);
  const beams = new THREE.InstancedMesh(new THREE.BoxGeometry(HALF * 2, 0.35, 0.22), standard(0x263040, { metalness: 0.5, roughness: 0.5 }), 9);
  const lights = new THREE.InstancedMesh(new THREE.BoxGeometry(3, 0.06, 0.32), glow(0xf2f6ff), 24);
  const placement = new THREE.Object3D();
  for (let i = 0; i < 9; i++) {
    placement.position.set(0, HEIGHT + FLOOR_Y - 0.2, -12 + i * 3); placement.updateMatrix();
    beams.setMatrixAt(i, placement.matrix);
  }
  let light = 0;
  for (let row = 0; row < 6; row++) {
    for (let column = 0; column < 4; column++) {
      placement.position.set(-7.5 + column * 5, HEIGHT + FLOOR_Y - 0.42, -10.5 + row * 4.2); placement.updateMatrix();
      lights.setMatrixAt(light++, placement.matrix);
    }
  }
  beams.name = 'hall-beams'; lights.name = 'hall-ceiling-lights';
  // r128 culls an InstancedMesh by its base geometry at the origin, not by its instances.
  beams.frustumCulled = lights.frustumCulled = false;
  hall.add(beams, lights);

  // ── arena dressing ──────────────────────────────────────────────────────
  // The back wall and columns are colliders (physics.js); these sit on their faces.
  // The wall face is at z = -2.51: the bezel sits on it, the screen just in front.
  mesh(new THREE.BoxGeometry(4.76, 1.78, 0.012), standard(0x0a0d12, { metalness: 0.6, roughness: 0.4 }), [0, 1.3, -2.5035]);
  const screen = mesh(new THREE.PlaneGeometry(4.6, 1.62), glow(0xffffff, { map: screenMap }), [0, 1.3, -2.4965]);
  screen.name = 'arena-screen';
  mesh(new THREE.BoxGeometry(5.8, 0.035, 0.035), glow(0x57bcc9), [0, 2.21, -2.5]);
  for (const side of [-1, 1]) {
    mesh(new THREE.BoxGeometry(0.025, 1.4, 0.02), glow(side < 0 ? 0x57bcc9 : 0xf0a742), [side * 2.45, 0.8, -1.335]);
  }
  const mat = mesh(new THREE.CircleGeometry(2.6, 96), new THREE.MeshBasicMaterial({
    map: matMap, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
  }), [0, -0.0124, 0], hall, [-Math.PI / 2, 0, 0]);
  mat.name = 'arena-mat-markings'; mat.renderOrder = 1;

  // ── props, outside the arena and out of the front and side camera views ─
  const steel = standard(0x3a4554, { metalness: 0.7, roughness: 0.35 });
  const rubber = standard(0x15181d, { roughness: 0.9 });
  // Heavy bags on a frame (left).
  mesh(new THREE.BoxGeometry(0.08, 2.7, 0.08), steel, [-4.6, 1.3, -0.9], detail);
  mesh(new THREE.BoxGeometry(0.08, 2.7, 0.08), steel, [-4.6, 1.3, -3.0], detail);
  mesh(new THREE.BoxGeometry(0.1, 0.1, 2.3), steel, [-4.6, 2.62, -1.95], detail);
  for (const [z, color] of [[-1.45, 0xb8323a], [-2.45, 0x23272e]]) {
    mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.6, 6), steel, [-4.6, 2.28, z], detail);
    mesh(new THREE.CylinderGeometry(0.19, 0.19, 1.05, 24), standard(color, { roughness: 0.55 }), [-4.6, 1.45, z], detail);
    mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.06, 24), rubber, [-4.6, 1.97, z], detail);
    mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.06, 24), rubber, [-4.6, 0.93, z], detail);
  }
  // Dumbbell rack (left front): two tiers of instanced dumbbells.
  mesh(new THREE.BoxGeometry(0.5, 0.05, 1.8), steel, [-3.8, 0.42, 1.1], detail);
  mesh(new THREE.BoxGeometry(0.5, 0.05, 1.8), steel, [-3.8, 0.78, 1.1], detail);
  for (const z of [0.25, 1.95]) mesh(new THREE.BoxGeometry(0.06, 0.8, 0.06), steel, [-3.8, 0.4, z], detail);
  const plates = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.075, 0.075, 0.05, 20), rubber, 24);
  const handles = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.016, 0.016, 0.32, 8), steel, 12);
  let plate = 0, handle = 0;
  for (const y of [0.52, 0.88]) {
    for (let i = 0; i < 6; i++) {
      const z = 0.4 + i * 0.28;
      placement.rotation.set(0, 0, Math.PI / 2);
      placement.position.set(-3.8, y, z); placement.updateMatrix(); handles.setMatrixAt(handle++, placement.matrix);
      for (const dx of [-0.14, 0.14]) {
        placement.position.set(-3.8 + dx, y, z); placement.updateMatrix(); plates.setMatrixAt(plate++, placement.matrix);
      }
    }
  }
  placement.rotation.set(0, 0, 0);
  plates.frustumCulled = handles.frustumCulled = false;
  detail.add(plates, handles);
  // Plyo boxes (left, near the camera side).
  for (const [position, size, color] of [[[-4.9, 0.25, 1.2], [0.75, 0.5, 0.6], 0x2b3442], [[-4.9, 0.66, 1.2], [0.6, 0.32, 0.5], 0xf0a742], [[-5.6, 0.3, 1.5], [0.6, 0.6, 0.6], 0x2b3442]]) {
    mesh(new THREE.BoxGeometry(...size), standard(color, { roughness: 0.7 }), position, detail);
  }
  // Bench and kettlebells (right).
  const bench = new THREE.Group(); bench.position.set(4.6, 0, -1.9); bench.rotation.y = 0.35; detail.add(bench);
  mesh(new THREE.BoxGeometry(0.34, 0.1, 1.25), standard(0x1c2128, { roughness: 0.6 }), [0, 0.46, 0], bench);
  for (const z of [-0.5, 0.5]) mesh(new THREE.BoxGeometry(0.3, 0.42, 0.06), steel, [0, 0.21, z], bench);
  for (let i = 0; i < 4; i++) {
    const kettlebell = new THREE.Group(); kettlebell.position.set(4.1 + i * 0.36, 0, 1.75); detail.add(kettlebell);
    const color = [0x3ecf8e, 0x5b9dff, 0xf0a742, 0xf0576b][i];
    mesh(new THREE.SphereGeometry(0.11 + i * 0.012, 20, 14), standard(0x22262d, { roughness: 0.5, metalness: 0.3 }), [0, 0.12, 0], kettlebell);
    mesh(new THREE.TorusGeometry(0.07, 0.016, 8, 20), standard(color, { roughness: 0.5 }), [0, 0.27, 0], kettlebell);
  }
  // Scoreboard on a stand (right back), turned to face the arena.
  const board = new THREE.Group(); board.position.set(4.9, 0, -3.3); board.rotation.y = -0.85; detail.add(board);
  mesh(new THREE.BoxGeometry(0.08, 1.6, 0.08), steel, [0, 0.8, 0], board);
  mesh(new THREE.BoxGeometry(1.7, 1.0, 0.08), standard(0x0a0d12, { metalness: 0.5, roughness: 0.4 }), [0, 1.9, 0], board);
  mesh(new THREE.PlaneGeometry(1.6, 0.9), glow(0xffffff, { map: scoreboardMap }), [0, 1.9, 0.041], board);
  // Plants and speakers in the back corners.
  const foliage = standard(0x2f7a4f, { roughness: 0.85, flatShading: true });
  for (const side of [-1, 1]) {
    const plant = new THREE.Group(); plant.position.set(side * 3.35, 0, -2.45); detail.add(plant);
    mesh(new THREE.CylinderGeometry(0.2, 0.15, 0.42, 16), standard(0xd9dde3, { roughness: 0.5 }), [0, 0.21, 0], plant);
    for (const [x, y, z, r] of [[0, 0.72, 0, 0.3], [0.13, 0.98, 0.05, 0.2], [-0.12, 0.92, -0.06, 0.22], [0.02, 1.18, 0, 0.15]]) {
      mesh(new THREE.IcosahedronGeometry(r, 0), foliage, [x, y, z], plant);
    }
    // Speakers sit on the corners of the arena wall, angled at the arena, clear of the front view.
    const speaker = new THREE.Group(); speaker.position.set(side * 2.62, 2.2, -2.5); speaker.rotation.y = -side * 0.35; detail.add(speaker);
    mesh(new THREE.BoxGeometry(0.3, 0.42, 0.28), rubber, [0, 0.23, 0], speaker);
    mesh(new THREE.CircleGeometry(0.09, 20), standard(0x2b3340, { roughness: 0.4, metalness: 0.4 }), [0, 0.27, 0.141], speaker);
  }
  // Bleachers along the wall behind the default camera, seen when orbiting.
  for (let step = 0; step < 3; step++) {
    mesh(new THREE.BoxGeometry(12, 0.45, 0.9), standard(step % 2 ? 0x2a3442 : 0x222b37, { roughness: 0.8 }),
      [0, 0.22 + step * 0.45, 11.2 + step * 0.9], detail);
  }

  // Accent lights: cool on the left, warm on the right, no shadows.
  const accents = [];
  for (const [x, color] of [[-5.5, 0x57bcc9], [5.5, 0xf0b070]]) {
    const point = new THREE.PointLight(color, 0.9, 13, 2);
    point.position.set(x, 3.2, -3.4);
    hall.add(point); accents.push(point);
  }

  mergeStatic(hall, [detail]);
  mergeStatic(detail);

  return {
    group: hall,
    // {title, value, sub}: value empty shows the idle board. Redraws only on change.
    setScoreboard(next) {
      const state = { title: String(next.title ?? '準備就緒'), value: String(next.value ?? ''), sub: String(next.sub ?? '') };
      if (JSON.stringify(state) === JSON.stringify(scoreboardState)) return;
      scoreboardState = state;
      const canvas = scoreboardMap.image;
      drawScoreboard(canvas.getContext('2d'), canvas.width, canvas.height);
      scoreboardMap.needsUpdate = true;
    },
    get scoreboard() { return { ...scoreboardState }; },
    setQuality(level) {
      const full = level !== 'low';
      detail.visible = full;
      for (const point of accents) point.visible = full;
    },
  };
};
