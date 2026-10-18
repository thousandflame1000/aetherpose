"""Import FreeRouting SES, then independently check routed copper geometry.

Requires shapely; does not substitute for KiCad's parser, ERC or DRC.
"""
from pathlib import Path
import re,json,math,html
from shapely.geometry import box,LineString,Point
from shapely.ops import unary_union
ROOT=Path(__file__).resolve().parent
def val(t):return json.loads(t) if t.startswith('"') else t
def q(t):return json.dumps(str(t))
def parse(s):
    stack=[];result=None
    for t in re.findall(r'"(?:\\.|[^"\\])*"|\(|\)|[^\s()]+',s):
        if t=='(':
            n=[]
            if stack:stack[-1].append(n)
            stack.append(n)
        elif t==')':result=stack.pop()
        else:stack[-1].append(t)
    assert not stack
    return result
def dump(n):return '('+' '.join(dump(x) if isinstance(x,list) else str(x) for x in n)+')'
def child(n,k):return next((x for x in n if isinstance(x,list) and x and x[0]==k),None)
def children(n,k):return [x for x in n if isinstance(x,list) and x and x[0]==k]
d=json.loads((ROOT/'design.json').read_text())
assert (ROOT/'aetherpose_custom.ses').stat().st_mtime >= (ROOT/'aetherpose_custom.dsn').stat().st_mtime, 'SES is older than DSN: wait for the current routing run to finish.'
ses=parse((ROOT/'aetherpose_custom.ses').read_text())
routes=child(ses,'routes');resolution=child(routes,'resolution')
assert resolution[1]=='um',resolution
scale=1000*float(resolution[2])
network=child(routes,'network_out');tracks=[];vias=[]
for n in children(network,'net'):
    net=val(n[1]);assert net in d['nets'] or net.startswith('NC_'),net
    for w in children(n,'wire'):
        p=child(w,'path');layer=val(p[1]);width=float(p[2])/scale
        coords=list(map(float,p[3:])); points=[(coords[i]/scale,-coords[i+1]/scale) for i in range(0,len(coords),2)]
        for a,b in zip(points,points[1:]):tracks.append(dict(net=net,layer=layer,width=width,a=a,b=b))
    for v in children(n,'via'):vias.append(dict(net=net,x=float(v[2])/scale,y=-float(v[3])/scale,size=.6,drill=.3))
assert tracks,'No routing was imported'
pcb=parse((ROOT/'aetherpose_custom.kicad_pcb').read_text())
pcb[:]=[n for n in pcb if not (isinstance(n,list) and n and n[0] in ['segment','via'])]
for t in tracks:
    assert not t['net'].startswith('NC_'),'Unexpected connection of deliberately unused pins'
    pcb.append(['segment',['start',str(t['a'][0]),str(t['a'][1])],['end',str(t['b'][0]),str(t['b'][1])],['width',str(t['width'])],['layer',q(t['layer'])],['net',str(d['nets'].index(t['net']))]])
for v in vias:pcb.append(['via',['at',str(v['x']),str(v['y'])],['size',str(v['size'])],['drill',str(v['drill'])],['layers','"F.Cu"','"B.Cu"'],['net',str(d['nets'].index(v['net']))]])
(ROOT/'aetherpose_custom.kicad_pcb').write_text(dump(pcb),encoding='utf-8')
(ROOT/'routing.json').write_text(json.dumps(dict(tracks=tracks,vias=vias),indent=2),encoding='utf-8')
objects=[]
for i,p in enumerate(d['pads']):
    net=p['net'] or f'NC_{p["ref"]}_{p["pin"] or i}'
    objects.append(dict(net=net,shape=box(p['x']-p['w']/2,p['y']-p['h']/2,p['x']+p['w']/2,p['y']+p['h']/2),layers=set(p['layers']),label=f'{p["ref"]}.{p["pin"]}',npth=p['npth']))
for t in tracks:objects.append(dict(net=t['net'],shape=LineString([t['a'],t['b']]).buffer(t['width']/2,quad_segs=12),layers={t['layer']},label='track',npth=False))
for v in vias:objects.append(dict(net=v['net'],shape=Point(v['x'],v['y']).buffer(v['size']/2,quad_segs=16),layers={'F.Cu','B.Cu'},label='via',npth=False))
errors=[]; adj=[set() for o in objects];mingap=1000
for i,a in enumerate(objects):
    for j in range(i):
        b=objects[j]
        if not a['layers']&b['layers']:continue
        distance=a['shape'].distance(b['shape'])
        if a['net']==b['net'] and not a['npth'] and not b['npth']:
            if distance<=.0002:adj[i].add(j);adj[j].add(i)
        else:
            mingap=min(mingap,distance)
            if distance<.149-1e-6:errors.append(f'Clearance {distance:.4f}mm {a["net"]} {a["label"]} / {b["net"]} {b["label"]}')
