"""Opt-in, local-only webcam anchor. Camera I/O stays off the inference thread."""
import base64
import json
import queue
import threading
import time
from pathlib import Path

import numpy as np
import app_paths
from root_position import RootPosition

PROFILE_DIR = (app_paths.data_dir() if app_paths.frozen() else Path(__file__).resolve().parent) / 'camera_profiles'


def marker_points(length):
    h = length/2
    return np.array([[-h,h,0],[h,h,0],[h,-h,0],[-h,-h,0]], np.float64)


def tag_pose(cv, corners, length, matrix, distortion):
    corners = np.asarray(corners, np.float64).reshape(4, 2)
    if min(np.linalg.norm(corners-np.roll(corners, 1, axis=0), axis=1)) < 20:
        return None
    points = marker_points(length)
    ok, rvecs, tvecs, *_ = cv.solvePnPGeneric(points, corners, matrix, distortion,
                                             flags=cv.SOLVEPNP_IPPE_SQUARE)
    if not ok:
        return None
    candidates = []
    for r, t in zip(rvecs, tvecs):
        if not np.isfinite(r).all() or not np.isfinite(t).all() or t[2, 0] <= 0:
            continue
        projected = cv.projectPoints(points, r, t, matrix, distortion)[0].reshape(4, 2)
        error = float(np.sqrt(np.mean(np.sum((projected-corners)**2, axis=1))))
        if error > 2.5:
            continue
        transform = np.eye(4)
        transform[:3,:3] = cv.Rodrigues(r)[0]
        transform[:3,3] = t.ravel()
        candidates.append((error, transform))
    candidates.sort(key=lambda item: item[0])
    if not candidates:
        return None
    if len(candidates)>1 and candidates[1][0]-candidates[0][0]<.15:
        relative = candidates[0][1][:3,:3].T@candidates[1][1][:3,:3]
        angle = np.degrees(np.arccos(np.clip((np.trace(relative)-1)/2,-1,1)))
        if angle > 20:
            return None
    return candidates[0]


def read_profile(path, width, height):
    data = json.loads(path.read_text(encoding='utf-8'))
    if data['width'] != width or data['height'] != height:
        raise ValueError('相機解析度與鏡頭校正檔不符，請重新校正。')
    matrix, distortion = np.array(data['matrix'], float), np.array(data['distortion'], float)
    if matrix.shape != (3,3) or distortion.size < 4 or not np.isfinite(matrix).all() or not np.isfinite(distortion).all() or min(matrix[0,0],matrix[1,1])<=0:
        raise ValueError('無效鏡頭校正檔。')
    return matrix, distortion


