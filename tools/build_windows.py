"""Windows onedir build. Never includes local model/config data."""
import argparse,hashlib,json,os,shutil,subprocess,sys,tomllib
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import importlib.metadata as metadata

ROOT=Path(__file__).resolve().parents[1]
VERSION='0.2.0-preview.2'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def package(output,work,backend):
 if sys.platform!='win32':raise RuntimeError('Build the Windows bundle on Windows')
 if not backend.is_file():raise RuntimeError('Compile the Rust backend with cargo build --release first')
 sources=[*ROOT.glob('src/**/*.rs'),ROOT/'Cargo.toml',ROOT/'Cargo.lock']
 if max(p.stat().st_mtime for p in sources)>backend.stat().st_mtime+1:
  raise RuntimeError('Backend is older than its sources. Build it again before packaging.')
 for name in ('full','lite'):
  if not (ROOT/f'external/vision/pose_landmarker_{name}.task').is_file():raise RuntimeError('Install the official vision task models first')
 from download_vision_models import download
 download()
 work.mkdir(parents=True,exist_ok=True);output.mkdir(parents=True,exist_ok=True)
 command=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--windowed','--noupx',
  '--name','AetherPose','--distpath',str(work/'dist'),'--workpath',str(work/'build'),
  '--specpath',str(work/'spec'),'--paths',str(ROOT/'frontend'),'--paths',str(ROOT),
  '--collect-all','mediapipe','--collect-all','cv2',
  '--add-data',str(ROOT/'webui')+';webui']
 for name in ('full','lite'):
  command+=['--add-data',str(ROOT/f'external/vision/pose_landmarker_{name}.task')+';external/vision']
 for module in ('torch','tensorflow','pandas','sklearn','IPython','notebook','pytest','PyQt5','PyQt6','PySide2','PySide6'):
  command+=['--exclude-module',module]
 command.append(str(ROOT/'packaging/launcher.py'))
 subprocess.run(command,check=True,cwd=ROOT,env={**os.environ,'MPLBACKEND':'Agg'})
 bundle=work/'dist/AetherPose';(bundle/'_internal/bin').mkdir(parents=True,exist_ok=True)
 # Matplotlib's example datasets are unused by pose inference. Keep the strict
 # ban on research data, rather than allowing arbitrary NPZ/CSV files.
 samples=bundle/'_internal/matplotlib/mpl-data/sample_data'
 if samples.exists():
  checked=samples.resolve();checked.relative_to(bundle.resolve())
  if checked!=bundle.resolve()/'_internal/matplotlib/mpl-data/sample_data':raise RuntimeError('Unexpected sample data path')
  shutil.rmtree(checked)
 shutil.copy2(backend,bundle/'_internal/bin/aetherpose.exe')
 # Advanced research worker is source, not the licensed model or Python 3.8.
 for name in ('globalpose_worker.py','globalpose_rates.py','cpu_latency.py'):
  target=bundle/'_internal/frontend'/name;target.parent.mkdir(exist_ok=True)
  shutil.copy2(ROOT/'frontend'/name,target)
 for name in ('WINDOWS_README.txt','THIRD_PARTY_NOTICES.md'):
  shutil.copy2(ROOT/'packaging'/name,bundle/name)
 licenses=bundle/'licenses';licenses.mkdir(exist_ok=True)
 packages=('numpy','scipy','matplotlib','mediapipe','opencv-contrib-python','websockets','bleak','pyserial','pyinstaller',
           'absl-py','flatbuffers','sounddevice','cffi','pycparser','contourpy','cycler','fonttools','kiwisolver',
           'pillow','python-dateutil','packaging','pyparsing','six')
 dependencies=[]
 for name in packages:
  try:dist=metadata.distribution(name)
  except metadata.PackageNotFoundError:continue
  dependencies.append(dict(name=name,version=dist.version))
  for item in dist.files or ():
   if ('license' in str(item).lower() or 'copying' in item.name.lower()) and item.suffix.lower() in ('.txt','.md','.rst',''):
    source=Path(dist.locate_file(item))
    if source.is_file():
     relative=Path(*(part for part in item.parts if part not in ('..','.')))
     target=licenses/'python'/name/relative
     target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
 python_license=Path(sys.base_prefix)/'LICENSE.txt'
 if python_license.exists():shutil.copy2(python_license,licenses/'Python-LICENSE.txt')
 shutil.copy2(ROOT/'webui/vendor/three/LICENSE',licenses/'Threejs-LICENSE.txt')
 # Include the original licence text for each locally available Rust dependency.
 cargo=tomllib.loads((ROOT/'Cargo.lock').read_text(encoding='utf-8'))
 registries=list((Path.home()/'.cargo/registry/src').glob('*'))
 rust=[]
 for item in cargo['package']:
  name,version=item['name'],item['version'];folders=[p/f'{name}-{version}' for p in registries]
  folder=next((p for p in folders if (p/'Cargo.toml').is_file()),None)
  if folder is None:continue
  package_info=tomllib.loads((folder/'Cargo.toml').read_text(encoding='utf-8')).get('package',{})
  rust.append(dict(name=name,version=version,license=package_info.get('license','see original notice')))
  for file in folder.iterdir():
   if file.is_file() and file.name.upper().startswith(('LICENSE','COPYING','NOTICE')):
    dest=licenses/'rust'/f'{name}-{version}';dest.mkdir(parents=True,exist_ok=True);shutil.copy2(file,dest/file.name)
 (licenses/'dependencies.json').write_text(json.dumps(dict(python=dependencies,rust=rust),indent=2),encoding='utf-8')
 # Verify all delivered paths before writing the ZIP. No user data or research
 # model geometry is accepted in the distributable, including accidental data.
 forbidden=('external_paths.json','hybrid_paths.json','config.json','truth.json','bootstrap-data.js')
 files=[]
 for path in bundle.rglob('*'):
  if not path.is_file():continue
  rel=path.relative_to(bundle).as_posix()
  if path.name in forbidden or path.suffix.lower() in ('.npz','.pkl','.pt','.csv') or 'camera_profiles/' in rel:
   raise RuntimeError('Private/restricted runtime data found: '+rel)
  files.append((path,rel))
 manifest=dict(version=VERSION,platform='windows-x64',backend_sha256=sha(backend),
  backend_source_max_mtime=max(p.stat().st_mtime for p in sources),
  note='Procedural body; official MediaPipe task models. No SMPL, GlobalPose or TransPose weights/data.',
  files={rel:dict(bytes=path.stat().st_size,sha256=sha(path)) for path,rel in files})
 (bundle/'BUILD_MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
 archive=output/f'AetherPose-{VERSION}-windows-x64.zip'
 if archive.exists():raise RuntimeError('Output already exists: '+str(archive))
 with ZipFile(archive,'w',ZIP_DEFLATED,compresslevel=6,strict_timestamps=False) as zipfile:
  for path in bundle.rglob('*'):
   if path.is_file():zipfile.write(path,'AetherPose/'+path.relative_to(bundle).as_posix())
 (archive.with_suffix('.zip.sha256')).write_text(sha(archive)+'  '+archive.name+'\n',encoding='ascii')
 return dict(archive=str(archive),sha256=sha(archive),bytes=archive.stat().st_size,executable=str(bundle/'AetherPose.exe'))

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
 parser.add_argument('--work',type=Path,required=True);parser.add_argument('--backend',type=Path,default=ROOT/'target/release/aetherpose.exe')
 args=parser.parse_args();print(json.dumps(package(args.output,args.work,args.backend),indent=2))
