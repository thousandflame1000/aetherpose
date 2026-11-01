"""Python 3.8 JSON-lines worker isolating GlobalPose's native physics bindings."""
import contextlib
import json
import os
import sys
import traceback
import pickle
import hashlib
from pathlib import Path
import threading
import math

# Small dynamics systems suffer badly when BLAS creates a large thread pool.
# Set these before NumPy/SciPy/PyTorch are imported in this isolated process.
for variable in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[variable]='1'

if len(sys.argv)>1:sys.path.insert(0,sys.argv[1])
sys.path.insert(0,str(Path(__file__).resolve().parent))
if os.name=='nt' and os.environ.get('AETHER_GP_AFFINITY'):
    import ctypes
    kernel=ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype=ctypes.c_void_p
    kernel.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
    kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(),int(os.environ['AETHER_GP_AFFINITY'],0))
try:
    from cpu_latency import configure_cpu_latency
    print('CPU latency policy:',configure_cpu_latency(os.environ.get('AETHER_WINDOWS_LATENCY','1')=='1'),file=sys.stderr,flush=True)
except ImportError:pass
if os.name=='nt' and len(sys.argv)>2:
    def watch_parent():
        import ctypes
        kernel=ctypes.windll.kernel32
        kernel.OpenProcess.restype=ctypes.c_void_p
        handle=kernel.OpenProcess(0x00100000,False,int(sys.argv[2]))
        if handle:
            kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
            kernel.WaitForSingleObject(handle,0xffffffff)
            os._exit(0)
    threading.Thread(target=watch_parent,daemon=True).start()

protocol=sys.stdout
sys.stdout=sys.stderr  # upstream initialization logs cannot corrupt the protocol

def reply(value):
    protocol.write(json.dumps(value,allow_nan=False,separators=(',',':'))+'\n');protocol.flush()