class CameraAnchor:
    def __init__(self):
        self._lock = threading.Lock()
        self._commands = queue.Queue(maxsize=24)
        self._status = {'enabled':False,'state':'off','message':'相機定位未啟動。'}
        self._preview = None
        self._preview_version = 0
        self._thread = None
        self.on_pose = None

    def command(self, data):
        action = data.get('action')
        if action not in ('start','stop','sample','solve','align','reference'):
            raise ValueError('不支援的相機操作。')
        if action == 'start':
            index, size = int(data.get('index',0)), float(data.get('marker_m',.12))
            if not 0<=index<=9 or not .03<=size<=.5:
                raise ValueError('相機編號需為 0–9，標記外框邊長需為 0.03–0.5 公尺。')
            with self._lock:
                if self._thread and self._thread.is_alive():
                    raise ValueError('請先停止目前相機，再重新啟動。')
                while not self._commands.empty():
                    self._commands.get_nowait()
                self._status = {'enabled':True,'state':'starting','message':'正在開啟相機…','pose_only':data.get('purpose')=='hybrid'}
                self._thread = threading.Thread(target=self._run,args=(index,size,data.get('purpose')=='hybrid',data.get('vision_model','full')),daemon=True,name='camera-anchor')
                self._thread.start()
        else:
            with self._lock:
                running = self._thread and self._thread.is_alive()
                if action == 'stop' and not running:
                    self._status = {'enabled':False,'state':'off','message':'相機已停止。'}
                    self._preview = None
                    return
            if not running:
                raise ValueError('請先啟動相機。')
            try:
                self._commands.put_nowait(action)
            except queue.Full:
                raise ValueError('相機正在處理操作，請稍候。') from None

    def snapshot(self):
        with self._lock:
            result = {**self._status,'preview_version':self._preview_version}
        capture = result.get('capture_monotonic')
        if capture is not None and result.get('pose_only') and result.get('state')!='error':
            result['age_ms']=round(max(0,time.monotonic()-capture)*1000)
            if result['age_ms']>300:
                result.update(state='pose_stale',body_complete=False,can_score=False,
                              message='影像更新中斷；若持續發生，請改用快速模式或重開相機。')
        if capture is not None and result.get('state') in ('tracking','recovering','occluded','lost'):
            elapsed = max(0,time.monotonic()-capture)
            age = result.get('age_ms')
            if age is not None:
                result['age_ms'] = age+round(elapsed*1000)
                if result['age_ms']>300 and result.get('aligned'):
                    result.update(state='lost',can_score=False,message='相機位置資料過期，保持末位置。')
        return result

    def preview(self, after):
        with self._lock:
            return (self._preview_version, self._preview if after!=self._preview_version else None)

    def _publish(self, status, frame=None, cv=None):
        preview = None
        if frame is not None:
            h,w = frame.shape[:2]
            small = cv.resize(frame,(min(640,w),round(h*min(640,w)/w)))
            ok,jpg = cv.imencode('.jpg',small,[cv.IMWRITE_JPEG_QUALITY,65])
            if ok:
                preview = base64.b64encode(jpg).decode('ascii')
        with self._lock:
            self._status = status
            if preview:
                self._preview = preview
                self._preview_version += 1

    def _run(self, index, length, pose_only=False, vision_model="full"):
        cap = None
        vision = None
        try:
            import cv2 as cv
            if pose_only:
                from vision_pose import VisionPose
                vision = VisionPose(vision_model)
            cap = cv.VideoCapture(index, cv.CAP_DSHOW)
            if not cap.isOpened():
                raise ValueError('無法開啟相機；請確認編號、Windows 權限及其他程式是否占用。')
            cap.set(cv.CAP_PROP_FRAME_WIDTH,1280)
            cap.set(cv.CAP_PROP_FRAME_HEIGHT,720)
            cap.set(cv.CAP_PROP_BUFFERSIZE,1)
            detector = cv.aruco.ArucoDetector(cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50))
            root, world_camera, reference_seen = RootPosition(), None, None
            floor_bad = 0
            captures, image_points = [], []
            board = np.zeros((9*6,3),np.float32)
            board[:,:2] = np.mgrid[0:9,0:6].T.reshape(-1,2)*.025
            matrix=distortion=None
            profile_checked=False
            capture_size=None
            last_preview=0
            pose_at=None;pose_fps=0
            notice=''
            while True:
                ok,frame = cap.read()
                captured_at=time.monotonic()
                if not ok:
                    raise ValueError('相機影像中斷；已保持末位置，請停止後重開相機。')
                height,width=frame.shape[:2]
                if capture_size is not None and capture_size!=(width,height):
                    raise ValueError('相機解析度改變，請重新啟動並重新校正鏡頭。')
                capture_size=(width,height)
                profile=PROFILE_DIR/f'camera-{index}-{width}x{height}.json'
                if not profile_checked:
                    profile_checked=True
                    if profile.exists():
                        try:
                            matrix,distortion=read_profile(profile,width,height)
                        except (ValueError,KeyError,TypeError,OSError):
                            notice='儲存的鏡頭校正檔不適用，請重新收集棋盤並計算校正。'
                actions=[]
                while not self._commands.empty():
                    actions.append(self._commands.get_nowait())
                if 'stop' in actions:
                    break
                if pose_only:
                    infer_started=time.perf_counter()
                    observation=vision.detect(frame,captured_at)
                    inference_ms=(time.perf_counter()-infer_started)*1000
                    if pose_at is not None and captured_at>pose_at:
                        hz=1/(captured_at-pose_at)
                        pose_fps=hz if not pose_fps else .2*hz+.8*pose_fps
                    pose_at=captured_at
                    if self.on_pose:self.on_pose(observation,captured_at)
                    visible=0 if observation is None else int(np.sum(observation[1]>=.65))
                    critical=[7,8,11,12,13,14,15,16,23,24,25,26,27,28]
                    complete=observation is not None and bool(np.min(observation[1][critical])>=.65)
                    message=('全身骨架追蹤中。' if complete else
                             f'目前只看到部分身體（{visible}/33 個點），請讓頭、雙手與雙腳入鏡。' if observation is not None else
                             '尚未看到人體；請讓一人全身入鏡，保持光線充足。')
                    status={'enabled':True,'pose_only':True,'state':'pose_tracking' if complete else 'pose_partial' if observation is not None else 'pose_searching',
                            'message':message,'visible_points':visible,'vision_model':vision_model,'body_complete':complete,
                            'tracking_fps':round(pose_fps,1),'inference_ms':round(inference_ms,1),
                            'index':index,'resolution':[width,height],'capture_monotonic':captured_at,'can_score':False}
                    if captured_at-last_preview>=.1:
                        self._publish(status,frame,cv);last_preview=captured_at
                    else:self._publish(status)
                    continue
                gray=cv.cvtColor(frame,cv.COLOR_BGR2GRAY)
                if 'sample' in actions:
                    found,points=cv.findChessboardCornersSB(gray,(9,6))
                    if found:
                        captures.append(board.copy());image_points.append(points.astype(np.float32))
                        notice=f'已收集 {len(captures)} 張棋盤；請改變角度與位置再收集。'
                    else:
                        notice='沒有看到完整的 9×6 內角點棋盤。'
                if 'solve' in actions:
                    if len(captures)<12:
                        notice='至少需要 12 張不同角度與位置的棋盤影像。'
                    else:
                        rms,k,d,*_=cv.calibrateCamera(captures,image_points,(width,height),None,None)
                        if not np.isfinite(rms) or rms>1.5:
                            notice=f'鏡頭校正未通過（重投影 RMS {rms:.2f} px），請重新收集。'
                        else:
                            PROFILE_DIR.mkdir(exist_ok=True)
                            profile.write_text(json.dumps({'width':width,'height':height,'matrix':k.tolist(),'distortion':d.tolist(),'rms_px':rms}),encoding='utf-8')
                            matrix,distortion=k,d
                            root,world_camera=RootPosition(),None
                            notice=f'鏡頭校正已儲存，RMS {rms:.2f} px；請放好地面板。'
                if 'reference' in actions:
                    root,world_camera,reference_seen=RootPosition(),None,None
                    floor_bad=0
                    notice='參考座標已清除；請固定地面板與相機後重新記原點。'
                corners,ids,_=detector.detectMarkers(gray)
                poses={}
                if ids is not None:
                    cv.aruco.drawDetectedMarkers(frame,corners,ids)
                    if matrix is not None:
                        for ident,quad in zip(ids.ravel(),corners):
                            if int(ident) not in (0,1):continue
                            result=tag_pose(cv,quad,length,matrix,distortion)
                            if result:poses[int(ident)]=result
                if 0 in poses:
                    # floor-marker X -> world X, outward normal -> world Y
                    world_floor=np.array([[1,0,0,0],[0,0,1,0],[0,-1,0,0],[0,0,0,1]],float)
                    candidate=world_floor@np.linalg.inv(poses[0][1])
                    if world_camera is None:
                        world_camera=candidate
                    else:
                        rotation=world_camera[:3,:3].T@candidate[:3,:3]
                        angle=np.degrees(np.arccos(np.clip((np.trace(rotation)-1)/2,-1,1)))
                        changed=np.linalg.norm(candidate[:3,3]-world_camera[:3,3])>.05 or angle>3
                        floor_bad=floor_bad+1 if changed else 0
                        if floor_bad>=3:root.invalidate_world()
                    reference_seen=captured_at
                reference_fresh=reference_seen is not None and captured_at-reference_seen<2
                if 1 in poses and world_camera is not None and reference_fresh:
                    measured=(world_camera@poses[1][1])[:3,3]
                    root.observe(measured,captured_at)
                if 'align' in actions:
                    try:
                        root.align(captured_at);notice='位置原點已記錄。'
                    except ValueError as exc:
                        notice=str(exc)
                status=root.snapshot(captured_at)
                if matrix is None:
                    status.update(state='needs_intrinsics',message='先以棋盤完成鏡頭校正，再進行位置測試。',can_score=False)
                elif not root.needs_reset and (world_camera is None or not reference_fresh):
                    status.update(state='needs_reference',message='需要看到固定地面標記 ID 0。',can_score=False)
                status.update(enabled=True,marker_m=length,index=index,resolution=[width,height],
                              calibration_samples=len(captures),intrinsics_ready=matrix is not None,
                              notice=notice,visible_ids=[] if ids is None else ids.ravel().tolist(),
                              capture_monotonic=captured_at)
                if captured_at-last_preview>=.2:
                    self._publish(status,frame,cv);last_preview=captured_at
                else:
                    self._publish(status)
                time.sleep(.01)
        except Exception as exc:
            with self._lock:
                # Preserve last position when the capture process fails.
                self._status={**self._status,'enabled':True,'state':'error','can_score':False,
                              'message':f'{"影像骨架" if pose_only else "相機定位"}錯誤：{exc}'}
        finally:
            if cap is not None:cap.release()
            if vision is not None:vision.close()
            if pose_only and self.on_pose:self.on_pose(None,time.monotonic())
            with self._lock:
                if self._status.get('state')!='error':
                    self._status={'enabled':False,'state':'off','message':'相機已停止。'}
                self._preview=None
