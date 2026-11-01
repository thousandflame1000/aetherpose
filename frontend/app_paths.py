"""Source checkout and frozen app paths, with writable per-user runtime data."""
import os
import sys
from pathlib import Path

def frozen():return bool(getattr(sys,'frozen',False))
def project_dir():return Path(sys.executable).resolve().parent if frozen() else Path(__file__).resolve().parents[1]
def asset_dir():return Path(getattr(sys,'_MEIPASS',project_dir()))
def data_dir():
 raw=os.environ.get('AETHER_DATA_DIR')
 if raw:return Path(raw).expanduser().resolve()
 if frozen():return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'AetherPose'
 return project_dir()
