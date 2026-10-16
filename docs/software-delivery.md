# 軟體展示與驗收

本次範圍依使用者 2026-10-15 指示，限定軟體成熟化。硬體燒錄、實體穿戴與真人實驗保留為研究限制與後續擴充，不作此次工作的完成門檻，也不要求提供硬體資訊。

## 軟體交付條件

| 項目 | 判定方式 |
|---|---|
| 相容環境 | Windows、64 位元 Python 3.11 以上、鎖定套件與必要外部資源檢查；本機實際驗證 Python 3.12.1 |
| 安裝與啟動 | 安裝前拒絕過舊／32 位元 Python；安裝命令失敗停止；啟動檢查服務身分與連接埠，不覆用其他應用程式 |
| 核心展示 | 模擬 UDP → 後端 → 原模型推論 → 身體校正 → 3D 人體 → 深蹲計分，展示時明示模擬來源 |
| 錯誤復原 | 資料過期、來源改變、服務斷線、頁面背景化、校正開始／失效及校正要求待回覆，不能繼續有效計分 |
| 可重跑驗收 | 完整軟體／Live 腳本退出碼 0，保留跳過項目、固定視窗模型數值對照及重複負載觀察 |
| 可交接來源 | 新版本來源 ZIP、逐檔雜湊、解壓副本檢查、外部依賴說明與同版本證據摘要 |

同機解壓與依賴檢查不等於他機安裝。正式報告與簡報的校方格式、簽名及作者資料不在程式內推定；文字工作來源仍為 `docs/thesis-source.md`。

## 1. 建立與檢查環境

準備 64 位元 Python、Rust 工具鏈及 Chromium／Chrome／Edge，依 `external_paths.example.json` 設定自己取得的 TransPose、SMPL 與權重。外部檔案不會自動下載或打包。

```powershell
.\setup.ps1
..\.venv\Scripts\python.exe tools\check_environment.py --strict-lock
..\.venv\Scripts\python.exe -m pip check
```

若虛擬環境建在專案內，以上 Python 路徑改成 `.\.venv\Scripts\python.exe`。`run.ps1` 與測試會優先使用上層 `.venv`，其次使用專案內 `.venv`，不要混用兩個環境。

環境檢查只讀套件 metadata、檔案與瀏覽器位置，不連裝置、不載入權重、不安裝或修改設定。`--strict-lock` 將套件版本偏離列為失敗；不帶此選項時偏離會列警告。缺套件或必要檔案仍失敗。`--json` 可輸出診斷 JSON；包含本機路徑，對外提供前檢查內容。此檢查不代替真正載入模型與服務驗收。

## 2. 展示核心流程

```powershell
.\run.ps1
```

頁面開啟後，在另一個終端執行：

```powershell
..\.venv\Scripts\python.exe tools\simulate_trackers.py --motion squat --follow-calibration
```

此命令會發送六顆模擬 UDP 追蹤器，ID 為 240–245。只在沒有既有追蹤器的展示環境執行，以免與其他輸入混合。到「準備」確認六顆指派、按「校正身體」，模擬器會依服務指令做 T-pose 與 bow。完成後到「遊戲」選 Squat Rhythm，再開始回合。遊戲仍會先校準站姿。

頁面 `LIVE 6/6` 表示六個即時輸入槽均有資料，不代表實物證明。此展示與截圖應標示「六顆 UDP 模擬輸入」，不能只憑 LIVE 字樣稱真人穿戴。示範資料與混合輸入各有獨立成績來源；未校正即時／混合輸入會拒絕開局。

結束時先在模擬器終端按 Ctrl+C，等待「The backend forgot the simulated trackers」後再關閉服務：

```powershell
.\stop.ps1
```

不要先關後端，否則模擬器無法完成清理。若先前異常關閉留下 240–245，先確認來源再在頁面移除這些模擬追蹤器；不要清除所有設定或刪除其他資料。

## 3. 自動驗收與重複負載

服務啟動後執行：

```powershell
powershell -NoProfile -File tests\run_software_checks.ps1 -Live
```

Live 測試會修改並恢復部分設定，建立／清理模擬輸入，應在獨立展示時段執行。保留完整輸出與退出碼。符號連結建立測試可能因 Windows 權限跳過，必須揭露，不能算成實際執行通過。

效能量測另開一次，避免與完整測試同時競爭 CPU：

```powershell
..\.venv\Scripts\python.exe tools\profile_runtime.py --seconds 30 --cycles 2 --simulate --output logs\software-runtime-new.json
```

此工具要求後端沒有既有追蹤器；完成後驗證模擬器清理。報告各繪圖／抑制繪圖階段、輸入略過與模型耗時，不能只摘最高 Hz。效能觀察和測試數量都不是遊戲真人辨識準確率。

目前已知限制：本機獨立補測的繪圖階段曾為 9.8／21.9 Hz，並有輸入略過，尚未達成持續至少 15 Hz 的既定目標。不能將功能驗收通過寫成效能一致性已完成。完整觀察與受其他檢查干擾的紀錄見 [效能診斷](performance.md)。

## 4. 交付

按 [來源包說明](submission.md) 使用新檔名打包與驗證，不覆寫舊快照。提交 README、外部路徑範例、測試命令、來源與限制說明，以及對應版本的驗收摘要。模型／權重、個人路徑、環境與原始紀錄不自動放入 ZIP。

本次軟體交付可主張「端到端軟體整合、數值一致性、異常處理與模擬驗收」。實體 BLE 穩定性、真人動作準確率與端到端真人延遲維持未測，不影響本次軟體工作範圍完成判定。

本輪完整功能驗收：`logs/graduation-software-scope-full-20261015.log`，退出碼 0；兩種尺寸各 768 項瀏覽器檢查、環境預檢三項測試、Python／Rust 與 Live 流程通過，固定 20 秒模擬深蹲得分 5。符號連結建立測試仍因 Windows 環境限制跳過一項；安裝腳本的臨時直譯器負向測試遭自動審核拒絕，未執行，不列為通過。功能驗收不解除前述效能一致性限制。
