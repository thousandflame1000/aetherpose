"""Single-camera + any available assigned IMUs, with optional six-IMU GP prior."""
import threading
import time
from typing import NamedTuple
import numpy as np
from scipy.spatial.transform import Rotation
import body_calibration
import external_paths
from smpl_fk import SMPLForwardKinematics
from hybrid_fusion import BONE_TO_JOINT, GP_BONES, RotationFusion, landmarks_to_smpl, heading_from_camera, head_orientation
from globalpose_client import GlobalPoseClient
from tracking_fusion import RealtimeFusion


class Pose(NamedTuple):
    joints:np.ndarray
    rotations:list
    translation:list


class HybridRunner:
    def __init__(self):
        self._lock=threading.RLock();self._calib_lock=threading.RLock()
        self.body=body_calibration.BodyCalibration()
        self._status='Loading hybrid…';self._pose=None;self._version=0
        self._faces=self._skin=self.fusion=None
        self._generic_body=False
        self.camera=None;self.camera_head=None;self.alignment=None;self._last_sensors={};self.gp=None
        self._rotations=np.tile(np.eye(3),(24,1,1));self._origin=None;self._translation=np.zeros(3);self._gp_epoch=None
        self.on_new_frame=None;self.stats={'device':'cpu','pose_fps':0.,'frame_ms':0.,'model':'hybrid',
            'imu_count':0,'uncalibrated':0,'camera':False,'camera_aligned':False,'globalpose':False}
        self._last_at=None;self._gp_valid=False;self._gp_signature=None;self._last_camera_at=None;self._last_calibrated_at=None
        self._tracking=None;self._tracking_options=dict(stabilize=True,constraints=True)
        self._input_ids=None;self._last_gp_translation=None
        self.stats.update(joint_constraints=True,rotation_filter=True,constraint_profile='smpl_tpose',tracking_version='realtime-v2',heading_feedback_deg=0.,heading_feedback_active=False,camera_fused=False)
        threading.Thread(target=self._init,daemon=True,name='hybrid-init').start()

    def _init(self):
        try:
            paths,_=external_paths.resolve()
            if paths['smpl_npz'].is_file():fk=SMPLForwardKinematics(str(paths['smpl_npz']))
            else:
                from generic_body import GenericBody
                fk=GenericBody();self._generic_body=True
            with self._lock:
                self.fusion=RotationFusion(fk.J_rest,fk.parents)
                self.fusion.bind_foot_skin(fk)
                self._faces=fk.faces.astype(np.int32);self._skin=fk.page_skin()
                self.stats.update(avatar_model='generic' if self._generic_body else 'smpl')
                self._status='Ready hybrid: 請開啟影像骨架；IMU 可選。'
            # The native model loads when all six required inputs become available.
        except Exception as exc:
            with self._lock:self._status=f'Error: {exc}'

    @property
    def faces(self):
        with self._lock:return self._faces
    @property
    def skin(self):
        with self._lock:return self._skin
    @property
    def status(self):
        with self._lock:return self._status
    def get_runtime_stats(self):
        with self._lock:return dict(self.stats)
    def get_frame_if_new(self,version):
        with self._lock:
            return (self._pose if version!=self._version else None,self._version,self._status,dict(self.stats))
    def get_pose_if_new(self,version):return self.get_frame_if_new(version)[:2]
    def start_body_calibration(self):
        with self._calib_lock:self.body.start()
        with self._lock:
            self.alignment=None;self._rotations=np.tile(np.eye(3),(24,1,1));self._reset_tracking()
        if self.gp:self.gp.invalidate()
    def cancel_body_calibration(self):
        with self._calib_lock:self.body.cancel()
    def body_calibration_state(self):
        with self._calib_lock:return self.body.state()
    def reset_origin(self):
        with self._lock:self._origin=None;self._translation=np.zeros(3);self._gp_epoch=None;self._last_gp_translation=None

    def _reset_tracking(self,keep_heading=False):
        initial=None if self._pose is None else np.array(self._pose.rotations).reshape(24,3,3)
        if self._tracking is not None:self._tracking.reset(initial=initial,keep_heading=keep_heading)
        self._last_camera_at=None

    def configure_tracking(self,*,stabilize,constraints):
        if type(stabilize) is not bool or type(constraints) is not bool:raise ValueError('追蹤選項必須是開啟或關閉。')
        with self._lock:
            self._tracking_options=dict(stabilize=stabilize,constraints=constraints)
            if self._tracking is not None:self._tracking.configure(**self._tracking_options)
            self.stats.update(rotation_filter=stabilize,joint_constraints=constraints)
        return dict(self._tracking_options)

    def push_camera(self, observation, at):
        with self._lock:
            self.camera=None if observation is None else (*landmarks_to_smpl(*observation),at)
            self.camera_head=None if observation is None else head_orientation(*observation)

    def reset_camera_alignment(self):
        with self._lock:self.camera=None;self.camera_head=None;self.alignment=None;self._reset_tracking()

    def align_camera(self):
        with self._lock:
            if self.camera is None or time.monotonic()-self.camera[2]>.3:
                raise ValueError('請先開啟影像骨架，讓全身入鏡。')
            q,c,_=self.camera
            target=next((self._last_sensors[j] for j in (0,9,15) if j in self._last_sensors),np.eye(3))
            self.alignment=target@heading_from_camera(q,c).T
            self._reset_tracking()
        return True

    def _trackers(self,trackers):
        by_bone={};raw_frames={};uncalibrated=0;reference=None
        for t in trackers.values():
            if not isinstance(t,dict) or t.get('assigned_bone') not in BONE_TO_JOINT:continue
            try:
                bone=t['assigned_bone'];ident=int(t['id']);age=float(t.get('last_update_ms',float('inf')))
                quat=np.asarray(t['rotation'],float);acc=np.asarray(t['accel'],float)
                if not 0<=age<=250 or quat.shape!=(4,) or acc.shape!=(3,) or not np.isfinite(quat).all() or not np.isfinite(acc).all() or np.linalg.norm(quat)<1e-6:continue
                r=Rotation.from_quat(quat).as_matrix()
                # Current Nano 33 BLE firmware sends raw left-handed accel/gyro
                # while its quaternion uses the right-handed Fusion frame.
                a=r@(acc*[-1,1,1])-np.array([0,0,9.81])
                raw_frames[ident]=(r,a)
                if bone in (0,2,4):reference=ident
                with self._calib_lock:
                    if not self.body.is_calibrated(ident):uncalibrated+=1;continue
                    orientation,acceleration=self.body.apply(ident,r,a)
                    gyro=np.asarray(t.get('gyro',[]),float)
                    angular=None
                    if gyro.shape==(3,) and np.isfinite(gyro).all():
                        angular=self.body.smpl2imu@r@(gyro*[-1,1,1])*(0.070/(2000/32768))
                if bone in by_bone:
                    # Duplicate segment measurements are ambiguous. Exclude
                    # the segment rather than arbitrarily selecting a device.
                    by_bone[bone]=None
                else:by_bone[bone]=(orientation,acceleration,angular,ident)
            except (KeyError,TypeError,ValueError,OverflowError):continue
        with self._calib_lock:self.body.observe(raw_frames,reference)
        return {b:v for b,v in by_bone.items() if v is not None},uncalibrated

    def push_frame(self,trackers):
        started=time.monotonic();started_perf=time.perf_counter()
        observations,uncalibrated=self._trackers(trackers)
        sensors={BONE_TO_JOINT[b]:v[0] for b,v in observations.items()}
        valid=not self._generic_body and all(b in observations and observations[b][2] is not None for b in GP_BONES)
        with self._calib_lock:calibration_epoch=self.body.calibrated_at
        signature=(calibration_epoch,tuple((b,observations[b][3]) for b in GP_BONES)) if valid else None
        if signature!=self._gp_signature:
            if self.gp:self.gp.invalidate()
            self._gp_signature=signature
        if valid and self.gp is None:self.gp=GlobalPoseClient()
        if self.gp:
            if valid:
                arrays=[np.stack([observations[b][i] for b in GP_BONES]) for i in (1,2,0)]
                self.gp.submit(*arrays,started)
            # Missing inputs and changed device identities invalidate above.
        self._gp_valid=valid
        prior,error=self.gp.latest(started) if self.gp else (None,'GlobalPose 會在六個指定位置齊備後載入。')
        if not valid:prior=None
        with self._lock:
            self._last_sensors=sensors
            if self.fusion is None:return
            if self._tracking is None:
                self._tracking=RealtimeFusion(self.fusion)
                self._tracking.configure(**self._tracking_options)
            input_ids=tuple(sorted((bone,value[3]) for bone,value in observations.items()))
            if input_ids!=self._input_ids:
                self._reset_tracking(keep_heading=True);self._input_ids=input_ids
            with self._calib_lock:calibrated_at=self.body.calibrated_at
            if calibrated_at!=self._last_calibrated_at:
                self.alignment=None;self._last_calibrated_at=calibrated_at;self._reset_tracking()
            camera=self.camera
            fresh=camera is not None and 0<=started-camera[2]<=.3 and np.sum(camera[1]>=.65)>=8
            # Camera-only works immediately in camera space. IMU+camera needs
            # an explicit standing alignment to share the calibrated heading.
            fused_camera=None
            if fresh and (not sensors or self.alignment is not None):
                q,c,at=camera
                fused_camera=(q if self.alignment is None else q@self.alignment.T,c)
            self.stats.update(globalpose_epoch=getattr(self.gp,'epoch',0),globalpose_step_s=getattr(self.gp,'step_s',1/60),globalpose_dropped_frames=getattr(self.gp,'dropped_frames',0),globalpose_completed_frames=getattr(self.gp,'completed_frames',0),globalpose_latency_ms=getattr(self.gp,'last_latency_ms',0),globalpose_device=getattr(self.gp,'device','not_loaded'),globalpose_quantized=getattr(self.gp,'quantized',False),imu_count=len(sensors),uncalibrated=uncalibrated,camera=bool(fresh),
                camera_aligned=self.alignment is not None,globalpose=prior is not None,
                globalpose_message=error or ('需要雙前臂、雙小腿、頭與骨盆六個位置及有效角速度。' if not valid else '資料等待中'),
                model='globalpose+hybrid' if prior is not None else 'hybrid',
                unobserved=24,waiting_alignment=bool(fresh and sensors and self.alignment is None))
            if self._generic_body:self.stats['globalpose_message']='GlobalPose 需另行安裝並匯入已授權 SMPL 模型。'
            if not sensors and fused_camera is None and prior is None:
                self.stats.update(camera_fused=False,heading_feedback_active=False)
                self._status='Waiting hybrid: 請開啟影像骨架，或連接並校正 IMU。'
                return
            # Solve only once for each camera sample unless fresh IMUs or GP
            # supply a new prediction; repeated camera frames are not new data.
            camera_at=camera[2] if fused_camera is not None else None
            if camera_at==self._last_camera_at and not sensors and prior is None:return
            self._last_camera_at=camera_at
            base=prior[0] if prior is not None else None
            camera_axes={}
            if fused_camera is not None and self.camera_head is not None:
                axes,quality=self.camera_head
                camera_axes[15]=(axes if self.alignment is None else self.alignment@axes,quality)
            # Windows/Python 3.12 monotonic() can repeat within a clock tick.
            # Use the real high-resolution clock for integration intervals;
            # camera freshness and GP protocol keep their existing timebase.
            raw,rotations,observed,yaw=self._tracking.step(self._rotations,fused_camera,sensors,camera_axes,base,started_perf,camera_at)
            self._rotations=raw
            self.stats.update(self._tracking.diagnostics)
            translation=self._translation.copy()
            if prior is not None:
                epoch=getattr(self.gp,'epoch',0)
                if self._origin is None:
                    self._origin=prior[1].copy();self._last_gp_translation=prior[1].copy()
                elif epoch!=self._gp_epoch or self._last_gp_translation is None:
                    self._origin=prior[1]-self._translation;self._last_gp_translation=prior[1].copy()
                # Correct world velocity, not the accumulated path: changing
                # heading while standing must never orbit the avatar's position.
                translation=self._translation+yaw@(prior[1]-self._last_gp_translation)
                self._last_gp_translation=prior[1].copy()
                self._gp_epoch=epoch
                self._translation=translation.copy()
            else:self._last_gp_translation=None
            relative_joints=self.fusion.joints(rotations)
            camera_grounded=False
            accepted_camera=self._tracking.effective_camera
            if prior is None and accepted_camera is not None and np.min(accepted_camera[1][[1,2,4,5,7,8]])>=.65:
                # Root-relative monocular landmarks do not measure global Y.
                # Ground the visual avatar by its lowest foot so crouching
                # does not leave it floating at its standing pelvis height.
                # This is a display/contact assumption, never jump-height data.
                translation[1]=self.fusion.foot_floor_translation(rotations,relative_joints)
                self._translation=translation.copy();camera_grounded=True
            self.stats['camera_floor_assumption']=camera_grounded
            joints=relative_joints+translation
            self._pose=Pose(joints,np.round(rotations,5).ravel().tolist(),np.round(translation,5).tolist())
            self._version+=1
            full=prior is not None or (accepted_camera is not None and np.min(accepted_camera[1][[0,1,2,4,5,7,8,12,15,16,17,18,19,20,21]])>=.65)
            source='HYBRID' if full else 'PARTIAL'
            self._status=f'Streaming #{self._version} {source} imu={len(sensors)} camera={int(accepted_camera is not None)} gp={int(prior is not None)}'
            if uncalibrated:self._status+=f' · {uncalibrated} uncalibrated'
            ended=time.perf_counter()
            dt=ended-(self._last_at or ended);self._last_at=ended
            self.stats.update(frame_ms=round((ended-started_perf)*1000,1),pose_fps=round(1/dt,1) if dt>0 else 0,unobserved=24-len(observed))
        if self.on_new_frame:self.on_new_frame()
