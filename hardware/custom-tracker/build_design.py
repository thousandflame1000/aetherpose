"""Generate a reviewable schematic, PCB and router input from one pin/net model.

Not production sign-off: manufacturer pin/land patterns and KiCad ERC/DRC remain
independent checks. No firmware or measured hardware claims are made here.
"""
from pathlib import Path
import re,json,uuid,math,csv,html
ROOT=Path(__file__).resolve().parent
FP=ROOT/'Aetherpose.pretty'
def q(x):return json.dumps(str(x),ensure_ascii=False)
def val(x):return json.loads(x) if x.startswith('"') else x
def parse(s):
    tokens=re.findall(r'"(?:\\.|[^"\\])*"|\(|\)|[^\s()]+',s); stack=[]; result=None
    for t in tokens:
        if t=='(':
            n=[]
            if stack:stack[-1].append(n)
            stack.append(n)
        elif t==')':
            result=stack.pop()
        else:stack[-1].append(t)
    assert not stack
    return result
def dump(n):return '('+' '.join(dump(x) if isinstance(x,list) else str(x) for x in n)+')'
def children(n,k):return [x for x in n if isinstance(x,list) and x and x[0]==k]
def field(n,k,default=None):return next(iter(children(n,k)),default)
def uid(s):return str(uuid.uuid5(uuid.NAMESPACE_URL,'aetherpose-custom-v1/'+s))
parts=[]
def add(ref,value,foot,x,y,pins,names=None,price=None,source='',rotation=0):
    parts.append(dict(ref=ref,value=value,footprint=foot,x=x,y=y,pins={str(k):v for k,v in pins.items()},names={str(k):v for k,v in (names or {}).items()},price=price,source=source,rotation=rotation))
R='R_0603_1608Metric'; C='C_0603_1608Metric'; C8='C_0805_2012Metric'
esp={n:'GND' for n in [1,2,11,14,*range(36,54)]}
esp.update({3:'+3V3',5:'STRAP2',6:'IMU_INT',8:'CHIP_EN',12:'BAT_ADC',16:'LED_DRV',18:'I2C_SDA',19:'I2C_SCL',21:'PGOOD',22:'STRAP8',23:'BOOT',30:'UART_RX',31:'UART_TX'})
espnames={3:'3V3',5:'GPIO2',6:'GPIO3',8:'EN',12:'GPIO0',13:'GPIO1',16:'GPIO10',18:'GPIO4',19:'GPIO5',20:'GPIO6',21:'GPIO7',22:'GPIO8',23:'GPIO9',26:'USB_D-',27:'USB_D+',30:'RXD0',31:'TXD0'}
add('U1','ESP32-C3-MINI-1-H4X','ESP32-C3-MINI-1',22,3,esp,espnames,4.01,'https://www.mouser.com/en/ProductDetail/Espressif-Systems/ESP32-C3-MINI-1-H4X')
add('U2','BMI270','Bosch_LGA-14_3x2.5mm_P0.5mm',31,21,{1:'GND',4:'IMU_INT',5:'+3V3',6:'GND',7:'GND',8:'+3V3',12:'+3V3',13:'I2C_SCL',14:'I2C_SDA'}, {1:'SDO_ADDR',2:'ASDA_NC',3:'ASCL_NC',4:'INT1',5:'VDDIO',6:'GNDIO',7:'GND',8:'VDD',9:'INT2_NC',10:'OCSB_NC',11:'OSDO_NC',12:'CSB',13:'SCL',14:'SDA'},1.8389,'https://www.lcsc.com/product-detail/C2836813.html')
add('U3','QMC5883P','LGA-16_3x3mm_P0.5mm',39,14,{1:'I2C_SCL',2:'+3V3',9:'GND',10:'MAG_CAP',11:'GND',16:'I2C_SDA'},{1:'SCL',2:'VDD',9:'GND',10:'C1_4u7',11:'GND',16:'SDA'},1.5551,'https://www.lcsc.com/product-detail/C2847467.html')
add('U4','BQ24075RGTR','VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm_ThermalVias',9,32,{1:'BAT_NTC',2:'VBAT',3:'VBAT',4:'GND',5:'GND',6:'GND',7:'PGOOD',8:'GND',9:'CHG',10:'VSYS',11:'VSYS',12:'CHG_ILIM',13:'VBUS',15:'GND',16:'CHG_ISET',17:'GND'}, {1:'TS',2:'BAT',3:'BAT',4:'CE_N',5:'EN2',6:'EN1_USB100',7:'PGOOD_N',8:'VSS',9:'CHG_N',10:'OUT',11:'OUT',12:'ILIM',13:'IN',14:'TMR_NC',15:'SYSOFF',16:'ISET',17:'EP'},1.2,'https://www.lcsc.com/product-detail/C15464.html')
add('U5','TLV75533PDBVR','SOT-23-5',19,27,{1:'VSYS',2:'GND',3:'LDO_EN',5:'+3V3'},{1:'IN',2:'GND',3:'EN',4:'NC',5:'OUT'},.30,'https://www.ti.com/product/TLV755P/part-details/TLV75533PDBVR')
usb={'A1':'GND','A4':'VBUS','A5':'CC1','A9':'VBUS','A12':'GND','B1':'GND','B4':'VBUS','B5':'CC2','B9':'VBUS','B12':'GND','S1':'GND'}
add('J1','USB-C_CHARGE_ONLY','USB_C_Receptacle_HRO_TYPE-C-31-M-12',9,44,usb,price=.4)
add('J2','BAT+ / NTC / GND','JST_PH_B3B-PH-K_1x03_P2.00mm_Vertical',29,40,{1:'VBAT',2:'BAT_NTC',3:'GND'},price=.3)
add('SW1','JS202011CQN_DPDT','SW_CuK_JS202011CQN_DPDT_Straight',4,15,{1:'GND',2:'LDO_EN',3:'VSYS',4:'GND',5:'BAT_SENSE',6:'VBAT'},{1:'OFF1',2:'COMMON1',3:'ON1',4:'OFF2',5:'COMMON2',6:'ON2'},.8)
rn=0; cn=0
def resistor(value,a,b,x,y,price=.008):
    global rn;rn+=1;add(f'R{rn}',value,R,x,y,{1:a,2:b},price=price)
