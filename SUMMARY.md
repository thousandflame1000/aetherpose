# Aetherpose — 專案總結

## 架構概覽

```
[BLE IMU Trackers]
       │ UDP/Serial
       ▼
┌─────────────────────────────┐
│  Rust Backend (aetherpose)  │
│  - EKF 姿態估計              │
│  - IK Solver                │
│  - OSC Output               │
│  - axum WebSocket :9009     │
└────────────┬────────────────┘
             │ ws://127.0.0.1:9009/ws
             │ JSON
             ▼
┌─────────────────────────────┐
│  Python Frontend (main.py)  │
│  - Dear PyGui 2.3.1 UI      │
│  - TransPose 推理            │
│  - Open3D SMPL 3D 視窗       │
└─────────────────────────────┘
```

---

## 檔案結構

```
G_project/
├── aetherpose/
│   ├── Cargo.toml                  # Rust 依賴（axum 0.7，移除 eframe）
│   ├── src/
│   │   ├── main.rs                 # 入口：tokio::main → runtime::run()
│   │   └── app/
│   │       ├── runtime.rs          # 啟動 axum server + backend 執行緒
│   │       ├── ws_server.rs        # WebSocket handler（broadcast + mpsc）
│   │       ├── types.rs            # WsSnapshot, WsBone, BackendCommand (Serialize)
│   │       └── backend/
│   │           ├── pipeline.rs     # publish_snapshot() → 填 bones: Vec<WsBone>
│   │           └── ...
│   └── frontend/
│       ├── main.py                 # 主 UI（Dear PyGui）
│       ├── ws_client.py            # WebSocket 客戶端（背景執行緒 + asyncio）
│       └── live_o3d.py             # Open3D SMPL mesh 視窗（獨立 Process）
│
└── .venv/                          # Python venv（在 G_project 根目錄）
    └── Scripts/python.exe

# 外部依賴路徑
D:\Download\TransPose\TransPose-main\   # TransPoseNet model
D:\Download\SMPL_MALE.npz               # SMPL shape model
D:\Download\SMPL_MALE.pkl               # SMPL pkl（TransPose 用）
D:\Download\weights.pt                  # TransPose 預訓練權重
D:\Download\DIPIMUandOthers\...         # DIP-IMU dataset（mask 資料）

C:\Users\20050\OneDrive\桌面\bone_data_anylasis\
├── dip_loader.py                   # SMPLForwardKinematics, lbs_frame()
├── viewer_desktop.py               # SkeletonViewer（骨架播放器）
└── live_transpose.py               # 獨立腳本：1 live tracker + 5 DIP mask → TransPose batch
```

---

## WebSocket 協定

### Server → Client（JSON）

```json
{
  "type": "Snapshot",
  "data": {
    "packet_count": 12345,
    "trackers": {
      "1": {
        "id": 1,
        "assigned_bone": 33,
        "battery": 0.85,
        "tps": 60,
        "rssi": -65,
        "accel": [0.1, 9.8, 0.0],
        "rotation": [0.0, 0.0, 0.0, 1.0],
        "connection_type": "BLE",
        "lost_packets": 2,
        "received_packets": 998,
        "last_update_ms": 16
      }
    },
    "bones": [
      { "id": 0, "name": "Hip", "parent_id": null, "pos": [0.0, 0.9, 0.0] },
      ...
    ],
    "is_recording": false,
    "leg_ratio": 0.52,
    "floor_offset": 0.0,
    ...
  }
}
```

### Client → Server（JSON）

```json
"AutoAssign"
"ResetYaw"
"ResetMounting"
"StartRecording"
"StopRecording"
"AutoFloor"
{ "AssignTracker": [tracker_id, bone_id] }
{ "SetIkSmoothness": 0.5 }
{ "SetFloorOffset": 0.05 }
{ "SetProportions": { "leg": 1.0, "arm": 1.0, "spine": 1.0 } }
{ "SetOscTarget": ["127.0.0.1", 9000] }
{ "SetRecorderConfig": { "filename": "rec.bin", "batch_size": 128, "flush_interval_ms": 500 } }
{ "SetSerialConfig": { "enabled": true, "port": "COM3", "baud": 115200 } }
```

