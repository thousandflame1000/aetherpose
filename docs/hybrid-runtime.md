# 單鏡頭＋可變數量 IMU

目前預設姿態服務已改為 HybridRunner。TransPose 舊程式保留供既有資料與測試參考，不再是預設推論來源。

## 使用

1. 安裝一次：在專案執行 `powershell -NoProfile -ExecutionPolicy Bypass -File tools/setup_hybrid.ps1`。本機開發環境已安裝。
2. 用 `run.ps1 -Restart` 開啟專案，在「準備 → 影像＋IMU 動作捕捉」按「開啟影像骨架」。攝影機只在按下後開啟，關閉最後一個網頁會釋放攝影機。
3. 可完全不使用 IMU；也可把已有 IMU 指派到實際穿戴部位。支援後端現有 19 個部位，可用其中任何子集，不必湊滿六顆。現有後端每個部位只接受一顆；未指派、過期、方向無效或未校正的裝置不參與融合。
4. 有 IMU 時先「校正身體」：T-pose、鞠躬。手臂作方向參考時，保持與軀幹相對固定一起鞠躬。
5. 站直、面向剛才校正的正前方，按「對齊相機與 IMU」。移動相機或重新校正 IMU 後須重新對齊。
6. 具有雙前臂、雙小腿、頭、**骨盆 Hip 0** 六個位置及有效角速度時，GlobalPose 會自動提供姿態與位移先驗。胸口 Chest 2 不會冒充骨盆。額外 IMU 繼續參與對應部位融合。

「相機位置追蹤」仍是原有標記定位功能，與影像骨架共用相機，切換時先停止當前相機。影像骨架不需列印標記或先完成棋盤校正。相機畫面與辨識在本機處理，程式不傳送影像到雲端。

## 實際演算法

- 預設 MediaPipe Pose Landmarker Full 提供 33 個人體點及可見度／存在度，介面可改為 Lite「快速」模式。影像採本機辨識，預覽會疊上實際可信的關節與骨段，顯示實測影像 FPS。
- 依實際時間間隔平滑關節，出鏡的點立即降低可信度；未偵測到人即清除平滑紀錄，重新入鏡不混合舊人的點。完整、部分、搜尋中、更新中斷分開顯示。
- 使用臉部平面補足 SMPL 葉節點頭部的方向，避免頭部只繼承頸部旋轉。低可信臉部不參與；已校正頭部 IMU 保持較高權重。
- 映射到 SMPL 骨架，以每個骨段的方向、實際可用的校正 IMU 方向、時間先驗及選用 GlobalPose 輸出，逐關節求解加權 Wahba 旋轉擬合（SVD，結果位於 SO(3)）。前向運動學保留 SMPL 固定骨長。
- 此版本是工程融合基線，**不是 RTOF、DiffCap 或 IMUCoCo 的復現**，沒有宣稱重現它們的精度。GlobalPose 分支使用官方 GPNet 與原生物理求解器；融合後的姿態不等於再經過一次完整 GlobalPose 物理優化。
- 每顆 IMU 都需指定已支援的身體部位與 sensor-to-segment 校正。「數量可變」不代表任意位置免校正、任意精度，或以少數 IMU 完全觀測全身。
- Nano 33 BLE 現行韌體傳送原始左手系加速度／角速度，服務先翻轉 X，並對角速度套用韌體相同的 LSM9DS1 靈敏度修正，再轉入已校正世界座標。其他 IMU 硬體需適配此輸入轉換。

## 資料失效與計分

- 相機觀測 300 ms、IMU 250 ms 以上即不使用；沒有有效輸入時停止產生新姿態。
- 只有部分 IMU、影像遮擋且 GlobalPose 不可用時，輸出標示「部分追蹤」，維持可觀測部位，暫停遊戲計分。未觀測部位可能保持舊方向，不能當成完整追蹤。
- GlobalPose 六個位置缺少任何一個時停止採用其先驗，不會填入 T-pose／示範訊號補足。過期的 GlobalPose 輸出也會被排除。
- 相機有可信雙腿且沒有 GlobalPose 位移時，採最低腳掌接觸虛擬地面的顯示假設，用實際蒙皮腳掌表面調整骨盆高度。這可避免屈膝懸空，但不量測真實跳躍高度。
- 單鏡頭人體點是相對骨盆的估計，沒有保證絕對尺度或場景位置。需要絕對定位時，另用既有標記功能或經校正的其他定位來源。

## 環境

主程式沿用 Python 3.12，影像模型位於 `external/vision/`。
GlobalPose 官方版本 `eef0e3b59b10104a80970261c3ad46d6c4681f29` 位於 `external/GlobalPose/`，使用隔離的 Python 3.8、PyTorch 2.0.1 與官方原生物理模組。有相容 NVIDIA 顯示卡時使用 CUDA；CPU 模式預設啟用 LSTM 動態量化，可設 `AETHER_GP_QUANTIZE=0` 回到浮點權重計算。量化屬本機效能適配，未宣稱與論文浮點模型完全相同精度。

本機 GPU 執行環境放在 C 槽，路徑由不進 Git 的 `hybrid_paths.json` 保存；來源專案仍在 D 槽。移動專案到另一台電腦後請重新安裝，或更新該檔的 `globalpose_dir`、`globalpose_python`。環境變數 `AETHER_GLOBALPOSE_DIR`、`AETHER_GLOBALPOSE_PYTHON` 優先於此檔，影像模型可用 `AETHER_VISION_MODEL` 指定。

