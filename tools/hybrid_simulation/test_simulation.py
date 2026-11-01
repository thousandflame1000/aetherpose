"""Numerical and counterfactual checks for the synthetic experiment."""
from pathlib import Path
import os
import json,sys,numpy as np
from scipy.spatial.transform import Rotation
from engine import Simulator,ORDER
BASE=Path(os.environ.get('AETHER_SIM_DATA_DIR',str(Path(__file__).parent/'data')));BASE.mkdir(parents=True,exist_ok=True);sim=Simulator(BASE);checks=[]
ideal=sim.measurements(0,0);initial=sim.truth['local'][0].copy()
out=sim.estimate(sim.observations['clear'][:30],ideal[:30],ORDER,initial)
maximum=0
for i,row in enumerate(out):
 R=Rotation.from_rotvec(np.array(row['imu_unfiltered']['aa']).reshape(24,3)).as_matrix()
 maximum=max(maximum,float(np.max(np.linalg.norm(sim.fusion.joints(R)-sim.truth['joints'][i],axis=1))))
# The production solver deliberately retains a .15 temporal prior against
# weight-5 IMU measurements, so moving ideal inputs have a small regularization
# lag. Check exact static mounting separately from that bounded dynamic lag.
assert maximum<.002,maximum
static=sim.estimate([dict(camera=None)]*3,[ideal[0]]*3,ORDER,initial)
for row in static:
 R=Rotation.from_rotvec(np.array(row['imu']['aa']).reshape(24,3)).as_matrix()
 assert np.max(np.linalg.norm(sim.fusion.joints(R)-sim.truth['joints'][0],axis=1))<.00002
checks.append('ideal mounting reconstructs static joints within 0.02 mm; unfiltered dynamic solver error stays below 2 mm (filter latency is evaluated separately)')
frozen=sim.measurements(.8,2)
sample=sim.observations['occluded'][:30]
expected=sim.estimate(sample,frozen[:30],ORDER[:6],initial)
class ForbiddenTruth:
 def __getitem__(self,key):raise AssertionError('Estimator attempted to access animated truth')
truth=sim.truth;sim.truth=ForbiddenTruth()
try:blind=sim.estimate(sample,frozen[:30],ORDER[:6],initial)
finally:sim.truth=truth
assert expected==blind
checks.append('estimates are unchanged when the animated truth is inaccessible')
none=[dict(camera=None) for _ in range(30)]
no_camera=sim.estimate(none,frozen[:30],ORDER[:6],initial)
assert all(f['raw_imu']==f['weighted'] and f['imu']==f['feedback'] for f in no_camera)
checks.append('without images, matched constrained branches agree, and matched unconstrained branches agree')
camera_only=sim.estimate(sample,frozen[:30],[],initial)
assert all(not f['feedback_active'] and f['correction_deg']==0 for f in camera_only)
checks.append('zero IMUs does not invent inertial information or heading correction')
results={}
for name,selected,noise,drift,occ in [('default',ORDER[:6],.8,2,True),('clear',ORDER[:6],.8,2,False),('two',ORDER[:2],.8,2,True),('all',ORDER,.8,2,True),('ideal_all',ORDER,0,0,True)]:
 r=sim.run(selected,noise,drift,occ);results[name]=r['summary']
 for i,f in enumerate(r['frames']):
  for method in ('imu','weighted','feedback'):assert np.isfinite(f[method]['aa']).all()
  for method in ('imu','feedback'):
   vectors=np.array(f[method]['aa']).reshape(24,3)
   for j,axis,sign in ((4,0,1),(5,0,1),(18,2,1),(19,2,-1)):
    assert np.linalg.norm(np.delete(vectors[j],axis))<1e-6
    assert -.00001<=sign*vectors[j,axis]<=np.deg2rad(145)+.00001
   assert not f[method]['joint_warnings']
  if not f['camera_available']:
   assert not f['feedback_active']
   if i:assert f['correction_deg']==r['frames'][i-1]['correction_deg']
 if name=='default':
  (BASE/'default-result.json').write_text(json.dumps(r,separators=(',',':')),encoding='utf-8')
  absent=[f for f in r['frames'][150:180] if not f['camera_available']]
  assert len(absent)>=28,len(absent)
 print(name,json.dumps(r['summary']),flush=True)
checks.append('all presets remain finite; no new visual heading correction when observations are absent')
checks.append('at least 28 of 30 fully blocked frames have no usable camera observation')
checks.append('constrained IMU and fusion have zero elbow/knee reverse bends or off-axis rotations in every preset frame')
report=dict(passed=True,checks=checks,ideal_max_joint_error_mm=maximum*1000,results=results,
            notes='One synthetic scene/trajectory/seed; improvements are reported, not a test requirement.')
(BASE/'simulation-tests.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS',len(checks),'checks')
