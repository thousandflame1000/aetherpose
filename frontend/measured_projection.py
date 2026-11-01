"""Project measured WORLD orientations without free child counter-rotation.

Unmeasured proximal joints adapt to measured distal directions while the
filtered local hinge is fixed. Conflicting measured pairs/rig bounds remain
explicit residuals. Head/neck ambiguity uses a bounded regularized split;
the split is a hypothesis, not an observed neck angle.
"""
import math
import numpy as np
from scipy.spatial.transform import Rotation
from scipy.optimize import least_squares

def error(A,B):return float(np.degrees(Rotation.from_matrix(A@B.T).magnitude()))

def globals_(R,parents):
 G=np.empty_like(R)
 for j,p in enumerate(parents):G[j]=R[j] if p<0 else G[p]@R[j]
 return G

def box_angles(R,bounds):
 cy=math.hypot(R[0,0],R[1,0]);y=math.atan2(-R[2,0],cy)
 x=math.atan2(R[2,1],R[2,2]) if cy>1e-8 else math.atan2(-R[1,2],R[1,1])
 z=math.atan2(R[1,0],R[0,0]) if cy>1e-8 else 0.
 e=np.array([x,y,z]);other=np.array([x+np.pi,np.pi-y,z+np.pi]);other=(other+np.pi)%(2*np.pi)-np.pi
 candidates=[np.clip(v,*bounds) for v in (e,other)]
 return min(candidates,key=lambda v:error(Rotation.from_euler('xyz',v).as_matrix(),R))

def bounded(R,j,fitter):
 if j not in fitter.bounds:return R.copy()
 bounds=np.deg2rad(fitter.bounds[j]);e=box_angles(R,bounds)
 return Rotation.from_euler('xyz',e).as_matrix()

def repair_pair(R,j,target,targets,fitter,reference):
 """A measured free joint with one unmeasured bounded parent, e.g. head/neck."""
 parent=int(fitter.parents[j]);grand=int(fitter.parents[parent])
 if parent in targets or parent not in fitter.bounds or j not in fitter.bounds:return None
 G=globals_(R,fitter.parents);base=np.eye(3) if grand<0 else G[grand]
 prior_parent,prior_child=reference[parent].copy(),reference[j].copy()
 bounds_parent=np.deg2rad(fitter.bounds[parent]);bounds_child=np.deg2rad(fitter.bounds[j])
 start=np.r_[box_angles(prior_parent,bounds_parent),box_angles(prior_child,bounds_child)]
 lower=np.r_[bounds_parent[0],bounds_child[0]];upper=np.r_[bounds_parent[1],bounds_child[1]]
 def residual(x):
  A,B=Rotation.from_euler('xyz',x.reshape(2,3)).as_matrix()
  # The measured orientation has high precision; finite priors decide the
  # unobservable split without importing any true parent angle.
  observed=Rotation.from_matrix((base@A@B)@target.T).as_rotvec()*300
  regularize=np.r_[Rotation.from_matrix(A@prior_parent.T).as_rotvec(),Rotation.from_matrix(B@prior_child.T).as_rotvec()]
  return np.r_[observed,regularize]
 solution=least_squares(residual,start,bounds=(lower,upper),max_nfev=40,ftol=1e-8,xtol=1e-8,gtol=1e-8)
 A,B=Rotation.from_euler('xyz',solution.x.reshape(2,3)).as_matrix()
 exact=(base@A).T@target
 if error(exact,bounded(exact,j,fitter))<.01:B=exact
 R[parent],R[j]=A,B
 return error(base@A@B,target)<.05

def condition(local,targets,fitter,reference=None):
 R=np.array(local,copy=True);conflicts=[];pairs=[]
 reference=R.copy() if reference is None else np.array(reference,copy=True)
 if not targets:return R,dict(parent_bound_conflicts=[],measured_pair_conflicts=[],head_neck_hypothesis=False)
 G=globals_(R,fitter.parents)
 if 0 in targets:R[0]=targets[0];G=globals_(R,fitter.parents)
 hinges={chain[1] for chain in fitter.CHAINS}
 # Measured torso/proximal/free segments use global-to-parent conversion.
 for j in sorted(targets):
  if j==0 or j in hinges or j==15:continue
  parent=fitter.parents[j];desired=targets[j] if parent<0 else G[parent].T@targets[j]
  proposal=bounded(desired,j,fitter)
  if error(proposal,desired)>.05:
   repaired=repair_pair(R,j,targets[j],targets,fitter,reference)
   if not repaired:
    conflicts.append(j)
    if repaired is None:R[j]=proposal
  else:R[j]=desired
  G=globals_(R,fitter.parents)
 for proximal,hinge,distal,axis,sign in fitter.CHAINS:
  if hinge not in targets:continue
  # Keep this local hinge, including its constrained axial component, fixed.
  H=R[hinge].copy();parent=fitter.parents[proximal]
  if proximal not in targets:
   desired=targets[hinge]@H.T
   relative=desired if parent<0 else G[parent].T@desired
   proposal=bounded(relative,proximal,fitter)
   if error(proposal,relative)>.05:conflicts.append(proximal)
   R[proximal]=proposal
  else:
   desired=targets[proximal].T@targets[hinge]
   projected=fitter.project(np.tile(np.eye(3),(24,1,1)))
   projected[hinge]=desired;projected=fitter.project(projected)
   R[hinge]=projected[hinge]
   if error(R[hinge],desired)>.05:pairs.append([proximal,hinge])
  G=globals_(R,fitter.parents)
 repaired_head=False
 if 15 in targets:
  desired=G[fitter.parents[15]].T@targets[15]
  proposal=bounded(desired,15,fitter)
  if error(proposal,desired)>.05:
   repaired_head=repair_pair(R,15,targets[15],targets,fitter,reference)
   if not repaired_head:
    conflicts.append(15)
    if repaired_head is None:R[15]=proposal
  else:R[15]=desired
 # Parent chains have now settled. Rebase independently measured free child
 # segments (ankles/wrists/etc.) in topological order. Never replace a
 # constrained local knee/elbow with an arbitrary SO(3) counter-rotation.
 reconciled=[]
 for j in sorted(targets):
  G=globals_(R,fitter.parents)
  if j in hinges:continue
  parent=fitter.parents[j]
  desired=targets[j] if parent<0 else G[parent].T@targets[j]
  proposal=bounded(desired,j,fitter)
  if error(proposal,desired)>.05:conflicts.append(j)
  if error(G[j],targets[j])>.05:reconciled.append(j)
  R[j]=proposal
 G=globals_(R,fitter.parents)
 final_errors={str(j):error(G[j],target) for j,target in targets.items()}
 final_conflicts=[j for j in sorted(targets) if final_errors[str(j)]>.05]
 return R,dict(parent_bound_conflicts=sorted(set(conflicts)),measured_pair_conflicts=pairs,head_neck_hypothesis=bool(repaired_head),
  final_measured_reconciliation=dict(rebased=reconciled,conflicts=final_conflicts,residual_deg=final_errors))
