"""Camera rotation from independent calibrated IMU bone rays, not an upright body assumption."""
import itertools
import numpy as np
from hybrid_fusion import proper_rotation

def estimate_camera_alignment(fusion,sensors,points,confidence):
 """Return world_from_camera and measured-ray diagnostics, or reject ambiguity.

 Inputs are camera-estimated relative points and actual calibrated segment
 rotations. No ground truth, GlobalPose pose or world-up torso proxy is used.
 """
 q=np.asarray(points,float);c=np.asarray(confidence,float)
 if q.shape!=(24,3) or c.shape!=(24,) or not np.isfinite(q).all() or not np.isfinite(c).all():raise ValueError('無效的影像校正資料。')
 rays=[]
 def add(j,a,b,source,target):
  quality=float(min(c[a],c[b]))
  na,nb=np.linalg.norm(source),np.linalg.norm(target)
  if quality>=.8 and na>.035 and nb>.035:rays.append((j,source/na,target/nb,quality))
 if 0 in sensors:add(0,1,2,q[1]-q[2],sensors[0]@(fusion.rest[1]-fusion.rest[2]))
 for j,R in sensors.items():
  if j==0:continue
  # Use measured endpoint bones, never interpolated vertebral points.
  for child in fusion.children[j]:
   if child in (3,6,9,13,14):continue
   add(j,j,child,q[child]-q[j],R@(fusion.rest[child]-fusion.rest[j]))
 if len(rays)<2:raise ValueError('校正需要兩個不同方向的可信 IMU 骨段；請讓骨盆與腿部，或兩條彎曲手臂清楚入鏡。')
 sources=np.array([r[1] for r in rays]);targets=np.array([r[2] for r in rays]);weights=np.array([r[3] for r in rays])
 best=None
 for i,j in itertools.combinations(range(len(rays)),2):
  if rays[i][0]==rays[j][0] or min(np.linalg.norm(np.cross(sources[i],sources[j])),np.linalg.norm(np.cross(targets[i],targets[j])))<np.sin(np.deg2rad(25)):continue
  candidate=proper_rotation(np.outer(targets[i],sources[i])+np.outer(targets[j],sources[j]))
  errors=np.arccos(np.clip(np.sum((sources@candidate.T)*targets,axis=1),-1,1))
  good=errors<np.deg2rad(20);score=(float(weights[good].sum()),-float(np.sum(np.minimum(errors,np.deg2rad(60))*weights)))
  if best is None or score>best[0]:best=(score,good)
 if best is None:raise ValueError('目前骨段方向幾乎平行，無法確定相機旋轉；請彎一條手臂後重試。')
 good=best[1]
 matrix=np.einsum('n,ni,nj->ij',weights[good],targets[good],sources[good])
 R=proper_rotation(matrix)
 errors=np.degrees(np.arccos(np.clip(np.sum((sources@R.T)*targets,axis=1),-1,1)))
 if np.mean(errors[good])>15:raise ValueError('影像與 IMU 的方向不一致，請確認身體部位指派與感測器校正。')
 return R,dict(method='measured_bone_rays',rays=len(rays),inliers=int(good.sum()),mean_residual_deg=round(float(np.mean(errors[good])),3))
