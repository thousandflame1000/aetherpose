# Aetherpose 可穿戴追蹤器底板 v0.1

> **2026-10-18 方案停用：使用者已明確要求降低成本、以自製追蹤器取代 Nano 33 BLE。** 本目錄既有 `aetherpose_carrier.kicad_pcb`、`bom.csv` 與預覽僅為舊底板草稿，不是新板設計或採購清單。新方向見 [自製追蹤器設計需求](custom-tracker/DESIGN.md)。

2026-10-18。已選方向：沿用 **Arduino Nano 33 BLE 原版 ABX00030／帶針 ABX00034（LSM9DS1）**，製作供電與固定底板；六個穿戴位置各用一套。

這是已佈線的 PCB 工程草稿。尚未經 KiCad 開檔／DRC、實物配合及打樣驗證，**不是已驗收的量產或直接下單資料**。沒有產生 Gerber，以免將未通過正式檢查的資料誤送製。

## 檔案

- `aetherpose_carrier.kicad_pcb`：KiCad 8 格式，內嵌自訂焊盤，60 × 50 mm、雙層、1.6 mm；無需外部封裝庫即可檢視 PCB。沒有附原理圖同步工程。
- `pcb-preview.svg`：頂視圖，紅色頂層、藍色底層；虛線為 Nano 暫定外形。
- `build_carrier.py`：產生 PCB 與預覽的來源。
- `layout.json`、`check_layout.py`、`verification.txt`：幾何及連通性檢查資料與結果；不能取代 KiCad DRC。
- `bom.csv`：每套與六套用量；外接模組、開關、電池亦列出。

## 已對照專案的功能

來源：`../README.md`、`../HANDOFF.md`、`../src/skeleton/tracker_firmware/tracker_firmware.ino`。

追蹤器供六個部位（頭、胸、左右前臂、左右小腿）使用。現行韌體透過 ArduinoBLE 傳送方向、加速度、陀螺儀、磁力計及電量，傳送間隔 10 ms，IMU 設定 119 Hz。3D、TransPose、遊戲、Combat 由電腦執行，底板不需增加處理器。

不把 Nano 33 BLE Rev2 或 Sense Rev2 視為免改韌體替代品；其感測器必須另行核對。追蹤器 ID 仍由 MAC 末位推得，六顆組裝後要確認 ID 沒有碰撞；末位不是唯一性保證。

## 電路連線（本文件為接線依據）

```text
受保護 1S LiPo ──> 外接充電／升壓模組 BAT（電池插座）
模組 USB         <── 充電線
模組 5V 輸出     ──> J1.1 ── J2.1 ──[SW1 第一極]── J2.2 ──> Nano VIN
模組 BAT 量測點  ──> J1.2 ── J2.3 ──[SW1 第二極]── J2.4 ──> R1 100k ──┬──> Nano A0
模組 GND         ──> J1.3 ──> Nano GND / R2 / C1                      │
                                                                      R2 100k
                                                                      │
                                                                     GND
Nano A0 ── C1 100nF ── GND
```

SW1 是外接 **DPST ON/OFF 雙極同步開關**，接通時 J2.1–2 與 J2.3–4 同時閉合；四條線連到 J2。也可用 DPDT ON/ON 開關，每極只接公共端與同一方向的接點，另一方向懸空作 OFF。不可把 J2.2–3 當一對短接。底板沒有內建充電晶片、USB 充電插座或升壓晶片。

J1 使用三芯線接外部模組的 **5V、BAT、GND**，不是把模組整排直接插到 J1。BAT 必須是電池實際電壓，不是 VS 或 5V。J1.2 不承擔負載供電。

100k / 100k 對應現行韌體設定。電池 4.2 V 時 A0 理論為 2.1 V，分壓電流 21 µA；C1 用於 ADC 濾波，等效 RC 時間常數 5 ms。電量為電壓線性估算，非精確剩餘容量。關機時雙極開關隔離 BAT，避免透過 A0 對未供電 Nano 注入電流。

