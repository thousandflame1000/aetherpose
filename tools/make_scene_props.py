"""Build the training props of the scene library as self-contained GLB 2.0 files.

    python tools/make_scene_props.py

Writes webui/assets/props/<name>.glb from primitives (boxes, cylinders, cones,
spheres, tori) with PBR material colours, so the library has more than the two
downloaded models and needs no third-party asset host. Only numpy is needed.
The models are original works of this project, dedicated to the public domain
(CC0 1.0). Units are metres, +Y up, resting on y = 0.
"""
import json
import struct
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / 'webui' / 'assets' / 'props'


# ── geometry: each returns (positions, normals, indices) ───────────────────
def box(size, center=(0, 0, 0)):
    sx, sy, sz = (s / 2 for s in size)
    faces = [((1, 0, 0), [(sx, -sy, -sz), (sx, sy, -sz), (sx, sy, sz), (sx, -sy, sz)]),
             ((-1, 0, 0), [(-sx, -sy, sz), (-sx, sy, sz), (-sx, sy, -sz), (-sx, -sy, -sz)]),
             ((0, 1, 0), [(-sx, sy, -sz), (-sx, sy, sz), (sx, sy, sz), (sx, sy, -sz)]),
             ((0, -1, 0), [(-sx, -sy, sz), (-sx, -sy, -sz), (sx, -sy, -sz), (sx, -sy, sz)]),
             ((0, 0, 1), [(-sx, -sy, sz), (sx, -sy, sz), (sx, sy, sz), (-sx, sy, sz)]),
             ((0, 0, -1), [(sx, -sy, -sz), (-sx, -sy, -sz), (-sx, sy, -sz), (sx, sy, -sz)])]
    positions, normals, indices = [], [], []
    for normal, corners in faces:
        base = len(positions)
        positions += [np.add(c, center) for c in corners]
        normals += [normal] * 4
        indices += [base, base + 1, base + 2, base, base + 2, base + 3]
    return np.array(positions, float), np.array(normals, float), np.array(indices)


def lathe(profile, segments=32, center=(0, 0, 0)):
    """Surface of revolution around +Y from (radius, y) points, with flat end caps."""
    profile = np.asarray(profile, float)
    angles = np.linspace(0, 2 * np.pi, segments + 1)
    positions, normals, indices = [], [], []
    # Side: normals from the profile slope.
    for i, (r, y) in enumerate(profile):
        prev, nxt = profile[max(i - 1, 0)], profile[min(i + 1, len(profile) - 1)]
        dr, dy = nxt[0] - prev[0], nxt[1] - prev[1]
        nr, ny = dy, -dr
        length = np.hypot(nr, ny) or 1.0
        for a in angles:
            positions.append((r * np.cos(a), y, r * np.sin(a)))
            normals.append((nr / length * np.cos(a), ny / length, nr / length * np.sin(a)))
    ring = segments + 1
    for i in range(len(profile) - 1):
        for j in range(segments):
            a, b = i * ring + j, (i + 1) * ring + j
            indices += [a, b, a + 1, a + 1, b, b + 1]
    # Caps where the profile ends away from the axis.
    for (r, y), up in ((profile[0], -1.0), (profile[-1], 1.0)):
        if r <= 1e-6:
            continue
        center_index = len(positions)
        positions.append((0, y, 0)); normals.append((0, up, 0))
        for a in angles:
            positions.append((r * np.cos(a), y, r * np.sin(a))); normals.append((0, up, 0))
        for j in range(segments):
            first, second = center_index + 1 + j, center_index + 2 + j
            indices += [center_index, second, first] if up > 0 else [center_index, first, second]
    return np.array(positions, float) + center, np.array(normals, float), np.array(indices)


def cylinder(radius, height, center=(0, 0, 0), segments=32, top_radius=None):
    top = radius if top_radius is None else top_radius
    return lathe([(radius, -height / 2), (top, height / 2)], segments, center)


def sphere(radius, center=(0, 0, 0), segments=32, rings=18):
    profile = [(radius * np.sin(t), -radius * np.cos(t)) for t in np.linspace(0, np.pi, rings + 1)]
    return lathe(profile, segments, center)


