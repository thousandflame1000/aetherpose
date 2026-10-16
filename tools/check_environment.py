"""Read-only software preflight. Never install packages, load weights, or touch devices."""
import argparse
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'frontend'))
import external_paths  # noqa: E402


def locked_versions(text):
    pins = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split('#', 1)[0].strip()
        if not line or line.startswith('--extra-index-url '):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s;]+)', line)
        if not match:
            raise ValueError(f'Unsupported lock entry on line {number}: {line}')
        name, version = match.groups()
        key = re.sub(r'[-_.]+', '-', name).lower()
        if key in pins:
            raise ValueError(f'Duplicate locked package: {name}')
        pins[key] = version
    if not pins:
        raise ValueError('Package lock is empty')
    return pins


def package_checks(pins, version_for=metadata.version, strict=False):
    checks = []
    for name, expected in sorted(pins.items()):
        try:
            installed = version_for(name)
        except metadata.PackageNotFoundError:
            checks.append({'name': 'package:' + name, 'status': 'fail',
                           'detail': f'missing; locked={expected}'})
            continue
        checks.append({'name': 'package:' + name,
                       'status': 'pass' if installed == expected else 'fail' if strict else 'warn',
                       'detail': f'installed={installed}; locked={expected}'})
    return checks


def inspect(strict=False):
    checks = []

    def add(name, ok, detail, optional=False):
        checks.append({'name': name, 'status': 'pass' if ok else 'warn' if optional else 'fail',
                       'detail': detail})

    add('python', sys.version_info >= (3, 11) and struct.calcsize('P') == 8,
        f'{platform.python_version()} / {struct.calcsize("P") * 8}-bit; minimum=3.11 / 64-bit')
    add('platform', sys.platform == 'win32', platform.platform())
    checks.extend(package_checks(locked_versions((ROOT / 'frontend/requirements_freeze.txt').read_text(encoding='utf-8')), strict=strict))
    paths, problems = external_paths.resolve()
    for problem in problems:
        add('external-config', False, problem)
    for item in external_paths.ITEMS:
        path = paths[item.key] / item.marker if item.marker else paths[item.key]
        add('external:' + item.key, path.is_file() if item.marker or item.key != 'dip_root' else path.is_dir(),
            str(path), optional=not item.required)
    backend = ROOT / 'target/release/aetherpose.exe'
    add('backend', backend.is_file(), str(backend))
    # The full asset closure is checked by test_project_integration.py.
    for relative in ('webui/index.html', 'webui/vendor/three/three.min.js'):
        add('file:' + relative, (ROOT / relative).is_file(), relative)
    browser = next((str(path) for path in (
        shutil.which('chromium'), shutil.which('google-chrome'),
        Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe',
        Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe',
    ) if path and Path(path).is_file()), None)
    add('browser', browser is not None, browser or 'Chromium/Chrome/Edge not found')
    failed = any(check['status'] == 'fail' for check in checks)
    return {'schema_version': 1, 'status': 'fail' if failed else 'warn' if any(c['status'] == 'warn' for c in checks) else 'pass',
            'strict_lock': strict, 'python_executable': sys.executable, 'checks': checks,
            'limits': ['Package metadata and required file presence only; no model inference or binary import validation.',
                       'No service, network, device, hardware or clean-machine acceptance.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--strict-lock', action='store_true', help='version drift is a failure rather than a warning')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        report = inspect(args.strict_lock)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Preflight failed: {exc}\n')
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        for check in report['checks']:
            print(f'{check["status"].upper():4} {check["name"]}: {check["detail"]}')
        print('Result: ' + report['status'].upper() + '; file/metadata preflight only')
    return int(report['status'] == 'fail')


if __name__ == '__main__':
    sys.exit(main())
