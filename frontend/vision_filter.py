"""Timestamp-aware light smoothing; confidence is never carried forward."""
import numpy as np


class LandmarkFilter:
    def __init__(self,time_constant=.025):
        self.time_constant=time_constant
        self.reset()

    def reset(self):
        self.points=None;self.confidence=None;self.at=None

    def update(self,points,confidence,at):
        points=np.asarray(points,float);confidence=np.asarray(confidence,float)
        if points.shape!=(33,3) or confidence.shape!=(33,) or not np.isfinite(points).all() or not np.isfinite(confidence).all() or not np.isfinite(at):
            raise ValueError('Invalid vision landmark sample')
        if self.at is None or not 0<at-self.at<=.3:
            filtered=points.copy()
        else:
            alpha=1-np.exp(-(at-self.at)/self.time_constant)
            valid=(confidence>=.65)&(self.confidence>=.65)
            filtered=points.copy()
            filtered[valid]=self.points[valid]+alpha*(points[valid]-self.points[valid])
        self.points=filtered.copy();self.confidence=confidence.copy();self.at=at
        return filtered,confidence.copy()