def capacitor(value,a,b,x,y,large=False,price=.015):
    global cn;cn+=1;add(f'C{cn}',value,C8 if large else C,x,y,{1:a,2:b},price=price)
resistor('4.7k','+3V3','I2C_SDA',30,16)
resistor('4.7k','+3V3','I2C_SCL',34,16)
resistor('10k','+3V3','CHIP_EN',14,15)
resistor('10k','+3V3','STRAP2',13,12)
resistor('10k','+3V3','STRAP8',32,28)
resistor('10k','+3V3','BOOT',36,28)
resistor('100k','BAT_SENSE','BAT_ADC',22,34)
resistor('100k','BAT_ADC','GND',26,34)
resistor('8.87k_1pct','CHG_ISET','GND',6,37)
resistor('3.24k_1pct','CHG_ILIM','GND',12,36)
resistor('5.1k_1pct','CC1','GND',2,40)
resistor('5.1k_1pct','CC2','GND',16,40)
resistor('10k','+3V3','PGOOD',21,23)
resistor('2.2k','LED_DRV','LED_A',37,24)
resistor('2.2k','VBUS','CHG_LED_A',4,32)
resistor('1M','LDO_EN','GND',15,30)
capacitor('100nF','+3V3','GND',30,24)
capacitor('100nF','+3V3','GND',34,24)
capacitor('100nF','+3V3','GND',42,10)
capacitor('4.7uF','MAG_CAP','GND',39,18,True,.03)
capacitor('1uF','CHIP_EN','GND',14,18)
capacitor('100nF','BAT_ADC','GND',26,31)
capacitor('10uF_10V_X5R','VBUS','GND',5,28,True,.04)
capacitor('10uF_10V_X5R','VBAT','GND',12,28,True,.04)
capacitor('10uF_10V_X5R','VSYS','GND',14,24,True,.04)
capacitor('10uF_10V_X5R','+3V3','GND',19,31,True,.04)
capacitor('10uF_10V_X5R','+3V3','GND',13,6,True,.04)
capacitor('100nF','+3V3','GND',13,9)
add('D1','STATUS_GREEN','LED_0603_1608Metric',41,24,{1:'GND',2:'LED_A'},price=.03)
add('D2','CHARGE_AMBER','LED_0603_1608Metric',4,35,{1:'CHG',2:'CHG_LED_A'},price=.03)
# Six 1.3mm surface test pads: shared 3.3V UART jig. VREF is sense-only.
test=['GND','+3V3','UART_RX','UART_TX','BOOT','CHIP_EN']
for i,n in enumerate(test):
    name='TestPad_1.3mm'
    if not (FP/(name+'.kicad_mod')).exists():
        (FP/(name+'.kicad_mod')).write_text('(footprint "TestPad_1.3mm" (layer "F.Cu") (attr smd) (pad "1" smd circle (at 0 0) (size 1.3 1.3) (layers "F.Cu" "F.Mask")))',encoding='utf-8')
    add('TP'+str(i+1),n,name,24+i*3,45,{1:n},price=0)

