#include <Arduino.h>
#include <Arduino_LSM9DS1.h>
#include <ArduinoBLE.h>

#define STATUS_LED_PIN LED_BUILTIN

#define BLE_DEVICE_NAME "Aetherpose Tracker Switchable"
#define BLE_SERVICE_UUID "19B10000-E8F2-537E-4F6C-D104768A1214"
#define BLE_DATA_CHARACTERISTIC_UUID "19B10001-E8F2-537E-4F6C-D104768A1214"
#define BLE_MODE_CHARACTERISTIC_UUID "19B10002-E8F2-537E-4F6C-D104768A1214"

#define BATTERY_PIN A0
#define VOLTAGE_DIVIDER_R1 100000.0f
#define VOLTAGE_DIVIDER_R2 100000.0f
#define ADC_REFERENCE_VOLTAGE 3.3f
#define ADC_RESOLUTION 4095.0f
#define BATTERY_MAX_VOLTAGE 4.2f
#define BATTERY_MIN_VOLTAGE 3.0f

// Mode characteristic: 0 = 9-axis (with mag), 1 = 6-axis (no mag)
enum FusionMode : uint8_t {
  FUSION_MODE_9AXIS = 0,
  FUSION_MODE_6AXIS = 1,
};

// Packet type 0x03: raw IMU data for host-side EKF
// Layout (45 bytes, packed):
//   packet_type : uint8   (0x03)
//   id          : uint8
//   sequence    : uint16
//   gyro[3]     : float[3]  rad/s
//   accel[3]    : float[3]  m/s²
//   batt        : uint8
//   mag[3]      : float[3]  uT (zeros in 6-axis mode)
//   dt          : float     seconds
#define PACKET_TYPE_RAW_IMU 0x03

struct __attribute__((packed)) RawImuPacket {
  uint8_t packet_type = PACKET_TYPE_RAW_IMU;
  uint8_t id = 1;
  uint16_t sequence = 0;
  float gyro[3] = {0.0f, 0.0f, 0.0f};
  float accel[3] = {0.0f, 0.0f, 0.0f};
  uint8_t batt = 100;
  float mag[3] = {0.0f, 0.0f, 0.0f};
  float dt = 1.0f / 119.0f;
};

static_assert(sizeof(RawImuPacket) == 45, "Packet size mismatch");

BLEService aetherpose_service(BLE_SERVICE_UUID);
BLECharacteristic data_characteristic(
    BLE_DATA_CHARACTERISTIC_UUID,
    BLERead | BLENotify,
    sizeof(RawImuPacket) + 5);
BLEByteCharacteristic mode_characteristic(
    BLE_MODE_CHARACTERISTIC_UUID,
    BLERead | BLEWrite | BLENotify);

RawImuPacket packet;
FusionMode current_fusion_mode = FUSION_MODE_9AXIS;
unsigned long last_send_time = 0;
unsigned long last_battery_read_time = 0;
unsigned long last_imu_time = 0;

const int SEND_INTERVAL_MS = 10;
const int BATTERY_READ_INTERVAL_MS = 5000;

uint8_t getBatteryPercentage();
void updateSensorData();
void handleControlInputs();
void handleSerialCommands();
void handleBleModeWrites();
void setFusionMode(FusionMode mode);
const char* fusionModeName(FusionMode mode);

uint16_t crc16_ccitt_false(const uint8_t* data, size_t len) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < len; ++i) {
    crc ^= static_cast<uint16_t>(data[i]) << 8;
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : (crc << 1);
    }
  }
  return crc;
}

const char* fusionModeName(FusionMode mode) {
  return mode == FUSION_MODE_6AXIS ? "6-axis" : "9-axis";
}

void setFusionMode(FusionMode mode) {
  if (current_fusion_mode == mode) {
    mode_characteristic.writeValue(static_cast<uint8_t>(current_fusion_mode));
    return;
  }
  current_fusion_mode = mode;
  last_imu_time = 0;
  mode_characteristic.writeValue(static_cast<uint8_t>(current_fusion_mode));
  if (Serial) {
    Serial.print("Switched fusion mode to ");
    Serial.println(fusionModeName(current_fusion_mode));
  }
}

void setup() {
  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, HIGH);

  pinMode(BATTERY_PIN, INPUT);
  analogReadResolution(12);

  Serial.begin(115200);
  const unsigned long serial_wait_start = millis();
  while (!Serial && millis() - serial_wait_start < 3000) {}

  Serial.println("Aetherpose Tracker Switchable (raw IMU) starting...");

  if (!IMU.begin()) {
    Serial.println("Failed to initialize IMU.");
    while (true) {
      digitalWrite(STATUS_LED_PIN, HIGH); delay(100);
      digitalWrite(STATUS_LED_PIN, LOW);  delay(100);
    }
  }

  packet.batt = getBatteryPercentage();

  if (!BLE.begin()) {
    Serial.println("Failed to initialize BLE.");
    while (true) {
      digitalWrite(STATUS_LED_PIN, HIGH); delay(50);
      digitalWrite(STATUS_LED_PIN, LOW);  delay(50);
    }
  }

  mode_characteristic.writeValue(static_cast<uint8_t>(current_fusion_mode));

  BLE.setLocalName(BLE_DEVICE_NAME);
  BLE.setAdvertisedService(aetherpose_service);
  aetherpose_service.addCharacteristic(data_characteristic);
  aetherpose_service.addCharacteristic(mode_characteristic);
  BLE.addService(aetherpose_service);
  BLE.setConnectionInterval(6, 12);
  BLE.advertise();

  Serial.print("Default fusion mode: ");
  Serial.println(fusionModeName(current_fusion_mode));
  Serial.println("BLE advertising started.");
  digitalWrite(STATUS_LED_PIN, LOW);
}