try:
    import numpy as np
    import torch
    torch.set_num_threads(int(os.environ.get('AETHER_GP_THREADS','2')))
    import articulate as art
    inside=art.ParametricModel.is_inside
    def bounded_inside(self,points,vertices):
        return torch.cat([inside(self,points[i:i+256],vertices) for i in range(0,len(points),256)])
    art.ParametricModel.is_inside=bounded_inside
    properties=art.ParametricModel.physical_properties
    def cached_properties(self,shape=None,res=.02):
        shape_key=np.zeros(10,np.float32) if shape is None else shape.detach().cpu().numpy()
        digest=hashlib.sha256(Path('models/SMPL_male.pkl').read_bytes()+shape_key.tobytes()+str(res).encode()).hexdigest()[:24]
        cache=Path('data/physics-cache')/(digest+'.npz')
        if cache.is_file():
            data=np.load(str(cache))
            return tuple(torch.from_numpy(data[k]).to(self._v_template.device) for k in ('mass','com','inertia'))
        print('Computing exact SMPL physics properties (cached after first load).',flush=True)
        result=properties(self,shape,res)
        cache.parent.mkdir(parents=True,exist_ok=True)
        np.savez(str(cache),**{k:v.detach().cpu().numpy() for k,v in zip(('mass','com','inertia'),result)})
        print('SMPL physics cache saved.',flush=True)
        return result
    art.ParametricModel.physical_properties=cached_properties
    from net import GPNet
    # Keep the official neural equations and physics equations intact, while
    # allowing small physics substeps between less-frequent neural predictions.
    # A large single Euler step is unstable with GP's original PD gains.
    import ast,inspect,textwrap,copy
    original=ast.parse(textwrap.dedent(inspect.getsource(GPNet.forward_frame))).body[0]
    boundary=next(i for i,node in enumerate(original.body)
                  if isinstance(node,ast.If) and isinstance(node.test,ast.UnaryOp)
                  and isinstance(node.test.operand,ast.Attribute)
                  and node.test.operand.attr=='is_init')
    predictor=copy.deepcopy(original);predictor.name='_predict_observation'
    predictor.body=predictor.body[:boundary]+[ast.Return(value=ast.Tuple(elts=[ast.Name(id=n,ctx=ast.Load()) for n in ('pose','velocity','stationary_prob','cjoint','stationary_weight')],ctx=ast.Load()))]
    dynamics=copy.deepcopy(original);dynamics.name='_advance_dynamics'
    dynamics.args.args=[ast.arg(arg=n) for n in ('self','pose','velocity','stationary_prob','cjoint','stationary_weight')]
    dynamics.body=dynamics.body[boundary:]
    predictor.args.args.append(ast.arg(arg='sample_dt'))
    class ObservationTime(ast.NodeTransformer):
        def visit_Attribute(self,node):
            if node.attr=='dt' and isinstance(node.value,ast.Name) and node.value.id=='self':
                return ast.copy_location(ast.Name(id='sample_dt',ctx=ast.Load()),node)
            return self.generic_visit(node)
    predictor=ObservationTime().visit(predictor)
    functions={}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[predictor,dynamics],type_ignores=[])),
                 '<GlobalPose rate adapter>','exec'),sys.modules[GPNet.__module__].__dict__,functions)
    GPNet._predict_observation=functions['_predict_observation']
    GPNet._advance_dynamics=functions['_advance_dynamics']
    qp_original=sys.modules[GPNet.__module__].solve_qp
    def reliable_qp(P,q,lb=None,solver='osqp',**kwargs):
        if os.environ.get('AETHER_GP_DENSE_QP','1')=='1':
            # GP's contact-force objective is strictly convex (ridge > 0)
            # and only has box bounds. Convert it exactly to a tiny bounded
            # least-squares problem instead of rebuilding an OSQP workspace
            # for each tentative contact in every physics substep.
            from scipy.linalg import cholesky,solve_triangular
            from scipy.optimize import lsq_linear
            lower=cholesky(P.toarray(),lower=True)
            target=-solve_triangular(lower,q,lower=True)
            result=lsq_linear(lower.T,target,bounds=(lb,np.full(len(q),np.inf)),
                              method='bvls',tol=1e-9,max_iter=100)
            if result.success and np.isfinite(result.x).all():return result.x
        answer=qp_original(P,q,lb=lb,solver=solver,**kwargs)
        if answer is not None and np.isfinite(answer).all():return answer
        # These GP contact-force QPs have only lower bounds. If OSQP fails
        # to converge, solve the same convex objective with bound-constrained
        # L-BFGS-B instead of allowing a None force into the dynamics.
        from scipy.optimize import minimize
        bounds=[(None if v==-np.inf else float(v),None) for v in lb]
        start=np.maximum(np.zeros(len(q)),lb)
        result=minimize(lambda x:.5*x.dot(P.dot(x))+q.dot(x),start,
            jac=lambda x:P.dot(x)+q,bounds=bounds,method='L-BFGS-B',
            options={'maxiter':500,'ftol':1e-10,'gtol':1e-7})
        if not result.success or not np.isfinite(result.x).all():raise RuntimeError('GlobalPose contact solver did not converge')
        return result.x
    sys.modules[GPNet.__module__].solve_qp=reliable_qp
    if os.environ.get('AETHER_GP_DENSE_LS','1')=='1':
        # GP's two least-squares systems are small and nearly dense. LAPACK
        # solves the same unconstrained objective without repeated sparse
        # Python iterations. OSQP contact constraints remain unchanged.
        from scipy.linalg import lstsq
        def dense_lsqr(matrix,rhs):
            return (lstsq(matrix.toarray(),rhs,lapack_driver='gelsy')[0],)
        sys.modules[GPNet.__module__].lsqr=dense_lsqr
    # Official checkpoints were saved on CUDA; retain original source while
    # explicitly remapping storage during this CPU worker's construction.
    load=torch.load
    def cpu_load(*args,**kwargs):
        kwargs['map_location']='cpu'
        return load(*args,**kwargs)
    torch.load=cpu_load
    class SMPLUnpickler(pickle.Unpickler):
        def find_class(self,module,name):
            # The user's licensed SMPL asset was resaved with NumPy 2;
            # its arrays use the renamed _core module. Preserve the model
            # values and map only that module name in the legacy worker.
            if module.startswith('numpy._core'):module=module.replace('numpy._core','numpy.core',1)
            return super().find_class(module,name)
    pickle_load=pickle.load
    def smpl_load(file,**kw):
        value=SMPLUnpickler(file,**kw).load()
        if isinstance(value,dict) and 'shapedirs' in value:
            # GP's physics armature uses the original 10 SMPL shape PCs.
            # Newer licensed SMPL releases include 300; select the same first
            # ten components (the zero-shape template remains unchanged).
            value['shapedirs']=np.asarray(value['shapedirs'])[:,:,:10].copy()
        return value
    pickle.load=smpl_load
    try:net=GPNet().cpu().eval()
    finally:
        torch.load=load
        pickle.load=pickle_load
    device=torch.device('cuda' if torch.cuda.is_available() and os.environ.get('AETHER_GP_DEVICE','auto')!='cpu' else 'cpu')
    net=net.to(device)
    if device.type=='cpu' and os.environ.get('AETHER_GP_QUANTIZE','1')=='1':
        # Preserve the official architecture/checkpoint and physics equations;
        # use PyTorch's CPU LSTM weight quantization for batch-one inference.
        net=torch.ao.quantization.quantize_dynamic(net,{torch.nn.LSTM},dtype=torch.qint8,inplace=True)
    net.rnn_initialize()
    reply({'ready':True,'device':str(device),'quantized':device.type=='cpu' and os.environ.get('AETHER_GP_QUANTIZE','1')=='1'})
    from globalpose_rates import DynamicsClock,StaleObservation
    clock=DynamicsClock(net) if os.environ.get('AETHER_GP_ASYNC')=='1' and os.environ.get('AETHER_GP_REFERENCE')!='1' else None
    last_sample=None
    epoch=0
    for line in sys.stdin:
        try:
            data=json.loads(line)
            sample=data.get('sample_at')
            gap=None if sample is None or last_sample is None else float(sample)-last_sample
            if sample is not None and (not np.isfinite(float(sample)) or (gap is not None and gap<=0)):
                raise ValueError('Invalid or out-of-order IMU timestamp')
            reset=data.get('reset') or (gap is not None and gap>.25)
            if reset:
                if clock is not None:clock.reset()
                else:net.rnn_initialize()
                epoch+=1
            # The worker consumes available samples at its own update rate.
            # Use elapsed time for velocity integration, contact and dynamics;
            # never integrate one 1/60 step across a longer observation gap.
            observed_dt=1/60 if reset or gap is None else min(.25,max(1/240,gap))
            if clock is None:net.dt=observed_dt
            if sample is not None:last_sample=float(sample)
            pose=tran=None
            with torch.no_grad():
                for frame in data.get('frames',[]):
                    arrays=[np.asarray(frame[k],np.float32) for k in ('acc','gyro','ori')]
                    if [a.shape for a in arrays]!=[(6,3),(6,3),(6,3,3)] or not all(np.isfinite(a).all() for a in arrays):
                        raise ValueError('Invalid GlobalPose frame')
                    inputs=[torch.from_numpy(a).to(device) for a in arrays]
                    elapsed=observed_dt
                    if clock is not None and sample is not None:
                        prediction=net._predict_observation(*inputs,observed_dt)
                        clock.observe(prediction,float(sample))
                        pose,tran,_,epoch,_=clock.wait(float(sample))
                    elif os.environ.get('AETHER_GP_REFERENCE')=='1':
                        pose,tran=net.forward_frame(*inputs)
                    else:
                        predicted,velocity,stationary,contacts,weights=net._predict_observation(*inputs,observed_dt)
                        substeps=max(1,int(math.ceil(elapsed*60-1e-6)))
                        net.dt=elapsed/substeps
                        for _ in range(substeps):
                            pose,tran=net._advance_dynamics(predicted,velocity,stationary,contacts,weights)
                    net.dt=elapsed
            reply({'rotations':pose.numpy().tolist(),'translation':tran.numpy().tolist(),'epoch':epoch,'step_s':observed_dt})
        except StaleObservation:
            reply({'stale':True})
        except Exception as exc:reply({'error':str(exc) or type(exc).__name__})
except Exception as exc:
    traceback.print_exc();reply({'error':str(exc)});sys.exit(1)
