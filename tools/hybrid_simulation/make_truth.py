"""Known articulated motion and sensor mounting, used only for simulation input/evaluation."""
from pathlib import Path
import os
import json,sys
import numpy as np
from scipy.spatial.transform import Rotation
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'frontend'))
from smpl_fk import SMPLForwardKinematics
from hybrid_fusion import RotationFusion,BONE_TO_JOINT

BASE=Path(os.environ.get('AETHER_SIM_DATA_DIR',str(Path(__file__).parent/'data')));BASE.mkdir(parents=True,exist_ok=True)
FPS=15;SECONDS=18
from external_paths import resolve
fk=SMPLForwardKinematics(str(resolve()[0]['smpl_npz']))
fusion=RotationFusion(fk.J_rest,fk.parents);fusion.bind_foot_skin(fk)
frames=[];local=[];global_r=[];joints=[]
for i in range(FPS*SECONDS):
 t=i/FPS;R=np.tile(np.eye(3),(24,1,1))
 def set_r(j,x=0,y=0,z=0):R[j]=Rotation.from_euler('xyz',[x,y,z],degrees=True).as_matrix()
 squat=19*(1-np.cos(t*1.1))*.5
 set_r(0,y=10*np.sin(t*.6))
 set_r(1,x=-squat-8*np.sin(t*1.8));set_r(2,x=-squat+8*np.sin(t*1.8))
 set_r(4,x=2*squat+6*(1+np.sin(t*1.8)));set_r(5,x=2*squat+6*(1-np.sin(t*1.8)))
 set_r(7,x=-squat*.7);set_r(8,x=-squat*.7)
 set_r(3,x=squat*.4);set_r(9,y=6*np.sin(t*.8))
 set_r(16,y=16*np.sin(t*1.3),z=-65+27*np.sin(t*1.5))
 set_r(17,y=-16*np.sin(t*1.2),z=65-27*np.sin(t*1.5+.5))
 set_r(18,z=45+33*np.sin(t*1.7));set_r(19,z=-45-33*np.sin(t*1.7+.8))
 set_r(15,y=10*np.sin(t*.9),x=3*np.sin(t*.8))
 P=fusion.joints(R);translation=[0,float(fusion.foot_floor_translation(R,P)),0]
 G=np.empty_like(R)
 for j,p in enumerate(fk.parents):G[j]=R[j] if p<0 else G[p]@R[j]
 local.append(R);global_r.append(G);joints.append(P)
 frames.append(dict(t=round(t,5),rotations=R.round(6).ravel().tolist(),translation=translation,joints=P.round(6).tolist()))
sensor_joints=list(BONE_TO_JOINT.values())
mounts=Rotation.from_euler('xyz',np.random.default_rng(1206).uniform(-40,40,(19,3)),degrees=True).as_matrix()
np.savez_compressed(BASE/'truth.npz',local=np.array(local),global_r=np.array(global_r),joints=np.array(joints),rest=fk.J_rest,parents=fk.parents,mounts=mounts,sensor_joints=sensor_joints)
data=dict(fps=FPS,seconds=SECONDS,skin=fk.page_skin(),faces=fk.faces.ravel().tolist(),frames=frames,sensor_joints=sensor_joints)
(BASE/'truth.json').write_text(json.dumps(data,separators=(',',':')),encoding='utf-8')
head=fk.v_template[fk.weights[:,15]>.5]
print('head relative bounds',head.min(0)-fk.J_rest[15],head.max(0)-fk.J_rest[15])
print('Generated',len(frames),'truth frames and',len(sensor_joints),'fixed sensor mountings.')
