#include <Arduino.h>
#include <Arduino_LSM9DS1.h>
#include <ArduinoBLE.h>
#include <Wire.h>
#include "src/Fusion/Fusion.h"  // x-io Fusion AHRS, see src/Fusion/VERSION.txt

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

// Per-device magnetic calibration in the native Arduino_LSM9DS1 mag frame.
// Replace these defaults with measured values; defaults are NOT a calibration.
const bool USE_MAGNETOMETER = true;
// Tracker 43 (D4:3F:A8:D9:D3:2B), tools/mag_calibrate.py, 2026-09-28.
const float MAG_OFFSET_UT[3] = {25.70f, 22.09f, 10.04f};
const float MAG_SCALE[3] = {0.9158f, 1.1117f, 0.9915f};
float gyro_bias_dps[3] = {0.0f, 0.0f, 0.0f};
// Arduino_LSM9DS1 scales ±2000 dps as 2000/32768 dps/LSB; the datasheet
// sensitivity is 70 mdps/LSB. Applied to the filter input only.
const float GYRO_SENSITIVITY_FIX = 0.070f / (2000.0f / 32768.0f);
// Arduino_LSM9DS1 fixes the accelerometer at ±4 g, which fast arm swings
// exceed. setup() switches it to ±16 g (datasheet 0.732 mg/LSB) while the
// library still scales as 4 g / 32768, so readings are rescaled by accel_scale.
const float ACCEL_16G_SCALE = 0.732f / (4000.0f / 32768.0f);
float accel_scale = 1.0f;
const float IMU_SAMPLE_RATE = 119.0f;  // Hz, Arduino_LSM9DS1 accel/gyro ODR

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
//   quat[4]     : float[4]  [x,y,z,w]  Fusion AHRS estimate (NWU, mag frame)
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

// ── BLE objects ──────────────────────────────────────────────────────────────
BLEService         aetherposeService(BLE_SERVICE_UUID);
BLECharacteristic  dataCharacteristic(BLE_CHARACTERISTIC_UUID,
                                      BLERead | BLENotify,
                                      sizeof(RawImuPacketV2) + 5);
BLECharacteristic  syncCharacteristic(BLE_SYNC_UUID,
                                      BLEWrite | BLEWriteWithoutResponse,
                                      16);

FusionAhrs ahrs;
FusionBias gyro_bias_tracker;  // run-time gyro drift correction while still
RawImuPacketV2 packet;

unsigned long last_send_time        = 0;
unsigned long last_battery_read_time= 0;
unsigned long last_imu_time         = 0;
unsigned long last_mag_time         = 0;
bool have_mag = false;
bool packet_ready = false;


const int SEND_INTERVAL_MS         = 10;    // 100 Hz
const int BATTERY_READ_INTERVAL_MS = 5000;