## 外接電源模組與電池

可用 Adafruit PowerBoost 1000C 作參考：5V 升壓輸出接 J1.1、BAT 接 J1.2、GND 接 J1.3；電池接模組本身電池插座。其預設 1 A 充電，電池必須明確允許至少 1 A 充電，並具適當保護；初版可採容量約 2000 mAh 且資料表符合充放電規格的 1S 電池。不可直接替換成未核對充電電流的小容量穿戴電池。此模組未設計直接安裝封裝，放在外殼獨立隔艙，以線束連接；不是一片 PCB 全部整合。

若改用較小模組，先核對 5 V 穩壓輸出、電池保護、充電電流及實際接線。不要使用單純充電板直接供 VIN。供電走 VIN，不接 Nano 3V3 或 VUSB，不需切 Nano 焊橋。Nano 3.3 V I/O 不耐 5 V。

燒錄前關閉 SW1，再接 Nano USB；充電接電源模組 USB。開關只關追蹤器負載，不是電池總隔離開關；模組仍可能有待機耗電，長期收納需斷電池。初次充電及熱測在桌面進行。

## 機構與佈局

U1 使用兩條 1×15、2.54 mm 母座，排距 15.24 mm。PCB 自訂 U1 焊盤號遵照 ABX00030 資料表：1=D13、4=A0、14=GND、15=VIN；16=TX、19=GND、30=D12。**與常見 Nano 封裝編號不同，不可直接替換封裝！** 頂視 USB 朝左，VIN 在下排最左，D13 在下排最右。焊接前以實物絲印及官方 pinout 再核對。

四個 Ø3.2 mm 非金屬化固定孔位於 (4,4)、(56,4)、(4,46)、(56,46) mm。採尼龍螺絲與絕緣外殼，底板不直接接觸皮膚。尺寸尚未依使用者既有外殼核對。

右側 (43,14)–(55,25) mm 設上下層禁止走線／覆銅區，作暫定天線保留；不是廠商保證的 RF keepout。需依實際 Nano／NINA 模組天線位置擴大核對，電池、線束、金屬與人體遮蔽也要實測。電源模組與電池避開 IMU 及天線，不疊在感測器上，線束固定後重新做磁力計校正。

## 製板前與首件驗證

1. 用 KiCad 8 或更新版開啟 PCB，核對檔案解析、封裝、焊盤號、孔徑與 Nano 插座方向；按實物列印 1:1 紙樣。
2. 建立原理圖並與上述連線逐一對照；原理圖轉 PCB 時須保留這個自訂 U1 編號。補齊未使用接點的 no-connect 意圖。
3. 跑 KiCad DRC，處理所有短路、未連線、間距、孔邊與絲印問題；確認板廠規則後輸出 Gerber／鑽孔並用 Gerber viewer 複核。
4. 未插 Nano、未接電池時，量測電源無短路、開關兩極隔離、分壓值與接頭極性。用限流電源驗證模組與底板。
5. 插 Nano 後量測 VIN 約 5–5.2 V、A0 不超過 3.3 V；4.2 V 電池時 A0 約 2.1 V。驗證 OFF 時 VIN 及 A0 已放電、USB 燒錄、充電溫升及續航。
6. 六顆逐一確認 ID、BLE 封包、電量、三軸方向與磁校正，再同時穿戴驗證斷線率與實際更新率。沒有實測前不宣稱達到 100 Hz 或任何續航數字。

## 官方參考

- Arduino Nano 33 BLE：https://docs.arduino.cc/hardware/nano-33-ble/
- ABX00030 pinout：https://docs.arduino.cc/resources/pinouts/ABX00030-full-pinout.pdf
- ABX00030 datasheet：https://docs.arduino.cc/resources/datasheets/ABX00030-datasheet.pdf
- PowerBoost 1000C：https://learn.adafruit.com/adafruit-powerboost-1000c-load-share-usb-charge-boost

重建：在本目錄執行 `python build_carrier.py`，再執行 `python check_layout.py`。
