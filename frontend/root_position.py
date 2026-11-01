"""Camera-root filtering in metres, independent of rendering and model inference.

Horizontal camera positions are authoritative in v1. Missing cameras never
fall back to the mixed/demo model's translation. No claim of inertial odometry.
"""
import math
import numpy as np


class RootPosition:
    def __init__(self):
        self.origin = None
        self.position = np.zeros(3)
        self.last_observation = None
        self.last_time = None
        self.consistent = 0
        self.state = 'waiting'
        self.reason = '等待腰牌與地面參考板。'
        self.epoch = 0
        self.needs_reset = False

    def align(self, now):
        if self.needs_reset or self.last_time is None or now-self.last_time > .3:
            raise ValueError('目前沒有可信腰牌位置；請讓腰牌和地面板可見。')
        self.origin = self.last_observation.copy()
        self.position[:] = 0
        self.consistent = 0
        self.epoch += 1
        self.state, self.reason = 'recovering', '原點已記錄，等待連續穩定位置。'

    def invalidate_world(self):
        self.needs_reset = True
        self.state, self.reason = 'needs_reset', '相機或地面板已移動，請重設參考板並重新記原點。'

    def observe(self, value, now):
        value = np.asarray(value, dtype=float)
        if value.shape != (3,) or not np.isfinite(value).all() or not math.isfinite(now):
            self.reason = '拒絕無效位置資料。'
            return False
        if self.needs_reset:
            return False
        if self.last_time is not None:
            dt = now-self.last_time
            if dt <= 0:
                self.reason = '拒絕倒退時間戳。'
                return False
            distance = np.linalg.norm((value-self.last_observation)[[0, 2]])
            if distance > .08+3.0*min(dt, .3):
                self.consistent = 0
                self.reason = '位置跳變過大；等待穩定觀測或重設參考板。'
                return False
        else:
            dt = 0
        gap = self.last_time is None or dt > .3
        self.last_time, self.last_observation = now, value.copy()
        if self.origin is None:
            self.state, self.reason = 'ready', '已看到腰牌；站在起點後按「記錄位置原點」。'
            return True
        target = value-self.origin
        target[1] = 0  # v1 does not replace vertical pose/floor constraints
        if gap and np.linalg.norm(target-self.position) > .5:
            self.invalidate_world()
            return False
        if gap:
            self.consistent = 0
        self.consistent += 1
        if self.consistent < 5:
            self.state, self.reason = 'recovering', '正在重新確認腰牌位置；位置計分暫停。'
            return True
        error = target-self.position
        # Frame-rate independent smoothing; cap corrections after reacquisition.
        update = error*(1-math.exp(-min(dt, .1)*10))
        length = np.linalg.norm(update)
        limit = max(.001, min(dt, .1)*2.0)
        if length > limit:
            update *= limit/length
        self.position += update
        settled = np.linalg.norm(target-self.position) < .08
        self.state = 'tracking' if settled else 'recovering'
        self.reason = '相機水平位置有效。' if settled else '平滑恢復位置中，暫停位置計分。'
        return True

    def snapshot(self, now):
        age = None if self.last_time is None else max(0.0, now-self.last_time)
        state, reason = self.state, self.reason
        if not self.needs_reset and age is not None and age > .3:
            state = 'occluded' if age <= .8 else 'lost'
            reason = '腰牌暫不可見，保持末位置。' if age <= .8 else '位置已失效；請讓腰牌與地面板重新可見。'
        return {'state': state, 'message': reason, 'position': self.position.round(5).tolist(),
                'age_ms': None if age is None else round(age*1000),
                'epoch': self.epoch, 'aligned': self.origin is not None,
                'position_source': 'camera', 'can_score': state == 'tracking'}
