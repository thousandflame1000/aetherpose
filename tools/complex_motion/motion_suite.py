"""Deterministic challenging kinematic trajectories, not motion-capture ground truth."""
import numpy as np
from scipy.spatial.transform import Rotation

FPS=60
SECONDS=6
CASES=[('cross_reach','交叉伸手與反向轉胸'),('overhead','過頭抬手與轉肩'),
       ('squat_twist','深蹲加骨盆／胸口反向扭轉'),('knee_lift','單腳抬膝與手臂反向擺動'),
       ('back_reach','轉身與手往背後伸'),('counter_bend','左右不同步彎肘、屈髖')]
SENSORS=[18,19,4,5,15,0]
VERTICES=[1961,5424,1176,4662,411,3021]

def globals_and_joints(local,rest,parents):
 g=np.empty_like(local);p=np.zeros((24,3))
 for j,parent in enumerate(parents):
  g[j]=local[j] if parent<0 else g[parent]@local[j]
  if parent>=0:p[j]=p[parent]+g[parent]@(rest[j]-rest[parent])
 return g,p

def trajectory(case,t):
 R=np.tile(np.eye(3),(24,1,1))
 # Two seconds of identical T-pose warm-up; quintic ramp avoids acceleration impulses.
 z=np.clip((t-2)/1,0,1);a=10*z**3-15*z**4+6*z**5
 u=max(t-2,0);s=np.sin(2*np.pi*u/3);c=np.cos(2*np.pi*u/3)
 def put(j,x=0,y=0,z=0):R[j]=Rotation.from_euler('xyz',a*np.array([x,y,z]),degrees=True).as_matrix()
 if case=='cross_reach':
  put(3,y=18*s);put(9,y=-30*s);put(16,y=-60,z=-40+20*c);put(17,y=60,z=40-20*c)
  put(18,y=-75-35*s);put(19,y=75-35*s);put(15,y=20*s)
 elif case=='overhead':
  put(16,x=25*s,y=30*s,z=55+35*c);put(17,x=-25*s,y=-30*s,z=-55-35*c)
  put(18,y=-55-40*s);put(19,y=55-40*s);put(9,x=-15,y=18*s)
 elif case=='squat_twist':
  q=35*(1+c)/2;put(0,y=30*s);put(1,x=-q);put(2,x=-q);put(4,x=2*q);put(5,x=2*q)
  put(7,x=-q);put(8,x=-q);put(3,x=q*.5,y=-12*s);put(9,y=-28*s)
  put(16,z=-55);put(17,z=55);put(18,y=-95);put(19,y=95)
 elif case=='knee_lift':
  q=(1+s)/2;put(1,x=-85*q,y=20*q);put(4,x=100*q);put(2,x=-12*(1-q));put(5,x=18*(1-q))
  put(9,z=10*s);put(16,y=-40*s,z=-45);put(17,y=40*s,z=45);put(18,y=-55);put(19,y=75)
 elif case=='back_reach':
  put(0,y=110*np.sin(np.pi*u/4));put(9,y=35*s);put(16,x=-35,y=45,z=-35)
  put(17,x=25,y=-50,z=35);put(18,y=-105-20*s);put(19,y=100+20*s);put(15,y=-30*s)
 elif case=='counter_bend':
  put(1,x=-35*(1+s)/2);put(4,x=65*(1+s)/2);put(2,x=-35*(1-s)/2);put(5,x=65*(1-s)/2)
  put(16,y=35*s,z=-40);put(17,y=-35*c,z=40);put(18,y=-75-55*s);put(19,y=75+55*c)
  put(3,x=15,y=20*s);put(9,y=-20*c)
 return R

def generate(fk):
 local=[];glb=[];joints=[];translation=[];positions=[];case_ids=[]
 # Use the six attachment vertices of the official GlobalPose synthesis code.
 weights=fk.weights[VERTICES];vertices=fk.v_template[VERTICES]
 for k,(case,_) in enumerate(CASES):
  for i in range(FPS*SECONDS):
   R=trajectory(case,i/FPS);G,P=globals_and_joints(R,fk.J_rest,fk.parents)
   # Root-relative floor grounding is a constructed motion assumption.
   y=-.97-min(P[10,1],P[11,1]);T=np.array([0,y,0])
   delta=P-np.einsum('jab,jb->ja',G,fk.J_rest-fk.J_rest[0])
   v=np.einsum('vj,jab,vb->va',weights,G,vertices-fk.J_rest[0])+weights@delta+T
   local.append(R);glb.append(G);joints.append(P);translation.append(T);positions.append(v);case_ids.append(k)
 return {k:np.array(v) for k,v in dict(local=local,global_r=glb,joints=joints,translation=translation,sensor_positions=positions,case_ids=case_ids).items()}

def measurements(data,seed=20261101):
 rng=np.random.default_rng(seed);ori=data['global_r'][:,SENSORS].copy();pos=data['sensor_positions']
 acc=np.zeros_like(pos);gyro=np.zeros_like(pos)
 for k in range(len(CASES)):
  sl=slice(k*FPS*SECONDS,(k+1)*FPS*SECONDS);p=pos[sl];r=ori[sl]
  acc[sl]=np.gradient(np.gradient(p,1/FPS,axis=0,edge_order=2),1/FPS,axis=0,edge_order=2)
  delta=r[1:]@r[:-1].transpose(0,1,3,2)
  omega=Rotation.from_matrix(delta.reshape(-1,3,3)).as_rotvec().reshape(-1,6,3)*FPS
  gyro[sl][1:]=omega;gyro[sl][0]=omega[0]
 # Explicit engineered noise, not a reproduction of the paper's IMU simulator.
 noise=Rotation.from_rotvec(np.deg2rad(.5)*rng.normal(size=(len(ori)*6,3))).as_matrix().reshape(ori.shape)
 ori=ori@noise
 acc+=rng.normal(0,.05,acc.shape);gyro+=rng.normal(0,.005,gyro.shape)
 return dict(ori=ori,acc=acc,gyro=gyro)

def ambiguity(rest,parents):
 # Exact rigid-segment counterexample. No anatomical validity is assumed:
 # an unmeasured upper arm twists while the forearm counter-rotates.
 poses=[]
 axis=rest[18]-rest[16];axis=axis/np.linalg.norm(axis)
 for degrees in (-40,40):
  R=np.tile(np.eye(3),(24,1,1));twist=Rotation.from_rotvec(axis*np.deg2rad(degrees)).as_matrix()
  R[16]=twist;R[18]=twist.T
  poses.append(R)
 A,pa=globals_and_joints(poses[0],rest,parents);B,pb=globals_and_joints(poses[1],rest,parents)
 return dict(parent_separation_deg=float(np.degrees(Rotation.from_matrix(A[16]@B[16].T).magnitude())),
  measured_orientation_max_difference=float(np.max(np.abs(A[SENSORS]-B[SENSORS]))),
  joint_center_max_difference_m=float(np.max(np.abs(pa-pb))),
  worst_case_parent_error_lower_bound_deg=40.,
  scope='Exact rigid-segment, joint-center sensor counterexample; not an anatomically validated motion or exact skin-mounted-vertex equality. Static acceleration and gyro are identical. Position-only camera landmarks cannot observe this axial twist.')
