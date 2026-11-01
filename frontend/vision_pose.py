"""Local MediaPipe Tasks detector, owned by the existing camera capture thread."""
import os
from pathlib import Path
import app_paths
import numpy as np


class PoseObservation(tuple):
    """Legacy two-item observation with optional original image measurements."""
    def __new__(cls,world,confidence,image_points=None,image_size=None):
        value=super().__new__(cls,(world,confidence))
        value.image_points=None if image_points is None else np.asarray(image_points,float).copy()
        value.image_confidence=np.asarray(confidence,float).copy()
        value.image_size=image_size
        return value

def undo_image_rotation(world,image,k):
    """Undo np.rot90(k) in raw x/right,y/down,z/away camera coordinates."""
    world=np.asarray(world,float).copy();image=np.asarray(image,float).copy();k%=4
    x,y=world[:,0].copy(),world[:,1].copy();u,v=image[:,0].copy(),image[:,1].copy()
    if k==1:world[:,0],world[:,1]=-y,x;image[:,0],image[:,1]=1-v,u
    elif k==2:world[:,0],world[:,1]=-x,-y;image[:,0],image[:,1]=1-u,1-v
    elif k==3:world[:,0],world[:,1]=y,-x;image[:,0],image[:,1]=v,1-u
    return world,image

def restore_region(world,image,k,region):
    """World landmarks remain metric/root-relative; image points undo the crop.

    Points extrapolated outside the actual crop remain unobserved even when
    their restored coordinates fall inside the original full image.
    """
    world,image=undo_image_rotation(world,image,k)
    outside=np.any((image<0)|(image>1),axis=1)
    if region is not None:
        x0,y0,x1,y1=region
        image=image*np.array([x1-x0,y1-y0])+np.array([x0,y0])
    outside|=np.any((image<0)|(image>1),axis=1)
    return world,image,outside

class VisionPose:
    def __init__(self,model_name="full"):
        if model_name not in ("lite","full"):raise ValueError("無效的影像精度選項。")
        from vision_filter import LandmarkFilter
        self.filter=LandmarkFilter()
        from cpu_latency import configure_cpu_latency
        self.cpu_policy=configure_cpu_latency(os.environ.get('AETHER_WINDOWS_LATENCY','1')=='1')
        import mediapipe as mp
        self.mp=mp
        model=Path(os.environ.get('AETHER_VISION_MODEL',str(app_paths.asset_dir()/f'external/vision/pose_landmarker_{model_name}.task')))
        if not model.is_file():raise ValueError('缺少影像骨架模型，請執行 tools/setup_hybrid.ps1。')
        self.detector=mp.tasks.vision.PoseLandmarker.create_from_options(
            mp.tasks.vision.PoseLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,num_poses=1,
                min_pose_detection_confidence=.6,min_pose_presence_confidence=.6,
                min_tracking_confidence=.6))
        self.last_ms=-1

    def detect(self, bgr, captured_at):
        import cv2
        # A smaller copy reduces inference work; landmark coordinates retain
        # their normalized and root-relative metric definitions.
        h,w=bgr.shape[:2]; width=min(640,w)
        rgb=cv2.cvtColor(cv2.resize(bgr,(width,round(h*width/w))),cv2.COLOR_BGR2RGB)
        timestamp=max(self.last_ms+1,int(captured_at*1000));self.last_ms=timestamp
        result=self.detector.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB,data=rgb),timestamp)
        if not result.pose_world_landmarks:
            self.filter.reset()
            return None
        landmarks=result.pose_world_landmarks[0]
        world=np.array([[p.x,p.y,p.z] for p in landmarks])
        confidence=np.array([min(p.visibility,p.presence) for p in landmarks])
        # A high world-landmark confidence cannot make an off-screen body part
        # a visible measurement. Crop status must also come from image space.
        for i,p in enumerate(result.pose_landmarks[0]):
            if not 0<=p.x<=1 or not 0<=p.y<=1:confidence[i]=0
        world,confidence=self.filter.update(world,confidence,captured_at)
        image_points=result.pose_landmarks[0]
        for a,b in ((11,12),(11,13),(13,15),(12,14),(14,16),(11,23),(12,24),
                    (23,24),(23,25),(25,27),(24,26),(26,28),(27,29),(29,31),(28,30),(30,32)):
            x,y=image_points[a],image_points[b]
            if min(confidence[a],confidence[b])>=.65:
                cv2.line(bgr,(round(x.x*w),round(x.y*h)),(round(y.x*w),round(y.y*h)),(80,240,100),2)
        for i,p in enumerate(image_points):
            if confidence[i]>=.65:
                cv2.circle(bgr,(round(p.x*w),round(p.y*h)),3,(80,240,100),-1)
        return PoseObservation(world,confidence,
            np.array([[p.x,p.y] for p in image_points]),(w,h))

    def close(self):self.detector.close()
