# Aetherpose 自製追蹤器 v0.1

2026-10-18。使用者已授權由設計端選型及抓預算，先以 **6 顆**樣品規劃。這是取代 Nano 33 BLE 的新電路，板上整合 MCU／BLE、九軸感測、充電、穩壓與電量量測。

**工程審閱草稿，尚未完成 KiCad 開檔／ERC／DRC、實際焊接、韌體移植及穿戴驗證。不可直接當作可下單的完成品。** `verification.json` 只記錄獨立幾何與連通性檢查，不是 KiCad 認證。未輸出 Gerber，避免未經審核資料被誤送製。

## 選定的第一版

| 功能 | 元件／設計 | 理由與限制 |
|---|---|---|
| MCU、BLE | Espressif ESP32-C3-MINI-1-H4X | 使用原廠 RF 模組，省去裸晶天線調校；取消 Arduino 開發板。首版僅用 BLE，不啟動 Wi-Fi；仍需實測耗電及六顆同連 |
| 加速度、陀螺儀 | Bosch BMI270 | 六軸，移植感測器驅動與 Fusion，不使用 LSM9DS1 的修正倍率 |
| 磁力計 | QST QMC5883P | 保留三軸磁場輸入；採 3×3 mm LGA，避免首版增加更小 WLCSP 的組裝難度。不是 QMC5883L，驅動不可混用 |
| 充電與電源路徑 | TI BQ24075RGTR | 板載充電與負載分流；100 mA USB 輸入限制，約 100 mA 充電設定 |
| 3.3 V | TI TLV75533PDBVR | 500 mA LDO；無升壓電感。低電量可用容量會受 dropout 限制，續航待量測 |
| 電池 | 受保護 1S、4.2 V 滿充、約 250 mAh | 電池須允許至少 110 mA 充電並有 10kΩ 103AT-2 曲線 NTC，或將等效外部 NTC 貼附於電池；不可用 4.35 V 化學體系代換 |
| 充電口 | USB-C，兩個 5.1kΩ CC 下拉 | 僅作 5 V 充電，資料腳未接，沒有 PD／快充 |
| 燒錄 | 六個 UART pogo 焊盤 | 六顆共用 3.3 V USB-UART／治具；沒有每板 USB-UART IC |
| 電源開關 | C&K JS202011CQN DPDT | 同步切換 LDO EN 與電池分壓來源，關機不從 A0 注入電流 |

板框 **45 × 48 mm、雙層、暫定 1.6 mm**；天線向上超出板框約 5.3 mm，因此外殼內部長度至少還要包含突出天線與機構間隙。無穿戴固定孔，採絕緣外殼卡槽固定。此版是功能打樣尺寸，尚未做最小化。

## 開啟與檔案

- `aetherpose_custom.kicad_pro`：最小專案設定，預設線寬 0.2 mm、間距 0.15 mm；需在實際 KiCad 載入時核對規則與板廠能力。
- `aetherpose_custom.kicad_sch`：KiCad 8 原生原理圖，符號內嵌，不依賴外部符號庫。符號採逐腳方塊表達，各接點有網名或 no-connect；所有腳位目前是 passive ERC 類型，所以 ERC 不會替你檢查電源輸出衝突。
- `aetherpose_custom.kicad_pcb`：新板 PCB，精確佈線狀態以 `verification.json` 與板內連線檢視為準；不是先前的 Nano 底板。
- `pcb-preview.svg`／`pcb-preview.png`：從實際路由資料產生的工程預覽，紅色上層、藍色下層。
- `schematic-preview.svg`／`schematic-preview.png`：同一腳位模型的原理圖預覽；不是 KiCad 實際 render，仍須用 KiCad 開檔複核。
- `bom.csv`：44 個板上位置的用量、料號與成本欄。前三個主要 IC 是參考單價，其餘多數為設計預留價，**不是完整已報價的採購單**。
- `pin-netlist.csv`：逐腳網表；`design.json` 是原理圖、PCB 與網表共用來源。
- `COST.md`：成本拆分與小量預算，電池／外殼不混在電子料單價內。
- `FIRMWARE.md`：GPIO、驅動、ADC、BLE 與軸向移植要求；尚未交付可燒錄的自製板韌體。
- `Aetherpose.pretty/`、`fp-lib-table`：隨附 KiCad／Espressif 上游封裝；來源見 `sources/upstream-manifest.json`。

上層 `../bom.csv`、`../aetherpose_carrier.kicad_pcb` 是停用的 Nano 插座底板，請勿採購或混用。

## 電源與充電設計

USB VBUS → BQ24075 IN；BAT → 電池；OUT → VSYS → TLV75533 → 3V3。BQ 的電源路徑可將負載電流與充電分開，避免用一般充電 IC 直接帶負載而影響終止判斷。

第一版 EN1、EN2 固定接地，採 **USB100 模式**。ILIM 以 3.24kΩ 接地，但不使用外部 ILIM 模式，不能按此阻值宣稱輸入 500 mA。ISET 8.87kΩ，按 890 AΩ 典型係數計約 100 mA，元件誤差下可接近 110 mA；輸入限制、負載及溫度可能使實際充電更低。

