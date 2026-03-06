#include <Arduino.h>
// 引入 Nano 33 BLE 內建 IMU 函式庫
// 請透過 Arduino IDE 函式庫管理員安裝 "Arduino_LSM9DS1"
#include <Arduino_LSM9DS1.h>
// [新增] 引入 ArduinoBLE 函式庫
#include <ArduinoBLE.h>

// --- 狀態指示燈設定 ---
// 使用內建 LED，如果您的開發板沒有或想用別的腳位，請修改此處
#define STATUS_LED_PIN LED_BUILTIN

// --- BLE 設定 ---
#define BLE_DEVICE_NAME "Aetherpose Tracker"
// 為您的服務和特徵定義唯一的 UUID (可以使用 uuidgen 等工具生成)
#define BLE_SERVICE_UUID "19B10000-E8F2-537E-4F6C-D104768A1214"
#define BLE_CHARACTERISTIC_UUID "19B10001-E8F2-537E-4F6C-D104768A1214"

// --- 電池電量讀取設定 ---
#define BATTERY_PIN A0 // 用於讀取電池電壓的類比腳位 (請根據您的接線修改)

// 電壓分壓電路設定 (Voltage Divider)
// (V_BATT) --- R1 --- (ADC_PIN) --- R2 --- (GND)
// 如果您沒有使用分壓電路，請勿直接連接高於 MCU 電壓的電池！
// 如果使用兩個相同電阻，電壓會減半。
#define VOLTAGE_DIVIDER_R1 100000.0f // R1 電阻值 (ohms)
#define VOLTAGE_DIVIDER_R2 100000.0f // R2 電阻值 (ohms)

// ADC 參考電壓與解析度
#define ADC_REFERENCE_VOLTAGE 3.3f // nRF52840 (Nano 33 BLE) 工作電壓為 3.3V
#define ADC_RESOLUTION 4095.0f     // nRF52840 支援 12-bit ADC (0-4095)
#define BATTERY_MAX_VOLTAGE 4.2f   // 充滿電的電壓 (LiPo)
#define BATTERY_MIN_VOLTAGE 3.0f   // 電量耗盡的電壓 (LiPo)

// 定義封包結構 (必須與 Rust 端 src/net/protocol.rs 的 FullDataPacket 一致)
// 總長度: 1 (Type) + 1 (ID) + 2 (Seq) + 16 (Quat) + 12 (Accel) + 1 (Batt) + 12 (Mag) = 45 bytes
// 使用 packed 屬性確保沒有 padding
struct __attribute__((packed)) FullDataPacket {
  uint8_t packet_type = 0x02;   // PACKET_TYPE_FULL (避免使用 type 關鍵字)
  uint8_t id = 1;        // Tracker ID
  uint16_t sequence = 0; // 序列號
  
  // 四元數 [x, y, z, w] (float = 4 bytes)
  float quat[4] = {0.0, 0.0, 0.0, 1.0}; 
  
  // 加速度 [x, y, z] (float = 4 bytes, 單位: m/s^2)
  float accel[3] = {0.0, 0.0, 0.0};
  
  // 電量百分比
  uint8_t batt = 100;
  
  // 磁力計 [x, y, z] (float = 4 bytes, 單位: uT)
  float mag[3] = {0.0, 0.0, 0.0};
};

// --- 自定義 Madgwick 濾波器實作 ---
// 解決官方函式庫將 q0-q3 設為 private 導致無法讀取的問題
class Madgwick {
public:
    float q0 = 1.0f, q1 = 0.0f, q2 = 0.0f, q3 = 0.0f; // 公開成員，方便存取
    float beta = 0.1f; // 演算法增益
    float invSampleFreq = 1.0f / 100.0f;

    void begin(float sampleFrequency) {
        invSampleFreq = 1.0f / sampleFrequency;
    }

