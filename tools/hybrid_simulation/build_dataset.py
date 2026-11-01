"""Rebuild synthetic RGB and real detector observations; no live camera is opened."""
import argparse,os,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
a=p.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
env={**os.environ,'AETHER_SIM_DATA_DIR':str(a.output_dir.resolve())}
for name in ('make_truth.py','build_scene.py','render_observations.py'):
 subprocess.run([sys.executable,str(Path(__file__).parent/name)],env=env,check=True)
print('Dataset ready:',a.output_dir.resolve())
