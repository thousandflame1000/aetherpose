from pathlib import Path
import sys,unittest
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'frontend'))
from generic_body import GenericBody
from hybrid_fusion import RotationFusion
from tracking_fusion import RealtimeFusion

class SparseMetadataTests(unittest.TestCase):
 def test_unmigrated_sparse_geometry_is_not_changed_by_optional_2d_metadata(self):
  body=GenericBody();f=RotationFusion(body.J_rest,body.parents);eye=np.tile(np.eye(3),(24,1,1))
  basis=Rotation.from_euler('yx',[45,25],degrees=True).as_matrix()
  for count in (0,2):
   a,b=RealtimeFusion(f),RealtimeFusion(f);pa,pb=eye.copy(),eye.copy()
   for i in range(24):
    q=f.joints(eye);q[:,2]+=.04*np.sin(i/3+np.arange(24));c=np.ones(24)
    if 8<=i<15:c[[1,4,7,16,18,20]]=.2
    sensors={} if not count else {18:np.eye(3),19:np.eye(3)}
    cam=None if 18<=i<21 else (q,c);at=1+i/60;camera_at=1+(i//6)*.1 if cam is not None else None
    pa,oa,_,_=a.step(pa,cam,sensors,{},None,at,camera_at)
    pb,ob,_,_=b.step(pb,cam,sensors,{},None,at,camera_at,camera_basis=basis,camera_image=(q@basis[:,:2],c))
    np.testing.assert_allclose(oa,ob,atol=1e-10)
 def test_tracking_option_changes_clear_world_filter_history(self):
  body=GenericBody();f=RealtimeFusion(RotationFusion(body.J_rest,body.parents));eye=np.tile(np.eye(3),(24,1,1))
  f.step(eye,None,{0:np.eye(3)},{},eye,1,None)
  self.assertTrue(f.sensor_filters)
  f.configure(stabilize=False,constraints=True)
  self.assertEqual(f.sensor_filters,{})

if __name__=='__main__':unittest.main()