    void update(float gx, float gy, float gz, float ax, float ay, float az, float mx, float my, float mz) {
        // 將 Gyro 單位從 deg/s 轉為 rad/s (LSM9DS1 輸出為 deg/s)
        gx *= 0.0174533f; gy *= 0.0174533f; gz *= 0.0174533f;
        
        float recipNorm;
        float s0, s1, s2, s3;
        float qDot1, qDot2, qDot3, qDot4;
        float hx, hy;
        float _2q0mx, _2q0my, _2q0mz, _2q1mx, _2bx, _2bz, _4bx, _4bz, _2q0, _2q1, _2q2, _2q3, _2q0q2, _2q2q3, q0q0, q0q1, q0q2, q0q3, q1q1, q1q2, q1q3, q2q2, q2q3, q3q3;

        // Rate of change of quaternion from gyroscope
        qDot1 = 0.5f * (-q1 * gx - q2 * gy - q3 * gz);
        qDot2 = 0.5f * (q0 * gx + q2 * gz - q3 * gy);
        qDot3 = 0.5f * (q0 * gy - q1 * gz + q3 * gx);
        qDot4 = 0.5f * (q0 * gz + q1 * gy - q2 * gx);

        // Compute feedback only if accelerometer measurement valid
        if(!((ax == 0.0f) && (ay == 0.0f) && (az == 0.0f))) {
            // Normalise accelerometer measurement
            recipNorm = 1.0f / sqrtf(ax * ax + ay * ay + az * az);
            ax *= recipNorm; ay *= recipNorm; az *= recipNorm;

            // Normalise magnetometer measurement
            recipNorm = 1.0f / sqrtf(mx * mx + my * my + mz * mz);
            mx *= recipNorm; my *= recipNorm; mz *= recipNorm;

            // Auxiliary variables
            _2q0mx = 2.0f * q0 * mx; _2q0my = 2.0f * q0 * my; _2q0mz = 2.0f * q0 * mz; _2q1mx = 2.0f * q1 * mx;
            _2q0 = 2.0f * q0; _2q1 = 2.0f * q1; _2q2 = 2.0f * q2; _2q3 = 2.0f * q3;
            _2q0q2 = 2.0f * q0 * q2; _2q2q3 = 2.0f * q2 * q3;
            q0q0 = q0 * q0; q0q1 = q0 * q1; q0q2 = q0 * q2; q0q3 = q0 * q3;
            q1q1 = q1 * q1; q1q2 = q1 * q2; q1q3 = q1 * q3;
            q2q2 = q2 * q2; q2q3 = q2 * q3; q3q3 = q3 * q3;

            // Reference direction of Earth's magnetic field
            hx = mx * q0q0 - _2q0my * q3 + _2q0mz * q2 + mx * q1q1 + _2q1 * my * q2 + _2q1 * mz * q3 - mx * q2q2 - mx * q3q3;
            hy = _2q0mx * q3 + my * q0q0 - _2q0mz * q1 + _2q1mx * q2 - my * q1q1 + my * q2q2 + _2q2 * mz * q3 - my * q3q3;
            _2bx = sqrtf(hx * hx + hy * hy);
            _2bz = -_2q0mx * q2 + _2q0my * q1 + mz * q0q0 + _2q1mx * q3 - mz * q1q1 + _2q2 * my * q3 - mz * q2q2 + mz * q3q3;
            _4bx = 2.0f * _2bx; _4bz = 2.0f * _2bz;

            // Gradient decent algorithm corrective step
            s0 = -_2q2 * (2.0f * q1q3 - _2q0q2 - ax) + _2q1 * (2.0f * q0q1 + _2q2q3 - ay) - _2bz * q2 * (_2bx * (0.5f - q2q2 - q3q3) + _2bz * (q1q3 - q0q2) - mx) + (-_2bx * q3 + _2bz * q1) * (_2bx * (q1q2 - q0q3) + _2bz * (q0q1 + q2q3) - my) + _2bx * q2 * (_2bx * (q0q2 + q1q3) + _2bz * (0.5f - q1q1 - q2q2) - mz);
            s1 = _2q3 * (2.0f * q1q3 - _2q0q2 - ax) + _2q0 * (2.0f * q0q1 + _2q2q3 - ay) - 4.0f * q1 * (1 - 2.0f * q1q1 - 2.0f * q2q2 - az) + _2bz * q3 * (_2bx * (0.5f - q2q2 - q3q3) + _2bz * (q1q3 - q0q2) - mx) + (_2bx * q2 + _2bz * q0) * (_2bx * (q1q2 - q0q3) + _2bz * (q0q1 + q2q3) - my) + (_2bx * q3 - _4bz * q1) * (_2bx * (q0q2 + q1q3) + _2bz * (0.5f - q1q1 - q2q2) - mz);
            s2 = -_2q0 * (2.0f * q1q3 - _2q0q2 - ax) + _2q3 * (2.0f * q0q1 + _2q2q3 - ay) - 4.0f * q2 * (1 - 2.0f * q1q1 - 2.0f * q2q2 - az) + (-_4bx * q2 - _2bz * q0) * (_2bx * (0.5f - q2q2 - q3q3) + _2bz * (q1q3 - q0q2) - mx) + (_2bx * q1 + _2bz * q3) * (_2bx * (q1q2 - q0q3) + _2bz * (q0q1 + q2q3) - my) + (_2bx * q0 - _4bz * q2) * (_2bx * (q0q2 + q1q3) + _2bz * (0.5f - q1q1 - q2q2) - mz);
            s3 = _2q1 * (2.0f * q1q3 - _2q0q2 - ax) + _2q2 * (2.0f * q0q1 + _2q2q3 - ay) + (-_4bx * q3 + _2bz * q1) * (_2bx * (0.5f - q2q2 - q3q3) + _2bz * (q1q3 - q0q2) - mx) + (-_2bx * q0 + _2bz * q2) * (_2bx * (q1q2 - q0q3) + _2bz * (q0q1 + q2q3) - my) + _2bx * q1 * (_2bx * (q0q2 + q1q3) + _2bz * (0.5f - q1q1 - q2q2) - mz);
            recipNorm = 1.0f / sqrtf(s0 * s0 + s1 * s1 + s2 * s2 + s3 * s3);
            s0 *= recipNorm; s1 *= recipNorm; s2 *= recipNorm; s3 *= recipNorm;

            // Apply feedback step
            qDot1 -= beta * s0; qDot2 -= beta * s1; qDot3 -= beta * s2; qDot4 -= beta * s3;
        }

        // Integrate rate of change
        q0 += qDot1 * invSampleFreq;
        q1 += qDot2 * invSampleFreq;
        q2 += qDot3 * invSampleFreq;
        q3 += qDot4 * invSampleFreq;

        // Normalise quaternion
        recipNorm = 1.0f / sqrtf(q0 * q0 + q1 * q1 + q2 * q2 + q3 * q3);
        q0 *= recipNorm; q1 *= recipNorm; q2 *= recipNorm; q3 *= recipNorm;
    }
};