uint8_t  getBatteryPercentage();
void     updateSensorData();
void     calibrateGyroscope();
bool     setAccelRange16g();
bool     readAccelG(float& x, float& y, float& z);
void     initFusion();

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
  Serial.println("Aetherpose Tracker v2 (Fusion AHRS) starting...");

  if (!IMU.begin()) {
    Serial.println("IMU init failed!");
    while (true) { digitalWrite(STATUS_LED_PIN, HIGH); delay(100);
                   digitalWrite(STATUS_LED_PIN, LOW);  delay(100); }
  }
  if (setAccelRange16g()) {
    accel_scale = ACCEL_16G_SCALE;
    Serial.println("Accelerometer range: +/-16 g");
  } else Serial.println("Accelerometer range change failed; staying at +/-4 g");

  calibrateGyroscope();
  initFusion();

  packet.batt = getBatteryPercentage();

  if (!BLE.begin()) {
    Serial.println("BLE init failed!");
    while (true) { digitalWrite(STATUS_LED_PIN, HIGH); delay(50);
                   digitalWrite(STATUS_LED_PIN, LOW);  delay(50); }
  }

  // ── Derive a short tracker ID from BLE MAC address ────────────────────────
  // MAC format: "aa:bb:cc:dd:ee:ff"  (ArduinoBLE returns lowercase hex)
  // Last-byte IDs can collide; use the full BLE address to select a test device.
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
  // Track continuously, including while advertising/disconnected.
  BLE.poll();
  updateSensorData();
  BLEDevice central = BLE.central();
  if (central) {
    if (Serial) { Serial.print("Connected: "); Serial.println(central.address()); }
    digitalWrite(STATUS_LED_PIN, HIGH);

    while (central.connected()) {
      BLE.poll();
      // Battery refresh
      if (millis() - last_battery_read_time >= BATTERY_READ_INTERVAL_MS) {
        last_battery_read_time = millis();
        packet.batt = getBatteryPercentage();
      }

      // Optional host orientation sync (the standalone tester never writes it).
      if (syncCharacteristic.written()) {
        const uint8_t* buf = syncCharacteristic.value();
        const int      len = syncCharacteristic.valueLength();
        if (len == 16) {
          float sx, sy, sz, sw;
          memcpy(&sx, buf + 0,  4);
          memcpy(&sy, buf + 4,  4);
          memcpy(&sz, buf + 8,  4);
          memcpy(&sw, buf + 12, 4);
          const float n = sqrtf(sx*sx + sy*sy + sz*sz + sw*sw);
          if (std::isfinite(n) && n > 1e-6f) {
            const FusionQuaternion q = {.element = {sw / n, sx / n, sy / n, sz / n}};
            FusionAhrsSetQuaternion(&ahrs, q);
            if (Serial) Serial.println("Orientation sync received.");
          }
        }
      }

      // ── IMU + Fusion AHRS ────────────────────────────────────────────────
      updateSensorData();

      // ── Send packet at 100 Hz ─────────────────────────────────────────────
      if (packet_ready && millis() - last_send_time >= SEND_INTERVAL_MS) {
        last_send_time = millis();
        packet_ready = false;
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
  if (!readAccelG(ax, ay, az) || !IMU.readGyroscope(gx, gy, gz)
      || !std::isfinite(gx) || !std::isfinite(gy) || !std::isfinite(gz)) {
    last_imu_time = 0;
    packet_ready = false;
    return;
  }

  const unsigned long now = micros();
  float dt = (last_imu_time == 0) ? (1.0f / 119.0f)
                                   : ((now - last_imu_time) / 1000000.0f);
  last_imu_time = now;
  // Do not integrate a single recent reading across an unobserved long gap.
  if (dt <= 0.0f || dt > 0.05f) dt = 1.0f / 119.0f;

  // Preserve raw samples in the packet. Bias is subtracted only for the filter.
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
    if (IMU.readMagneticField(mx, my, mz)
        && std::isfinite(mx) && std::isfinite(my) && std::isfinite(mz)
        && mx*mx + my*my + mz*mz > 1e-6f) {
      packet.mag[0] = mx;
      packet.mag[1] = my;
      packet.mag[2] = mz;
      last_mag_time = millis();
      have_mag = true;
    } else {
      have_mag = false;
    }
  }

  // Fusion frame = the right-handed LSM9DS1 mag frame. The accel/gyro axes are
  // left-handed; flipping their X (after bias removal) aligns them with it.
  // https://github.com/jremington/LSM9DS1-AHRS/blob/main/Mahony_AHRS/MahonyUW_AHRS.ino
  float mx = 0.0f, my = 0.0f, mz = 0.0f;
  if (USE_MAGNETOMETER && have_mag && millis() - last_mag_time < 200) {
    mx = (packet.mag[0] - MAG_OFFSET_UT[0]) * MAG_SCALE[0];
    my = (packet.mag[1] - MAG_OFFSET_UT[1]) * MAG_SCALE[1];
    mz = (packet.mag[2] - MAG_OFFSET_UT[2]) * MAG_SCALE[2];
  }
  FusionVector gyroscope = {.axis = {-(gx - gyro_bias_dps[0]) * GYRO_SENSITIVITY_FIX,
                                      (gy - gyro_bias_dps[1]) * GYRO_SENSITIVITY_FIX,
                                      (gz - gyro_bias_dps[2]) * GYRO_SENSITIVITY_FIX}};
  const FusionVector accelerometer = {.axis = {-ax, ay, az}};
  gyroscope = FusionBiasUpdate(&gyro_bias_tracker, gyroscope);
  FusionAhrsSetSamplePeriod(&ahrs, dt);
  if (mx != 0.0f || my != 0.0f || mz != 0.0f) {
    const FusionVector magnetometer = {.axis = {mx, my, mz}};
    FusionAhrsUpdate(&ahrs, gyroscope, accelerometer, magnetometer);
  } else {
    FusionAhrsUpdateNoMagnetometer(&ahrs, gyroscope, accelerometer);
  }

  const FusionQuaternion q = FusionAhrsGetQuaternion(&ahrs);
  if (!std::isfinite(q.element.w) || !std::isfinite(q.element.x)
      || !std::isfinite(q.element.y) || !std::isfinite(q.element.z)) {
    FusionAhrsRestart(&ahrs);  // never publish or keep a poisoned pose
    packet_ready = false;
    return;
  }
  packet.quat[0] = q.element.x;
  packet.quat[1] = q.element.y;
  packet.quat[2] = q.element.z;
  packet.quat[3] = q.element.w;
  packet_ready = true;
}

// Rejection/recovery settings follow the Fusion advanced example.
void initFusion() {
  FusionAhrsInitialise(&ahrs);
  FusionAhrsSettings settings = fusionAhrsDefaultSettings;
  settings.sampleRate = IMU_SAMPLE_RATE;
  settings.convention = FusionConventionNwu;
  settings.gain = 0.5f;
  settings.gyroscopeRange = 2000.0f;
  settings.accelerationRejection = 10.0f;
  settings.magneticRejection = 10.0f;
  settings.rejectionTimeout = 5.0f;
  FusionAhrsSetSettings(&ahrs, &settings);

  FusionBiasInitialise(&gyro_bias_tracker);
  FusionBiasSettings bias_settings = fusionBiasDefaultSettings;
  bias_settings.sampleRate = IMU_SAMPLE_RATE;
  FusionBiasSetSettings(&gyro_bias_tracker, &bias_settings);
}

// CTRL_REG6_XL = ODR_XL[7:5] 011 (119 Hz) | FS_XL[4:3] 01 (±16 g) = 0x68.
// FS_XL: 00 ±2 g, 01 ±16 g, 10 ±4 g, 11 ±8 g. Read back to confirm.
bool setAccelRange16g() {
  const uint8_t address = 0x6B, ctrl_reg6_xl = 0x20, value = 0x68;
  Wire1.beginTransmission(address);
  Wire1.write(ctrl_reg6_xl);
  Wire1.write(value);
  if (Wire1.endTransmission() != 0) return false;
  delay(20);  // let the new full scale settle
  Wire1.beginTransmission(address);
  Wire1.write(ctrl_reg6_xl);
  if (Wire1.endTransmission(false) != 0 || Wire1.requestFrom(address, (uint8_t)1) != 1)
    return false;
  return Wire1.read() == value;
}

bool readAccelG(float& x, float& y, float& z) {
  if (!IMU.readAcceleration(x, y, z)) return false;
  x *= accel_scale; y *= accel_scale; z *= accel_scale;
  return std::isfinite(x) && std::isfinite(y) && std::isfinite(z);
}

// Estimate constant gyro bias only from a quiet startup window. If the board
// moves or samples are invalid, keep zero bias and report that calibration failed.
void calibrateGyroscope() {
  Serial.println("Keep IMU still for gyro calibration (about 2 seconds).");
  const unsigned long started = millis();
  const int target = 240;
  int count = 0;
  float sum[3] = {}, sum2[3] = {};
  int resets = 0;
  float rejected_a2 = NAN;  // |a|^2 in g^2 of the last rejected sample
  while (count < target && millis() - started < 5000) {
    if (!(IMU.accelerationAvailable() && IMU.gyroscopeAvailable())) {
      delay(1);
      continue;
    }
    float ax = NAN, ay = NAN, az = NAN, g[3] = {NAN, NAN, NAN};
    bool good = readAccelG(ax, ay, az)
             && IMU.readGyroscope(g[0], g[1], g[2]);
    const float a2 = ax*ax + ay*ay + az*az;
    good = good && std::isfinite(a2) && fabsf(a2 - 1.0f) < 0.16f;
    // Only reject clear motion here: the zero-rate offset itself can reach
    // ±30 dps (datasheet); stillness is decided by the variance check below.
    for (int i = 0; i < 3; ++i)
      good = good && std::isfinite(g[i]) && fabsf(g[i]) < 30.0f;
    if (!good) {
      ++resets;
      rejected_a2 = a2;
      count = 0;
      for (int i = 0; i < 3; ++i) sum[i] = sum2[i] = 0;
      continue;
    }
    for (int i = 0; i < 3; ++i) { sum[i] += g[i]; sum2[i] += g[i]*g[i]; }
    ++count;
  }
  bool stable = count == target;
  if (stable) {
    for (int i = 0; i < 3; ++i) {
      const float mean = sum[i] / count;
      // Still-board noise at ±2000 dps measured 0.46-0.75 dps std (Tracker 43),
      // so allow 1 dps std; hand-held tremor is several dps.
      stable = stable && sum2[i] / count - mean*mean < 1.0f;
    }
  }
  if (stable) {
    for (int i = 0; i < 3; ++i) gyro_bias_dps[i] = sum[i] / count;
    Serial.print("Gyro bias (dps): ");
    for (int i = 0; i < 3; ++i) { Serial.print(gyro_bias_dps[i], 5); Serial.print(' '); }
    Serial.println();
  } else {
    Serial.print("Gyro calibration skipped: restart with the board still. samples ");
    Serial.print(count); Serial.print('/'); Serial.print(target);
    Serial.print(", resets "); Serial.print(resets);
    Serial.print(", last rejected |a|^2 "); Serial.print(rejected_a2, 3);
    if (count > 0) {
      Serial.print(", mean/variance (dps, dps^2):");
      for (int i = 0; i < 3; ++i) {
        const float mean = sum[i] / count;
        Serial.print(' '); Serial.print(mean, 3); Serial.print('/');
        Serial.print(sum2[i] / count - mean*mean, 4);
      }
    }
    Serial.println();
  }
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
