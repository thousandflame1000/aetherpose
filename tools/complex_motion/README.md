# GlobalPose 母關節複雜動作檢查

這是構造動作的離線壓力測試，不是人體精度驗收。程式不開攝影機、不連實體 IMU，也不更動正式追蹤的演算法或參數。

六組動作：交叉伸手／反向轉胸、過頭抬手／轉肩、深蹲轉體、單腳抬膝、轉身往背後伸手、左右不同步屈肘與屈髖。每組 6 秒，前 2 秒共同 T-pose 暖機、1 秒平滑進入動作，評分最後 3 秒。這些是確定性的運動學軌跡，未經人體解剖或動力學驗證。

```powershell
..\.venv\Scripts\python.exe tools\complex_motion\benchmark.py --data C:\AetherPoseStudies\complex-inputs --output C:\AetherPoseStudies\results
```

可用 `--stage generate|render|model|score` 分段重跑。`--project` 可指定專案位置。執行前需自行準備合法 SMPL NPZ、GlobalPose／其隔離 Python、MediaPipe Full、Chrome 與 FFmpeg；沿用專案既有外部路徑設定，不自動下載研究模型。

資料流程與隔離：

- 真值只產生虛擬量測及評分。六個感測部位為雙前臂、雙小腿、頭、骨盆；位置採官方合成程式的六個 SMPL 頂點 ID，以本專案 LBS 計算。位置二階差分生成去重力世界加速度，相鄰姿態的旋轉對數生成世界角速度；固定種子加入 0.5° 方向、0.05 m/s² 加速度及 0.005 rad/s 角速度高斯雜訊。這不是官方完整感測器／AHRS 模擬的復現。
- 真實 GlobalPose 官方權重與本專案原生物理 worker 接收 60 Hz 時間戳，離線同步逐幀執行，不丟幀，不把處理耗時當即時 FPS。CPU 模式沿用既有 LSTM 動態量化。
- 3D 場景渲染 10 Hz RGB，正式 MediaPipe Full 只接收影像。每組 3.0–4.1 秒部分遮擋、4.3–5.0 秒完全遮擋。置信度來自辨識器，沒有真值補點。
- 比較 GlobalPose 原輸出、正式 RealtimeFusion 的 GP＋IMU、再加入清楚／遮擋影像。共同場景座標校正已知；未測真實外參／時間同步誤差。
- 報告包含母關節全域旋轉誤差、各組／各部位、P95、遮擋片段、骨盆相對 MPJPE、辨識率與融合是否使用相機。整體旋轉誤差包含軸向扭轉，不只比較關節中心。

獨立的 80° 上臂反向補償反例只證明剛體骨架的可觀測性限制；不主張它是經解剖驗證的人體動作。其六個量測方向相同，靜態加速度與角速度相同，因此相同輸入無法唯一決定兩種不同母關節姿態。位置型相機骨架也無法識別純軸向扭轉。

輸出為本機比較頁、兩段含辨識疊圖的 RGB 影片與 JSON 指標。比較頁只含構造關節與旋轉，不含 SMPL 網格／範本。資料夾內的 `truth.npz`、`truth.json`、場景網格與模型資料不得放進專案或上傳 Git。

演算法來源：[GlobalPose 官方程式與合成方法](https://github.com/Xinyu-Yi/GlobalPose)，SIGGRAPH 2025 [論文／專案](https://xinyu-yi.github.io/GlobalPose/)。工程 Hybrid 融合與關節保護為 AetherPose 自己的基線，不是論文的影像融合復現。

數值檢查：`python -m unittest discover -s tools/complex_motion -p test_motion_suite.py`。