// 建立 Madgwick 濾波器物件
Madgwick filter;
// [新增] 建立 BLE 服務和特徵
BLEService aetherposeService(BLE_SERVICE_UUID);
// 建立一個特徵來發送我們的數據封包
// 屬性: READ (可讀), NOTIFY (可訂閱通知)
// 大小: FullDataPacket 的大小
// 擴充特徵大小以容納 framed 格式 (magic(2) + len(1) + payload + crc16(2))
BLECharacteristic dataCharacteristic(BLE_CHARACTERISTIC_UUID, BLERead | BLENotify, sizeof(FullDataPacket) + 5);

FullDataPacket packet;
unsigned long last_send_time = 0;
unsigned long last_battery_read_time = 0;
unsigned long last_led_blink_time = 0;     // LED 狀態計時器
const int SEND_INTERVAL_MS = 10; // 100Hz (數據更新率)
const int BATTERY_READ_INTERVAL_MS = 5000; // 每 5 秒讀取一次電量
const int LED_BLINK_INTERVAL_MS = 1000;    // 每 1 秒閃爍一次

uint8_t getBatteryPercentage(); // 函式原型宣告
void updateSensorData(); // 函式原型宣告

void setup() {
  // 設定 LED 腳位為輸出模式
  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, HIGH); // 開機時點亮 LED，表示正在初始化

  // 設定電池讀取腳位為輸入模式
  pinMode(BATTERY_PIN, INPUT);

  // [重要] 為 nRF52840 設定 12-bit ADC 解析度 (預設可能為 10-bit)
  analogReadResolution(12);

  // 啟動序列埠通訊 (用於除錯輸出)
  Serial.begin(115200);
  
  // 等待序列埠連接 (最多 3 秒)，方便查看除錯訊息
  unsigned long start = millis();
  while (!Serial && millis() - start < 3000);

  Serial.println("nRF52840 Tracker System Starting...");
  
  // 初始化內建 IMU (LSM9DS1)
  Serial.println("Initializing internal IMU (LSM9DS1)...");
  if (!IMU.begin()) {
    Serial.println("Failed to initialize IMU!");
    while (1) {
      digitalWrite(STATUS_LED_PIN, HIGH);
      delay(100);
      digitalWrite(STATUS_LED_PIN, LOW);
      delay(100);
    }
  }
  Serial.println("IMU initialized!");
  
  // 初始化 Madgwick 濾波器 (LSM9DS1 預設採樣率約為 119Hz)
  filter.begin(119);

  // 進行一次初始的電量讀取
  packet.batt = getBatteryPercentage();

  // [新增] 初始化藍牙
  Serial.println("Initializing Bluetooth...");
  if (!BLE.begin()) {
    Serial.println("Starting BLE failed!");
    // 快速閃爍 LED 表示 BLE 錯誤
    while (1) {
      digitalWrite(STATUS_LED_PIN, HIGH); delay(50);
      digitalWrite(STATUS_LED_PIN, LOW); delay(50);
    }
  }

  // 設定 BLE 廣播的名稱
  BLE.setLocalName(BLE_DEVICE_NAME);
  // 設定要廣播的服務
  BLE.setAdvertisedService(aetherposeService);
  // 將特徵加入服務中
  aetherposeService.addCharacteristic(dataCharacteristic);
  // 將服務加入 BLE 核心
  BLE.addService(aetherposeService);
  // 開始廣播
  BLE.advertise();
  Serial.println("Bluetooth advertising started.");

  digitalWrite(STATUS_LED_PIN, LOW); // 初始化完成，熄滅 LED，準備等待連線
}

