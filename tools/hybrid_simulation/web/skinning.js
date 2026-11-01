// The body mesh is skinned here, in the page: the pose service sends the SMPL template, rest
// joints, parents and each vertex's four bone weights once, then the 24 joint rotations and the
// translation with every pose. Same linear blend skinning as frontend/smpl_fk.py lbs_frame, with
// the pelvis as origin plus the translation (what the service used to send as vertices).
const smplSkinning = (() => {
  const JOINTS = 24, WEIGHTS = 4;
  const finite = values => Array.isArray(values) && values.every(Number.isFinite);

  // The skin as sent by the service, checked once; null when it is not usable.
  function load(skin) {
    if (!skin || !finite(skin.template) || !finite(skin.joints) || !finite(skin.weights) ||
        !Array.isArray(skin.parents) || !Array.isArray(skin.bones)) return null;
    const count = skin.template.length / 3;
    if (!count || !Number.isInteger(count) || skin.joints.length !== JOINTS * 3 || skin.parents.length !== JOINTS ||
        skin.bones.length !== count * WEIGHTS || skin.weights.length !== count * WEIGHTS) return null;
    // Each joint's parent comes before it (the root has -1), so one pass chains the transforms.
    if (skin.parents[0] !== -1 || !skin.parents.every((p, j) => j === 0 || (Number.isInteger(p) && p >= 0 && p < j))) return null;
    if (!skin.bones.every(b => Number.isInteger(b) && b >= 0 && b < JOINTS)) return null;
    return {
      count,
      template: Float32Array.from(skin.template),
      joints: Float64Array.from(skin.joints),
      parents: Int8Array.from(skin.parents),
      bones: Uint8Array.from(skin.bones),
      weights: Float32Array.from(skin.weights),
    };
  }

  // Vertices (x, y, z per vertex) for one pose: `rotations` is 24 row-major 3x3 local rotations.
  function pose(skin, rotations, translation, out = new Float32Array(skin.count * 3)) {
    if (!skin || !finite(rotations) || rotations.length !== JOINTS * 9 || !finite(translation) || translation.length !== 3) return null;
    const A = new Float64Array(JOINTS * 9), t = new Float64Array(JOINTS * 3), J = skin.joints;
    for (let j = 0; j < JOINTS; j++) {
      const p = skin.parents[j], r = j * 9;
      if (p < 0) {
        for (let k = 0; k < 9; k++) A[r + k] = rotations[r + k];
        for (let k = 0; k < 3; k++) t[j * 3 + k] = J[j * 3 + k];
        continue;
      }
      // World transform = parent's world transform after (local rotation, offset from the parent).
      const q = p * 9;
      for (let row = 0; row < 3; row++) {
        for (let col = 0; col < 3; col++) {
          A[r + row * 3 + col] = A[q + row * 3] * rotations[r + col] + A[q + row * 3 + 1] * rotations[r + 3 + col] +
            A[q + row * 3 + 2] * rotations[r + 6 + col];
        }
        const dx = J[j * 3] - J[p * 3], dy = J[j * 3 + 1] - J[p * 3 + 1], dz = J[j * 3 + 2] - J[p * 3 + 2];
        t[j * 3 + row] = A[q + row * 3] * dx + A[q + row * 3 + 1] * dy + A[q + row * 3 + 2] * dz + t[p * 3 + row];
      }
    }
    // Bone transform: rest-pose point -> posed point, i.e. A v + (t - A J_rest).
    const b = new Float64Array(JOINTS * 3);
    for (let j = 0; j < JOINTS; j++) {
      for (let row = 0; row < 3; row++) {
        b[j * 3 + row] = t[j * 3 + row] - (A[j * 9 + row * 3] * J[j * 3] + A[j * 9 + row * 3 + 1] * J[j * 3 + 1] +
          A[j * 9 + row * 3 + 2] * J[j * 3 + 2]);
      }
    }
    // Pelvis origin plus the pose's translation.
    const ox = translation[0] - J[0], oy = translation[1] - J[1], oz = translation[2] - J[2];
    const v = skin.template, bones = skin.bones, weights = skin.weights;
    for (let i = 0; i < skin.count; i++) {
      const x = v[i * 3], y = v[i * 3 + 1], z = v[i * 3 + 2];
      let px = 0, py = 0, pz = 0;
      for (let k = 0; k < WEIGHTS; k++) {
        const w = weights[i * WEIGHTS + k];
        if (!w) continue;
        const bone = bones[i * WEIGHTS + k], m = bone * 9, o = bone * 3;
        px += w * (A[m] * x + A[m + 1] * y + A[m + 2] * z + b[o]);
        py += w * (A[m + 3] * x + A[m + 4] * y + A[m + 5] * z + b[o + 1]);
        pz += w * (A[m + 6] * x + A[m + 7] * y + A[m + 8] * z + b[o + 2]);
      }
      out[i * 3] = px + ox; out[i * 3 + 1] = py + oy; out[i * 3 + 2] = pz + oz;
    }
    return out;
  }

  return { load, pose };
})();