安裝至其他磁碟：`tools/setup_hybrid.ps1 -RuntimeDirectory C:\AetherPoseRuntime\python38`；無 GPU 可加 `-CpuOnly`。日誌位於 `logs/globalpose.err.log`。

GlobalPose 分支與影像／IMU 融合採不同更新率：只處理最新有效感測器觀測，物理積分依時間戳決定步長，並拆成不超過 1/60 秒的小步，以維持原版 PD 控制器穩定。神經網路仍使用官方權重；其原始訓練採樣率為 60Hz，本機較低神經網路更新率是工程適配，不代表已驗證相同準確度。

原生 60Hz 的 40 幀合成序列測試中，拆分後的神經網路／物理方程與未拆分方程旋轉及位移差為零。這驗證該時序的程式等價，不能推廣成其他時序或真人精度保證。

物理修正中的兩個小型最小平方問題預設由 LAPACK 解同一目標；接觸力的正定凸二次目標則用 Cholesky 轉成相同的盒約束最小平方，由 BVLS 求解。若未成功，退回 OSQP，再以 L-BFGS-B 解相同的下界約束凸目標；若仍失敗會回報並停止採用該模型輸出。`AETHER_GP_DENSE_LS=0` 可沿用官方 LSQR，`AETHER_GP_DENSE_QP=0` 可跳過 BVLS。這是求解器適配，不代表逐位元相同輸出。

預設採同步神經網路／物理子步，避免在本機產生額外執行緒競爭。`AETHER_GP_ASYNC=1` 仍保留獨立物理時鐘實驗模式，本機量測較差，因此不預設啟用。原始 60Hz 方程比較以同步模式驗證。

Windows 同一計時刻度可能回傳重複時間戳。輸入端直接跳過重複、倒序及無限／NaN 時間，不偽造新時間；因此不會讓原生模型因重複時間中止。

六個指定位置資料齊備時才載入 GlobalPose；首次載入會計算並快取相同取樣解析度的物理參數，避免佔用不必要的記憶體與啟動時間。頁面列出是否參與融合及未就緒原因。本機可用 NVIDIA MX550；實際更新率和 GlobalPose 參與率由驗收工具量測，不能以硬體名稱推定效能。

## 影片驗證（不需開相機）

`python tools/analyze_pose_video.py --video PATH --output-dir OUTPUT` 會以正式影像／融合程式逐幀分析影片，輸出疊圖 MP4、實際 SMPL 姿態及數值檢查記錄。輸出影片需 FFmpeg；平常的相機功能不需 FFmpeg。工具採原片時間間隔處理，不把離線處理耗時當作真人即時 FPS。

已使用 TensorFlow 官方測試庫的 `pose_1.mp4`、`pose_squats.mp4`，以及 RickyBennison 的公開單腳深蹲影片測試。另有明確標示的人工裁切、黑畫面和恢復片段。全身跨步、深蹲保持完整追蹤；側身遮擋保留部分追蹤並停分。這些影片沒有同步 IMU 或真人誤差真值，不能驗證 Hybrid 人體精度。

- https://github.com/tensorflow/tfjs-models/tree/master/pose-detection/test_data
- https://commons.wikimedia.org/wiki/File:Basic_single_leg_squat.webm （RickyBennison，CC BY-SA 4.0；疊圖衍生影片同授權）

## 可重現驗證

`python tests/test_vision_filter.py` 檢查平滑、低可信／出鏡點、重新入鏡與相機停止更新。

`python tests/check_vision_recovery.py --image PATH_TO_PERSON_IMAGE` 使用實際 Full／Lite 模型驗證全身→裁切→空畫面→恢復。

`python tests/test_hybrid_fusion.py` 檢查 0、1、2、4、6、7、12、19 顆配置、失效資料、指定六位置、裝置替換、骨長、子關節繼承與位置連續性。

`python tests/test_webui_browser.py --suite webui_hybrid.js` 在實際 Chromium 檢查新控制區、來源標示、部分追蹤計分限制、錯誤及對齊命令。

`python tests/check_hybrid_runtime.py --image PATH_TO_PERSON_IMAGE` 使用真實影像模型。加 `--globalpose --seconds 30 --output logs/hybrid-acceptance.json`，會用明確標示的合成六 IMU 輸入驗證真實官方模型持續參與及斷線退回。相機與六 IMU 的合成組合只是軟體驗收，不是同步真人精度實驗。

首次六 IMU 模型載入可能需要數分鐘計算物理參數；之後使用模型與形狀參數雜湊對應的快取。CPU 若處理不及，過期輸出會排除；不能以增加顯示更新率當作模型已跟上。

## 論文依據

- [RobustCap，SIGGRAPH Asia 2023](https://shaohua-pan.github.io/robustcap-page/)：單鏡頭與六顆 IMU、雙座標融合與輸入退化回饋。
- [DiffCap，TVCG 2025](https://arxiv.org/html/2508.06139v1)：單鏡頭序列與六顆 IMU 的擴散融合。
- [RTOF，2024 預印本](https://arxiv.org/abs/2404.17837)：視覺骨架、慣性方向與時間片段優化，作為運動學融合設計參考。
- [DiffusionPoser，CVPR 2024](https://arxiv.org/abs/2308.16682)：預定位置中 1–13 顆 IMU 組合；原版不含相機融合。
- [IMUCoCo，UIST 2025](https://arxiv.org/abs/2508.01894)：可變數量與人體表面位置特徵，屬後續學習式擴充參考，並未在此版本接入。

完整查證與需求背景另見交付的研究方案。
