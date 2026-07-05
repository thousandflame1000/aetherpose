# Aetherpose 進度報告（2026-05-14 ~ 2026-06-05）

---

## 韌體（Arduino Nano 33 BLE）

- **MAC-based 唯一 ID**：Tracker ID 由 BLE MAC 末位自動決定，解決多顆 ID=1 衝突 / 骨架抖動問題
- **BLE 名稱**：廣播名改為 `Aetherpose Tracker {ID}`，主機識別不再依賴順序
- **濾波器**：保留 Madgwick AHRS，`beta = 0.1`（文獻標準值，適合動作捕捉）
- **arduino-cli 自動刷韌體**：自動偵測 COM port，支援多顆批量刷入，不需要手動操作 Arduino IDE
- **本週驗證**：5 顆 IMU 同時 BLE 連線成功（ID: 31, 43, 69, 76, 190）

---

## Rust 後端

### Bug 修正
- **BLE 多裝置發現問題**：Windows btleplug 第一顆連線後只發 `DeviceUpdated`，導致第二顆永遠找不到 → 加入 `DeviceUpdated` 事件處理 + `seen_ids` HashSet 防止重複連線
- **移除 EKF**：`imu/ekf.rs` 整個刪除（從未被呼叫，dead code），fusion.rs 清除相關殘留

### Dead Code 清理（~6000 行）
- 刪除舊 GUI 殘留：`gui.rs`, `render.rs`, `ui/`, `main_1.rs`, `theme.rs`
- 移除 `CameraProjectionMode`, `Tab` enum，config 中 GUI 專用欄位
- **`cargo check` 0 warnings, 0 errors**

### 功能
- Auto-assign 優先骨骼順序調整為 TransPose 優先（Chest → L/R ForeArm → Head → L/R Leg）
- 新 tracker 連線時自動觸發 auto-assign

---

## Python 前端

### TransPose 多 IMU 支援
- `push_frame()` 改為接受全部 trackers dict，透過 `BONE_TO_SLOT` 自動路由
- `BONE_TO_SLOT = {32:0, 42:1, 11:2, 21:3, 4:4, 2:5}`
- 未覆蓋的 slot 由 DIP mask 補足

### 加速度格式修正（重要）
- **問題發現**：對比 TransPose `live_demo.py`，發現訓練資料用的是 gravity-free global frame 加速度
- **修正**：`a_global = R @ a_local - [0, 0, 9.81]`
- firmware 不需要改動，Python 端處理

### DIP Mask 優化
- 分析 DIP s_01~s_10 全部 clips 的 motion variance，選 **s_03/05（var=0.76，最靜）** 作 idle mask
- 新增 `make_tpose_mask.py`：生成合成 T-pose mask（`acc=[0,0,9.81]`，`ori=I`）
- `TransPoseRunner` 自動優先載入 `tpose_mask.npz`，不存在則 fallback DIP mask

### Open3D 單視窗（`main_o3d.py`）
- DearPyGui + 獨立 Open3D 視窗合併為**單一 Open3D GUI 視窗**，解決 WGL context 衝突
- **FPS free camera**：yaw/pitch，roll 鎖定，WASD + 滑鼠，R 重置視角
- **3D 場景**：SMPL mesh + IK skeleton + TP skeleton，統一樣式（左=青、右=橙）
- **60fps 限速修正**：加入 `time.sleep(frame_remaining)` 解決 CPU 100% 問題
- 控制面板四分頁：Calibration / Monitor / Body / System
- T-Pose 重置按鈕

---

## 交接與工具

- **`HANDOFF.md`**：從零開始完整操作說明（Arduino → Rust → Python）
- **`setup.ps1`**：一鍵建立環境（venv + pip + cargo build），`-FlashFirmware` 選項自動刷韌體
- **`run.ps1`**：一鍵啟動後端 + 前端
- **`requirements_freeze.txt`**：精確 Python 依賴版本
- **`G_project_5_24.zip`**（0.19 MB）：原始碼打包

---

## 已知問題 / 下週待處理

| 問題 | 說明 |
|------|------|
| IMU 靜止骨架輕微漂移 | Madgwick 無 bias 補償；需 T-pose 校正流程 |
| T-pose 校正未整合 | TransPose `live_demo.py` 有完整參考，待移植 |
| 第 6 顆 IMU 不在手邊 | slot 3（R.Knee）由 DIP mask 補足 |
| Open3D GUI 樣式 | 框架限制，無法深色主題 |
