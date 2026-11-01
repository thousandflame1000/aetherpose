"""Frozen multiview/posture v1 catalog. Constructed kinematics, not human mocap."""
import numpy as np
from scipy.spatial.transform import Rotation

FPS=60;SECONDS=6;CAMERA_FPS=10;SEED=202611011
SENSORS=[18,19,4,5,15,0];VERTICES=[1961,5424,1176,4662,411,3021]
CASES=[
 {'id':'stand_reach','split':'dev','posture':'stand','label':'站立交叉伸手'},
 {'id':'sit_twist','split':'dev','posture':'sit','label':'坐姿轉體伸手'},
 {'id':'squat_reach','split':'dev','posture':'squat','label':'蹲姿伸手'},
 {'id':'supine_reach','split':'dev','posture':'supine','label':'仰躺抬手屈膝'},
 {'id':'prone_press','split':'dev','posture':'prone','label':'俯躺屈肘抬頭'},
 {'id':'side_reach','split':'dev','posture':'side','label':'側躺伸手屈腿'},
 {'id':'stand_overhead','split':'heldout','posture':'stand','label':'站立過頭交替抬手'},
 {'id':'sit_to_stand','split':'heldout','posture':'sit','label':'坐姿到站立'},
 {'id':'squat_turn','split':'heldout','posture':'squat','label':'蹲姿轉身起伏'},
 {'id':'supine_roll','split':'heldout','posture':'supine','label':'仰躺轉側躺'},
 {'id':'prone_reach','split':'heldout','posture':'prone','label':'俯躺交替伸手'},
 {'id':'side_roll','split':'heldout','posture':'side','label':'側躺轉仰躺'}]
VIEWS=[
 {'id':'front','yaw':0.,'elevation':8.},
 {'id':'side','yaw':90.,'elevation':8.},
 {'id':'back','yaw':180.,'elevation':8.},
 {'id':'oblique','yaw':-45.,'elevation':20.},
 {'id':'high','yaw':30.,'elevation':55.},
 {'id':'low','yaw':-20.,'elevation':-8.}]

def smooth(x):
 x=np.clip(x,0,1);return 10*x**3-15*x**4+6*x**5