netnames=['']+sorted({n for p in parts for n in p['pins'].values() if n})
padrecords=[]
def prep(p):
    f=parse((FP/(p['footprint']+'.kicad_mod')).read_text(encoding='utf-8'))
    f[0]='footprint';f[1]=q('Aetherpose:'+p['footprint'])
    f[:]=[x for x in f if not (isinstance(x,list) and x[0] in ('tedit','tstamp','version','generator','model','zone'))]
    f.insert(2,['at',str(p['x']),str(p['y']),str(p['rotation'])]);f.insert(3,['path',q('/'+uid(p['ref']))])
    f.insert(4,['tstamp',uid('pcb/'+p['ref'])])
    for x in f:
        if not isinstance(x,list):continue
        if x[0]=='fp_text':
            if x[1]=='reference':x[2]=q(p['ref'])
            if x[1]=='value':x[2]=q(p['value'])
            if x[1]=='user' and val(x[2])=='%R':x[2]=q('${REFERENCE}')
        if x[0].startswith('fp_'):
            w=field(x,'width')
            if w:x.remove(w);x.append(['stroke',['width',w[1]],['type','default']])
        if x[0]!='pad':continue
        number=val(x[1]); net=p['pins'].get(number,'')
        if net:x.append(['net',str(netnames.index(net)),q(net)])
        at=field(x,'at');size=field(x,'size'); layers=[val(t) for t in field(x,'layers')[1:]]
        if not size:continue
        copper_layers=['F.Cu','B.Cu'] if '*.Cu' in layers else [l for l in layers if l in ('F.Cu','B.Cu')]
        if not copper_layers:continue
        xx,yy=map(float,at[1:3]);w,h=map(float,size[1:3]);theta=float(at[3]) if len(at)>3 else 0
        if theta%180:w,h=h,w
        # Router envelope conservatively encloses custom solder pads.
        if x[3]=='custom':w=h=1.45
        radians=math.radians(p['rotation']);gx=p['x']+xx*math.cos(radians)+yy*math.sin(radians);gy=p['y']-xx*math.sin(radians)+yy*math.cos(radians)
        if p['rotation']%180:w,h=h,w
        padrecords.append(dict(ref=p['ref'],pin=number,net=net,x=round(gx,5),y=round(gy,5),w=w,h=h,layers=copper_layers,npth=(x[2]=='np_thru_hole'),through=('*.Cu' in layers),drill=float(field(x,'drill',['drill','0'])[1]) if field(x,'drill') and field(x,'drill')[1]!='oval' else 0))
    return f

