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

// ── Packet type 0x04: raw IMU + onboard Mahony quaternion (61 bytes) ────────
// Layout (packed):
//   packet_type : uint8    0x04
//   id          : uint8
//   sequence    : uint16
//   gyro[3]     : float[3]  rad/s
//   accel[3]    : float[3]  m/s²
//   batt        : uint8
//   mag[3]      : float[3]  uT
//   dt          : float     seconds
//   quat[4]     : float[4]  [x,y,z,w]  Mahony estimate
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

// ── Lightweight Mahony AHRS ──────────────────────────────────────────────────
// Convention: q0=w, q1=x, q2=y, q3=z
class MahonyAHRS {
public:
  float q0 = 1.0f, q1 = 0.0f, q2 = 0.0f, q3 = 0.0f;
  // Kp_acc: accel correction gain (roll/pitch, reliable)
  // Kp_mag: mag correction gain — kept low because hard-iron is uncalibrated on device.
  //         Host EKF uses calibrated mag; device Mahony only needs coarse yaw reference.
  float Kp_acc = 2.0f, Kp_mag = 0.3f, Ki = 0.005f;
  float eInt[3] = {0.0f, 0.0f, 0.0f};

  // Resync from host EKF result [x,y,z,w]
  void resync(float x, float y, float z, float w) {
    float n = sqrtf(x*x + y*y + z*z + w*w);
    if (n < 1e-6f) return;
    q0 = w / n;
    q1 = x / n;
    q2 = y / n;
    q3 = z / n;
    // Reset integral to avoid a kick
    eInt[0] = eInt[1] = eInt[2] = 0.0f;
  }

  // 9-axis update (gyro rad/s, accel normalised, mag normalised)
  void update(float gx, float gy, float gz,
              float ax, float ay, float az,
              float mx, float my, float mz,
              float dt) {
    if (mx == 0.0f && my == 0.0f && mz == 0.0f) {
      updateIMU(gx, gy, gz, ax, ay, az, dt);
      return;
    }

    float recipNorm;
    float q0q0, q0q1, q0q2, q0q3, q1q1, q1q2, q1q3, q2q2, q2q3, q3q3;
    float hx, hy, bx, bz;
    float halfvx, halfvy, halfvz, halfwx, halfwy, halfwz;
    float halfex, halfey, halfez;
    float qa, qb, qc;

    if (ax == 0.0f && ay == 0.0f && az == 0.0f) return;
    recipNorm = 1.0f / sqrtf(ax*ax + ay*ay + az*az);
    ax *= recipNorm; ay *= recipNorm; az *= recipNorm;

    recipNorm = 1.0f / sqrtf(mx*mx + my*my + mz*mz);
    mx *= recipNorm; my *= recipNorm; mz *= recipNorm;

    q0q0 = q0*q0; q0q1 = q0*q1; q0q2 = q0*q2; q0q3 = q0*q3;
    q1q1 = q1*q1; q1q2 = q1*q2; q1q3 = q1*q3;
    q2q2 = q2*q2; q2q3 = q2*q3; q3q3 = q3*q3;

    hx = 2.0f*(mx*(0.5f - q2q2 - q3q3) + my*(q1q2 - q0q3) + mz*(q1q3 + q0q2));
    hy = 2.0f*(mx*(q1q2 + q0q3) + my*(0.5f - q1q1 - q3q3) + mz*(q2q3 - q0q1));
    bx = sqrtf(hx*hx + hy*hy);
    bz = 2.0f*(mx*(q1q3 - q0q2) + my*(q2q3 + q0q1) + mz*(0.5f - q1q1 - q2q2));

    halfvx = q1q3 - q0q2;
    halfvy = q0q1 + q2q3;
    halfvz = q0q0 - 0.5f + q3q3;
    halfwx = bx*(0.5f - q2q2 - q3q3) + bz*(q1q3 - q0q2);
    halfwy = bx*(q1q2 - q0q3)         + bz*(q0q1 + q2q3);
    halfwz = bx*(q1q2 + q0q3)         + bz*(0.5f - q1q1 - q2q2);

    // Split error: accel part uses Kp_acc, mag part uses Kp_mag (lower, uncalibrated)
    float acc_ex = ay*halfvz - az*halfvy;
    float acc_ey = az*halfvx - ax*halfvz;
    float acc_ez = ax*halfvy - ay*halfvx;
    float mag_ex = my*halfwz - mz*halfwy;
    float mag_ey = mz*halfwx - mx*halfwz;
    float mag_ez = mx*halfwy - my*halfwx;
    halfex = acc_ex + mag_ex;
    halfey = acc_ey + mag_ey;
    halfez = acc_ez + mag_ez;

    if (Ki > 0.0f) {
      eInt[0] += 2.0f * Ki * halfex * dt;
      eInt[1] += 2.0f * Ki * halfey * dt;
      eInt[2] += 2.0f * Ki * halfez * dt;
    } else {
      eInt[0] = eInt[1] = eInt[2] = 0.0f;
    }

    gx += 2.0f * Kp_acc * acc_ex + 2.0f * Kp_mag * mag_ex + eInt[0];
    gy += 2.0f * Kp_acc * acc_ey + 2.0f * Kp_mag * mag_ey + eInt[1];
    gz += 2.0f * Kp_acc * acc_ez + 2.0f * Kp_mag * mag_ez + eInt[2];

    gx *= 0.5f * dt; gy *= 0.5f * dt; gz *= 0.5f * dt;
    qa = q0; qb = q1; qc = q2;
    q0 += (-qb*gx - qc*gy - q3*gz);
    q1 += ( qa*gx + qc*gz - q3*gy);
    q2 += ( qa*gy - qb*gz + q3*gx);
    q3 += ( qa*gz + qb*gx - qc*gy);

    recipNorm = 1.0f / sqrtf(q0*q0 + q1*q1 + q2*q2 + q3*q3);
    q0 *= recipNorm; q1 *= recipNorm; q2 *= recipNorm; q3 *= recipNorm;
  }

