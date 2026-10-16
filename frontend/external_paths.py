"""
Where the external TransPose code, SMPL model, pretrained weights and DIP-IMU
data live. They are not in the repository (licences and size), so each machine
names their location, checked in this order for every item:

  1. environment variable (AETHER_TRANSPOSE_DIR, AETHER_SMPL_NPZ, ...)
  2. aetherpose/external_paths.json (copy external_paths.example.json)
  3. the default location under aetherpose/external/

Relative paths in the JSON file are relative to the aetherpose folder.

    python frontend/external_paths.py

prints what was found and exits with code 1 when a required item is missing.
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_DIR / 'external_paths.json'
DEFAULT_DIR = PROJECT_DIR / 'external'


@dataclass(frozen=True)
class Item:
    key: str
    env: str
    default: str
    label: str
    required: bool
    marker: str = ''  # file that must exist inside a directory item


ITEMS = (
    Item('transpose_dir', 'AETHER_TRANSPOSE_DIR', 'TransPose', 'TransPose 原始碼', True, 'net.py'),
    Item('smpl_npz', 'AETHER_SMPL_NPZ', 'SMPL_MALE.npz', 'SMPL 模型（.npz）', True),
    Item('smpl_pkl', 'AETHER_SMPL_PKL', 'SMPL_MALE.pkl', 'SMPL 模型（.pkl，TransPose 讀取）', True),
    Item('weights', 'AETHER_TRANSPOSE_WEIGHTS', 'weights.pt', 'TransPose 預訓練權重', True),
    Item('dip_root', 'AETHER_DIP_ROOT', 'DIP_IMU', 'DIP-IMU 資料（示範資料用）', False),
)


def resolve(env=None, config_file=CONFIG_FILE):
    """Return ({key: Path}, [problem, ...]). Never raises: a bad config file is
    reported as a problem and ignored, so the caller can still show a status."""
    env = os.environ if env is None else env
    config_file = Path(config_file)
    problems = []
    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding='utf-8-sig'))
            if not isinstance(config, dict):
                raise ValueError('expected a JSON object')
        except (OSError, ValueError) as e:
            problems.append(f'{config_file.name} ignored: {e}')
            config = {}
    known = {item.key for item in ITEMS}
    for key in config:
        if key not in known and not key.startswith('_'):
            problems.append(f'{config_file.name}: unknown key "{key}"')

    paths = {}
    for item in ITEMS:
        raw = env.get(item.env) or config.get(item.key)
        if raw is not None and not isinstance(raw, str):
            problems.append(f'{config_file.name}: "{item.key}" must be a path string')
            raw = None
        path = Path(raw).expanduser() if raw else DEFAULT_DIR / item.default
        paths[item.key] = path if path.is_absolute() else PROJECT_DIR / path
    return paths, problems


def missing(paths, required_only=True):
    """Items whose file (or, for a directory, its marker file) does not exist."""
    lacking = []
    for item in ITEMS:
        if required_only and not item.required:
            continue
        path = paths[item.key]
        if not (path / item.marker if item.marker else path).exists():
            lacking.append(item)
    return lacking


def main():
    paths, problems = resolve()
    for problem in problems:
        print(f'warning: {problem}')
    lacking = {item.key for item in missing(paths, required_only=False)}
    for item in ITEMS:
        state = 'ok' if item.key not in lacking else ('MISSING' if item.required else 'absent (optional)')
        print(f'{state:18} {item.label}\n{"":18} {paths[item.key]}  [{item.env}]')
    if any(item.required and item.key in lacking for item in ITEMS):
        print(f'\nSet the missing paths in {CONFIG_FILE.name} (copy {CONFIG_FILE.stem}.example.json) '
              'or with the environment variables shown in brackets.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