---

## TransPose 整合

### 6 感測器槽對應

| Slot | 部位 | DIP sensor index |
|------|------|-----------------|
| 0 | L.Elbow（左手肘） | 7 |
| 1 | R.Elbow（右手肘） | 8 |
| 2 | L.Knee（左膝） | 11 |
| 3 | R.Knee（右膝） | 12 |
| 4 | Head（頭） | 0 |
| 5 | Belly（腹部） | 2 |

### 運作流程

```
每幀：
  mask_acc/ori[i % N_mask]        ← DIP dataset 循環填充（5 槽）
  tracker 即時 accel + rotation   → 覆蓋 live_slot（目前 slot 0 = L.Elbow）

背景執行緒（tp-online）：
  normalize_and_concat(acc, ori)  → (72,) tensor
  net.forward_online(x)           → pose (24,3,3), tran (3,)
  SMPLForwardKinematics.forward() → joints (24,3)
  → 更新 _joints（主執行緒讀取渲染）

每 6 幀：
  fk.lbs_frame(R_24x3x3)         → SMPL 6890 頂點
  → 送到 Open3D Process（mp.Queue）顯示 3D mesh
```

### 推理速度
- `forward_online()` CPU：約 9ms / 幀，背景執行緒不阻塞 UI

---

## UI 四個 Tab

### Calibration
- 左：Aetherpose IK 骨架（PIL 渲染 → DPG texture）
- 右：TransPose SMPL 骨架（PIL 渲染 → DPG texture）
- 可拖曳旋轉（左鍵拖 = yaw/pitch）、滾輪縮放
- Open3D 視窗獨立彈出（`multiprocessing.Process`）

### Monitor
- 顯示所有 tracker：ID / 分配骨頭 / 狀態 / 電量 / TPS / 丟包率 / RSSI
- Combo box 手動分配骨頭

### Body
- IK Smoothness 滑桿
- 肢體比例（Legs / Arms / Spine）
- One Euro Filter 參數
- 軌跡積分模式（EKF+RK4 / EKF+Euler）
- Virtual Floor offset
- Leg calibration

### System
- OSC 輸出（IP / Port）
- ZUPT 參數
- 錄製（filename / batch size / flush ms）
- Serial 設定

---

## 啟動方式

### 1. Rust Backend
```powershell
cd d:\Download\G_project\G_project\aetherpose
cargo run --release
# 監聽 127.0.0.1:9009
```

### 2. Python Frontend
```powershell
& "d:\Download\G_project\G_project\.venv\Scripts\python.exe" `
  "d:\Download\G_project\G_project\aetherpose\frontend\main.py"
```

### 3. 獨立 TransPose 腳本（可選）
```powershell
& "d:\Download\G_project\G_project\.venv\Scripts\python.exe" `
  "C:\Users\20050\OneDrive\桌面\bone_data_anylasis\live_transpose.py" `
  --slot 0 --tracker 1 --subj s_01 --clip 0 --buf 300
```

---

## Python 依賴（.venv）

```
dearpygui==2.3.1
Pillow
numpy
torch==2.11.0+cpu
scipy
open3d
websockets
```

---

## 已知問題 / 限制

| 問題 | 狀態 |
|------|------|
| TransPose 只有 L.Elbow 等 6 個槽，沒有手腕槽 | 設計限制 |
| Aetherpose IK 只有 1 tracker 時姿態重建效果差 | 需要更多 tracker |
| NumPy 2.4 dtype align warning（來自 SMPL pkl） | 無害警告 |
| Open3D 視窗在 Windows 必須用獨立 Process | Windows EGL 限制 |
| DPG texture 必須在 `create_context()` 後生成 UUID | 已修正 |

---

## Bone ID 對應（Aetherpose）

```
0=Hip  1=Waist  2=Chest  3=Neck  4=Head
10=L_UpLeg  11=L_Leg  12=L_Foot
20=R_UpLeg  21=R_Leg  22=R_Foot
30=L_Shoulder  31=L_UpperArm  32=L_ForeArm  33=L_Hand
40=R_Shoulder  41=R_UpperArm  42=R_ForeArm  43=R_Hand
```
