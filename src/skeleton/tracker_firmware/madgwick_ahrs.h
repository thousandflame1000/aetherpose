#pragma once
#include <cmath>

// Madgwick IMU/MARG filter. Hamilton quaternion, sensor -> world (Z-up).
// Gyro inputs are rad/s; dt is seconds; accel/mag are normalised internally.
// Equations cross-checked against Arduino MadgwickAHRS (SOH Madgwick):
// https://github.com/arduino-libraries/MadgwickAHRS/blob/master/src/MadgwickAHRS.cpp
// beta is a correction gain, not a sample rate or a gyro-bias estimator.
class MadgwickAHRS {
public:
  float q0 = 1.0f, q1 = 0.0f, q2 = 0.0f, q3 = 0.0f;
  float beta = 0.1f;

  // Initial attitude from gravity and (when available) a tilt-compensated
  // magnetic heading. Call once while stationary, not on every update.
  bool align(float ax, float ay, float az, float mx, float my, float mz) {
    if (!validVector(ax, ay, az)) return false;
    const float roll = atan2f(ay, az);
    const float pitch = atan2f(-ax, sqrtf(ay*ay + az*az));
    float yaw = 0.0f;
    if (validVector(mx, my, mz)) {
      const float hx = mx*cosf(pitch) + (my*sinf(roll) + mz*cosf(roll))*sinf(pitch);
      const float hy = my*cosf(roll) - mz*sinf(roll);
      if (hx*hx + hy*hy > 1e-12f) yaw = -atan2f(hy, hx);
    }
    const float cr=cosf(roll/2), sr=sinf(roll/2);
    const float cp=cosf(pitch/2), sp=sinf(pitch/2);
    const float cy=cosf(yaw/2), sy=sinf(yaw/2);
    return resync(sr*cp*cy-cr*sp*sy, cr*sp*cy+sr*cp*sy,
                  cr*cp*sy-sr*sp*cy, cr*cp*cy+sr*sp*sy);
  }

  bool resync(float x, float y, float z, float w) {
    float n = sqrtf(x*x + y*y + z*z + w*w);
    if (!std::isfinite(n) || n < 1e-6f) return false;
    q0 = w/n; q1 = x/n; q2 = y/n; q3 = z/n;
    return true;
  }

  bool update(float gx, float gy, float gz,
              float ax, float ay, float az,
              float mx, float my, float mz,
              float dt) {
    if (!validStep(gx, gy, gz, dt)) return false;
    if (!validVector(mx, my, mz))
      return updateIMU(gx, gy, gz, ax, ay, az, dt);
    float recipNorm;
    float s0, s1, s2, s3;
    float qDot1 = 0.5f*(-q1*gx - q2*gy - q3*gz);
    float qDot2 = 0.5f*( q0*gx + q2*gz - q3*gy);
    float qDot3 = 0.5f*( q0*gy - q1*gz + q3*gx);
    float qDot4 = 0.5f*( q0*gz + q1*gy - q2*gx);
    if (validVector(ax, ay, az)) {
      recipNorm = 1.0f/sqrtf(ax*ax+ay*ay+az*az);
      ax*=recipNorm; ay*=recipNorm; az*=recipNorm;
      recipNorm = 1.0f/sqrtf(mx*mx+my*my+mz*mz);
      mx*=recipNorm; my*=recipNorm; mz*=recipNorm;
      float _2q0mx=2.0f*q0*mx,_2q0my=2.0f*q0*my,_2q0mz=2.0f*q0*mz,_2q1mx=2.0f*q1*mx;
      float _2q0=2.0f*q0,_2q1=2.0f*q1,_2q2=2.0f*q2,_2q3=2.0f*q3;
      float q0q0=q0*q0,q0q1=q0*q1,q0q2=q0*q2,q0q3=q0*q3;
      float q1q1=q1*q1,q1q2=q1*q2,q1q3=q1*q3;
      float q2q2=q2*q2,q2q3=q2*q3,q3q3=q3*q3;
      float hx=mx*q0q0-_2q0my*q3+_2q0mz*q2+mx*q1q1+_2q1*my*q2+_2q1*mz*q3-mx*q2q2-mx*q3q3;
      float hy=_2q0mx*q3+my*q0q0-_2q0mz*q1+_2q1mx*q2-my*q1q1+my*q2q2+_2q2*mz*q3-my*q3q3;
      float _2bx=sqrtf(hx*hx+hy*hy),_2bz=-_2q0mx*q2+_2q0my*q1+mz*q0q0+_2q1mx*q3-mz*q1q1+_2q2*my*q3-mz*q2q2+mz*q3q3;
      float _4bx=2.0f*_2bx,_4bz=2.0f*_2bz;
      s0=-_2q2*(2.0f*(q1q3-q0q2)-ax)+_2q1*(2.0f*(q0q1+q2q3)-ay)+(-_2bz*q2)*(_2bx*(0.5f-q2q2-q3q3)+_2bz*(q1q3-q0q2)-mx)+(-_2bx*q3+_2bz*q1)*(_2bx*(q1q2-q0q3)+_2bz*(q0q1+q2q3)-my)+_2bx*q2*(_2bx*(q0q2+q1q3)+_2bz*(0.5f-q1q1-q2q2)-mz);
      s1= _2q3*(2.0f*(q1q3-q0q2)-ax)+_2q0*(2.0f*(q0q1+q2q3)-ay)-4.0f*q1*(1.0f-2.0f*(q1q1+q2q2)-az)+_2bz*q3*(_2bx*(0.5f-q2q2-q3q3)+_2bz*(q1q3-q0q2)-mx)+(_2bx*q2+_2bz*q0)*(_2bx*(q1q2-q0q3)+_2bz*(q0q1+q2q3)-my)+(_2bx*q3-_4bz*q1)*(_2bx*(q0q2+q1q3)+_2bz*(0.5f-q1q1-q2q2)-mz);
      s2=-_2q0*(2.0f*(q1q3-q0q2)-ax)+_2q3*(2.0f*(q0q1+q2q3)-ay)-4.0f*q2*(1.0f-2.0f*(q1q1+q2q2)-az)+(-_4bx*q2-_2bz*q0)*(_2bx*(0.5f-q2q2-q3q3)+_2bz*(q1q3-q0q2)-mx)+(_2bx*q1+_2bz*q3)*(_2bx*(q1q2-q0q3)+_2bz*(q0q1+q2q3)-my)+(_2bx*q0-_4bz*q2)*(_2bx*(q0q2+q1q3)+_2bz*(0.5f-q1q1-q2q2)-mz);
      s3= _2q1*(2.0f*(q1q3-q0q2)-ax)+_2q2*(2.0f*(q0q1+q2q3)-ay)+(-_4bx*q3+_2bz*q1)*(_2bx*(0.5f-q2q2-q3q3)+_2bz*(q1q3-q0q2)-mx)+(-_2bx*q0+_2bz*q2)*(_2bx*(q1q2-q0q3)+_2bz*(q0q1+q2q3)-my)+_2bx*q1*(_2bx*(q0q2+q1q3)+_2bz*(0.5f-q1q1-q2q2)-mz);
      const float stepNorm2 = s0*s0+s1*s1+s2*s2+s3*s3;
      // At equilibrium the gradient is exactly zero: keep gyro integration.
      if (std::isfinite(stepNorm2) && stepNorm2 > 1e-12f) {
        recipNorm = 1.0f/sqrtf(stepNorm2);
        qDot1 -= beta*s0*recipNorm; qDot2 -= beta*s1*recipNorm;
        qDot3 -= beta*s2*recipNorm; qDot4 -= beta*s3*recipNorm;
      }
    }
    // Commit only a finite, normalised candidate. Never poison the last pose.
    return resync(q1+qDot2*dt, q2+qDot3*dt, q3+qDot4*dt, q0+qDot1*dt);
  }

