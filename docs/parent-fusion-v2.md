# 母關節融合 v2：修正與驗證

已整合正式 HybridRunner，Windows 版本為 `0.2.0-preview.2`。原 6 組複雜動作的清楚影像母關節平均旋轉誤差由 **21.47° 降到 16.36°（約 24%）**；另一組事先固定的不同動作由 **17.68° 降到 14.68°（約 17%）**。不是重新訓練 GlobalPose，也沒有替換其權重或物理解算器。

## 修正內容

- 連續高影像置信度不再略過 IMU 一致性檢查。量測骨段方向與影像矛盾時，降低對應影像部位的使用，不會因全身連續出現就解除保護。
- 前臂 IMU 的世界方向維持為量測約束。肘彎曲與前臂扭轉以有限模型先驗共同求解；接近伸直時，缺乏可觀測性的扭轉保留先驗，避免用單鏡頭的深度／彎曲平面硬算上臂方向。
- 使用重尾 Cauchy 方向殘差，降低高置信度深度異常值的拉力。五步以內的小型 Gauss–Newton 求解，保留原有因果式降抖與關節保護。25° 殘差尺度是工程參數，不是人體誤差保證。
- 影像內插出的脊椎與鎖骨點，不再被當作各自獨立的旋轉觀測；沒有直接感測時保留 GlobalPose 的相對分配。有額外胸口／脊椎 IMU 時，會依父節點重新換算局部旋轉以維持其實際世界方向。
- 有 GlobalPose 先驗時，共同朝向修正需至少三個獨立骨段同意，並保留小誤差死區；不再重複計算骨盆的多條子骨段來製造共識。

## 同條件數據

兩組各 6 段、各 2,160 幀。模型／IMU 時間軸 60 Hz，真實 MediaPipe 對合成 RGB 以 10 Hz 執行，含部分遮擋與完全遮擋。每段前 2 秒暖機、1 秒進入動作，統計最後 3 秒。母關節為大腿、脊椎、鎖骨與上臂共 9 處，指標含軸向扭轉。真值只造輸入和評分，未提供給估計器。

| 測試 | 修正前 | 修正後 |
|---|---:|---:|
| 原動作／清楚影像 | 21.47° | 16.36° |
| 原動作／遮擋影像 | 20.22° | 16.31° |
| 另一組／清楚影像 | 17.68° | 14.68° |
| 另一組／遮擋影像 | 15.76° | 14.16° |

原動作逐段母關節平均：

| 動作 | 修正前／清楚 | 修正後／清楚 | 修正前／遮擋 | 修正後／遮擋 |
|---|---:|---:|---:|---:|
| 交叉伸手 | 13.76° | 11.75° | 16.88° | 13.46° |
| 過頭抬手 | 27.26° | 17.16° | 26.42° | 16.96° |
| 深蹲轉體 | 24.22° | 21.15° | 24.94° | 20.14° |
| 單腳抬膝 | 16.43° | 16.11° | 17.09° | 15.45° |
| 背後伸手 | 19.77° | 15.62° | 18.42° | 16.08° |
| 左右不同步彎曲 | 27.37° | 16.37° | 17.57° | 15.77° |

## 驗證與限制

- 46 項 Python 回歸檢查通過，包括不讓持續高置信度影像蓋過 IMU、伸直肢體的扭轉歧義、可信彎曲觀測改善母關節、額外胸口 IMU、任意裝置子集、時序與 Windows 啟停保護。882 項 Chromium/WebGL 檢查通過。
- 正式 HybridRunner＋實際 GlobalPose 持續 15 秒測試通過：900 個 60 Hz 合成輸入皆有未逾時模型結果，實際模型約 54.3 Hz。這使用重複合成圖片的觀測，沒有開相機；不是實際相機 FPS，也不是 900 筆互不相同的模型輸出。
- 原測試清楚影像的融合耗時約 4.4 ms，P95 約 5.7 ms；修正前約 3.4 ms。只計融合，不含影像辨識、GlobalPose、網路與顯示；此次以增加約 1 ms 換取穩健性。
- 過頭抬手的上臂誤差由 74.06° 降到 41.26°，仍偏大。這段亦有最大 10° 超出工程關節界線的構造姿態，不能把所有誤差都歸因於模型。
- 另一組動作的清楚影像結果 14.68°，仍差於該組新模型＋IMU但無影像的 13.97°；影像不是每個案例都加分。沒有宣稱所有母關節已可唯一推導，也沒有真人精度保證。
- 兩組皆為構造運動學軌跡，未做人體解剖／動力學有效性驗證；初始外參已知，沒有實際磁干擾／校正誤差。驗證資料不是具統計代表性的人體測試集。部分動作的角加速度指標略增，不能宣稱全面降低抖動。

## 複現

原動作使用 `tools/complex_motion/benchmark.py`。另一組動作由以下程式產生，權重／人體授權資源仍需自行準備：

```powershell
python tools/complex_motion/make_validation_suite.py --data C:\AetherPoseStudies\validation --output C:\AetherPoseStudies\results
python tools/complex_motion/benchmark.py --data C:\AetherPoseStudies\validation --output C:\AetherPoseStudies\results --stage render
python tools/complex_motion/benchmark.py --data C:\AetherPoseStudies\validation --output C:\AetherPoseStudies\results --stage model
python tools/complex_motion/evaluate_versions.py --impl frontend --data C:\AetherPoseStudies\validation --output-dir C:\AetherPoseStudies\results --label optimized
```

修正前版本為 Git 提交 `3059bb3`，`evaluate_versions.py --impl` 可指定另一個版本的 frontend 資料夾。兩個版本必須使用同一份已渲染影像觀測、虛擬 IMU 與模型輸出；不為某一版本重製較有利的輸入。模型訓練／架構來源仍為 [GlobalPose 官方專案](https://github.com/Xinyu-Yi/GlobalPose)，此處融合與穩健求解為 AetherPose 工程修正。
