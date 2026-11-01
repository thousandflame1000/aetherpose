"""Freeze different compound trajectories before inspecting candidate scores."""
from pathlib import Path
import sys,runpy,argparse,numpy as np
from scipy.spatial.transform import Rotation
p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).resolve().parent))
import motion_suite as suite
original_measurements=suite.measurements
def motion(case,t):
 R=np.tile(np.eye(3),(24,1,1));z=np.clip(t-2,0,1);a=10*z**3-15*z**4+6*z**5
 u=max(0,t-2);s=np.sin(2*np.pi*u/3.7);c=np.cos(2*np.pi*u/2.9+.4)
 def put(j,x=0,y=0,z=0):R[j]=Rotation.from_euler('xyz',a*np.array([x,y,z]),degrees=True).as_matrix()
 if case=='cross_reach':
  put(0,y=25*s);put(9,x=15,y=-22*s);put(16,x=20*c,y=-45*s,z=-35);put(17,x=-12*c,y=35*s,z=40)
  put(18,y=-75-40*c);put(19,y=75+35*s);put(15,y=15*c)
 elif case=='overhead':
  put(13,z=8*s);put(14,z=-8*s);put(16,x=20*s,y=20*c,z=30+40*s);put(17,x=-15*c,y=-25*s,z=-30-35*c)
  put(18,y=-45-30*c);put(19,y=55+30*s);put(9,y=15*c)
 elif case=='squat_twist':
  q=28+12*s;put(1,x=-q);put(2,x=-q-8*c);put(4,x=2*q);put(5,x=2*q+12*c)
  put(0,y=-25*s);put(9,x=15,y=30*c);put(16,y=15*c,z=-60);put(17,y=-20*s,z=45);put(18,y=-95);put(19,y=105)
 elif case=='knee_lift':
  put(1,x=-40-30*s,z=10*c);put(4,x=75+35*s);put(2,x=-15,z=-12*c);put(5,x=25)
  put(0,y=25*c);put(16,y=-30*s,z=-30);put(17,y=35*c,z=50);put(18,y=-60-25*s);put(19,y=60+30*c)
 elif case=='back_reach':
  put(0,y=75*s);put(9,y=-25*c);put(16,x=-20,y=65,z=-40);put(17,x=25,y=-40,z=35)
  put(18,y=-95-15*c);put(19,y=85+20*s);put(15,y=20*c)
 else:
  put(16,y=25*s,z=-35);put(17,y=-25*c,z=35)
  R[18]=Rotation.from_euler('y',-a*(70+25*s),degrees=True).as_matrix()@Rotation.from_euler('x',a*70*c,degrees=True).as_matrix()
  R[19]=Rotation.from_euler('y',a*(80+20*c),degrees=True).as_matrix()@Rotation.from_euler('x',-a*65*s,degrees=True).as_matrix()
  put(1,x=-20-10*s);put(4,x=45+20*s);put(2,x=-20+10*c);put(5,x=45-20*c)
 return R
suite.trajectory=motion
suite.measurements=lambda data,seed=20261102:original_measurements(data,seed)
sys.argv=['benchmark.py','--project',str(ROOT),'--data',str(a.data.resolve()),'--output',str(a.output.resolve()),'--stage','generate']
runpy.run_path(str(Path(__file__).with_name('benchmark.py')),run_name='__main__')