def pose(case,t):
 posture=case['posture'];u=max(t-2,0);a=smooth(u);s=np.sin(2*np.pi*u/3.6);c=np.cos(2*np.pi*u/3.1+.4)
 R=np.tile(np.eye(3),(24,1,1))
 def put(j,x=0,y=0,z=0):R[j]=Rotation.from_euler('xyz',[x,y,z],degrees=True).as_matrix()
 # Warm-up is held in the actual base posture, including the lying root.
 if posture=='sit':
  put(1,x=-85);put(2,x=-85);put(4,x=90);put(5,x=90);put(16,z=-55);put(17,z=55);put(18,y=-70);put(19,y=70)
 elif posture=='squat':
  put(1,x=-65);put(2,x=-65);put(4,x=120);put(5,x=120);put(7,x=-50);put(8,x=-50);put(3,x=25);put(16,z=-45);put(17,z=45);put(18,y=-80);put(19,y=80)
 elif posture=='supine':
  put(0,x=-90);put(16,z=-50);put(17,z=50);put(18,y=-25);put(19,y=25)
 elif posture=='prone':
  put(0,x=90);put(16,y=-20,z=-45);put(17,y=20,z=45);put(18,y=-90);put(19,y=90);put(12,x=-15)
 elif posture=='side':
  put(0,z=90);put(16,z=-60);put(17,z=35);put(18,y=-50);put(19,y=75);put(1,x=-25);put(2,x=-15);put(4,x=35);put(5,x=25)
 else:
  put(16,z=-45);put(17,z=45);put(18,y=-35);put(19,y=35)
 if t<2:return R
 ident=case['id']
 if ident=='stand_reach':
  put(9,y=-25*a*s);put(16,y=-45*a,z=-45+15*a*c);put(17,y=45*a,z=45-15*a*c);put(18,y=-35-55*a*(1+s)/2);put(19,y=35+55*a*(1-s)/2)
 elif ident=='sit_twist':
  put(9,y=30*a*s);put(16,y=-35*a,z=-55+20*a*c);put(17,y=30*a,z=55-20*a*c);put(18,y=-70-25*a*s);put(19,y=70+25*a*c)
 elif ident=='squat_reach':
  q=65+10*a*s;put(1,x=-q);put(2,x=-q);put(4,x=2*q-10);put(5,x=2*q-10);put(9,y=25*a*s);put(16,y=-30*a,z=-45);put(17,y=30*a,z=45);put(18,y=-80-20*a*c);put(19,y=80+20*a*s)
 elif ident=='supine_reach':
  put(16,y=-45*a*s,z=-50+25*a*c);put(17,y=35*a*c,z=50-25*a*s);put(18,y=-25-60*a*(1+s)/2);put(19,y=25+60*a*(1-c)/2);put(1,x=-45*a*(1+s)/2);put(4,x=75*a*(1+s)/2)
 elif ident=='prone_press':
  put(16,x=15*a*s,y=-20,z=-45);put(17,x=-15*a*c,y=20,z=45);put(18,y=-90-25*a*s);put(19,y=90+25*a*c);put(12,x=-15-15*a*(1+s)/2);put(4,x=25*a*(1+c)/2)
 elif ident=='side_reach':
  put(17,x=30*a*s,y=35*a,z=35+20*a*c);put(19,y=75+35*a*s);put(2,x=-15-35*a*(1+s)/2);put(5,x=25+50*a*(1+s)/2);put(9,y=20*a*s)
 elif ident=='stand_overhead':
  put(16,x=20*a*s,y=20*a*c,z=-45+110*a*(1+s)/2);put(17,x=-15*a*c,y=-25*a*s,z=45-105*a*(1+c)/2);put(18,y=-35-50*a*(1+c)/2);put(19,y=35+50*a*(1+s)/2);put(9,y=18*a*s)
 elif ident=='sit_to_stand':
  rise=smooth((u-.5)/2.6);put(1,x=-85*(1-rise));put(2,x=-85*(1-rise));put(4,x=90*(1-rise));put(5,x=90*(1-rise));put(9,x=18*a*(1-rise),y=18*a*s);put(18,y=-70+25*a*s);put(19,y=70+25*a*c)
 elif ident=='squat_turn':
  q=65-20*a*(1+s)/2;put(1,x=-q);put(2,x=-q-5*a*c);put(4,x=2*q-10);put(5,x=2*q-10+10*a*c);put(0,y=50*a*s);put(9,y=-25*a*c);put(18,y=-80-25*a*s);put(19,y=80+25*a*c)
 elif ident=='supine_roll':
  put(0,x=-90+90*a*(1+s)/2,z=90*a*(1+s)/2);put(1,x=-35*a);put(2,x=-20*a);put(4,x=65*a);put(5,x=40*a);put(16,z=-50+20*a*c);put(17,z=50+20*a*s);put(18,y=-25-45*a);put(19,y=25+45*a)
 elif ident=='prone_reach':
  put(16,y=-20-40*a*s,z=-45+45*a*(1+c)/2);put(17,y=20+40*a*c,z=45-45*a*(1+s)/2);put(18,y=-90+65*a*(1+s)/2);put(19,y=90-65*a*(1+c)/2);put(12,x=-15-10*a*s);put(5,x=40*a*(1+s)/2)
 elif ident=='side_roll':
  roll=smooth((u-.5)/2.5);put(0,x=-90*roll,z=90*(1-roll));put(9,y=20*a*s);put(17,y=40*a,z=35+25*a*c);put(19,y=75+20*a*s);put(2,x=-15-25*a*c);put(5,x=25+40*a*(1+c)/2)
 return R

def globals_and_joints(local,rest,parents):
 G=np.empty_like(local);P=np.zeros((24,3))
 for j,p in enumerate(parents):
  G[j]=local[j] if p<0 else G[p]@local[j]
  if p>=0:P[j]=P[p]+G[p]@(rest[j]-rest[p])
 return G,P