  bool updateIMU(float gx, float gy, float gz,
                 float ax, float ay, float az, float dt) {
    if (!validStep(gx, gy, gz, dt)) return false;
    float recipNorm, s0, s1, s2, s3;
    float qDot1=0.5f*(-q1*gx-q2*gy-q3*gz);
    float qDot2=0.5f*( q0*gx+q2*gz-q3*gy);
    float qDot3=0.5f*( q0*gy-q1*gz+q3*gx);
    float qDot4=0.5f*( q0*gz+q1*gy-q2*gx);
    if (validVector(ax, ay, az)) {
      recipNorm=1.0f/sqrtf(ax*ax+ay*ay+az*az);
      ax*=recipNorm; ay*=recipNorm; az*=recipNorm;
      float _2q0=2.0f*q0,_2q1=2.0f*q1,_2q2=2.0f*q2,_2q3=2.0f*q3;
      float _4q0=4.0f*q0,_4q1=4.0f*q1,_4q2=4.0f*q2;
      float _8q1=8.0f*q1,_8q2=8.0f*q2;
      float q0q0=q0*q0,q1q1=q1*q1,q2q2=q2*q2,q3q3=q3*q3;
      s0=_4q0*q2q2+_2q2*ax+_4q0*q1q1-_2q1*ay;
      s1=_4q1*q3q3-_2q3*ax+4.0f*q0q0*q1-_2q0*ay-_4q1+_8q1*q1q1+_8q1*q2q2+_4q1*az;
      s2=4.0f*q0q0*q2+_2q0*ax+_4q2*q3q3-_2q3*ay-_4q2+_8q2*q1q1+_8q2*q2q2+_4q2*az;
      s3=4.0f*q1q1*q3-_2q1*ax+4.0f*q2q2*q3-_2q2*ay;
      const float stepNorm2 = s0*s0+s1*s1+s2*s2+s3*s3;
      // At equilibrium the gradient is exactly zero: keep gyro integration.
      if (std::isfinite(stepNorm2) && stepNorm2 > 1e-12f) {
        recipNorm = 1.0f/sqrtf(stepNorm2);
        qDot1 -= beta*s0*recipNorm; qDot2 -= beta*s1*recipNorm;
        qDot3 -= beta*s2*recipNorm; qDot4 -= beta*s3*recipNorm;
      }
    }
    // Commit only a finite, normalised candidate. Never poison the last pose.
    return resync(q1+qDot2*dt, q2+qDot3*dt, q3+qDot4*dt, q0+qDot1*dt);
  }
private:
  static bool validVector(float x, float y, float z) {
    const float n2 = x*x + y*y + z*z;
    return std::isfinite(n2) && n2 > 1e-12f;
  }
  bool validStep(float gx, float gy, float gz, float dt) const {
    return std::isfinite(gx) && std::isfinite(gy) && std::isfinite(gz)
        && std::isfinite(dt) && dt > 0.0f && dt <= 0.05f
        && std::isfinite(beta) && beta >= 0.0f;
  }
};
