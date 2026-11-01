# Hybrid 合成實驗

建立已知動作的 SMPL 人體、固定 IMU 安裝旋轉、單鏡頭場景、部分與完全遮擋。渲染 RGB 後使用正式 MediaPipe Full，再比較純方向量測、正式加權旋轉融合及新增的實驗保護。

目前本機設定在專案根目錄的 `simulation_paths.json`，不進 Git。資料與影片放 C 槽，避免增加 D 槽大型快取。

在專案根目錄啟動：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/hybrid_simulation/run.ps1
```

開啟 `http://127.0.0.1:18082/`。不需連接裝置或開啟相機。服務僅監聽本機，支援影片分段讀取，以保持時間軸跳轉正常。

重建渲染影片與真實模型觀測：

```powershell
..\.venv\Scripts\python.exe tools/hybrid_simulation/build_dataset.py --output-dir C:\AetherPoseSimulation
```

依賴專案既有 NumPy、SciPy、OpenCV、MediaPipe，合法的 SMPL NPZ、Chrome 及 FFmpeg。`make_truth.py` 透過既有 `external_paths.json` 解析模型；不重新下載模型。

指定另一個資料夾：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/hybrid_simulation/run.ps1 -DataDirectory C:\AetherPoseSimulation
```

資料隔離、理想量測與遮擋檢查：

```powershell
$env:AETHER_SIM_DATA_DIR='C:\AetherPoseSimulation'
..\.venv\Scripts\python.exe tools/hybrid_simulation/test_simulation.py
```

`engine.py` 的 `estimate()` 不接收動態真實姿態。真值只用於產生虛擬量測、共同初始校正和評分。方向觀測包含已知安裝旋轉，進入融合前套用 sensor-to-segment 校正。

本實驗用姿態方向誤差模型模擬 IMU，不是完整硬體／AHRS 模型。未啟動 GlobalPose，未測量全域位移，也不能替代真人驗證。原加權融合沒有被實驗保護覆寫；兩者均保留比較。

關節修正 v2：`anatomical_fusion.py` 使用此 rig 的鉸鏈軸與角度限制，並保留同限制 IMU 及舊自由關節對照。詳見實驗紀錄；這不是正式真人 rig 的通用限制。


目前預設為 v3：局部旋轉因果式自適應降抖，以及錄製姿態的最短路徑旋轉插值。頁面可分別關閉兩者，比較原始 v2；相機與姿態觀測仍為 15 Hz。原理、指標與延遲限制見 [實驗紀錄](EXPERIMENT.md)。

獨立降抖檢查：

```powershell
..\.venv\Scripts\python.exe tools/hybrid_simulation/test_temporal_filter.py
```
