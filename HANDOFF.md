# Aetherpose 交接說明

只驗收軟體、沒有 IMU 時，先依 [軟體展示與驗收](docs/software-delivery.md) 操作。以下韌體與穿戴步驟屬硬體擴充，不是本次軟體交付的必要條件。

## 硬體需求
- Windows 10/11（需有藍牙）
- Arduino Nano 33 BLE × N 顆
- USB 線

---

## 步驟一：刷 Arduino 韌體（每顆 IMU 各做一次）

1. 安裝 [Arduino IDE 2](https://www.arduino.cc/en/software)
2. Tools → Board Manager → 搜尋 `Arduino Mbed OS Nano Boards` → Install
3. Tools → Library Manager，安裝：
   - `ArduinoBLE`
   - `Arduino_LSM9DS1`
4. 用 USB 插上裝置，開啟 `src/skeleton/tracker_firmware/tracker_firmware.ino`
5. Tools → Board → **Arduino Nano 33 BLE**
6. Tools → Port → 選對應 COM 埠 → 按上傳（→）
7. 開啟 Serial Monitor（115200 baud），確認出現：
   ```
   Tracker ID: 76
   BLE name:   Aetherpose Tracker 76
   ```
   每顆 ID 由 MAC 末位自動決定，不會重複。

也可以在步驟三完成後用 `.\setup.ps1 -SkipPython -SkipRust -FlashFirmware` 一次刷入所有插著 USB 的追蹤器。

---

## 步驟二：安裝前置工具

| 工具 | 下載 |
|------|------|
| Python 3.11+，64 位元（本機驗證 3.12.1） | https://www.python.org/downloads/ |
| Rust | https://rustup.rs/ （下載 `rustup-init.exe`） |

安裝完後重開終端確認：
```powershell
python --version   # Python 3.11+；另確認為 64 位元
cargo --version    # cargo 1.x
```

---

## 步驟三：一鍵建立環境

```powershell
cd aetherpose
.\setup.ps1
```

腳本會自動：
1. 建立 Python `.venv` 並安裝所有套件（約 1–2 GB，需要幾分鐘）；上層資料夾已有 `.venv` 時直接沿用
2. 檢查 TransPose、SMPL 等外部檔案（見步驟四）
3. 編譯 Rust 後端（約 2–5 分鐘）

完成後印出啟動指令即代表成功；有缺項時最後會列出「待處理項目」。

---

## 步驟四：設定外部檔案

TransPose 程式碼、SMPL 模型、預訓練權重和 DIP-IMU 資料因為授權與大小不放在專案裡，每台電腦要自己準備（授權說明見 `EXTERNAL_DEPENDENCIES.md`）。

1. 複製 `external_paths.example.json` 為 `external_paths.json`
2. 填入各檔案在這台電腦上的位置（相對路徑以 `aetherpose` 資料夾為起點）；也可以直接放到 `aetherpose\external\` 下的預設名稱
3. 確認：
   ```powershell
   ..\.venv\Scripts\python.exe frontend\external_paths.py
   ```
   必要項目都顯示 `ok` 才能推論。DIP-IMU 是選用的，沒有時示範畫面改為靜止 T-pose。

`external_paths.json` 只屬於這台電腦，不會進 git。

---

## 步驟五：啟動

```powershell
cd aetherpose
.\run.ps1
.\run.ps1 -Combat    # 直接進入 Combat
.\stop.ps1          # 關閉所有服務
.\run.ps1 -Restart  # 更新程式後：重新啟動所有服務（後端程式碼較新時會先重新編譯）
```

只啟動還沒在跑的後端、mesh_bridge 與網頁伺服器，不會終止其他 Python 程式。上層資料夾的 `start.ps1` 做同一件事。詳見 `webui/README.md`。

---

## 確認連線成功

- 網頁的「準備」分頁最上方是「開始步驟」：連上追蹤器 → 指派到 6 個部位（頭、胸口、左右前臂、左右小腿）→ 校正身體 → 開始遊戲，會標出目前在哪一步、還缺什麼。
- 「準備」分頁列出已連線的追蹤器與指派的骨頭，「進階 › 監控」分頁顯示訊號與電量；電量 15% 以下會提醒充電。
- 分不出哪顆追蹤器是哪個 ID 時，在「追蹤器工具」選部位、按「搖動指派」，再搖一下戴在那個部位的追蹤器。
- 場景左上角的資料來源：「即時動作捕捉」代表 6 個槽位都是即時 IMU；「混合輸入（即時 n/6）」代表只有 n 顆，其餘用示範資料補；「示範資料」代表沒有即時 IMU。
- log 都在 `logs\`：`status_ble.log` 記錄每次 BLE 連線與斷線（`ble_connected:<MAC>`），`backend.err.log` 是後端的詳細 log，`mesh_bridge.err.log` 是推論服務的 log。

## 沒有追蹤器時試用即時模式

```powershell
..\.venv\Scripts\python.exe tools\simulate_trackers.py           # 6 顆模擬追蹤器，輕微擺動
..\.venv\Scripts\python.exe tools\simulate_trackers.py --follow-calibration   # 靜止，按「校正身體」時會自動做 T-pose 與鞠躬
..\.venv\Scripts\python.exe tools\simulate_trackers.py --motion squat          # 先站約 7 秒讓遊戲校準站姿，之後每 3.5 秒蹲一次，可以玩 Squat Rhythm
..\.venv\Scripts\python.exe tools\simulate_trackers.py --motion squat --headset --count 7   # 再加 Quest 頭戴裝置（UDP 9002）；把第 7 顆指派到左大腿就能試腿長校正
```

模擬追蹤器透過 UDP 9003 送出和韌體相同的封包，後端會像真的追蹤器一樣分配部位。停止時（Ctrl+C）工具會請後端忘掉這些追蹤器，等後端的追蹤器清單裡沒有它們才結束，`config.json` 恢復原狀；加 `--keep` 則保留。

## 身體校正（每次穿戴後）

戴好所有追蹤器後，在網頁「準備」分頁按「校正身體」：先 T-pose 靜止 2 秒，再向前鞠躬約 45° 靜止 1.5 秒。沒做之前，即時追蹤的人體姿態是錯的（資料來源會標示「未校正」）。詳見 `webui/README.md` 的「身體校正」。

## 磁力計校正（每顆新追蹤器做一次）

韌體依追蹤器 ID 查磁力計校正表；沒有校正值的追蹤器會關閉磁力計，只用陀螺儀算航向，時間久了會漂移。「進階 › 監控」分頁的追蹤器列會顯示「磁力計已校正」或「磁力計未校正」。

追蹤器連上後端並插著 USB 時，在網頁「進階 › 監控」分頁的「磁力計校正」選它、按「開始校正」，依提示慢慢把追蹤器轉過各個方向；工具會自動擬合、寫入韌體並重新燒錄，輸出顯示在網頁上。也可以在終端機執行同一個工具：

```powershell
..\.venv\Scripts\python.exe tools\calibrate_tracker.py --id 76
```

單顆 IMU 的方向可在網頁「進階 › 監控」分頁點該追蹤器的「三軸 ↗」檢查（說明見 `tools/IMU_AXES_README.md`）。

---

## 常見問題

Windows 的 CPU 推論預設會對推論程序提出延遲優先提示；是否成功可見 `logs/mesh_bridge.out.log`。若需沿用系統節能推定，在啟動前設定 `$env:AETHER_WINDOWS_LATENCY='0'` 並執行 `.\run.ps1 -Restart`。設定、耗電取捨與量測限制見 [效能診斷](docs/performance.md)；這不代表已保證所有機器都能穩定達到目標更新率。

| 問題 | 解法 |
|------|------|
| BLE 找不到裝置 | 先看「準備」分頁追蹤器清單下方的藍牙狀態；顯示「藍牙無法使用」時到 Windows 設定開啟藍牙（或關掉再開），後端會自動重試 |
| `setup.ps1` 報 Rust 未安裝 | 先裝 Rust（步驟二），重開終端再執行 |
| Python import 錯誤 | 確認用 `.venv` 的 python，不要用系統 python |
| 所有 IMU ID 都是 1 | 重新刷韌體（步驟一），新韌體用 MAC 自動分配唯一 ID |
| 網頁顯示「推論錯誤」 | 「準備」分頁的「開始步驟」會寫出原因；通常是外部檔案路徑不對（步驟四） |
| 動作卡頓、追蹤器時有時無 | 看「進階 › 監控」分頁：訊號 -80 dBm 以下或遺失超過 5% 會標成橘色，讓追蹤器靠近電腦、減少遮擋；電量 15% 以下會提醒充電 |
| 左上角出現橘色「姿態更新偏慢」 | 推論服務每秒少於 15 個姿態，遊戲判定可能不準。通常是其他程式在搶 CPU（包括沒有硬體加速、用 CPU 算 3D 的瀏覽器，頁面偵測到時會提醒）；關掉它們即可。有 NVIDIA 顯示卡時推論會自動改用 CUDA。開發用的電腦閒置時約每秒 46 個 |
| 開頭出現「config.json 讀不到」 | 後端改用預設設定，原檔備份為 `config.json.bad`；修好後改名回 `config.json`，再執行 `.\run.ps1 -Restart` |
| VRChat 收不到 OSC | 「進階 › 系統」分頁的 OSC 卡片會寫出目前送到哪裡或為什麼沒有輸出；IP 要填 IPv4 位址（例如 127.0.0.1），不能填 localhost |
| 多出來的追蹤器（例如備用的第 7 顆）不想讓它驅動骨架 | 在「準備」分頁把它的部位選成「未指派」；之後連上新追蹤器或重新啟動都不會再自動分配給它，直到你再指派一次 |
| 兩顆追蹤器指派到同一個部位 | 不會發生：指派到已被占用的部位時兩顆會互換，面板頂端會說明 |
| 一般測試 | `powershell -NoProfile -File tests\run_software_checks.ps1`，加 `-Live` 會啟動服務測試實際流程 |
