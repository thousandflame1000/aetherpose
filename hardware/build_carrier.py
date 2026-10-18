"""Generate an editable KiCad carrier draft and a matching top-view SVG (mm)."""
from pathlib import Path
import json, math

ROOT = Path(__file__).resolve().parent
nets = ['', 'GND', '+5V_IN', 'VIN_SW', 'VBAT_IN', 'VBAT_SW', 'BAT_ADC']
pads, tracks, parts = [], [], []
def footprint(ref, value, positions):
    parts.append((ref, value, positions))
    for number, x, y, net in positions:
        pads.append(dict(ref=ref, pin=str(number), x=x, y=y, net=net))
def route(net, layer, points, width=.4):
    for a,b in zip(points, points[1:]):
        tracks.append(dict(net=net,layer=layer,a=a,b=b,width=width))

# Custom numbering follows the Arduino ABX00030 datasheet, not generic Nano symbols.
# USB faces LEFT. Datasheet pins 1..15 run RIGHT to LEFT along lower socket row.
lower = ['D13','3V3','AREF','A0','A1','A2','A3','A4','A5','A6','A7','VUSB','RESET','GND','VIN']
upper = ['TX','RX','RESET','GND','D2','D3','D4','D5','D6','D7','D8','D9','D10','D11','D12']
nano = []
for i,label in enumerate(lower):
    nano.append((i+1, round(47.56-i*2.54,2),27.24, {'A0':'BAT_ADC','GND':'GND','VIN':'VIN_SW'}.get(label,'')))
for i,label in enumerate(upper):
    nano.append((i+16, round(12+i*2.54,2),12, 'GND' if label=='GND' else ''))
footprint('U1','Nano_33_BLE_ABX00030_USB_LEFT',nano)
footprint('J1','1:5V 2:BAT 3:GND',[(1,18,36,'+5V_IN'),(2,20.54,36,'VBAT_IN'),(3,23.08,36,'GND')])
footprint('J2','DPST_SWITCH:1-2,3-4',[(1,8,43,'+5V_IN'),(2,10.54,43,'VIN_SW'),(3,13.08,43,'VBAT_IN'),(4,15.62,43,'VBAT_SW')])
footprint('R1','100k_1pct_DIN0207',[(1,31,36,'VBAT_SW'),(2,38.62,36,'BAT_ADC')])
footprint('R2','100k_1pct_DIN0207',[(1,38.62,41,'BAT_ADC'),(2,46.24,41,'GND')])
footprint('C1','100nF_2.54mm',[(1,41,32,'BAT_ADC'),(2,43.54,32,'GND')])
route('+5V_IN','F.Cu',[(18,36),(18,38),(8,38),(8,43)],.6)
route('VIN_SW','B.Cu',[(10.54,43),(10.54,28.7),(12,27.24)],.6)
route('VBAT_IN','F.Cu',[(20.54,36),(20.54,40),(13.08,40),(13.08,43)])
route('VBAT_SW','F.Cu',[(15.62,43),(15.62,45),(29,45),(29,36),(31,36)])
route('BAT_ADC','F.Cu',[(38.62,41),(38.62,29),(39.94,27.24)],.3)
route('BAT_ADC','F.Cu',[(38.62,32),(41,32)],.3)
route('GND','B.Cu',[(14.54,27.24),(14.54,31),(25,31),(23.08,33),(23.08,36)],.6)
route('GND','B.Cu',[(23.08,36),(23.08,47),(46.24,47),(46.24,41),(46.24,32),(43.54,32)],.6)
route('GND','F.Cu',[(19.62,12),(19.62,8),(6,8),(6,30),(14.54,30)],.4)
vias=[(14.54,30,'GND')]
holes=[(4,4),(56,4),(4,46),(56,46)]

def q(s): return json.dumps(s)
out=['(kicad_pcb (version 20240108) (generator "aetherpose_carrier")',
     ' (general (thickness 1.6)) (paper "A4")',
     ' (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user "b.silkscreen") (37 "F.SilkS" user "f.silkscreen") (38 "B.Mask" user) (39 "F.Mask" user) (44 "Edge.Cuts" user) (46 "B.CrtYd" user) (47 "F.CrtYd" user) (48 "B.Fab" user) (49 "F.Fab" user))',
     ' (setup (pad_to_mask_clearance 0))']
for i,n in enumerate(nets): out.append(f' (net {i} {q(n)})')
for ref,value,pp in parts:
    out.append(f' (footprint "Aetherpose:{ref}" (layer "F.Cu") (at 0 0) (attr through_hole)')
    x,y=pp[0][1:3]
    for name,val,yy in [('Reference',ref,y-2),('Value',value,y+2)]:
        out.append(f'  (property {q(name)} {q(val)} (at {x} {yy}) (layer "F.SilkS")'+(' hide' if name=='Value' else '')+' (effects (font (size 1 1) (thickness .15))))')
    for number,x,y,net in pp:
        shape='rect' if number in (1,16) else 'circle'
        out.append(f'  (pad "{number}" thru_hole {shape} (at {x} {y}) (size 1.8 1.8) (drill 1) (layers "*.Cu" "*.Mask")'+(f' (net {nets.index(net)} {q(net)})' if net else '')+')')
    out.append(' )')