TMR 懸空保留原廠約 5 小時安全計時；250 mAh 為此設定的初版容量目標。若換成 500 mAh 或更大電池，需重新評估計時設定，不可只替換電池。NTC 開路時應停止充電；首件需用加熱／冷卻與開路測試驗證。無 NTC 的二線電池不可直接插上三線接頭後宣稱已完成溫度監測。

BQ24075 在足夠高的輸入下可將 OUT 調至 5.5 V；本板只允許 **5 V USB（設計輸入上限 5.25 V）**，不能把其 6.6 V 工作額定當作本板輸入額定，TLV75533 的建議輸入上限為 5.5 V。沒有 PD 協商，不可接入自行改線的高壓來源。首版未加入獨立連接器 ESD／浪湧保護元件，需在硬體審閱決定量產保護規格。

SW1：2 是 LDO_EN 公共端，5 是 BAT_SENSE 公共端。2–3／5–6 接通為 ON；2–1／5–4 接通為 OFF。OFF 將 EN 與電池分壓來源接地；充電 IC 仍可為電池充電。開關不是電池總隔離，長期收納仍需拔電池。

R7／R8 是 100kΩ／100kΩ；4.2 V 電池時 BAT_ADC 約 2.1 V。C6 100nF 配合 50kΩ 等效來源，時間常數約 5 ms。ESP32 ADC 需以校準 API 讀電壓，不能使用 Nano 的 `3.3 / 4095` 常數。

## 接頭、燒錄與組裝

J2：**1=BAT+、2=電池 NTC、3=GND**。這是自訂三芯定義，不代表與任意市售三線電池相容；核對極性與 NTC 後才做線束。

TP1=GND、TP2=3V3 參考電壓（僅量測，不注入電源）、TP3=ESP RX、TP4=ESP TX、TP5=BOOT/GPIO9、TP6=CHIP_EN。USB-UART TX 接 TP3、RX 接 TP4，共地；治具先拉 BOOT 低，再以 EN 低→高重設，之後釋放 BOOT 進行 ROM UART 燒錄。正常啟動 BOOT 由 10kΩ 上拉。治具必須使用 3.3 V 邏輯，關機時拔除或三態 UART 訊號。

QMC5883P 需回焊，不以手焊驗證細間距底部焊盤。保留封裝方向與 1 腳標記；現有腳位圖已對照各 IC 資料表，但仍需獨立覆核 **land pattern**。通用 Bosch LGA／QFN 封裝的焊墊、熱焊盤與錫膏設計也須與實際供貨封裝確認，不能只看封裝名稱相似。

天線在板邊外，外殼、電池、線束及金屬不得包住它。磁力計中心設走線／覆銅保留區，量產需按 QST 佈局規則進一步檢查周圍材料與電流迴路。充電器、電池、線束固定後重新做磁力計校正。尚未宣稱與 Nano 同等精度、續航或穩定度。

## 驗證狀態與下一道檢查

已做：資料表腳位與電源設定查閱、以共同網表產生原理圖與 PCB、FreeRouting 單執行緒佈線，以及獨立 named-net 連通性／保守焊墊間距／板邊／保留區檢查（結果以 `verification.json` 為準）。交付草稿關閉了較耗時的 post-route 最佳化；後續以 KiCad 手動調整供電與回流為優先。

本版獨立檢查結果：**PASS，28 個網路、588 段走線、38 個過孔，保守銅間距最小約 0.1507 mm**。這些數字不代表 KiCad DRC 或硬體功能已通過。

仍需：KiCad 實際載入與 ERC／DRC、封裝及機構 1:1 對照、接頭及充電溫度審閱、回焊規格、電源完整性與接地回流審閱。首版走線以 0.2 mm 為主；供電／地線、熱焊盤與接地平面須在 KiCad 內按電流及 RF 要求優化，不能把自動佈線的連通性當成電氣性能驗收。

首件以限流供電檢查 3V3、關機分壓、低電量／USB 插拔、充電電流、NTC、燒錄、感測器 ID 與軸向；移植韌體後才測六顆 BLE、100Hz 目標、延遲及穿戴精度。所有通過項目均應留下實測記錄。

## 重建

`python build_design.py` 會重建原理圖與 **未佈線 placement PCB**，覆蓋先前 PCB；之後必須重新路由或在 KiCad 手動走線。FreeRouting 1.9 使用單執行緒 `-mt 1`；不要使用有已知間距問題的多執行緒最佳化。

目前環境可用 Java 21。`java -jar sources/freerouting-1.9.0.jar -de aetherpose_custom.dsn -do aetherpose_custom.ses -mp 20 -mt 1` 完成後，執行 `python import_and_check.py` 匯入並檢查。此程式需 Shapely。預覽 PNG 需 PyMuPDF，由 SVG 轉換。
