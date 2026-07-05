#include <Arduino.h>
#include <Arduino_LSM9DS1.h>
#include <ArduinoBLE.h>

#define STATUS_LED_PIN LED_BUILTIN

#define BLE_DEVICE_NAME "Aetherpose Tracker"
#define BLE_SERVICE_UUID        "19B10000-E8F2-537E-4F6C-D104768A1214"
#define BLE_CHARACTERISTIC_UUID "19B10001-E8F2-537E-4F6C-D104768A1214"
#define BLE_SYNC_UUID           "19B10002-E8F2-537E-4F6C-D104768A1214"

#define BATTERY_PIN A0
#define VOLTAGE_DIVIDER_R1     100000.0f
#define VOLTAGE_DIVIDER_R2     100000.0f
#define ADC_REFERENCE_VOLTAGE  3.3f
#define ADC_RESOLUTION         4095.0f
#define BATTERY_MAX_VOLTAGE    4.2f
#define BATTERY_MIN_VOLTAGE    3.0f

// ── Packet type 0x04: raw IMU + onboard Madgwick quaternion (61 bytes) ───────
// Layout (packed):
//   packet_type : uint8    0x04
//   id          : uint8
//   sequence    : uint16
//   gyro[3]     : float[3]  rad/s
//   accel[3]    : float[3]  m/s²
//   batt        : uint8
//   mag[3]      : float[3]  uT
//   dt          : float     seconds
//   quat[4]     : float[4]  [x,y,z,w]  Madgwick estimate
#define PACKET_TYPE_IMU_V2 0x04

struct __attribute__((packed)) RawImuPacketV2 {
  uint8_t  packet_type = PACKET_TYPE_IMU_V2;
  uint8_t  id          = 1;
  uint16_t sequence    = 0;
  float    gyro[3]     = {0.0f, 0.0f, 0.0f};
  float    accel[3]    = {0.0f, 0.0f, 0.0f};
  uint8_t  batt        = 100;
  float    mag[3]      = {0.0f, 0.0f, 0.0f};
  float    dt          = 1.0f / 119.0f;
  float    quat[4]     = {0.0f, 0.0f, 0.0f, 1.0f};  // [x, y, z, w]
};

static_assert(sizeof(RawImuPacketV2) == 61, "Packet size mismatch");

// ── Madgwick AHRS ─────────────────────────────────────────────────────────────
// beta = 0.1: standard value for 100 Hz. Higher = faster correction but noisier.
// Suitable for motion capture — widely validated in literature.
class MadgwickAHRS {
public:
  float q0 = 1.0f, q1 = 0.0f, q2 = 0.0f, q3 = 0.0f;
  float beta = 0.1f;

  void resync(float x, float y, float z, float w) {
    float n = sqrtf(x*x + y*y + z*z + w*w);
    if (n < 1e-6f) return;
    q0 = w/n; q1 = x/n; q2 = y/n; q3 = z/n;
  }