void loop() {
  // 監聽 BLE 連線請求
  BLEDevice central = BLE.central();

  // 如果有中央設備連線
  if (central) {
    if (Serial) {
      Serial.print("Connected to central: ");
      Serial.println(central.address());
    }
    digitalWrite(STATUS_LED_PIN, HIGH); // LED 恆亮表示已連線

    // 當連線保持時
    while (central.connected()) {
      // 每隔一段時間更新一次電池電量
      if (millis() - last_battery_read_time >= BATTERY_READ_INTERVAL_MS) {
        last_battery_read_time = millis();
        packet.batt = getBatteryPercentage();
      }

      // 讀取感測器並更新濾波器
      updateSensorData();

      // 每隔 SEND_INTERVAL_MS 毫秒發送一次數據
      if (millis() - last_send_time >= SEND_INTERVAL_MS) {
        last_send_time = millis();
        packet.sequence++;
        // 組裝 framed 封包並發送
        const uint8_t MAGIC_LO = 0xAA;
        const uint8_t MAGIC_HI = 0x55;
        const uint8_t payload_len = sizeof(packet);
        uint8_t frame[sizeof(FullDataPacket) + 5];
        frame[0] = MAGIC_LO;
        frame[1] = MAGIC_HI;
        frame[2] = payload_len;
        memcpy(frame + 3, (uint8_t*)&packet, payload_len);

        // 計算 CRC16-CCITT (false)
        auto crc16_ccitt_false = [](const uint8_t* data, size_t len) -> uint16_t {
          uint16_t crc = 0xFFFF;
          for (size_t i = 0; i < len; ++i) {
            crc ^= (uint16_t)data[i] << 8;
            for (uint8_t b = 0; b < 8; ++b) {
              if (crc & 0x8000) crc = (crc << 1) ^ 0x1021;
              else crc <<= 1;
            }
          }
          return crc;
        };

        uint16_t crc = crc16_ccitt_false(frame + 3, payload_len);
        frame[3 + payload_len] = (uint8_t)(crc & 0xFF);
        frame[4 + payload_len] = (uint8_t)((crc >> 8) & 0xFF);

        // 發送 framed 通知
        dataCharacteristic.writeValue(frame, 5 + payload_len);
      }
    }

    // 當連線斷開時
    if (Serial) {
      Serial.print("Disconnected from central: ");
      Serial.println(central.address());
    }
    digitalWrite(STATUS_LED_PIN, LOW); // LED 熄滅表示已斷線
  }
  // 如果沒有連線，LED 會呈現呼吸燈效果
  else {
    // 讓 LED 呈現呼吸燈效果，表示正在等待連線
    float breath = (exp(sin(millis()/2000.0*PI)) - 0.36787944)*108.0;
    analogWrite(STATUS_LED_PIN, breath);
  }
}

