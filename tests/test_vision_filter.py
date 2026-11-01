from pathlib import Path
import sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'frontend'))
from vision_filter import LandmarkFilter

class FilterTests(unittest.TestCase):
    def test_smooths_motion_using_time_and_never_preserves_old_confidence(self):
        f=LandmarkFilter();f.update(np.zeros((33,3)),np.ones(33),10)
        p,c=f.update(np.ones((33,3)),np.ones(33),10.02)
        self.assertTrue(np.all((p>0)&(p<1)))
        p,c=f.update(np.ones((33,3))*2,np.zeros(33),10.04)
        np.testing.assert_array_equal(c,np.zeros(33))
    def test_lost_or_newly_visible_joint_does_not_blend_with_an_old_person(self):
        f=LandmarkFilter();f.update(np.zeros((33,3)),np.ones(33),10)
        p,_=f.update(np.ones((33,3)),np.ones(33),11)
        np.testing.assert_array_equal(p,np.ones((33,3)))
        f.update(np.zeros((33,3)),np.zeros(33),11.02)
        p,_=f.update(np.ones((33,3))*3,np.ones(33),11.04)
        np.testing.assert_array_equal(p,np.ones((33,3))*3)
    def test_no_person_clears_history_before_a_new_person(self):
        f=LandmarkFilter();f.update(np.zeros((33,3)),np.ones(33),10)
        f.reset()
        p,_=f.update(np.ones((33,3))*10,np.ones(33),10.01)
        np.testing.assert_array_equal(p,np.ones((33,3))*10)

    def test_invalid_shapes_and_nan_are_rejected(self):
        f=LandmarkFilter()
        for p,c,t in ((np.zeros((32,3)),np.ones(33),1),(np.full((33,3),np.nan),np.ones(33),1),(np.zeros((33,3)),np.ones(33),float('nan'))):
            with self.assertRaises(ValueError):f.update(p,c,t)

class VisionTests(unittest.TestCase):
    def test_offscreen_joint_is_not_used_and_empty_result_resets_filter(self):
        from types import SimpleNamespace as NS
        from vision_pose import VisionPose
        vision=VisionPose.__new__(VisionPose)
        image_points=[NS(x=.5,y=.5) for _ in range(33)]
        image_points[15].x=1.1
        world=[NS(x=0.,y=0.,z=0.,visibility=.99,presence=.99) for _ in range(33)]
        result=NS(pose_world_landmarks=[world],pose_landmarks=[image_points])
        vision.detector=NS(detect_for_video=lambda *args:result)
        vision.mp=NS(Image=lambda **kwargs:kwargs,ImageFormat=NS(SRGB=1))
        vision.filter=LandmarkFilter();vision.last_ms=-1
        _,confidence=vision.detect(np.zeros((100,100,3),np.uint8),10)
        self.assertEqual(confidence[15],0)
        self.assertGreater(confidence[14],.65)
        result.pose_world_landmarks=[]
        self.assertIsNone(vision.detect(np.zeros((100,100,3),np.uint8),10.01))
        self.assertIsNone(vision.filter.points)

    def test_stalled_camera_status_cannot_claim_full_tracking(self):
        import time
        from camera_anchor import CameraAnchor
        camera=CameraAnchor()
        camera._status=dict(enabled=True,pose_only=True,state='pose_tracking',
                            body_complete=True,capture_monotonic=time.monotonic()-1)
        state=camera.snapshot()
        self.assertEqual(state['state'],'pose_stale')
        self.assertFalse(state['body_complete'])
        self.assertFalse(state['can_score'])

if __name__=='__main__':unittest.main()
