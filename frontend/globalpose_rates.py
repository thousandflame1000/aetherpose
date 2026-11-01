"""Independent dynamics clock for GlobalPose's slower observation network.

The caller supplies the latest neural observation, with its original timestamp.
Physics advances in small substeps on its own thread; timestamps are never
refreshed merely because dynamics generated another prediction.
"""
import math
import threading
import time

class StaleObservation(RuntimeError):
    pass


class DynamicsClock:
    def __init__(self,net):
        self.net=net
        self.lock=threading.RLock()
        self.changed=threading.Condition(self.lock)
        self.latest=None;self.result=None;self.error=None;self.epoch=0;self.closed=False
        threading.Thread(target=self._run,daemon=True,name='globalpose-dynamics').start()

    def reset(self):
        with self.lock:
            self.net.rnn_initialize();self.net.dt=1/60
            self.epoch+=1;self.latest=None;self.result=None;self.error=None

    def observe(self,prediction,sample_at):
        with self.lock:
            self.latest=(prediction,sample_at,self.epoch)
            self.changed.notify_all()

    def wait(self,sample_at,timeout=20):
        deadline=time.perf_counter()+timeout
        with self.changed:
            while not self.closed:
                if self.error:raise RuntimeError(self.error)
                if self.result is not None and self.result[2]==sample_at:return self.result
                if time.monotonic()-sample_at>.3:
                    raise StaleObservation('Neural observation expired before dynamics could use it')
                remaining=deadline-time.perf_counter()
                if remaining<=0:raise TimeoutError('GlobalPose dynamics response timed out')
                self.changed.wait(min(remaining,.05))
        raise RuntimeError('GlobalPose dynamics stopped')

    def close(self):
        with self.lock:self.closed=True;self.changed.notify_all()

    def _run(self):
        next_at=time.perf_counter();previous=None
        while not self.closed:
            now=time.perf_counter()
            try:
                with self.lock:
                    item=self.latest
                    if item is None or not 0<=time.monotonic()-item[1]<=.3:
                        previous=None
                    else:
                        prediction,sample_at,epoch=item
                        elapsed=1/60 if previous is None else min(.25,max(1/240,now-previous))
                        steps=max(1,int(math.ceil(elapsed*60-1e-6)))
                        self.net.dt=elapsed/steps
                        for _ in range(steps):pose,translation=self.net._advance_dynamics(*prediction)
                        self.net.dt=1/60
                        self.result=(pose,translation,sample_at,epoch,elapsed)
                        self.changed.notify_all();previous=now
            except Exception as exc:
                with self.lock:self.error=str(exc);self.changed.notify_all()
                return
            next_at+=1/60
            current=time.perf_counter()
            if next_at<current-.1:next_at=current
            time.sleep(max(0,next_at-current))