  void update(float gx, float gy, float gz,
              float ax, float ay, float az,
              float mx, float my, float mz,
              float dt) {
    if (mx == 0.0f && my == 0.0f && mz == 0.0f) {
      updateIMU(gx, gy, gz, ax, ay, az, dt); return;
    }
    float recipNorm;
    float s0, s1, s2, s3;
    float qDot1 = 0.5f*(-q1*gx - q2*gy - q3*gz);
    float qDot2 = 0.5f*( q0*gx + q2*gz - q3*gy);
    float qDot3 = 0.5f*( q0*gy - q1*gz + q3*gx);
    float qDot4 = 0.5f*( q0*gz + q1*gy - q2*gx);
    if (!((ax==0.0f)&&(ay==0.0f)&&(az==0.0f))) {
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
      s0=-_2q2*(2.0f*(q1q3-q0q2)-ax)+_2q1*(2.0f*(q0q1+q2q3)-ay)+(-_4bz*q2)*(_2bx*(0.5f-q2q2-q3q3)+_2bz*(q1q3-q0q2)-mx)+(-_2bx*q3+_2bz*q1)*(_2bx*(q1q2-q0q3)+_2bz*(q0q1+q2q3)-my)+_2bx*q2*(_2bx*(q0q2+q1q3)+_2bz*(0.5f-q1q1-q2q2)-mz);
      s1= _2q3*(2.0f*(q1q3-q0q2)-ax)+_2q0*(2.0f*(q0q1+q2q3)-ay)-4.0f*q1*(1.0f-2.0f*(q1q1+q2q2)-az)+_2bz*q3*(_2bx*(0.5f-q2q2-q3q3)+_2bz*(q1q3-q0q2)-mx)+(_2bx*q2+_2bz*q0)*(_2bx*(q1q2-q0q3)+_2bz*(q0q1+q2q3)-my)+(_2bx*q3-_4bz*q1)*(_2bx*(q0q2+q1q3)+_2bz*(0.5f-q1q1-q2q2)-mz);
      s2=-_2q0*(2.0f*(q1q3-q0q2)-ax)+_2q3*(2.0f*(q0q1+q2q3)-ay)-4.0f*q2*(1.0f-2.0f*(q1q1+q2q2)-az)+(-_4bx*q2-_2bz*q0)*(_2bx*(0.5f-q2q2-q3q3)+_2bz*(q1q3-q0q2)-mx)+(_2bx*q1+_2bz*q3)*(_2bx*(q1q2-q0q3)+_2bz*(q0q1+q2q3)-my)+(_2bx*q0-_4bz*q2)*(_2bx*(q0q2+q1q3)+_2bz*(0.5f-q1q1-q2q2)-mz);
      s3= _2q1*(2.0f*(q1q3-q0q2)-ax)+_2q2*(2.0f*(q0q1+q2q3)-ay)+(-_4bx*q3+_2bz*q1)*(_2bx*(0.5f-q2q2-q3q3)+_2bz*(q1q3-q0q2)-mx)+(-_2bx*q0+_2bz*q2)*(_2bx*(q1q2-q0q3)+_2bz*(q0q1+q2q3)-my)+_2bx*q1*(_2bx*(q0q2+q1q3)+_2bz*(0.5f-q1q1-q2q2)-mz);
      recipNorm=1.0f/sqrtf(s0*s0+s1*s1+s2*s2+s3*s3);
      s0*=recipNorm; s1*=recipNorm; s2*=recipNorm; s3*=recipNorm;
      qDot1-=beta*s0; qDot2-=beta*s1; qDot3-=beta*s2; qDot4-=beta*s3;
    }
    q0+=qDot1*dt; q1+=qDot2*dt; q2+=qDot3*dt; q3+=qDot4*dt;
    recipNorm=1.0f/sqrtf(q0*q0+q1*q1+q2*q2+q3*q3);
    q0*=recipNorm; q1*=recipNorm; q2*=recipNorm; q3*=recipNorm;
  }

  void updateIMU(float gx, float gy, float gz,
                 float ax, float ay, float az, float dt) {
    float recipNorm, s0, s1, s2, s3;
    float qDot1=0.5f*(-q1*gx-q2*gy-q3*gz);
    float qDot2=0.5f*( q0*gx+q2*gz-q3*gy);
    float qDot3=0.5f*( q0*gy-q1*gz+q3*gx);
    float qDot4=0.5f*( q0*gz+q1*gy-q2*gx);
    if (!((ax==0.0f)&&(ay==0.0f)&&(az==0.0f))) {
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
      recipNorm=1.0f/sqrtf(s0*s0+s1*s1+s2*s2+s3*s3);
      s0*=recipNorm; s1*=recipNorm; s2*=recipNorm; s3*=recipNorm;
      qDot1-=beta*s0; qDot2-=beta*s1; qDot3-=beta*s2; qDot4-=beta*s3;
    }
    q0+=qDot1*dt; q1+=qDot2*dt; q2+=qDot3*dt; q3+=qDot4*dt;
    recipNorm=1.0f/sqrtf(q0*q0+q1*q1+q2*q2+q3*q3);
    q0*=recipNorm; q1*=recipNorm; q2*=recipNorm; q3*=recipNorm;
  }
};

// ── BLE objects ──────────────────────────────────────────────────────────────
BLEService         aetherposeService(BLE_SERVICE_UUID);
BLECharacteristic  dataCharacteristic(BLE_CHARACTERISTIC_UUID,
                                      BLERead | BLENotify,
                                      sizeof(RawImuPacketV2) + 5);
