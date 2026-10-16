"""Build and verify a source-only review package, without personal runtime data."""
import argparse
import hashlib
import json
import stat
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'aetherpose/'
MANIFEST = 'SUBMISSION_MANIFEST.json'
NOTES = 'PACKAGE_NOTES.md'
ROOT_FILES = {'.gitignore', 'Cargo.toml', 'Cargo.lock', 'README.md', 'HANDOFF.md',
              'EXTERNAL_DEPENDENCIES.md', 'external_paths.example.json',
              'setup.ps1', 'run.ps1', 'stop.ps1'}
EXTENSIONS = {
    'src': {'.rs', '.ino', '.c', '.h', '.cpp', '.md', '.txt'},
    'frontend': {'.py', '.txt'},
    'tools': {'.py', '.md'},
    'tests': {'.py', '.rs', '.cjs', '.js', '.ps1', '.cpp'},
    'docs': {'.md'},
    'webui': {'.html', '.css', '.js', '.py', '.ps1', '.md', '.json', '.txt'},
}
STATIC_FILES = {'docs/aetherpose.png', 'docs/combat-results.png',
                'webui/assets/robot/RobotExpressive.glb', 'webui/assets/lantern/Lantern.glb'} | {
    f'webui/assets/props/{name}.glb' for name in
    ('balance_pad', 'bench', 'dumbbell', 'gym_ball', 'hurdle', 'kettlebell',
     'plyo_box', 'potted_plant', 'standing_bag', 'training_cone')}
REQUIRED = ROOT_FILES | {'src/main.rs', 'frontend/mesh_bridge.py', 'frontend/external_paths.py',
                         'frontend/requirements.txt', 'frontend/requirements_freeze.txt',
                         'webui/index.html', 'webui/server.py', 'webui/services.ps1',
                         'tests/run_software_checks.ps1', 'tools/package_submission.py',
                         'src/skeleton/tracker_firmware/src/Fusion/LICENSE.md',
                         'webui/vendor/three/LICENSE', 'webui/assets/README.md',
                         'webui/assets/robot/README.md', 'webui/assets/lantern/SOURCE.md'}
MAX_BYTES = 512 * 1024 * 1024
PACKAGE_NOTES = """# Aetherpose source review package

This archive contains the working source tree, including uncommitted source.
SUBMISSION_MANIFEST.json lists every payload file with its size and SHA-256.
Hashes detect damage or modification; they are not a signature or approval.

Verify without extracting:
    python tools/package_submission.py verify <archive.zip>

On a Windows development machine, extract into a new directory, read HANDOFF.md,
run setup.ps1, configure external_paths.json from external_paths.example.json,
then run run.ps1. Obtain required external models/weights/code separately using
EXTERNAL_DEPENDENCIES.md. No model, dataset or private path configuration is bundled.

This is source, not a standalone executable. Python, Rust, dependencies and
appropriately obtained external resources are needed. Arduino upload is optional
and must be requested explicitly with setup.ps1 -FlashFirmware.

config.json, external_paths.json, local .cargo settings, logs, recordings,
experiments, build output and virtual environments are intentionally excluded.
The backend generates default configuration when no config.json exists.
Final Word reports, slides and human experiment videos are separate deliverables.
docs/thesis-source.md is a review draft, not the final signed report.

Software test history is documented in docs/acceptance-status.md. An archive
verification is not hardware acceptance, clean-machine installation proof, or
evidence that performance requirements have all been achieved.
"""


def safe_relative(name):
    path = PurePosixPath(name)
    reserved = {'con', 'prn', 'aux', 'nul'} | {f'{prefix}{i}' for prefix in ('com', 'lpt') for i in range(1, 10)}
    return (bool(name) and '\\' not in name and ':' not in name and '\x00' not in name
            and not path.is_absolute() and '..' not in path.parts
            and all(part.rstrip(' .') == part and part.split('.', 1)[0].casefold() not in reserved for part in path.parts)
            and path.as_posix() == name and not name.endswith('/'))


def allowed(name):
    if not safe_relative(name):
        return False
    if name in ROOT_FILES or name in STATIC_FILES or name in {NOTES, 'webui/vendor/three/LICENSE'}:
        return True
    parts = PurePosixPath(name).parts
    if len(parts) < 2 or parts[0] not in EXTENSIONS:
        return False
    if any(p.startswith('.') or p == '__pycache__' for p in parts):
        return False
    if parts[-1] in {'config.json', 'external_paths.json'}:
        return False
    return PurePosixPath(name).suffix.lower() in EXTENSIONS[parts[0]]


def linked(path):
    info = path.lstat()
    # Reparse-point detection also covers junctions on Python 3.10/3.11,
    # which do not yet expose Path.is_junction().
    return (stat.S_ISLNK(info.st_mode) or
            bool(getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)))


