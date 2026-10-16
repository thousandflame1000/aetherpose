"""Compare CPU backends against FP32 on fixed inputs; never changes the service.

This measures numerical agreement with the same pretrained model, not accuracy
against a human ground truth. Models/weights and raw datasets are not exported.
INT8 is an offline experimental candidate only, never a service default.
"""
import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'frontend'))
import external_paths


def synthetic_input(frames):
    t = np.arange(frames)[:, None] / 60
    axes = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [0, 1, 1], [1, 0, 1]], float)
    axes /= np.linalg.norm(axes, axis=1, keepdims=True)
    angles = .6 * np.sin(2 * np.pi * (.4 + .15 * np.arange(6)) * t)
    ori = Rotation.from_rotvec((angles[..., None] * axes).reshape(-1, 3)).as_matrix().reshape(frames, 6, 3, 3)
    acc = .8 * np.sin(2 * np.pi * .7 * t)[..., None] * np.ones((frames, 6, 3))
    return acc.astype(np.float32), ori.astype(np.float32)


def deviation(candidate, reference):
    angles, roots, matrix_error = [], [], []
    for (a, ta), (b, tb) in zip(candidate, reference):
        cosine = (np.einsum('...ij,...ij->...', a, b) - 1) / 2
        angles.extend(np.degrees(np.arccos(np.clip(cosine, -1, 1))))
        roots.append(float(np.linalg.norm(ta - tb)))
        matrix_error.append(float(np.max(np.abs(a - b))))
    return {'mean_joint_deg': float(np.mean(angles)), 'max_joint_deg': float(np.max(angles)),
            'max_root_m': max(roots), 'max_rotation_element_error': max(matrix_error)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames', type=int, default=120)
    parser.add_argument('--batches', type=int, nargs='+', default=[1, 3, 8])
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--backends', nargs='+', choices=['mkldnn', 'native', 'int8'], default=['mkldnn', 'native'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 60 <= args.frames <= 1800 or not 1 <= args.rounds <= 5 or not 1 <= args.threads <= 8:
        parser.error('frames 60–1800, rounds 1–5, threads 1–8 required')
    if any(batch not in (1, 3, 8) or args.frames % batch for batch in args.batches):
        parser.error('batches must be 1, 3 or 8, each dividing frames exactly')
    if args.output.exists():
        parser.error('output must not exist')
    if not args.backends or args.backends[0] != 'mkldnn':
        parser.error('mkldnn must be first to establish the FP32 reference')
    paths, problems = external_paths.resolve()
    if problems or external_paths.missing(paths):
        parser.error('external resources missing; check frontend/external_paths.py')
    import torch
    import transpose_runner
    import config as model_config
    model_config.paths.smpl_file = str(paths['smpl_pkl'])
    model_config.paths.weights_file = str(paths['weights'])
    from net import TransPoseNet
    from utils import normalize_and_concat
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    acc, ori = synthetic_input(args.frames)
    xs = normalize_and_concat(torch.from_numpy(acc), torch.from_numpy(ori))
    report = {'torch': torch.__version__, 'python': sys.version, 'platform': platform.platform(),
              'input': 'synthetic six-sensor motion, 60 Hz; not physical input',
              'frames': args.frames, 'threads': args.threads, 'rounds': args.rounds,
              'requested_backends': args.backends,
              'agreement_targets': {'mean_joint_deg': .1, 'max_joint_deg': 1.0, 'max_root_m': .01},
              'runs': []}
    reference = {}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve a fresh report before expensive work, retaining partial evidence on failure.
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    for round_index in range(args.rounds):
        for batch in args.batches:
            for backend in (args.backends if round_index % 2 == 0 else list(reversed(args.backends))):
                enabled = backend != 'native'
                net = TransPoseNet().eval()
                if backend == 'int8':
                    net = torch.ao.quantization.quantize_dynamic(
                        net, {torch.nn.LSTM, torch.nn.Linear}, dtype=torch.qint8)
                results, wall, cpu = [], [], []
                with torch.inference_mode(), torch.backends.mkldnn.flags(enabled=enabled):
                    for _ in range(8):
                        transpose_runner.forward_online_frames(net, xs[:batch])
                    net.reset()
                    for i in range(0, args.frames, batch):
                        started, cpu_started = time.perf_counter(), time.process_time()
                        pose, position = transpose_runner.forward_online_frames(net, xs[i:i + batch])
                        wall.append((time.perf_counter()-started)*1000)
                        cpu.append((time.process_time()-cpu_started)*1000)
                        results.append((pose.numpy().copy(), position.numpy().copy()))
                if batch not in reference and backend == 'mkldnn':
                    reference[batch] = results
                error = deviation(results, reference[batch])
                measured = wall[3:]  # first three calls retained but excluded from summary
                run = {'round': round_index + 1, 'batch': batch, 'backend': backend, 'mkldnn': enabled,
                       'wall_ms': wall, 'process_cpu_ms': cpu,
                       'median_ms': statistics.median(measured),
                       'p95_ms': float(np.percentile(measured, 95)), 'deviation': error,
                       'agreement_passed': all(error[k] <= v for k, v in report['agreement_targets'].items())}
                report['runs'].append(run)
                args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
                print(json.dumps({k: v for k, v in run.items() if k not in ('wall_ms', 'process_cpu_ms')}), flush=True)
    report['completed'] = True
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