BLECharacteristic  syncCharacteristic(BLE_SYNC_UUID,
                                      BLEWrite | BLEWriteWithoutResponse,
                                      16);

MadgwickAHRS filter;
RawImuPacketV2 packet;

unsigned long last_send_time        = 0;
unsigned long last_battery_read_time= 0;
unsigned long last_imu_time         = 0;


const int SEND_INTERVAL_MS         = 10;    // 100 Hz
const int BATTERY_READ_INTERVAL_MS = 5000;

uint8_t  getBatteryPercentage();
void     updateSensorData();

// ── CRC16-CCITT (false) ──────────────────────────────────────────────────────
uint16_t crc16_ccitt_false(const uint8_t* data, size_t len) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < len; ++i) {
    crc ^= static_cast<uint16_t>(data[i]) << 8;
    for (uint8_t bit = 0; bit < 8; ++bit)
      crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : (crc << 1);
  }
  return crc;
}

// ── setup ────────────────────────────────────────────────────────────────────
void setup() {
  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, HIGH);
  pinMode(BATTERY_PIN, INPUT);
  analogReadResolution(12);

  Serial.begin(115200);
  const unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 3000) {}
  Serial.println("Aetherpose Tracker v2 (Madgwick) starting...");

  if (!IMU.begin()) {
    Serial.println("IMU init failed!");
    while (true) { digitalWrite(STATUS_LED_PIN, HIGH); delay(100);
                   digitalWrite(STATUS_LED_PIN, LOW);  delay(100); }
  }

  packet.batt = getBatteryPercentage();

  if (!BLE.begin()) {
    Serial.println("BLE init failed!");
    while (true) { digitalWrite(STATUS_LED_PIN, HIGH); delay(50);
                   digitalWrite(STATUS_LED_PIN, LOW);  delay(50); }
  }

  // ── Derive unique tracker ID from BLE MAC address ─────────────────────────
  // MAC format: "aa:bb:cc:dd:ee:ff"  (ArduinoBLE returns lowercase hex)
  // Use the last byte as tracker ID; clamp to 1–254 to avoid 0 and 255.
  {
    String mac     = BLE.address();
    String hexByte = mac.substring(mac.length() - 2);
    uint8_t macId  = (uint8_t)strtol(hexByte.c_str(), nullptr, 16);
    packet.id      = (macId == 0 || macId == 255) ? 1 : macId;
  }

  // Set unique BLE device name so host can distinguish multiple trackers
  String deviceName = String(BLE_DEVICE_NAME) + " " + String(packet.id);
  BLE.setLocalName(deviceName.c_str());

  Serial.print("Tracker ID: ");  Serial.println(packet.id);
  Serial.print("BLE name:   ");  Serial.println(deviceName);

  BLE.setAdvertisedService(aetherposeService);
  aetherposeService.addCharacteristic(dataCharacteristic);
  aetherposeService.addCharacteristic(syncCharacteristic);
  BLE.addService(aetherposeService);
  BLE.setConnectionInterval(6, 12);
  BLE.advertise();

  Serial.println("BLE advertising started.");
  digitalWrite(STATUS_LED_PIN, LOW);
}

