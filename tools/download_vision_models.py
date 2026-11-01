"""Download versioned official task models, verifying pinned build hashes."""
from pathlib import Path
import hashlib,os,urllib.request,uuid
ROOT=Path(__file__).resolve().parents[1]
MODELS={
 'full':'5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1',
 'lite':'59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a'}
def download(folder=ROOT/'external/vision'):
 folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
 for name,expected in MODELS.items():
  target=folder/f'pose_landmarker_{name}.task'
  if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==expected:continue
  url=f'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_{name}/float16/1/pose_landmarker_{name}.task'
  temp=folder/(target.name+'.'+uuid.uuid4().hex+'.download')
  try:
   with urllib.request.urlopen(url,timeout=60) as response:
    data=response.read(64*1024*1024+1)
   if len(data)>64*1024*1024 or hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Vision model hash mismatch: '+name)
   temp.write_bytes(data);os.replace(temp,target)
  finally:
   if temp.exists():temp.unlink()
 return [str(folder/f'pose_landmarker_{name}.task') for name in MODELS]
if __name__=='__main__':
 for file in download():print(file)
