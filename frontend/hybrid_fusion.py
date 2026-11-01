"""Variable-observation SMPL rotation fitting. No fabricated IMU slots.

Each joint solves a weighted Wahba problem on SO(3): camera bone directions,
available calibrated sensor orientations, and a weak temporal/model prior.
This is a deterministic baseline inspired by visual/inertial kinematic fusion,
not a reproduction of RTOF, DiffCap, or GlobalPose's physics optimizer.
"""
import numpy as np

# Backend segment IDs -> SMPL joints. One measurement per assigned segment.
BONE_TO_JOINT = {0:0, 1:3, 2:9, 3:12, 4:15,
                 10:1, 11:4, 12:7, 20:2, 21:5, 22:8,
                 30:13, 31:16, 32:18, 33:20,
                 40:14, 41:17, 42:19, 43:21}
GP_BONES = (32, 42, 11, 21, 4, 0)  # forearms, shins, head, PELVIS (not chest)


def proper_rotation(matrix):
    u, _, vt = np.linalg.svd(matrix)
    return u @ np.diag([1., 1., np.linalg.det(u @ vt)]) @ vt


def landmarks_to_smpl(world, confidence):
    world, confidence = np.asarray(world, float), np.asarray(confidence, float)
    if world.shape != (33,3) or confidence.shape != (33,):
        raise ValueError('Expected 33 world landmarks and confidence values')
    if not np.isfinite(world).all() or not np.isfinite(confidence).all():
        raise ValueError('Non-finite camera observation')
    # MediaPipe camera axes -> right-handed Y-up renderer space.
    p = world * [1,-1,-1]
    q, c = np.zeros((24,3)), np.zeros(24)
    def put(j, ids, weights=None):
        q[j] = np.average(p[ids], axis=0, weights=weights)
        c[j] = np.min(confidence[ids])
    for j, ids in {0:[23,24],1:[23],2:[24],4:[25],5:[26],7:[27],8:[28],
                   10:[31],11:[32],12:[11,12],15:[7,8],16:[11],17:[12],
                   18:[13],19:[14],20:[15],21:[16],22:[19],23:[20]}.items():
        put(j, ids)
    for j, t in ((3,.3),(6,.6),(9,.85)):
        q[j]=(1-t)*q[0]+t*q[12]; c[j]=min(c[0],c[12])
    for j, shoulder in ((13,16),(14,17)):
        q[j]=.5*(q[12]+q[shoulder]);c[j]=min(c[12],c[shoulder])
    q -= q[0].copy()
    return q, np.clip(c,0,1)


def head_orientation(world,confidence):
    # A head is a leaf in SMPL: fitting only bone directions leaves its
    # orientation inherited from the neck. Use the observed face plane.
    confidence=np.asarray(confidence,float)
    quality=float(np.min(confidence[[2,5,7,8,9,10]]))
    if quality<.65:return None
    p=np.asarray(world,float)*[1,-1,-1]
    x=p[7]-p[8];y=(p[2]+p[5]-p[9]-p[10])*.5
    nx,ny=np.linalg.norm(x),np.linalg.norm(y)
    z=np.cross(x,y);nz=np.linalg.norm(z)
    if min(nx,ny)<1e-4 or nz<.2*nx*ny:return None
    x=x/nx;z=z/nz;y=np.cross(z,x)
    return np.column_stack([x,y,z]),quality


def heading_from_camera(points, confidence):
    if min(confidence[[1,2,12]]) < .65:
        raise ValueError('請讓肩膀與髖部清楚入鏡，再對齊相機方向。')
    x = points[1]-points[2]
    y = points[12]-points[0]
    x /= max(np.linalg.norm(x),1e-9)
    z = np.cross(x,y)
    if np.linalg.norm(z)<1e-5: raise ValueError('無法從目前骨架決定朝向。')
    z /= np.linalg.norm(z)
    y=np.cross(z,x)
    return np.column_stack([x,y,z])


class RotationFusion:
    def __init__(self, rest, parents):
        self.rest, self.parents = np.asarray(rest,float), np.asarray(parents,int)
        self.children = [[k for k in range(1,24) if self.parents[k]==j] for j in range(24)]
        self.foot_skin=None

    def bind_foot_skin(self,fk):
        selected=fk.weights[:,[7,8,10,11]].sum(axis=1)>.5
        weights=fk.weights[selected]
        bones=np.argsort(-weights,axis=1)[:,:4]
        weights=np.take_along_axis(weights,bones,axis=1)
        weights/=weights.sum(axis=1,keepdims=True)
        offsets=fk.v_template[selected,None,:]-self.rest[bones]
        self.foot_skin=(bones,weights,offsets)

    def foot_floor_translation(self,rotations,positions):
        if self.foot_skin is None:
            feet=[7,8,10,11]
            return np.min((self.rest-self.rest[0])[feet,1])-np.min(positions[feet,1])
        global_r=np.empty_like(rotations)
        for j in range(24):
            p=self.parents[j]
            global_r[j]=rotations[j] if p<0 else global_r[p]@rotations[j]
        bones,weights,offsets=self.foot_skin
        foot=np.einsum('nkij,nkj->nki',global_r[bones],offsets)+positions[bones]
        minimum=np.min((foot*weights[:,:,None]).sum(axis=1)[:,1])
        # avatar.js places its pelvis frame at Y=.97. Ground the skinned
        # sole, rather than an ankle/toe joint above the actual sole.
        return -.97-minimum

    def fit(self, previous, camera=None, sensors=None, prior=None, camera_axes=None):
        previous=np.asarray(previous,float)
        model_global=np.empty_like(previous) if prior is not None else None
        global_r=np.empty_like(previous); local=np.empty_like(previous)
        sensors=sensors or {}
        points, confidence = camera if camera is not None else (None,None)
        observed=set()
        for j in range(24):
            parent=self.parents[j]
            # The small isotropic term resolves axial twist when a camera only
            # observes one bone direction. SVD also handles antiparallel bones.
            temporal=previous[j] if parent<0 else global_r[parent]@previous[j]
            H=.15*temporal
            if prior is not None:
                model_global[j]=prior[j] if parent<0 else model_global[parent]@prior[j]
                H+=.5*model_global[j]
            if points is not None:
                for child in self.children[j]:
                    conf=min(confidence[j],confidence[child])
                    source=self.rest[child]-self.rest[j]
                    target=points[child]-points[j]
                    a,b=np.linalg.norm(source),np.linalg.norm(target)
                    if conf>=.65 and a>1e-5 and b>.015:
                        H+=3*conf*np.outer(target/b,source/a);observed.add(j)
            if camera_axes and j in camera_axes:
                axes,quality=camera_axes[j]
                H+=3*quality*axes;observed.add(j)
            if j in sensors:
                H+=5*np.asarray(sensors[j],float);observed.add(j)
            global_r[j]=proper_rotation(H)
            local[j]=global_r[j] if parent<0 else global_r[parent].T@global_r[j]
        return local, observed

    def joints(self, rotations):
        global_r=np.empty_like(rotations); positions=np.zeros((24,3))
        for j in range(24):
            p=self.parents[j]
            global_r[j]=rotations[j] if p<0 else global_r[p]@rotations[j]
            if p>=0: positions[j]=positions[p]+global_r[p]@(self.rest[j]-self.rest[p])
        return positions
