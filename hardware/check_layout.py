"""Limited geometric/continuity checks; NOT a replacement for KiCad DRC."""
import json, math
from pathlib import Path
root=Path(__file__).resolve().parent
d=json.loads((root/'layout.json').read_text())
def dist(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy))) if dx or dy else 0
    return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)
def cross(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
def sd(a,b,c,e):
    if cross(a,b,c)*cross(a,b,e)<0 and cross(c,e,a)*cross(c,e,b)<0:return 0
    return min(dist(a,c,e),dist(b,c,e),dist(c,a,b),dist(e,a,b))
objects=[]
for p in d['pads']:
    objects.append(dict(net=p['net'] or f'NC_{p["ref"]}_{p["pin"]}',a=(p['x'],p['y']),b=(p['x'],p['y']),r=.9,layers={'F.Cu','B.Cu'},label=f'{p["ref"]}.{p["pin"]}'))
for t in d['tracks']:objects.append(dict(net=t['net'],a=t['a'],b=t['b'],r=t['width']/2,layers={t['layer']},label='track'))
for x,y,n in d['vias']:objects.append(dict(net=n,a=(x,y),b=(x,y),r=.4,layers={'F.Cu','B.Cu'},label='via'))
adj=[set() for _ in objects]; errors=[]
for i,a in enumerate(objects):
    for j in range(i):
        b=objects[j]
        if not a['layers']&b['layers']:continue
        gap=sd(a['a'],a['b'],b['a'],b['b'])-a['r']-b['r']
        if a['net']==b['net'] and gap<=.001:adj[i].add(j);adj[j].add(i)
        elif a['net']!=b['net'] and gap<.2-1e-6:errors.append(f'Clearance {gap:.3f}mm: {a["net"]}/{b["net"]} {a["label"]}/{b["label"]}')
for net in {p['net'] for p in d['pads'] if p['net']}:
    ids=[i for i,o in enumerate(objects) if o['net']==net]
    seen={ids[0]}; todo=list(seen)
    while todo:
        for n in adj[todo.pop()]-seen:seen.add(n);todo.append(n)
    if set(ids)-seen:errors.append(f'Disconnected copper: {net}')
for o in objects:
    for x,y in (o['a'],o['b']):
        if min(x,y,60-x,50-y)<o['r']+.25:errors.append(f'Board edge clearance: {o["label"]}')
    for h in d['holes']:
        if dist(h,o['a'],o['b'])<1.6+o['r']+.25:errors.append(f'Mounting hole clearance: {o["label"]}')
report='Limited layout verification\n'+f'{len(d["pads"])} pads; {len(d["tracks"])} segments; {len(d["vias"])} vias\n'
report+='\n'.join(errors) if errors else 'PASS: named-net continuity, 0.20mm circular-envelope copper clearance, 0.25mm edge/hole clearance.\n'
report+='\nNOT CHECKED: KiCad parser/DRC, rectangular pad corners, mask/silkscreen, actual socket fit, RF performance, power integrity, fabricated hardware.\n'
(root/'verification.txt').write_text(report,encoding='utf-8')
print(report)
raise SystemExit(bool(errors))
