# 新板韌體移植規格（尚未實作）

現行來源：專案 `src/skeleton/tracker_firmware/tracker_firmware.ino`，後端 `src/net/ble.rs` 與 `src/net/protocol.rs`。現行 Nano 韌體不能直接燒入 ESP32-C3。本次沒有更動運作中的軟體與 Nano 韌體。

| ESP32-C3 GPIO | 模組焊盤 | 用途 |
|---:|---:|---|
| 0 | 12 | BAT_ADC，100k／100k，100nF |
| 2 | 5 | 上拉的啟動腳，保留 |
| 3 | 6 | BMI270 INT1 |
| 4 | 18 | I²C SDA |
| 5 | 19 | I²C SCL |
| 7 | 21 | BQ24075 PGOOD，低有效 |
| 8 | 22 | 上拉的啟動腳，保留 |
| 9 | 23 | BOOT，10k 上拉，TP5 |
| 10 | 16 | 狀態 LED，高有效 |
| 20 | 30 | UART RX，TP3 |
| 21 | 31 | UART TX，TP4 |
| EN（非 GPIO） | 8 | 10k／1µF 上電 RC，TP6 |

I²C 初始以 400 kHz、兩個 4.7k 上拉測試。BMI270 SDO 接地（預期 0x68），CSB 接 3V3，停用 secondary interface，未使用腳維持資料表要求。啟動需確認 CHIP_ID、載入 Bosch 初始化設定，量程先測 ±16g／±2000dps；不得使用原 LSM9DS1 的 119Hz、靈敏度修正及固定 X 軸反相。

QMC5883P 與 QMC5883L 的 I²C 位址、寄存器及量程不同。以本地 `sources/qmc5883p.pdf` Rev E 實作，確認 ID、資料狀態、溢位、輸出單位與軸向，不能套用 L 版驅動。先量測加速度／角速度與磁場對同一板座標的旋轉，再輸入 Fusion。每顆保存獨立磁校正及追蹤器 ID。

保留裝置名 `Aetherpose Tracker <ID>`、服務 `19B10000-E8F2-537E-4F6C-D104768A1214`、資料 `19B10001-E8F2-537E-4F6C-D104768A1214`、同步 `19B10002-E8F2-537E-4F6C-D104768A1214`。可評估 ESP-IDF NimBLE；使用時鎖定 SDK 及驅動版本並實際編譯，不以選型文件宣稱已移植完成。

資料為原專案 61-byte v2 payload：0x04、ID、uint16 sequence、gyro[3] rad/s、accel[3] m/s²、電量 uint8、mag[3] µT、dt float、quat[x,y,z,w]。保留 little-endian float32。外框是 AA 55、單 byte 長度、payload、payload 的 CRC16-CCITT-FALSE little-endian，合計 66 bytes。通知需要 ATT MTU ≥69；目標可請求更大的 MTU，但若協商不足就不得發送截斷封包。後端目前按完整封包解析，未實作新板分片協定。

同步 characteristic 的 16-byte 寫入是 float32 `[x,y,z,w]`，驗證 finite 及 norm 後更新 Fusion 四元數。取樣與 BLE 發送應分離，使用實際 dt，目標 100Hz；不得把請求的連線間隔視為 Windows 已接受的間隔。先用一顆與後端比對資料，再測六顆。

電量每約 5 秒量測一次，以 ADC 校準 API、適當 attenuation 讀取約 0–2.1V，再乘二換算電池電壓。在無 USB 的低電量條件下先做低電量提醒與進入低功耗；3.3V LDO 輸入不足時輸出會下降，門檻需以電源實測決定，不能沿用原版 3.0V 耗盡假設。不得繞過電池保護。NTC／充電由硬體處理，PGOOD 僅表示輸入有效，不表示充滿。

先量測待機、100Hz BLE、斷線廣播與充電時電流，再用 250mAh 電池做完整放電紀錄。沒有測量前不提供續航小時數或等同 Nano 精度的承諾。
