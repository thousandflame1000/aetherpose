# Aether Combat

Aetherpose 的子專案：用身上的 IMU 即時驅動 3D 人體（SMPL 網格）的瀏覽器畫面。

![Aether Combat](docs/screenshot.png)

## 資料流

```
IMU 追蹤器 ──BLE──> aetherpose.exe ──ws :9009──> frontend/mesh_bridge.py ──ws :9010──> combat/index.html
 (tracker_firmware)   (Rust 後端)                 (TransPose 推論)                      (three.js 畫面)
```

這個資料夾只包含網頁本身。後端、mesh_bridge 與韌體都是 aetherpose 主專案的一部分，這裡不另外複製。

## 啟動

從主程式（`frontend/main.py`）右側面板的 **Apps** 分頁按「Open Aether Combat」即可；
按鈕執行的就是下面的腳本。也可以在 `aetherpose/combat` 直接執行：

```powershell
.\run.ps1
```

腳本只會啟動**還沒在跑**的服務，然後開啟 <http://127.0.0.1:18081/>：

| 服務 | 埠 | 記錄檔 |
|---|---|---|
| Rust 後端 `aetherpose.exe` | 9009 | `aetherpose/backend_run_stderr.log` |
| `frontend/mesh_bridge.py` | 9010 | `aetherpose/frontend/mesh_bridge_stderr.log` |
| 網頁伺服器（本資料夾） | 18081 | `combat/http_server.err.log` |

選項：`-Port 18090` 換網頁埠，`-NoBrowser` 不自動開瀏覽器。

服務都在背景執行（沒有視窗）。關閉：

```powershell
.\stop.ps1               # 關閉網頁伺服器、mesh_bridge、後端
.\stop.ps1 -KeepBackend  # 保留後端
```

`webui/index.html` 也使用同一個後端與 mesh_bridge；兩者可以同時開著。

## 需求與注意事項

- 需先完成 aetherpose 的環境建置（`..\setup.ps1`）：Rust 後端已編譯、上層資料夾有 `.venv`。
- 頁面從 unpkg CDN 載入 three.js，需要網路連線。
- 一顆追蹤器同時只能被一個程式透過 BLE 連線。使用 `tools/imu_axes.py` 測單顆 IMU 時，要先關掉它，後端才連得上。
- 本頁只負責顯示，沒有校正與追蹤器管理功能；這些在主控介面 `webui/index.html` 的
  Calibration 分頁（Auto Assign、Reset Mounting、Reset Yaw）。要完整驅動身體需 6 顆追蹤器都開機，
  已連線的數量也在該分頁的 Trackers 卡片。
- 追蹤器韌體更新後（例如座標系或濾波器改變），請在主控介面重新做 Reset Mounting。
