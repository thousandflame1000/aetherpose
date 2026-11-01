import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
import cv2 as cv
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'frontend'))
from root_position import RootPosition
from camera_anchor import CameraAnchor, marker_points, tag_pose, read_profile
import camera_anchor


class PositionTests(unittest.TestCase):
    def start(self):
        r=RootPosition()
        r.observe([0,1,0],0)
        r.align(0)
        for i in range(1,10):r.observe([0,1,0],i/30)
        self.assertEqual(r.snapshot(.3)['state'],'tracking')
        return r

    def test_camera_moves_root_and_preserves_vertical_pose(self):
        r=self.start()
        for i in range(10,100):r.observe([.001*i,1+.01*i,-.002*i],i/30)
        self.assertGreater(r.position[0],.08)
        self.assertLess(r.position[2],-.15)
        self.assertEqual(r.position[1],0)

    def test_occlusion_holds_position_and_recovery_does_not_teleport(self):
        r=self.start();before=r.position.copy()
        self.assertEqual(r.snapshot(2)['state'],'lost')
        np.testing.assert_array_equal(before,r.position)
        for i in range(5):r.observe([.2,1,0],2+i/30)
        self.assertLess(r.position[0],.067)
        self.assertEqual(r.snapshot(2.14)['state'],'recovering')

    def test_large_reacquisition_requires_explicit_reference_reset(self):
        r=self.start();r.observe([.7,1,0],2)
        self.assertEqual(r.state,'needs_reset')
        with self.assertRaises(ValueError):r.align(2)

    def test_bad_and_delayed_measurements_are_rejected(self):
        r=self.start();before=r.position.copy()
        for p,t in [([float('nan'),0,0],.5),([2,1,0],.4),([0,1,0],.2)]:
            self.assertFalse(r.observe(p,t))
        np.testing.assert_array_equal(before,r.position)

    def test_moved_camera_invalidates_world(self):
        r=self.start();r.invalidate_world()
        self.assertFalse(r.observe([0,1,0],.4))
        self.assertFalse(r.snapshot(.4)['can_score'])

    def test_profile_resolution_validation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'profile.json'
            p.write_text(json.dumps({'width':640,'height':480,'matrix':[[600,0,320],[0,600,240],[0,0,1]],'distortion':[0]*5}))
            self.assertEqual(read_profile(p,640,480)[0].shape,(3,3))
            with self.assertRaises(ValueError):read_profile(p,1280,720)

    def test_projected_metric_tag_recovers_known_translation(self):
        k=np.array([[900.,0,640],[0,900,360],[0,0,1]])
        rot=np.array([2.7,.15,.1]);pos=np.array([.12,.08,1.5])
        quad=cv.projectPoints(marker_points(.12),rot,pos,k,np.zeros(5))[0]
        result=tag_pose(cv,quad,.12,k,np.zeros(5))
        self.assertIsNotNone(result)
        np.testing.assert_allclose(result[1][:3,3],pos,atol=1e-5)
        tiny=quad.reshape(4,2)*.01
        self.assertIsNone(tag_pose(cv,tiny,.12,k,np.zeros(5)))

    def test_camera_starts_off_and_invalid_commands_never_open_hardware(self):
        camera=CameraAnchor()
        self.assertFalse(camera.snapshot()['enabled'])
        for data in [{'action':'invalid'},{'action':'start','index':99},{'action':'start','marker_m':float('nan')}]:
            with self.assertRaises(ValueError):camera.command(data)
        self.assertIsNone(camera._thread)

    def test_stalled_capture_cannot_keep_claiming_valid_position(self):
        camera=CameraAnchor()
        camera._status={'enabled':True,'state':'tracking','can_score':True,'aligned':True,
                        'capture_monotonic':1.,'age_ms':0,'position':[.1,0,.2]}
        with patch.object(camera_anchor.time,'monotonic',return_value=3.):
            state=camera.snapshot()
        self.assertFalse(state['can_score'])
        self.assertEqual(state['position'],[.1,0,.2])
        camera._status['state']='needs_reset'
        with patch.object(camera_anchor.time,'monotonic',return_value=3.):
            self.assertEqual(camera.snapshot()['state'],'needs_reset')

    def test_capture_failure_releases_device_and_reports_error(self):
        class Capture:
            released=False
            def isOpened(self):return True
            def set(self,*args):pass
            def read(self):return False,None
            def release(self):self.released=True
        cap=Capture();camera=CameraAnchor()
        with patch.object(cv,'VideoCapture',return_value=cap):camera._run(0,.12)
        self.assertTrue(cap.released)
        self.assertEqual(camera.snapshot()['state'],'error')

    def test_printed_targets_are_detectable_with_expected_ids(self):
        folder=Path(__file__).resolve().parents[1]/'webui/camera-targets'
        detector=cv.aruco.ArucoDetector(cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50))
        for ident in (0,1):
            marker=cv.imread(str(folder/f'marker-{ident}.png'),cv.IMREAD_GRAYSCALE)
            image=cv.copyMakeBorder(marker,60,60,60,60,cv.BORDER_CONSTANT,value=255)
            ids=detector.detectMarkers(image)[1]
            self.assertEqual(ids.ravel().tolist(),[ident])
        checker=cv.imread(str(folder/'lens-checkerboard.png'),cv.IMREAD_GRAYSCALE)
        self.assertTrue(cv.findChessboardCornersSB(checker,(9,6))[0])


if __name__=='__main__':unittest.main()