def torus(radius, tube, center=(0, 0, 0), segments=32, sides=12, axis='z'):
    positions, normals, indices = [], [], []
    for i in range(segments + 1):
        u = 2 * np.pi * i / segments
        for j in range(sides + 1):
            v = 2 * np.pi * j / sides
            n = np.array([np.cos(u) * np.cos(v), np.sin(u) * np.cos(v), np.sin(v)])
            p = np.array([np.cos(u) * radius, np.sin(u) * radius, 0]) + tube * n
            positions.append(p); normals.append(n)
    for i in range(segments):
        for j in range(sides):
            a, b = i * (sides + 1) + j, (i + 1) * (sides + 1) + j
            indices += [a, b, a + 1, a + 1, b, b + 1]
    positions, normals = np.array(positions), np.array(normals)
    if axis == 'x':  # ring lying in the YZ plane
        rotate = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]])
        positions, normals = positions @ rotate.T, normals @ rotate.T
    return positions + center, normals, np.array(indices)


def rotated(part, matrix):
    positions, normals, indices = part
    centroid = positions.mean(axis=0)
    return (positions - centroid) @ np.asarray(matrix).T + centroid, normals @ np.asarray(matrix).T, indices


ROT_Z = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])  # a +Y cylinder becomes an X one


# ── GLB writer ───────────────────────────────────────────────────────────────
def linear(c):
    """sRGB component to linear: glTF baseColorFactor is linear."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def material(name, color, metallic=0.0, roughness=0.7):
    """color: sRGB components 0-1, as picked by eye."""
    factor = [round(linear(c), 4) for c in color]
    return {'name': name, 'pbrMetallicRoughness': {'baseColorFactor': [*factor, 1.0], 'metallicFactor': metallic,
                                                   'roughnessFactor': roughness}}


def write_glb(path, name, parts):
    """parts: [(material dict, [geometry, ...])]; geometries of one material are merged."""
    binary, views, accessors, primitives, materials = bytearray(), [], [], [], []

    def add(data, target, component, kind, count, minimum=None, maximum=None):
        while len(binary) % 4:
            binary.append(0)
        views.append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(data), 'target': target})
        binary.extend(data)
        accessor = {'bufferView': len(views) - 1, 'componentType': component, 'count': count, 'type': kind}
        if minimum is not None:
            accessor['min'], accessor['max'] = minimum, maximum
        accessors.append(accessor)
        return len(accessors) - 1

    for mat, geometries in parts:
        positions = np.concatenate([g[0] for g in geometries]).astype(np.float32)
        normals = np.concatenate([g[1] for g in geometries])
        normals = (normals / np.linalg.norm(normals, axis=1, keepdims=True)).astype(np.float32)
        offset, indices = 0, []
        for g in geometries:
            indices.append(np.asarray(g[2]) + offset)
            offset += len(g[0])
        indices = np.concatenate(indices).astype(np.uint32)
        position = add(positions.tobytes(), 34962, 5126, 'VEC3', len(positions),
                       positions.min(axis=0).tolist(), positions.max(axis=0).tolist())
        normal = add(normals.tobytes(), 34962, 5126, 'VEC3', len(normals))
        index = add(indices.tobytes(), 34963, 5125, 'SCALAR', len(indices))
        materials.append(mat)
        primitives.append({'attributes': {'POSITION': position, 'NORMAL': normal}, 'indices': index,
                           'material': len(materials) - 1})
    while len(binary) % 4:
        binary.append(0)
    # extras.aetherposeRealScale: the page keeps these real-world sizes instead of
    # normalising the model to 1.2 m like an arbitrary import.
    document = {'asset': {'version': '2.0', 'generator': 'aetherpose tools/make_scene_props.py',
                          'copyright': 'CC0 1.0 — Aetherpose project', 'extras': {'aetherposeRealScale': True}},
                'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'name': name, 'mesh': 0}],
                'meshes': [{'name': name, 'primitives': primitives}], 'materials': materials,
                'accessors': accessors, 'bufferViews': views, 'buffers': [{'byteLength': len(binary)}]}
    text = json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    text += b' ' * (-len(text) % 4)
    chunks = struct.pack('<II', len(text), 0x4E4F534A) + text + struct.pack('<II', len(binary), 0x004E4942) + binary
    path.write_bytes(struct.pack('<III', 0x46546C67, 2, 12 + len(chunks)) + chunks)


# ── props ────────────────────────────────────────────────────────────────────
STEEL = material('steel', (0.55, 0.58, 0.62), 0.8, 0.35)
RUBBER = material('rubber', (0.06, 0.065, 0.075), 0.0, 0.9)
ORANGE = material('orange', (0.94, 0.45, 0.12), 0.0, 0.55)
WHITE = material('white', (0.9, 0.91, 0.93), 0.0, 0.5)
TEAL = material('teal', (0.2, 0.62, 0.67), 0.0, 0.6)
WOOD = material('plywood', (0.72, 0.55, 0.36), 0.0, 0.75)
RED = material('red', (0.72, 0.16, 0.2), 0.0, 0.5)
GREEN = material('leaf', (0.18, 0.48, 0.3), 0.0, 0.8)
DARK = material('charcoal', (0.13, 0.15, 0.18), 0.1, 0.6)


def props():
    yield 'training_cone', '訓練錐', [
        (ORANGE, [lathe([(0.11, 0.03), (0.02, 0.42)], 32)]),
        (WHITE, [lathe([(0.075, 0.2), (0.058, 0.26)], 32)]),
        (DARK, [box((0.28, 0.03, 0.28), (0, 0.015, 0))]),
    ]
    yield 'plyo_box', '跳箱', [
        (WOOD, [box((0.76, 0.6, 0.5), (0, 0.3, 0))]),
        (DARK, [box((0.77, 0.04, 0.51), (0, 0.6, 0)), box((0.77, 0.04, 0.51), (0, 0.02, 0))]),
    ]
    plates = [cylinder(0.11, 0.05, (x, 0.11, 0)) for x in (-0.15, -0.09, 0.09, 0.15)]
    yield 'dumbbell', '啞鈴', [
        (STEEL, [rotated(cylinder(0.018, 0.42, (0, 0.11, 0)), ROT_Z)]),
        (RUBBER, [rotated(p, ROT_Z) for p in plates]),
    ]
    yield 'kettlebell', '壺鈴', [
        (DARK, [sphere(0.12, (0, 0.13, 0)), cylinder(0.08, 0.03, (0, 0.015, 0))]),
        (TEAL, [torus(0.075, 0.017, (0, 0.27, 0), axis='x')]),
    ]
    yield 'standing_bag', '立式沙袋', [
        (RED, [cylinder(0.17, 1.0, (0, 0.82, 0))]),
        (RUBBER, [cylinder(0.175, 0.06, (0, 1.33, 0)), cylinder(0.175, 0.06, (0, 0.31, 0)),
                  lathe([(0.32, 0.0), (0.3, 0.16), (0.12, 0.3)], 40)]),
        (STEEL, [cylinder(0.05, 0.1, (0, 0.27, 0))]),
    ]
    yield 'hurdle', '訓練欄架', [
        (STEEL, [box((0.04, 0.5, 0.04), (-0.4, 0.25, 0)), box((0.04, 0.5, 0.04), (0.4, 0.25, 0)),
                 box((0.04, 0.02, 0.36), (-0.4, 0.01, 0)), box((0.04, 0.02, 0.36), (0.4, 0.01, 0))]),
        (ORANGE, [box((0.86, 0.06, 0.03), (0, 0.48, 0))]),
    ]
    yield 'gym_ball', '健身球', [
        (TEAL, [sphere(0.33, (0, 0.33, 0), 40, 24)]),
        (WHITE, [torus(0.331, 0.006, (0, 0.33, 0), 64, 6)]),
    ]
    yield 'bench', '訓練椅', [
        (DARK, [box((1.2, 0.09, 0.3), (0, 0.45, 0))]),
        (STEEL, [box((0.05, 0.4, 0.26), (-0.5, 0.2, 0)), box((0.05, 0.4, 0.26), (0.5, 0.2, 0)),
                 box((0.08, 0.03, 0.42), (-0.5, 0.015, 0)), box((0.08, 0.03, 0.42), (0.5, 0.015, 0))]),
    ]
    yield 'potted_plant', '盆栽', [
        (WHITE, [lathe([(0.15, 0.0), (0.2, 0.4)], 32)]),
        (GREEN, [sphere(0.24, (0, 0.62, 0), 12, 8), sphere(0.17, (0.12, 0.84, 0.04), 12, 8),
                 sphere(0.15, (-0.11, 0.8, -0.06), 12, 8), sphere(0.12, (0.0, 1.0, 0.0), 12, 8)]),
    ]
    yield 'balance_pad', '平衡墊', [
        (TEAL, [lathe([(0.3, 0.0), (0.3, 0.05), (0.27, 0.07)], 48)]),
    ]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    catalogue = []
    for file_name, label, parts in props():
        write_glb(OUT / f'{file_name}.glb', file_name, parts)
        catalogue.append((file_name, label))
        print(f'{file_name}.glb  {label}')
    return catalogue


if __name__ == '__main__':
    main()
