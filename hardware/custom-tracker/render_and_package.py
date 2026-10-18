"""Render review previews and package only a passing geometry-check draft."""
from pathlib import Path
import json,zipfile
import pymupdf
root=Path(__file__).resolve().parent
report=json.loads((root/'verification.json').read_text())
assert report['status']=='PASS','Do not package failed copper checks.'
for name in ['pcb-preview','schematic-preview']:
    doc=pymupdf.open(root/(name+'.svg'))
    doc[0].get_pixmap().save(str(root/(name+'.png')))
files=[p for p in root.iterdir() if p.is_file() and p.suffix.lower() in {'.md','.py','.csv','.json','.svg','.png','.kicad_pcb','.kicad_sch','.kicad_pro','.dsn','.ses'} and p.name!='freerouting.json']
files+=[root/'fp-lib-table']
files+=list((root/'Aetherpose.pretty').glob('*.kicad_mod'))
files += [p for p in (root/'sources').iterdir() if p.name.endswith('LICENSE.md') or p.name=='upstream-manifest.json']
target=root.parent/'aetherpose-custom-v0.1-review.zip'
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files:z.write(p,'aetherpose-custom-v0.1/'+p.relative_to(root).as_posix())
print(f'Packaged {len(files)} review files: {target} ({target.stat().st_size} bytes)')
