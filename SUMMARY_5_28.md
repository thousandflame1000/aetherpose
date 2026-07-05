# Aetherpose 本週進度（2026-05-24 ~ 2026-06-05）

## 1. 韌體（Arduino Nano 33 BLE）

- **MAC-based 唯一 ID**：tracker ID 由 BLE MAC 末位自動決定，多顆 IMU 不再衝突
- **BLE 名稱**：廣播名改為 `Aetherpose Tracker {ID}`，方便識別
- **濾波器確認**：保留 Madgwick AHRS，`beta = 0.1`（文獻標準值）
- **arduino-cli 自動刷韌體**：可自動偵測 COM port，支援多顆批量刷入
- **本週連線驗證**：5 顆 IMU 同時 BLE 連線成功（ID: 31, 43, 69, 76, 190）

## 2. Rust 後端

- **移除 EKF**：`imu/ekf.rs` 刪除，fusion.rs 清除相關 dead code，直接使用 firmware Madgwick quaternion
- **Dead code 清理**：移除舊 GUI 殘留（gui.rs, render.rs, ui/, main_1.rs, theme.rs 等 ~6000 行）
- **cargo check 0 warnings、0 errors**

## 3. Python 前端

### TransPose 加速度格式修正
- **問題發現**：firmware 送出的是 local frame + 含重力的加速度，與 DIP 訓練資料格式不符
- **對比來源**：TransPose `live_demo.py` 明確指定 `Acceleration = Sensor local`，並在 Python 做 gravity 移除 + 全域轉換
- **修正**：`a_global = R @ a_local - [0, 0, 9.81]`（gravity-free global frame）

### 單視窗 Open3D GUI（`main_o3d.py`）
- DearPyGui + 獨立 Open3D 視窗合併為單一 Open3D GUI 視窗
- FPS free camera（yaw/pitch，roll 鎖定）：WASD 移動、滑鼠拖曳視角、R 重置
- 控制面板四分頁：Calibration / Monitor / Body / System
- T-Pose 重置按鈕：清除推理狀態，mesh 回 T-pose

### 3D 場景
- SMPL mesh（T-pose 預載，TransPose 推理後更新）
- IK skeleton + TP skeleton 統一樣式（左=青色、右=橙色、脊椎=白灰）

### DIP Mask 優化
- 分析 DIP s_01~s_10 全部 clip 的 motion variance，選 **s_03/05（var=0.76）** 作 idle mask
- 新增 `make_tpose_mask.py`：合成 T-pose mask（`acc=[0,0,9.81]`，`ori=I`）
- TransPoseRunner 自動優先載入 `tpose_mask.npz`，不存在則 fallback DIP mask

## 4. 交接包

- **`HANDOFF.md`**：從零開始操作說明（Arduino IDE → Rust → Python）
- **`setup.ps1`**：一鍵建立環境，`-FlashFirmware` 選項可自動刷韌體
- **`run.ps1`**：一鍵啟動後端 + 前端
- **`G_project_5_24.zip`**：原始碼打包（排除 target/、.arduino-*、.venv/）

## 5. 已知問題 / 待處理

| 問題 | 狀態 |
|------|------|
| IMU 靜止時骨架輕微移動 | Madgwick 無 bias 補償；T-pose 校正流程尚未整合 |
| T-pose 校正 | TransPose live_demo.py 有完整參考實作，待移植 |
| 第 6 顆 IMU | 不在手邊，slot 3（R.Knee）由 DIP mask 補足 |
| Open3D GUI 樣式限制 | 框架不支援深色主題，目前為預設外觀 |
