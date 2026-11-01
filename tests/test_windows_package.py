"""Portable readiness: no licensed model, scoped process ownership and paths."""
import importlib.util,io,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'frontend'))
import app_paths,hybrid_runner
from generic_body import GenericBody
from hybrid_fusion import BONE_TO_JOINT
spec=importlib.util.spec_from_file_location('aether_windows_launcher',ROOT/'packaging/launcher.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)

class WindowsPackageTests(unittest.TestCase):
 def test_procedural_skin_is_finite_and_has_normalized_weights(self):
  body=GenericBody();skin=body.page_skin()
  self.assertEqual(len(skin['parents']),24)
  np.testing.assert_allclose(body.weights.sum(axis=1),1)
  self.assertGreater(len(body.faces),100)
  self.assertLess(body.faces.max(),len(body.v_template))
  np.testing.assert_allclose(body.lbs_frame(np.tile(np.eye(3),(24,1,1))),body.v_template,atol=1e-6)

 def test_clean_machine_runner_loads_without_smpl_and_does_not_start_gp(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(hybrid_runner.threading.Thread,'start'),patch.object(hybrid_runner.external_paths,'resolve',return_value=({'smpl_npz':Path(folder)/'absent.npz'},[])):
   runner=hybrid_runner.HybridRunner();runner._init()
  self.assertIsNotNone(runner.fusion);self.assertEqual(runner.stats['avatar_model'],'generic')
  runner.body.smpl2imu=np.eye(3);trackers={}
  for bone in BONE_TO_JOINT:
   runner.body.device2bone[bone]=np.eye(3);runner.body.offsets[bone]=np.zeros(3)
   trackers[bone]=dict(id=bone,assigned_bone=bone,last_update_ms=0,rotation=[0,0,0,1],accel=[0,0,9.81],gyro=[0,0,0])
  with patch.object(hybrid_runner,'GlobalPoseClient',side_effect=AssertionError('GP requires licensed model')):runner.push_frame(trackers)
  self.assertEqual(runner.stats['imu_count'],19);self.assertIsNone(runner.gp)

 def test_busy_ports_never_launch_or_stop_another_app(self):
  manager=launcher.Services()
  with patch.object(launcher,'listening',return_value=True),patch.object(launcher.subprocess,'Popen') as spawn:
   with self.assertRaises(RuntimeError):manager.start()
   manager.stop();spawn.assert_not_called()

 def test_stop_only_terminates_owned_processes(self):
  class Process:
   def __init__(self):self.stopped=False
   def poll(self):return 0 if self.stopped else None
   def terminate(self):self.stopped=True
   def wait(self,timeout):return 0
  manager=launcher.Services();owned=Process();unowned=Process()
  manager.children=[owned];manager.streams=[io.BytesIO()];manager.stop()
  self.assertTrue(owned.stopped);self.assertFalse(unowned.stopped);self.assertFalse(manager.children)

 def test_frozen_data_is_separate_from_readonly_assets(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',folder+'/assets',create=True),patch.dict(os.environ,{'LOCALAPPDATA':folder}):
   with patch.dict(os.environ,{'AETHER_DATA_DIR':''}):
    self.assertEqual(app_paths.data_dir(),Path(folder)/'AetherPose')
    self.assertEqual(app_paths.asset_dir(),Path(folder)/'assets')

if __name__=='__main__':unittest.main()
