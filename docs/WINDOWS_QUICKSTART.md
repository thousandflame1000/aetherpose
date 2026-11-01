# Windows 快速開始

## 一般使用者

從 [GitHub Releases](https://github.com/thousandflame1000/aetherpose/releases)
下載 `AetherPose-…-windows-x64.zip`，完整解壓縮，再雙擊 `AetherPose.exe`。
請保留同資料夾的 `_internal`，不要只把 EXE 單獨搬走。

啟動器會啟動本機服務並打開網頁。在「影像＋IMU 動作捕捉」按
「開啟影像骨架」，讓一人全身入鏡即可。預設使用程式建構的通用人體，
不需要 SMPL 帳號、Python、Rust、Arduino 或六顆 IMU。

攝影機不會自動開啟。使用完按「停止追蹤」或關閉啟動器；只會停止本次
啟動的子程序。如果已有其他版本占用連接埠，不會強制關閉另一個程式。

設定、工具記錄放在 `%LOCALAPPDATA%\AetherPose`。如有啟動問題，按
「開啟記錄資料夾」查看；不用刪除原始碼資料夾或修改系統 Python。

## 選用功能

- **IMU**：指派實際裝置部位並完成校正。缺少裝置不會補成假的六顆輸入。
- **SMPL**：自行取得適用授權後，在啟動器匯入 `.npz`；停止並重新啟動生效。
- **GlobalPose**：需另外準備其 Python 3.8 環境、權重、合法 SMPL 檔案及
  六個指定 IMU 的旋轉、加速度和角速度，見 [進階 Hybrid 說明](hybrid-runtime.md)。
  基本 ZIP 不含這些受限資源；通用人體模式不啟動 GlobalPose。
- **韌體燒錄／磁力計工具**：使用原始碼版與 Arduino 工具鏈，基本 ZIP 不含編譯工具。

這是未簽章的預覽版。遇到 Windows 來源警告時，請核對官方下載位置與
附帶的 SHA-256；此說明不要求關閉任何系統安全防護。

## 開發者建置 Windows ZIP

建置機需 Windows x64、Python 3.12、Rust 與 MSVC C++ 工具鏈：

```powershell
python -m venv .build-venv
.\.build-venv\Scripts\python.exe -m pip install -r packaging\requirements-build.txt
cargo build --release --locked
.\.build-venv\Scripts\python.exe tools\download_vision_models.py
.\.build-venv\Scripts\python.exe tools\build_windows.py --work build\windows --output dist
```

產物是包含 Python 執行環境、原生後端、網頁與官方影像模型的 onedir ZIP。
打包器會拒絕使用比 Rust 原始碼舊的後端，且不接受個人設定、NPZ、PKL、
研究權重或實測 CSV 混入。`BUILD_MANIFEST.json` 列出檔案與雜湊，ZIP 另附 SHA-256。

解壓後可執行 `AetherPose.exe --self-test --report result.json`，在不開相機
的情況下檢查人體、蒙皮、MediaPipe 模型、網頁資源與正式融合初始化。
自動建置範本位於 `packaging/windows-release.yml.template`。具有 GitHub workflow
權限的維護者可複製為 `.github/workflows/windows-release.yml` 後提交，啟用後才會
由 Actions 重新編譯後端、建立 ZIP 並執行該檢查。本次發布未執行 GitHub Actions。