def payload_files(root):
    root = root.resolve()

    def walk(directory):
        for path in sorted(directory.iterdir()):
            if path.name.startswith('.') or path.name == '__pycache__':
                continue
            if linked(path):
                raise ValueError(f'Link or junction refused: {path.relative_to(root)}')
            path.resolve().relative_to(root)
            if path.is_dir():
                yield from walk(path)
            elif allowed(path.relative_to(root).as_posix()):
                yield path

    for name in sorted(ROOT_FILES):
        path = root / name
        try:
            is_link = linked(path)
        except FileNotFoundError:
            continue
        if is_link:
            raise ValueError(f'Link refused: {name}')
        if path.is_file():
            yield path
    for name in EXTENSIONS:
        directory = root / name
        try:
            is_link = linked(directory)
        except FileNotFoundError:
            continue
        if is_link:
            raise ValueError(f'Link or junction refused: {name}')
        if directory.is_dir():
            yield from walk(directory)


def build(root, output):
    root = root.resolve()
    files = list(payload_files(root))
    names = {p.relative_to(root).as_posix() for p in files}
    missing = REQUIRED - names
    if missing:
        raise ValueError(f'Missing required source/notice files: {sorted(missing)}')
    if sum(p.stat().st_size for p in files) > MAX_BYTES:
        raise ValueError('Source package exceeds size limit')
    payload = {p.relative_to(root).as_posix(): p.read_bytes() for p in files}
    payload[NOTES] = PACKAGE_NOTES.encode('utf-8')
    manifest = {'schema_version': 1, 'kind': 'source-review',
                'created_utc': datetime.now(timezone.utc).isoformat(),
                'hardware_acceptance': False,
                'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in sorted(payload.items())}}
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create: an earlier review package and its evidence are never overwritten.
    with output.open('xb') as stream, ZipFile(stream, 'w', ZIP_DEFLATED) as archive:
        for name, data in sorted(payload.items()):
            archive.writestr(PREFIX + name, data)
        archive.writestr(PREFIX + MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
    return verify(output)


def verify(path):
    with ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
            raise ValueError('Duplicate or case-colliding archive paths')
        if sum(entry.file_size for entry in entries) > MAX_BYTES:
            raise ValueError('Archive exceeds expanded size limit')
        for entry in entries:
            if (not entry.filename.startswith(PREFIX) or not safe_relative(entry.filename[len(PREFIX):])
                    or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1):
                raise ValueError(f'Unsafe archive entry: {entry.filename}')
        if PREFIX + MANIFEST not in names:
            raise ValueError('Missing manifest')
        if archive.getinfo(PREFIX + MANIFEST).file_size > 4 * 1024 * 1024:
            raise ValueError('Manifest exceeds size limit')
        manifest = json.loads(archive.read(PREFIX + MANIFEST))
        if (not isinstance(manifest, dict) or manifest.get('schema_version') != 1 or manifest.get('kind') != 'source-review'
                or manifest.get('hardware_acceptance') is not False):
            raise ValueError('Unsupported package schema')
        files = manifest.get('files')
        if not isinstance(files, dict) or not REQUIRED | {NOTES} <= set(files):
            raise ValueError('Required source/notice files missing from manifest')
        if set(names) != {PREFIX + name for name in files} | {PREFIX + MANIFEST}:
            raise ValueError('Archive contents do not match manifest')
        for name, expected in files.items():
            if not allowed(name):
                raise ValueError(f'Payload outside source policy: {name}')
            if (not isinstance(expected, dict) or type(expected.get('bytes')) is not int
                    or expected['bytes'] < 0 or not isinstance(expected.get('sha256'), str)
                    or len(expected['sha256']) != 64
                    or any(c not in '0123456789abcdef' for c in expected['sha256'])):
                raise ValueError(f'Malformed file record: {name}')
            info = archive.getinfo(PREFIX + name)
            if info.file_size != expected['bytes']:
                raise ValueError(f'Size mismatch: {name}')
            digest = hashlib.sha256()
            with archive.open(info) as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(chunk)
            if digest.hexdigest() != expected['sha256']:
                raise ValueError(f'Hash mismatch: {name}')
    return {'verified': True, 'files': len(files), 'bytes': sum(v['bytes'] for v in files.values()),
            'hardware_acceptance': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('build')
    create.add_argument('--output', type=Path, required=True)
    check = commands.add_parser('verify')
    check.add_argument('archive', type=Path)
    args = parser.parse_args()
    try:
        result = build(ROOT, args.output) if args.command == 'build' else verify(args.archive)
        print(json.dumps(result))
    except (OSError, ValueError, KeyError, TypeError, BadZipFile, RuntimeError, NotImplementedError) as exc:
        parser.exit(1, f'Package check failed: {exc}\n')


if __name__ == '__main__':
    main()