connectivity={}
for net in d['nets'][1:]:
    ids=[i for i,o in enumerate(objects) if o['net']==net]; seen={ids[0]};todo=list(seen)
    while todo:
        for i in adj[todo.pop()]-seen:seen.add(i);todo.append(i)
    missing=[objects[i]['label'] for i in ids if i not in seen]
    connectivity[net]=dict(objects=len(ids),connected=len(seen),missing=missing)
    if missing:errors.append(f'Unconnected copper on {net}: {missing}')
board=box(0,0,45,48)
for o in objects:
    if not board.buffer(-.149).covers(o['shape']):errors.append(f'Board-edge clearance {o["net"]} {o["label"]}')
for t in tracks:
    shape=LineString([t['a'],t['b']]).buffer(t['width']/2)
    for k in d['keepouts']:
        if shape.intersects(box(*k)):errors.append(f'Route in keepout: {t["net"]}')
for v in vias:
    for k in d['keepouts']:
        if Point(v['x'],v['y']).buffer(v['size']/2).intersects(box(*k)):errors.append(f'Via in keepout: {v["net"]}')
report=dict(status='PASS' if not errors else 'FAIL',parts=len(d['parts']),pads=len(d['pads']),segments=len(tracks),vias=len(vias),named_nets=len(d['nets'])-1,minimum_conservative_clearance_mm=mingap,errors=errors,connectivity=connectivity,
 limitations=['Independent rectangular-pad copper check, not KiCad DRC','No KiCad parser/footprint-courtyard/silkscreen/paste/thermal/EMC validation','Schematic block pins use passive electrical type; ERC is not a power-design sign-off','Manufacturer land-pattern final review and prototype electrical/radio testing required','Firmware has not been ported or tested on this board'])
(ROOT/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ['connectivity','limitations']},indent=2))

# An engineering preview of actual imported copper, with physical pad envelopes.
svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1050" height="1180" viewBox="-6 -12 70 79">', '<rect x="-6" y="-12" width="70" height="79" fill="#111c2e"/>', '<style>text{font-family:sans-serif;fill:#f2f6fa}</style>', '<text x="-1" y="-8" font-size="2.4">AETHERPOSE CUSTOM v0.1</text>', '<text x="-1" y="-5" font-size="1.3">BLE / 9-axis / LiPo charging — engineering draft</text>', '<rect width="45" height="48" fill="#174c3c" stroke="#cbd5e1" stroke-width=".18"/>', '<rect x="15.4" y="-5.3" width="13.2" height="5.4" fill="#c29e37" opacity=".5"/>', '<text x="15.8" y="-1.5" font-size="1.4">ANTENNA</text>']
for layer,color in [('B.Cu','#70a8ff'),('F.Cu','#f17f75')]:
    for t in tracks:
        if t['layer']!=layer:continue
        a,b=t['a'],t['b'];svg.append(f'<path d="M {a[0]} {a[1]} L {b[0]} {b[1]}" fill="none" stroke="{color}" stroke-width="{t["width"]}" stroke-linecap="round"/>')
for p in d['pads']:
    svg.append(f'<rect x="{p["x"]-p["w"]/2}" y="{p["y"]-p["h"]/2}" width="{p["w"]}" height="{p["h"]}" fill="#d8bd78"/>')
    if p['through']:
        radius=p['drill']/2 if p['drill'] else .3;svg.append(f'<circle cx="{p["x"]}" cy="{p["y"]}" r="{radius}" fill="#142235"/>')
for v in vias:svg.append(f'<circle cx="{v["x"]}" cy="{v["y"]}" r=".3" fill="#b5d3b9"/><circle cx="{v["x"]}" cy="{v["y"]}" r=".15" fill="#142235"/>')
for p in d['parts']:
    ref=p['ref']
    if ref.startswith('U'):
        w,h={'U1':(13.2,16.6),'U2':(3,2.5),'U3':(3,3),'U4':(3,3),'U5':(3,3)}[ref]
        svg.append(f'<rect x="{p["x"]-w/2}" y="{p["y"]-h/2}" width="{w}" height="{h}" fill="#101c25" fill-opacity=".5" stroke="#c4d6dd" stroke-width=".12"/>')
    if not ref.startswith('TP'):svg.append(f'<text x="{p["x"]}" y="{p["y"]-1.4}" text-anchor="middle" font-size=".85">{ref}</text>')
for i,line in enumerate(['45 x 48 mm PCB; antenna extends 5.3 mm beyond edge','U1 ESP32-C3-MINI-1-H4X','U2 BMI270 accelerometer + gyroscope','U3 QMC5883P magnetometer','U4 BQ24075 charger + power path','U5 TLV75533 3.3 V regulator','USB-C: charging only; UART pogo pads: programming',f'Copper check: {report["status"]} / {len(tracks)} segments / {len(vias)} vias','KiCad ERC/DRC and hardware validation still required']):
    svg.append(f'<text x="0" y="{52+i*1.55}" font-size="1.1">{html.escape(line)}</text>')
svg.append('</svg>');(ROOT/'pcb-preview.svg').write_text('\n'.join(svg).replace('<text ', '<text fill="#f2f6fa" font-family="sans-serif" '),encoding='utf-8')
if __name__=='__main__':raise SystemExit(bool(errors))