board=['kicad_pcb',['version','20240108'],['generator','"aetherpose"'],['general',['thickness','1.6']],['paper','"A4"'],
 ['layers',['0','"F.Cu"','signal'],['31','"B.Cu"','signal'],['34','"B.Paste"','user'],['35','"F.Paste"','user'],['36','"B.SilkS"','user'],['37','"F.SilkS"','user'],['38','"B.Mask"','user'],['39','"F.Mask"','user'],['44','"Edge.Cuts"','user'],['46','"B.CrtYd"','user'],['47','"F.CrtYd"','user'],['48','"B.Fab"','user'],['49','"F.Fab"','user']],['setup',['pad_to_mask_clearance','0']]]
for i,n in enumerate(netnames):board.append(['net',str(i),q(n)])
for p in parts:board.append(prep(p))
board.append(parse('(gr_rect (start 0 0) (end 45 48) (stroke (width 0.05) (type default)) (fill none) (layer "Edge.Cuts"))'))
# The complete antenna is beyond the top board edge; no copper beneath it.
keepouts=[(15.4,-5.3,28.6,.1),(38.15,13.15,39.85,14.85)]
for x1,y1,x2,y2 in keepouts:
    for layer in ['F.Cu','B.Cu']:
        board.append(parse(f'(zone (net 0) (net_name "") (layer "{layer}") (hatch edge .5) (connect_pads (clearance .15)) (min_thickness .15) (keepout (tracks not_allowed) (vias not_allowed) (pads allowed) (copperpour not_allowed) (footprints allowed)) (polygon (pts (xy {x1} {y1}) (xy {x2} {y1}) (xy {x2} {y2}) (xy {x1} {y2}))))'))
for text,x,y in [('AETHERPOSE CUSTOM v0.1',25,38),('USB-C CHARGE ONLY',12,47),('G V R T B E',31.5,43.1),('OFF     ON',6.5,13)]:
    board.append(parse(f'(gr_text {q(text)} (at {x} {y}) (layer "F.SilkS") (effects (font (size .7 .7) (thickness .12))))'))
(ROOT/'aetherpose_custom.kicad_pcb').write_text(dump(board),encoding='utf-8')
(ROOT/'design.json').write_text(json.dumps(dict(parts=parts,nets=netnames,pads=padrecords,keepouts=keepouts),indent=2),encoding='utf-8')
(ROOT/'fp-lib-table').write_text('(fp_lib_table (lib (name "Aetherpose") (type "KiCad") (uri "${KIPRJMOD}/Aetherpose.pretty") (options "") (descr "Vendored upstream footprints; see sources/upstream-manifest.json")))',encoding='utf-8')

