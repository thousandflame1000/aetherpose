# Aetherpose 低成本自製追蹤器

2026-10-18。下文保留最初選型需求；目前已依「由設計端抓預算、先做六顆」的指示產生 **ESP32-C3-MINI-1-H4X + BMI270 + QMC5883P** 的新板工程草稿。當前方案、成本與檔案狀態以 [README.md](README.md) 為準，下面 nRF52832／BMM350 等屬先前候選，不是現行 BOM。

## 目標

以新 PCB 取代 Arduino Nano 33 BLE 整塊開發板，降低每顆追蹤器的總成本。MCU／BLE、慣性感測器、電池供電與充電均整合到自製板。不沿用 Nano 插座底板，也不沿用外接 PowerBoost 1000C 的高成本方案。

暫以六顆功能樣品評估；單顆預算、製作數量、電池／外殼是否包含在預算中仍待使用者提供。成本必須分為裸板電子料、PCB、SMT組裝、電池／外殼與一次性治具／開發費；小量自製不保證總價低於現成板。

## 候選架構

| 區塊 | 優先評估 | 備選與取捨 |
|---|---|---|
| MCU / BLE | nRF52832 512KB Flash / 64KB RAM 的可自行燒錄 RF 模組，例如 Ebyte E73-2G4M04S1B；須再核對實際料號記憶體、內部電源及天線規則 | ESP32-C3 模組；比較實際採購價格、BLE工作電流與電池需求後再定案 |
| 六軸 IMU | BMI270，三軸加速度＋三軸角速度 | 不直接假設可替換 LSM9DS1 的驅動、靈敏度與座標方向 |
| 磁力計 | 保留獨立三軸磁力計，BMM350 為候選 | 可規劃不裝料的六軸版本，但需承認航向漂移與磁校正功能差異，不以六軸冒稱同等九軸功能 |
| 電源 | 受保護 1S 鋰電池＋低靜態電流穩壓，無需先升到 5V 再降壓 | 穩壓電壓依最終 MCU／感測器供電範圍決定；3.3V LDO 須評估低電量 dropout 與可用容量 |
| 充電 | 板載 USB 5V 輸入＋可設定充電電流的 1S 充電 IC | 電源路徑須定義充電時是否運作，避免負載干擾充電終止；充電電流按電池規格設定 |
| 燒錄 | nRF 方案採 SWD 焊盤＋共用燒錄器 | nRF52832 無原生 USB，USB-C 充電口不能直接視為韌體上傳口；不必每顆增加 USB-UART |

目前優先比較 RF 模組方案以降低首版天線調校成本；它仍是自製追蹤器 PCB，不是 Arduino 開發板底板。只有總量與報價足以支持時，再評估裸 nRF 晶片、晶振、匹配與天線的版本。以上候選未取得相同數量下的完整報價，不宣稱任何確切省錢幅度。

## 與現行軟體的相容要求

- 保留 `Aetherpose Tracker` 裝置命名與三個 BLE UUID；對照專案根目錄的 `src/net/ble.rs`。
- 以專案 `src/net/protocol.rs` 與 `src/skeleton/tracker_firmware/tracker_firmware.ino` 為規格來源，保留 0x04、61-byte payload、既有外層框架、CRC16、端序與 quaternion 順序。
- 實際通知內容不只 61 bytes：現行韌體增加 5-byte 外框。因此 BLE ATT MTU 必須足以承載完整 66-byte 通知（至少 69），或先實作並驗證收送雙方的分片協定，不能依賴預設 20-byte 通知。
- 保留同步／控制 characteristic 的現有語意；先核對指令，再決定是否需要修改後端。
- 目標為六顆各自約 100 Hz 傳送；感測器採樣頻率可不同，但必須用真實時間戳與 dt，不能套用舊 119 Hz 常數。
- 新 MCU、IMU 與 ADC 需要移植韌體；不能把原本 ArduinoBLE／Arduino_LSM9DS1 程式直接燒入。Fusion AHRS 可評估沿用，需做資源與效能量測。
- 移除 LSM9DS1 專屬暫存器設定與倍率修正。新感測器採 datasheet 單位、量程與軸向轉換，驗證 g、rad/s、µT 及座標系。
- 電池 ADC 依 MCU 參考電壓、分壓與採樣時間重新設計。舊版 3.3V／12bit 設定不直接照搬。
- 追蹤器 ID 改為可配置且持久保存，檢查六顆 ID 唯一；不把 MAC 最後一個 byte 當唯一性保證。
- 新板磁力計校正值不能沿用原 Nano 板的校正表；校正工具及儲存方式一併更新。

## 電路設計前需鎖定的事項

先取得 MCU 模組、IMU／磁力計、電源 IC 的官方 pinout、reference schematic、land pattern 和供貨報價。再建立原理圖與精確 BOM，確定電源預算、接頭、開關、SWD、IMU 中斷、感測器匯流排與天線淨空區。未鎖定料號與封裝前不產生假定可生產的 PCB。

先組一套 MCU＋IMU 功能驗證平台，確認 BLE MTU、66-byte 通知、100Hz 目標、Fusion、六裝置同連與 Windows 後端相容，再做完整板。送製前需 ERC、DRC、Gerber 檢視與尺寸核對；首件驗證電源、充電、量測、無線及續航。

## 官方資料（查閱日期 2026-10-18）

- Nordic nRF52832：https://docs.nordicsemi.com/r/bundle/ps_nrf52832/page/nrf52832_ps.html
- Ebyte E73-2G4M04S1B：https://www.cdebyte.com/products/E73-2G4M04S1B/2
- Bosch BMI270：https://www.bosch-sensortec.com/en/products/motion-sensors/imus/bmi270
- Bosch 感測器驅動：https://www.bosch-sensortec.com/en/software-tools/software/drivers
- ESP32-C3-MINI-1：https://documentation.espressif.com/esp32-c3-mini-1_datasheet_en.html
