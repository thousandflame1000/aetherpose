"""Fetch original manufacturer documents and upstream KiCad footprints."""
from pathlib import Path
from urllib.request import urlopen, Request
from concurrent.futures import ThreadPoolExecutor
import hashlib,json
ROOT=Path(__file__).resolve().parent
SRC=ROOT/'sources'; SRC.mkdir(exist_ok=True)
FP=ROOT/'Aetherpose.pretty'; FP.mkdir(exist_ok=True)
paths=[
'Capacitor_SMD.pretty/C_0603_1608Metric.kicad_mod',
'Capacitor_SMD.pretty/C_0805_2012Metric.kicad_mod',
'Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod',
'LED_SMD.pretty/LED_0603_1608Metric.kicad_mod',
'Package_TO_SOT_SMD.pretty/SOT-23-5.kicad_mod',
'Package_LGA.pretty/Bosch_LGA-14_3x2.5mm_P0.5mm.kicad_mod',
'Package_LGA.pretty/LGA-16_3x3mm_P0.5mm.kicad_mod',
'Package_DFN_QFN.pretty/VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm_ThermalVias.kicad_mod',
'Connector_USB.pretty/USB_C_Receptacle_HRO_TYPE-C-31-M-12.kicad_mod',
'Connector_JST.pretty/JST_PH_B3B-PH-K_1x03_P2.00mm_Vertical.kicad_mod',
'Button_Switch_THT.pretty/SW_CuK_JS202011CQN_DPDT_Straight.kicad_mod',
'Button_Switch_SMD.pretty/SW_SPST_TL3342.kicad_mod',
]
jobs=[(FP/Path(p).name,'https://raw.githubusercontent.com/KiCad/kicad-footprints/master/'+p) for p in paths]
jobs += [(FP/'ESP32-C3-MINI-1.kicad_mod','https://raw.githubusercontent.com/espressif/kicad-libraries/main/footprints/Espressif.pretty/ESP32-C3-MINI-1.kicad_mod'),
 (SRC/'qmc5883p.pdf','https://www.qstcorp.com/upload/pdf/202512/2C939E5AA0704285BC3BE71132B8629B.pdf'),
 (SRC/'freerouting-1.9.0.jar','https://github.com/freerouting/freerouting/releases/download/v1.9.0/freerouting-1.9.0.jar')]
def fetch(job):
    p,url=job
    try:
        if not p.exists():p.write_bytes(urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=60).read())
        b=p.read_bytes()
        return dict(file=str(p.relative_to(ROOT)),url=url,sha256=hashlib.sha256(b).hexdigest(),bytes=len(b))
    except Exception as e:return dict(file=str(p.relative_to(ROOT)),url=url,error=str(e))
if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=8) as ex:results=list(ex.map(fetch,jobs))
    (SRC/'upstream-manifest.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    for r in results:print(r['file'],r.get('error','OK'))