# Author a native schematic with embedded symbols and explicit no-connects.
rootid=uid('schematic');schematic=['kicad_sch',['version','20231120'],['generator','eeschema'],['uuid',rootid],['paper','"A2"']]
lib=['lib_symbols']; instances=[]; extra=[]
svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1782" height="1260" viewBox="0 0 594 420"><rect width="594" height="420" fill="#fcfaf4"/><style>text{font-family:monospace;fill:#14283c} .wire{stroke:#23794f;stroke-width:.25;fill:none}</style><text x="15" y="12" font-size="4">AETHERPOSE CUSTOM v0.1 — ELECTRICAL REVIEW DRAFT</text><text x="15" y="19" font-size="2.5">ESP32-C3 + BMI270 + QMC5883P | USB-C charging + UART jig programming</text>']
pinrows=[]
for idx,p in enumerate(parts):
    pp=[r for r in padrecords if r['ref']==p['ref'] and r['pin']]
    unique={r['pin']:r for r in pp};nums=sorted(unique,key=lambda s:(not s.isdigit(),int(s) if s.isdigit() else s))
    if p['ref']=='U1':sx,sy=65,85
    elif p['ref']=='U2':sx,sy=165,55
    elif p['ref']=='U3':sx,sy=265,55
    elif p['ref']=='U4':sx,sy=365,55
    elif p['ref']=='U5':sx,sy=465,55
    elif p['ref']=='J1':sx,sy=165,120
    elif p['ref']=='J2':sx,sy=265,110
    elif p['ref']=='SW1':sx,sy=365,110
    else:
        j=idx-8;sx=55+(j%6)*95;sy=175+(j//6)*32
    nleft=(len(nums)+1)//2;half=max(5.08,nleft*2.54/2+2.54);name=p['ref']+'_block'
    sym=['symbol',q('Aetherpose:'+name),['pin_names',['offset','0.5']],['in_bom','yes'],['on_board','yes'],
      ['property','"Reference"',q(p['ref']),['at','0',str(half+3), '0'],['effects',['font',['size','1.27','1.27']]]],
      ['property','"Value"',q(p['value']),['at','0',str(-half-3),'0'],['effects',['font',['size','1.0','1.0']]]],
      ['property','"Footprint"',q('Aetherpose:'+p['footprint']),['at','0','0','0'],['effects',['font',['size','1.27','1.27']],'hide']],
      ['symbol',q(name+'_0_1'),['rectangle',['start','-17.78',str(half)],['end','17.78',str(-half)],['stroke',['width','.254'],['type','default']],['fill',['type','background']]]]]
    body=['symbol',q(name+'_1_1')]
    svg.append(f'<rect x="{sx-17.78}" y="{sy-half}" width="35.56" height="{half*2}" fill="#eff2f5" stroke="#14283c" stroke-width=".25"/><text x="{sx}" y="{sy-half-2}" text-anchor="middle" font-size="2.3">{p["ref"]}</text><text x="{sx}" y="{sy+half+3}" text-anchor="middle" font-size="1.6">{html.escape(p["value"])}</text>')
    for j,num in enumerate(nums):
        left=j<nleft;row=j if left else j-nleft
        px=-22.86 if left else 22.86;py=(nleft-1)*1.27-row*2.54
        net=p['pins'].get(num,'');label=p['names'].get(num,'GND' if net=='GND' else num)
        body.append(['pin','passive','line',['at',str(px),str(py),'0' if left else '180'],['length','5.08'],['name',q(label),['effects',['font',['size','.85','.85']]]],['number',q(num),['effects',['font',['size','.85','.85']]]]])
        gx,gy=round(sx+px,5),round(sy-py,5);endx=round(gx+(-5.08 if left else 5.08),5)
        if net:
            extra.append(['wire',['pts',['xy',str(gx),str(gy)],['xy',str(endx),str(gy)]],['stroke',['width','0'],['type','default']],['uuid',uid(f'wire/{p["ref"]}/{num}')]])
            extra.append(['label',q(net),['at',str(endx),str(gy),'0'],['effects',['font',['size','1','1']],['justify','right' if left else 'left','bottom']],['uuid',uid(f'label/{p["ref"]}/{num}')]])
        else:extra.append(['no_connect',['at',str(gx),str(gy)],['uuid',uid(f'nc/{p["ref"]}/{num}')]])
        svg.append(f'<path class="wire" d="M {sx+(-17.78 if left else 17.78)} {gy} L {endx if net else gx} {gy}"/><text x="{sx+(-17 if left else 17)}" y="{gy-.4}" text-anchor="{"start" if left else "end"}" font-size="1.4">{html.escape(label)} [{num}]</text><text x="{endx+(-.5 if left else .5)}" y="{gy-.4}" text-anchor="{"end" if left else "start"}" font-size="1.5">{html.escape(net or "NC")}</text>')
        pinrows.append([p['ref'],num,label,net or 'NC'])
    sym.append(body);lib.append(sym)
    instances.append(['symbol',['lib_id',q('Aetherpose:'+name)],['at',str(sx),str(sy),'0'],['unit','1'],['in_bom','yes'],['on_board','yes'],['dnp','no'],['uuid',uid(p['ref'])],
      ['property','"Reference"',q(p['ref']),['at',str(sx),str(sy-half-3),'0'],['effects',['font',['size','1.27','1.27']]]],
      ['property','"Value"',q(p['value']),['at',str(sx),str(sy+half+3),'0'],['effects',['font',['size','1','1']]]],
      ['property','"Footprint"',q('Aetherpose:'+p['footprint']),['at',str(sx),str(sy),'0'],['effects',['font',['size','1.27','1.27']],'hide']],
      ['instances',['project','"aetherpose_custom"',['path',q('/'+rootid),['reference',q(p['ref'])],['unit','1']]]]])
schematic.append(lib);schematic.extend(extra);schematic.extend(instances)
(ROOT/'aetherpose_custom.kicad_sch').write_text(dump(schematic),encoding='utf-8')
svg.append('<text x="15" y="408" font-size="2.2">Review draft: all block pins use passive ERC type. Pin-to-pin checks are required; ERC alone cannot validate power design.</text></svg>')
(ROOT/'schematic-preview.svg').write_text('\n'.join(svg),encoding='utf-8')
with (ROOT/'pin-netlist.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['Reference','Pin','Function','Net']);w.writerows(pinrows)
with (ROOT/'bom.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['Reference','Value_MPN','Footprint','Qty_per_board','Qty_for_6','USD_budget_each','Price_status','Source'])
    for p in parts:w.writerow([p['ref'],p['value'],'Aetherpose:'+p['footprint'],1,6,p['price'],'reference_1pc' if p['ref'] in ['U1','U2','U3'] else 'engineering_allowance_not_quote',p['source']])

# FreeRouting input, individual pad images preserve all duplicate numbered pads.
def um(x):return str(round(x*1000))
dsn=['(pcb aetherpose_custom (parser (string_quote ") (space_in_quoted_tokens on) (host_cad "Aetherpose") (host_version "0.1")) (resolution um 10) (unit um)',
'(structure (layer F.Cu (type signal) (property (index 0))) (layer B.Cu (type signal) (property (index 1))) (boundary (rect pcb 0 -48000 45000 0)) (via VIA) (rule (width 200) (clearance 150)) (autoroute_settings (fanout off) (autoroute on) (postroute off) (vias on) (via_costs 50) (plane_via_costs 5) (start_ripup_costs 100) (start_pass_no 1) (layer_rule F.Cu (active on) (preferred_direction horizontal) (preferred_direction_trace_costs 1.0) (against_preferred_direction_trace_costs 2.5)) (layer_rule B.Cu (active on) (preferred_direction vertical) (preferred_direction_trace_costs 1.0) (against_preferred_direction_trace_costs 2.5)))']
for x1,y1,x2,y2 in keepouts:
    for layer in ['F.Cu','B.Cu']:dsn.append(f'(keepout (rect {layer} {um(x1)} {um(-y2)} {um(x2)} {um(-y1)}))')
dsn.append(') (placement')
for i,p in enumerate(padrecords):dsn.append(f'(component P{i} (place P{i} {um(p["x"])} {um(-p["y"])} front 0))')
dsn.append(') (library (padstack VIA (shape (circle F.Cu 600 0 0)) (shape (circle B.Cu 600 0 0)) (attach off))')
for i,p in enumerate(padrecords):
    dsn.append(f'(image P{i} (pin PS{i} 1 0 0)) (padstack PS{i}')
    for layer in p['layers']:dsn.append(f'(shape (rect {layer} {um(-p["w"]/2)} {um(-p["h"]/2)} {um(p["w"]/2)} {um(p["h"]/2)}))')
    dsn.append('(attach off))')
dsn.append(') (network')
router_nets={}
for i,p in enumerate(padrecords):router_nets.setdefault(p['net'] or f'NC_{i}',[]).append(f'P{i}-1')
for net,pp in router_nets.items():dsn.append(f'(net {q(net)} (pins '+ ' '.join(pp)+'))')
dsn.append('(class default '+ ' '.join(q(n) for n in router_nets)+' (circuit (use_via VIA)) (rule (width 200) (clearance 150)))) (wiring))')
(ROOT/'aetherpose_custom.dsn').write_text('\n'.join(dsn),encoding='utf-8')
print(f'Built schematic, placement PCB, BOM, pin netlist, router input: {len(parts)} parts, {len(padrecords)} pads, {len(netnames)-1} nets.')
