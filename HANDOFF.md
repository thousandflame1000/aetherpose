# Aetherpose 交接說明

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

---

## 步驟二：安裝前置工具

| 工具 | 下載 |
|------|------|
| Python 3.10+ | https://www.python.org/downloads/ |
| Rust | https://rustup.rs/ （下載 `rustup-init.exe`） |

安裝完後重開終端確認：
```powershell
python --version   # Python 3.10+
cargo --version    # cargo 1.x
```

---

## 步驟三：一鍵建立環境

```powershell
cd aetherpose
.\setup.ps1
```

腳本會自動：
1. 建立 Python `.venv` 並安裝所有套件（約 1–2 GB，需要幾分鐘）
2. 編譯 Rust 後端（約 2–5 分鐘）

完成後印出啟動指令即代表成功。

---

## 步驟四：啟動

開兩個終端：

**終端 1（後端）**
```powershell
cd aetherpose
cargo run --release
```

**終端 2（前端）**
```powershell
cd aetherpose\frontend
..\.venv\Scripts\python.exe main.py
```

---

## 確認連線成功

後端 log：
```
[BLE] Discovered ... name="Aetherpose Tracker 76" target=true
連線成功
```

Python console：
```
[tp] trackers=[76] bones=[2] live_slots=[5]
```

---

## 常見問題

| 問題 | 解法 |
|------|------|
| BLE 找不到裝置 | Windows 設定 → 藍牙關掉再開 |
| `setup.ps1` 報 Rust 未安裝 | 先裝 Rust（步驟二），重開終端再執行 |
| Python import 錯誤 | 確認用 `.venv` 的 python，不要用系統 python |
| 所有 IMU ID 都是 1 | 重新刷韌體（步驟一），新韌體用 MAC 自動分配唯一 ID |
