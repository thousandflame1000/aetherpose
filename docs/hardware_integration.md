# 硬體整合測試步驟

此文件列出在實機上驗證 BLE 與 Recorder 行為的步驟，以及需觀察的指標與故障排查方法。

1. 環境準備
   - 確認已插入或開啟 Tracker 裝置（BLE）。
   - 將開發機與 Tracker 放在同一房間，確保藍牙可連線。
   - 確認 `cargo run` 可以啟動應用。

2. 啟動後端與 GUI

```powershell
# 在專案根目錄
cargo run
```

- 觀察啟動日誌：應看到 UDP/OSC 綁定、BLE 掃描開始、字型載入等訊息。

3. 連線 Tracker
   - 在 GUI 的 Monitor 頁面確認追蹤器列表出現。
   - 檢查狀態欄是否顯示 `Active`、連線類型（BLE）與更新率（Hz）。

4. 啟用 Recorder
   - 到 System -> Recorder，設定 `Batch size`（例如 128）與 `Flush ms`（例如 500）。
   - 按 `Apply` 或 `Apply & Start` 啟動錄製。
   - 觀察左側/狀態列的 `REC` 指示燈與Recorder面板的 `掉落` / `寫入錯誤` 數值。

5. 壓力測試（驗證 dropped 與 write error）
   - 以高更新率模擬數據（若有硬體可調整 Tracker 輸出率，將其設為高頻），或在後端模擬輸入大量封包。
   - 觀察 `dropped` 計數是否上升；若頻繁上升，增大 `Batch size` 或降低寫入頻率，或檢查磁碟 I/O 性能。

6. 驗證檔案完整性與原子儲存
   - 停止錄製後，確認輸出檔案存在於工作目錄。
   - 檔案應為 CSV，並有頭欄（header）與多筆資料列。
   - 模擬中斷寫入（如強制中止程式）以檢查是否存在暫存檔或部分寫入情況。

7. 日誌與排查
   - 若看到大量 `write_error`，檢查硬碟空間與檔案權限。
   - 若大量 `dropped` 並伴隨高 CPU 使用，考慮調整 `batch_size` 與 `flush_interval_ms`，或改用更快的儲存媒體（NVMe）。

8. 建議測試矩陣
   - Batch size: [32, 64, 128, 256]
   - Flush ms: [100, 250, 500, 1000]
   - Tracker rate: [50 Hz, 100 Hz, 200 Hz]（視硬體能力）

9. 自動化（選項）
   - 可寫一個小工具模擬 UDP/OSC 封包以產生高頻資料流，方便在無硬體時做壓力測試。

---

需要我把這份檔案依據你的環境（目標資料夾、模擬腳本）補上具體指令嗎？