  // 6-axis update (no magnetometer)
  void updateIMU(float gx, float gy, float gz,
                 float ax, float ay, float az,
                 float dt) {
    float recipNorm, halfvx, halfvy, halfvz, halfex, halfey, halfez;
    float qa, qb, qc;

    if (!(ax == 0.0f && ay == 0.0f && az == 0.0f)) {
      recipNorm = 1.0f / sqrtf(ax*ax + ay*ay + az*az);
      ax *= recipNorm; ay *= recipNorm; az *= recipNorm;

      halfvx = q1*q3 - q0*q2;
      halfvy = q0*q1 + q2*q3;
      halfvz = q0*q0 - 0.5f + q3*q3;

      halfex = ay*halfvz - az*halfvy;
      halfey = az*halfvx - ax*halfvz;
      halfez = ax*halfvy - ay*halfvx;

      if (Ki > 0.0f) {
        eInt[0] += 2.0f * Ki * halfex * dt;
        eInt[1] += 2.0f * Ki * halfey * dt;
        eInt[2] += 2.0f * Ki * halfez * dt;
      } else {
        eInt[0] = eInt[1] = eInt[2] = 0.0f;
      }

      gx += 2.0f * Kp_acc * halfex + eInt[0];
      gy += 2.0f * Kp_acc * halfey + eInt[1];
      gz += 2.0f * Kp_acc * halfez + eInt[2];
    }

    gx *= 0.5f * dt; gy *= 0.5f * dt; gz *= 0.5f * dt;
    qa = q0; qb = q1; qc = q2;
    q0 += (-qb*gx - qc*gy - q3*gz);
    q1 += ( qa*gx + qc*gz - q3*gy);
    q2 += ( qa*gy - qb*gz + q3*gx);
    q3 += ( qa*gz + qb*gx - qc*gy);

    recipNorm = 1.0f / sqrtf(q0*q0 + q1*q1 + q2*q2 + q3*q3);
    q0 *= recipNorm; q1 *= recipNorm; q2 *= recipNorm; q3 *= recipNorm;
  }
};

// ── BLE objects ──────────────────────────────────────────────────────────────
BLEService         aetherposeService(BLE_SERVICE_UUID);
// Notify: tracker → host (IMU data, 61+5=66 bytes framed)
BLECharacteristic  dataCharacteristic(BLE_CHARACTERISTIC_UUID,
                                      BLERead | BLENotify,
                                      sizeof(RawImuPacketV2) + 5);
// Write: host → tracker (EKF sync quaternion, 16 bytes = 4×float [x,y,z,w])
BLECharacteristic  syncCharacteristic(BLE_SYNC_UUID,
                                      BLEWrite | BLEWriteWithoutResponse,
                                      16);

MahonyAHRS filter;
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
  Serial.println("Aetherpose Tracker v2 (Mahony + host-EKF sync) starting...");

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

  BLE.setLocalName(BLE_DEVICE_NAME);
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

      // ── IMU + Mahony ──────────────────────────────────────────────────────
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

  // Store raw IMU (converted units)
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

  // Run Mahony (uses rad/s gyro, g-unit accel internally via normalisation)
  // Pass raw deg/s gyro → converted to rad/s above; accel in g is fine since Mahony normalises
  const float gx_r = packet.gyro[0];
  const float gy_r = packet.gyro[1];
  const float gz_r = packet.gyro[2];
  // Accel in g (re-divide by 9.81) for Mahony which normalises it anyway
  const float ax_g = ax, ay_g = ay, az_g = az;

  filter.update(gx_r, gy_r, gz_r,
                ax_g, ay_g, az_g,
                packet.mag[0], packet.mag[1], packet.mag[2],
                dt);

  // Store Mahony result as [x,y,z,w]
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