// ── loop ─────────────────────────────────────────────────────────────────────
void loop() {
  BLEDevice central = BLE.central();
  if (central) {
    if (Serial) { Serial.print("Connected: "); Serial.println(central.address()); }
    digitalWrite(STATUS_LED_PIN, HIGH);

    while (central.connected()) {
      // Battery refresh
      if (millis() - last_battery_read_time >= BATTERY_READ_INTERVAL_MS) {
        last_battery_read_time = millis();
        packet.batt = getBatteryPercentage();
      }

      // ── Receive EKF sync from host ────────────────────────────────────────
      if (syncCharacteristic.written()) {
        const uint8_t* buf = syncCharacteristic.value();
        const int      len = syncCharacteristic.valueLength();
        if (len == 16) {
          float sx, sy, sz, sw;
          memcpy(&sx, buf + 0,  4);
          memcpy(&sy, buf + 4,  4);
          memcpy(&sz, buf + 8,  4);
          memcpy(&sw, buf + 12, 4);
          filter.resync(sx, sy, sz, sw);
          if (Serial) Serial.println("EKF sync received.");
        }
      }

      // ── IMU + Madgwick ───────────────────────────────────────────────────
      updateSensorData();

      // ── Send packet at 100 Hz ─────────────────────────────────────────────
      if (millis() - last_send_time >= SEND_INTERVAL_MS) {
        last_send_time = millis();
        packet.sequence++;

        const uint8_t  plen  = sizeof(packet);
        uint8_t        frame[sizeof(RawImuPacketV2) + 5];
        frame[0] = 0xAA;
        frame[1] = 0x55;
        frame[2] = plen;
        memcpy(frame + 3, reinterpret_cast<const uint8_t*>(&packet), plen);
        const uint16_t crc = crc16_ccitt_false(frame + 3, plen);
        frame[3 + plen]     = static_cast<uint8_t>(crc & 0xFF);
        frame[4 + plen]     = static_cast<uint8_t>((crc >> 8) & 0xFF);

        dataCharacteristic.writeValue(frame, 5 + plen);
      }
    }

    if (Serial) { Serial.print("Disconnected: "); Serial.println(central.address()); }
    digitalWrite(STATUS_LED_PIN, LOW);
  } else {
    const float breath = (exp(sinf(millis() / 2000.0f * PI)) - 0.36787944f) * 108.0f;
    analogWrite(STATUS_LED_PIN, static_cast<int>(breath));
  }
}

// ── updateSensorData ─────────────────────────────────────────────────────────
void updateSensorData() {
  if (!(IMU.accelerationAvailable() && IMU.gyroscopeAvailable())) return;

  float ax, ay, az, gx, gy, gz;
  IMU.readAcceleration(ax, ay, az);
  IMU.readGyroscope(gx, gy, gz);

  const unsigned long now = micros();
  float dt = (last_imu_time == 0) ? (1.0f / 119.0f)
                                   : ((now - last_imu_time) / 1000000.0f);
  last_imu_time = now;
  dt = constrain(dt, 0.001f, 0.05f);

  // Store raw gyro (Mahony Ki handles bias automatically)
  packet.gyro[0] = gx * DEG_TO_RAD;
  packet.gyro[1] = gy * DEG_TO_RAD;
  packet.gyro[2] = gz * DEG_TO_RAD;
  packet.accel[0] = ax * 9.81f;
  packet.accel[1] = ay * 9.81f;
  packet.accel[2] = az * 9.81f;
  packet.dt = dt;

  // Refresh magnetometer when ready (~20 Hz)
  if (IMU.magneticFieldAvailable()) {
    float mx, my, mz;
    IMU.readMagneticField(mx, my, mz);
    packet.mag[0] = mx;
    packet.mag[1] = my;
    packet.mag[2] = mz;
  }

  // Run Madgwick (gyro in rad/s, accel in g — units don't matter, all normalised internally)
  const float gx_r = packet.gyro[0];
  const float gy_r = packet.gyro[1];
  const float gz_r = packet.gyro[2];
  const float ax_g = ax, ay_g = ay, az_g = az;

  filter.update(gx_r, gy_r, gz_r,
                ax_g, ay_g, az_g,
                packet.mag[0], packet.mag[1], packet.mag[2],
                dt);

  // Store Madgwick result as [x,y,z,w]
  packet.quat[0] = filter.q1;  // x
  packet.quat[1] = filter.q2;  // y
  packet.quat[2] = filter.q3;  // z
  packet.quat[3] = filter.q0;  // w
}

// ── getBatteryPercentage ─────────────────────────────────────────────────────
uint8_t getBatteryPercentage() {
  const int   raw     = analogRead(BATTERY_PIN);
  const float pin_v   = raw * (ADC_REFERENCE_VOLTAGE / ADC_RESOLUTION);
  const float batt_v  = pin_v * (VOLTAGE_DIVIDER_R1 + VOLTAGE_DIVIDER_R2) / VOLTAGE_DIVIDER_R2;
  const float pct     = 100.0f * (batt_v - BATTERY_MIN_VOLTAGE)
                                / (BATTERY_MAX_VOLTAGE - BATTERY_MIN_VOLTAGE);
  return static_cast<uint8_t>(constrain(pct, 0.0f, 100.0f));
}
