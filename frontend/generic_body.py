"""Original procedural mannequin. No SMPL templates, weights or model data.

Dimensions below are manually chosen display proportions in metres. The 24
functional joint indices match the app's pose protocol; this is not SMPL shape.
"""
import numpy as np
from smpl_fk import SMPLForwardKinematics

class GenericBody:
 def __init__(self):
  self.parents=np.array([-1,0,0,0,1,2,3,4,5,6,7,8,9,9,9,12,13,14,16,17,18,19,20,21])
  self.J_rest=np.array([[0,0,0],[.085,-.07,0],[-.085,-.07,0],[0,.12,0],
   [.085,-.50,0],[-.085,-.50,0],[0,.27,0],[.085,-.87,0],[-.085,-.87,0],[0,.43,0],
   [.085,-.90,.13],[-.085,-.90,.13],[0,.55,0],[.075,.47,0],[-.075,.47,0],[0,.68,0],
   [.19,.47,0],[-.19,.47,0],[.48,.47,0],[-.48,.47,0],[.73,.47,0],[-.73,.47,0],
   [.80,.47,0],[-.80,.47,0]],dtype=np.float32)
  verts=[];faces=[];bones=[]
  def ellipsoid(center,radii,bone,basis=None):
   start=len(verts);basis=np.eye(3) if basis is None else basis
   for lat in range(9):
    theta=np.pi*lat/8
    for lon in range(12):
     phi=2*np.pi*lon/12
     v=np.array([np.sin(theta)*np.cos(phi),np.cos(theta),np.sin(theta)*np.sin(phi)])*radii
     verts.append(center+basis@v);bones.append(bone)
   for lat in range(8):
    for lon in range(12):
     a=start+lat*12+lon;b=start+lat*12+(lon+1)%12;c=a+12;d=b+12
     faces.extend([[a,c,b],[b,c,d]])
  def segment(a,b,radius,bone,depth=None):
   delta=b-a;y=delta/np.linalg.norm(delta);helper=np.array([0.,0,1.])
   if abs(np.dot(y,helper))>.95:helper=np.array([1.,0,0])
   x=np.cross(y,helper);x/=np.linalg.norm(x);z=np.cross(x,y)
   ellipsoid((a+b)/2,[radius,np.linalg.norm(delta)*.57,depth or radius],bone,np.column_stack([x,y,z]))
  J=self.J_rest
  ellipsoid(np.array([0.,-.015,0]),[.145,.115,.105],0)
  for a,b,r,d in ((0,3,.135,.095),(3,6,.13,.09),(6,9,.175,.105),(9,12,.115,.085),(12,15,.045,.045)):
   segment(J[a],J[b],r,a,d)
  ellipsoid(J[15]+[0,.065,0],[.085,.115,.09],15)
  ellipsoid(J[15]+[0,.05,.085],[.018,.025,.024],15)
  for hip,knee,ankle,toe,shoulder,elbow,wrist,hand in ((1,4,7,10,16,18,20,22),(2,5,8,11,17,19,21,23)):
   for a,b,r in ((hip,knee,.07),(knee,ankle,.05),(shoulder,elbow,.045),(elbow,wrist,.035),(wrist,hand,.027)):
    segment(J[a],J[b],r,a)
   for j,r in ((hip,.07),(knee,.052),(shoulder,.05),(elbow,.038)):
    ellipsoid(J[j],[r,r,r],j)
   ellipsoid(J[ankle]+[0,-.045,.06],[.055,.035,.12],ankle)
  self.v_template=np.asarray(verts,dtype=np.float32);self.faces=np.asarray(faces,dtype=np.int32)
  self.weights=np.zeros((len(verts),24),dtype=np.float32)
  self.weights[np.arange(len(verts)),bones]=1

 page_skin=SMPLForwardKinematics.page_skin
 lbs_frame=SMPLForwardKinematics.lbs_frame