// 讀取 IMU 數據並更新 Madgwick 濾波器
void updateSensorData() {
  float ax, ay, az;
  float gx, gy, gz;
  float mx, my, mz;

  // 檢查是否有新的數據可用
  if (IMU.accelerationAvailable() && IMU.gyroscopeAvailable() && IMU.magneticFieldAvailable()) {
    IMU.readAcceleration(ax, ay, az);
    IMU.readGyroscope(gx, gy, gz);
    IMU.readMagneticField(mx, my, mz);

    // 更新 Madgwick 濾波器
    // 注意：Madgwick 函式庫通常預期 Gyro 單位為 deg/s (Arduino_LSM9DS1 也是輸出 deg/s)
    filter.update(gx, gy, gz, ax, ay, az, mx, my, mz);

    // 1. 更新四元數 (x, y, z, w) - [修正]
    // Madgwick 函式庫的公開變數為 q0, q1, q2, q3，對應 (w, x, y, z)
    // 但我們的封包定義是 [x, y, z, w]，需要重新對應
    packet.quat[0] = filter.q1; // x
    packet.quat[1] = filter.q2; // y
    packet.quat[2] = filter.q3; // z
    packet.quat[3] = filter.q0; // w

    // 2. 更新加速度 (單位: g -> m/s^2)
    packet.accel[0] = ax * 9.81f;
    packet.accel[1] = ay * 9.81f;
    packet.accel[2] = az * 9.81f;

    // 3. 更新磁力計 (單位: uT)
    packet.mag[0] = mx;
    packet.mag[1] = my;
    packet.mag[2] = mz;
  }
}
// 函式：讀取電池電壓並轉換為百分比
uint8_t getBatteryPercentage() {
  // 1. 讀取類比腳位的原始值
  int rawValue = analogRead(BATTERY_PIN);

  // 2. 將原始值轉換為 ADC 腳位上的電壓
  float pinVoltage = rawValue * (ADC_REFERENCE_VOLTAGE / ADC_RESOLUTION);

  // 3. 根據分壓電路反推出實際電池電壓
  // V_pin = V_batt * R2 / (R1 + R2)  =>  V_batt = V_pin * (R1 + R2) / R2
  float batteryVoltage = pinVoltage * (VOLTAGE_DIVIDER_R1 + VOLTAGE_DIVIDER_R2) / VOLTAGE_DIVIDER_R2;

  // 4. 將電壓線性映射到百分比 (0-100)
  float percentage = 100.0 * (batteryVoltage - BATTERY_MIN_VOLTAGE) / (BATTERY_MAX_VOLTAGE - BATTERY_MIN_VOLTAGE);
  
  // 5. 使用 constrain 函式確保數值在 0 到 100 之間，並轉為 uint8_t
  return (uint8_t)constrain(percentage, 0, 100);
}