void loop() {
  BLE.poll();
  handleControlInputs();

  BLEDevice central = BLE.central();
  if (central) {
    if (Serial) {
      Serial.print("Connected to central: ");
      Serial.println(central.address());
    }
    digitalWrite(STATUS_LED_PIN, HIGH);

    while (central.connected()) {
      BLE.poll();
      handleControlInputs();

      if (millis() - last_battery_read_time >= BATTERY_READ_INTERVAL_MS) {
        last_battery_read_time = millis();
        packet.batt = getBatteryPercentage();
      }

      updateSensorData();

      if (millis() - last_send_time >= SEND_INTERVAL_MS) {
        last_send_time = millis();
        packet.sequence++;

        const uint8_t payload_len = sizeof(packet);
        uint8_t frame[sizeof(RawImuPacket) + 5];
        frame[0] = 0xAA;
        frame[1] = 0x55;
        frame[2] = payload_len;
        memcpy(frame + 3, reinterpret_cast<const uint8_t*>(&packet), payload_len);

        const uint16_t crc = crc16_ccitt_false(frame + 3, payload_len);
        frame[3 + payload_len] = static_cast<uint8_t>(crc & 0xFF);
        frame[4 + payload_len] = static_cast<uint8_t>((crc >> 8) & 0xFF);

        data_characteristic.writeValue(frame, 5 + payload_len);
      }
    }

    if (Serial) {
      Serial.print("Disconnected from central: ");
      Serial.println(central.address());
    }
    digitalWrite(STATUS_LED_PIN, LOW);
  } else {
    const float breath = (exp(sinf(millis() / 2000.0f * PI)) - 0.36787944f) * 108.0f;
    analogWrite(STATUS_LED_PIN, breath);
  }
}

void handleControlInputs() {
  handleSerialCommands();
  handleBleModeWrites();
}

void handleSerialCommands() {
  while (Serial && Serial.available() > 0) {
    const char command = static_cast<char>(Serial.read());
    if (command == '6') {
      setFusionMode(FUSION_MODE_6AXIS);
    } else if (command == '9') {
      setFusionMode(FUSION_MODE_9AXIS);
    } else if (command == 'm' || command == 'M') {
      Serial.print("Current mode: ");
      Serial.println(fusionModeName(current_fusion_mode));
    }
  }
}

void handleBleModeWrites() {
  if (!mode_characteristic.written()) return;
  const uint8_t raw_value = mode_characteristic.value();
  setFusionMode(raw_value == static_cast<uint8_t>(FUSION_MODE_9AXIS)
                    ? FUSION_MODE_9AXIS
                    : FUSION_MODE_6AXIS);
}

void updateSensorData() {
  if (!(IMU.accelerationAvailable() && IMU.gyroscopeAvailable())) {
    return;
  }

  float ax, ay, az;
  float gx, gy, gz;

  IMU.readAcceleration(ax, ay, az);
  IMU.readGyroscope(gx, gy, gz);

  const unsigned long now = micros();
  float dt = (last_imu_time == 0) ? (1.0f / 119.0f) : ((now - last_imu_time) / 1000000.0f);
  last_imu_time = now;
  dt = constrain(dt, 0.001f, 0.05f);

  packet.gyro[0] = gx * DEG_TO_RAD;
  packet.gyro[1] = gy * DEG_TO_RAD;
  packet.gyro[2] = gz * DEG_TO_RAD;

  packet.accel[0] = ax * 9.81f;
  packet.accel[1] = ay * 9.81f;
  packet.accel[2] = az * 9.81f;

  if (current_fusion_mode == FUSION_MODE_9AXIS && IMU.magneticFieldAvailable()) {
    float mx, my, mz;
    IMU.readMagneticField(mx, my, mz);
    packet.mag[0] = mx;
    packet.mag[1] = my;
    packet.mag[2] = mz;
  } else {
    packet.mag[0] = 0.0f;
    packet.mag[1] = 0.0f;
    packet.mag[2] = 0.0f;
  }

  packet.dt = dt;
}

uint8_t getBatteryPercentage() {
  const int raw_value = analogRead(BATTERY_PIN);
  const float pin_voltage = raw_value * (ADC_REFERENCE_VOLTAGE / ADC_RESOLUTION);
  const float battery_voltage =
      pin_voltage * (VOLTAGE_DIVIDER_R1 + VOLTAGE_DIVIDER_R2) / VOLTAGE_DIVIDER_R2;
  const float percentage =
      100.0f * (battery_voltage - BATTERY_MIN_VOLTAGE) / (BATTERY_MAX_VOLTAGE - BATTERY_MIN_VOLTAGE);
  return static_cast<uint8_t>(constrain(percentage, 0.0f, 100.0f));
}
