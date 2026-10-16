# 外部方法、資料與授權說明

本專題定位為「工程整合型專題」。系統目標是把六顆實體 IMU、BLE 通訊、Rust 後端、Python 前端與既有姿態重建方法串成可展示的端到端流程；不主張提出新的深度學習模型，也不主張 TransPose、Madgwick、DIP-IMU 或人體模型檔為本專題原創。

## 必須揭露的外部項目

| 項目 | 本專題用途 | 提交注意 |
|---|---|---|
| x-io Fusion AHRS（Madgwick 演算法的後繼版本） | 在追蹤器韌體內將 IMU 資料融合為方向四元數；原始碼在 `src/skeleton/tracker_firmware/src/Fusion/`（版本見同目錄 `VERSION.txt`）。 | MIT 授權，散布時需保留 `LICENSE.md`；報告中應說明為既有姿態融合方法，並引用 Madgwick 論文與 Fusion 函式庫。 |
| TransPose | 以前端 Python 載入既有模型，將六顆 IMU 輸入轉成完整人體姿態輸出。 | 報告中應引用 TransPose 論文；不得寫成本專題提出的新模型。 |
| TransPose 程式碼 | 外部程式碼，不在專案內；位置由 `external_paths.json` 的 `transpose_dir` 設定。 | 該目錄含 GPL-3.0 授權檔；若將其程式碼一併提交或散布，需遵守 GPL 條款。 |
| TransPose 權重 | 外部預訓練權重；位置由 `external_paths.json` 的 `weights` 設定。 | 不應在未確認授權前放入公開或提交包；報告需說明為外部權重。 |
| SMPL / 人體模型檔 | `SMPL_MALE.npz`、`SMPL_MALE.pkl` 供 TransPose 與 3D mesh 顯示使用；位置由 `external_paths.json` 設定。 | 通常需使用者自行取得授權；不應任意附在提交包或公開倉庫。 |
| DIP-IMU 資料集 | 開發階段可作資料格式除錯或 fallback mask。 | 若使用其資料，需依資料集授權並引用 DIP-IMU 論文；不得把 DIP-IMU mask 當成使用者真實肢體動作。 |
| RobotExpressive 機器人模型（Quaternius） | 對打的對手與場景庫的機器人。 | CC0 1.0；來源與修改紀錄見 `webui/assets/README.md`。 |
| Lantern 木燈籠模型（Khronos glTF Sample Assets，Microsoft） | 場景庫的木燈籠。 | CC0 1.0；來源見 `webui/assets/lantern/README.md`。 |
| Python/PyTorch/NumPy/SciPy、Three.js | 推論服務與瀏覽器 3D 介面的執行環境。 | 需在環境說明列出版本或安裝方式，以利重現。 |
| Rust/Tokio/axum/btleplug | 後端 BLE、資料整理與 WebSocket/JSON 串流。 | 報告可寫為本專題後端實作基礎，不需誇大成姿態重建核心。 |

## 外部檔案位置

每台電腦在 `external_paths.json`（由 `external_paths.example.json` 複製）或環境變數中指定上述檔案的位置，該檔不進 git。`python frontend/external_paths.py` 會列出每一項是否找到；`setup.ps1` 也會執行這項檢查。SMPL 正向運動學（`frontend/smpl_fk.py`）已放在專案內，不再引用專案外的程式碼。

## Demo 與驗收邊界

完整姿態重建展示應以六顆實體 IMU 均有穩定輸入為前提。若少於六顆 live IMU，而程式使用 `tpose_mask.npz` 或 DIP-IMU mask 補足未輸入槽位，該狀態只能視為資料格式、通訊流程或前端推論管線除錯，不能宣稱完成使用者完整全身姿態重建。

目前前端 `TransPoseRunner` 會在狀態列顯示：

- `LIVE 6/6`：六個 TransPose 槽位皆由 live tracker 提供，可作為完整展示候選。
- `DEBUG mask=... live n/6`：仍有槽位由 T-pose 或 DIP-IMU mask 補足，只能作為除錯或流程展示。

## 報告建議寫法

可寫：

> 本專題採用既有 TransPose 方法作為姿態重建核心，並以 x-io Fusion AHRS（Madgwick 演算法的後繼版本）完成追蹤器端姿態融合。開發階段可能使用 T-pose 或 DIP-IMU mask 檢查資料格式，但完整展示與驗收以六顆實體 IMU 均有穩定輸入為準。

避免寫：

> 本專題自行提出完整人體姿態重建模型。

避免寫：

> 未配戴感測器的肢體可由 DIP-IMU 資料集填補並視為使用者動作。

## 建議參考文獻

正式提交完整報告時，至少應補上以下來源：

1. Madgwick, S. O. H. An efficient orientation filter for inertial and inertial/magnetic sensor arrays.
   x-io Technologies. Fusion (AHRS library, MIT License). https://github.com/xioTechnologies/Fusion
2. Yi, X., Zhou, Y., and Xu, F. TransPose: Real-time 3D Human Translation and Pose Estimation with Six Inertial Sensors. ACM Transactions on Graphics, 2021.
3. Huang, Y., Kaufmann, M., Aksan, E., Black, M. J., Hilliges, O., and Pons-Moll, G. Deep Inertial Poser: Learning to Reconstruct Human Pose from Sparse Inertial Measurements in Real Time. ACM Transactions on Graphics, 2018.
4. SMPL model/software license and official download page, if the model files are used in the submitted demo.