for i,(x,y) in enumerate(holes,1):
    out.append(f' (footprint "MountingHole:MountingHole_3.2mm_M3" (layer "F.Cu") (at {x} {y}) (attr exclude_from_pos_files exclude_from_bom) (pad "" np_thru_hole circle (at 0 0) (size 3.2 3.2) (drill 3.2) (layers "*.Cu" "*.Mask")))')
for t in tracks:
    a,b=t['a'],t['b']
    out.append(f' (segment (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (width {t["width"]}) (layer "{t["layer"]}") (net {nets.index(t["net"])}))')
for x,y,n in vias: out.append(f' (via (at {x} {y}) (size .8) (drill .4) (layers "F.Cu" "B.Cu") (net {nets.index(n)}))')
out.append(' (gr_rect (start 0 0) (end 60 50) (stroke (width .05) (type default)) (fill none) (layer "Edge.Cuts"))')
for text,x,y,size in [('AETHERPOSE CARRIER v0.1',30,3,1.2),('USB <',7,18,1),('ANTENNA',48,18,1),('NO METAL / BATTERY',46,21,.8),('J1: 5V BAT GND',22,33,1),('J2: DPST 1-2 / 3-4',14,40.8,.8),('PROTOTYPE - VERIFY BEFORE FAB',31,49,.8)]:
    out.append(f' (gr_text {q(text)} (at {x} {y}) (layer "F.SilkS") (effects (font (size {size} {size}) (thickness .15))))')
out.append(' (zone (net 0) (net_name "") (layer "F.Cu") (hatch edge .5) (connect_pads (clearance .5)) (min_thickness .25) (keepout (tracks not_allowed) (vias not_allowed) (pads allowed) (copperpour not_allowed) (footprints allowed)) (polygon (pts (xy 43 14) (xy 55 14) (xy 55 25) (xy 43 25))))')
out.append(' (zone (net 0) (net_name "") (layer "B.Cu") (hatch edge .5) (connect_pads (clearance .5)) (min_thickness .25) (keepout (tracks not_allowed) (vias not_allowed) (pads allowed) (copperpour not_allowed) (footprints allowed)) (polygon (pts (xy 43 14) (xy 55 14) (xy 55 25) (xy 43 25))))')
out.append(')')
(ROOT/'aetherpose_carrier.kicad_pcb').write_text('\n'.join(out),encoding='utf-8')
(ROOT/'layout.json').write_text(json.dumps(dict(pads=pads,tracks=tracks,vias=vias,holes=holes),indent=2),encoding='utf-8')

svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="880" viewBox="-5 -8 70 62">', '<rect x="-5" y="-8" width="70" height="62" fill="#101827"/>', '<text x="0" y="-4" fill="white" font-size="2">Aetherpose Nano 33 BLE carrier — v0.1 draft</text>', '<rect width="60" height="50" rx="0.4" fill="#163b32" stroke="#ddd" stroke-width=".15"/>', '<rect x="7" y="10.6" width="45" height="18" fill="none" stroke="#81d4fa" stroke-width=".2" stroke-dasharray="1 .5"/>', '<rect x="43" y="14" width="12" height="11" fill="#e0a030" opacity=".25"/>']
for t in tracks:
    a,b=t['a'],t['b']; color='#ee776c' if t['layer']=='F.Cu' else '#72aaff'
    svg.append(f'<path d="M {a[0]} {a[1]} L {b[0]} {b[1]}" stroke="{color}" stroke-width="{t["width"]}"/>')
for p in pads:
    svg.append(f'<circle cx="{p["x"]}" cy="{p["y"]}" r=".9" fill="#d9bd73"/><circle cx="{p["x"]}" cy="{p["y"]}" r=".5" fill="#101827"/>')
for x,y in holes: svg.append(f'<circle cx="{x}" cy="{y}" r="1.6" fill="#101827" stroke="#bbb" stroke-width=".15"/>')
for txt,x,y in [('USB LEFT',8,20),('ANTENNA',44,18),('NO METAL',44,21),('J1: 5V BAT GND',17,33),('DPST SWITCH',6,48),('R1 100k',30,34),('R2 100k',38,44),('C1 100n',40,30),('60 x 50 mm / 2 layers / all dimensions provisional',1,53)]:
    svg.append(f'<text x="{x}" y="{y}" fill="white" font-size="1.15">{txt}</text>')
svg.append('</svg>')
(ROOT/'pcb-preview.svg').write_text('\n'.join(svg),encoding='utf-8')
print('Generated KiCad PCB, layout.json and pcb-preview.svg')
