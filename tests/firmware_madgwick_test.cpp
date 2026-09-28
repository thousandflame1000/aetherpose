#include "../src/skeleton/tracker_firmware/madgwick_ahrs.h"
#include <cassert>
#include <cstdio>

static float norm(const MadgwickAHRS& f) {
  return sqrtf(f.q0*f.q0+f.q1*f.q1+f.q2*f.q2+f.q3*f.q3);
}
static void healthy(const MadgwickAHRS& f) {
  assert(std::isfinite(norm(f)) && fabsf(norm(f)-1) < 2e-6f);
}
int main() {
  constexpr float dt = 1.0f/119.0f;
  MadgwickAHRS imu, marg;
  for (int i=0; i<10000; ++i) {
    assert(imu.update(0,0,0,0,0,1,0,0,0,dt));
    assert(marg.update(0,0,0,0,0,1,1,0,0,dt));
  }
  healthy(imu); healthy(marg);
  assert(imu.q0 == 1 && marg.q0 == 1);
  assert(!imu.resync(NAN,0,0,1));
  assert(!imu.resync(INFINITY,0,0,1));
  assert(!imu.resync(0,0,0,0));
  assert(!imu.update(NAN,0,0,0,0,1,1,0,0,dt));
  assert(!imu.update(0,0,0,0,0,1,1,0,0,0));
  assert(!imu.update(0,0,0,0,0,1,1,0,0,1));
  assert(!imu.update(0,0,0,0,0,1,1,0,0,NAN));
  assert(imu.q0 == 1);
  // Missing mag falls back to 6-axis; missing accel to finite gyro integration.
  assert(imu.update(0,0,0,0,0,1,NAN,0,0,dt));
  assert(imu.update(.1f,0,0,NAN,NAN,NAN,0,0,0,dt));
  healthy(imu);
  for (int axis=0; axis<3; ++axis) {
    MadgwickAHRS f;
    float gyro[3]={}; gyro[axis]=1.57079632679f;
    for (int i=0; i<119; ++i) assert(f.updateIMU(gyro[0],gyro[1],gyro[2],0,0,0,dt));
    healthy(f);
    float q[3]={f.q1,f.q2,f.q3};
    assert(fabsf(q[axis]-.70710678f)<2e-5f);
    assert(fabsf(f.q0-.70710678f)<2e-5f);
  }
  MadgwickAHRS tilt;
  tilt.resync(.2588190451f,0,0,.9659258263f);
  for (int i=0;i<1190;++i) tilt.updateIMU(0,0,0,0,0,1,dt);
  assert(fabsf(tilt.q1)<.001f); healthy(tilt);
  MadgwickAHRS init;
  assert(init.align(0,0,-1,1,0,0)); // upside-down startup must work
  assert(fabsf(init.q1)>0.9999f); healthy(init);
  assert(init.align(0,0,1,0,-1,0)); // body +X points world +Y
  assert(fabsf(init.q3-.70710678f)<2e-6f);
  assert(fabsf(init.q0-.70710678f)<2e-6f);
  assert(!init.align(0,0,0,1,0,0));
  MadgwickAHRS coefficient;
  coefficient.resync(.2f,.3f,-.1f,.9f);
  coefficient.update(.1f,.2f,.3f,.2f,-.1f,.95f,.4f,.1f,-.8f,dt);
  // Corrected reference result; the old doubled s0 term fails this regression.
  assert(fabsf(coefficient.q2-.307738602f)<1.2e-7f);
  std::puts("PASS: equilibrium, invalid inputs, recovery, XYZ rotations, tilt convergence, initial alignment, MARG coefficient");
}
