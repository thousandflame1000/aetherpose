# Aetherpose 一鍵環境建立腳本
# 在 aetherpose 資料夾內執行：  .\setup.ps1
# 本檔含中文，必須存成「UTF-8 含 BOM」，Windows PowerShell 5.1 才能正確讀取。
# 選用參數：
#   -SkipPython    跳過 Python 環境建立
#   -SkipRust      跳過 Rust 編譯
#   -FlashFirmware 編譯韌體並刷入所有以 USB 連接的 Nano 33 BLE

param(
    [switch]$SkipPython,
    [switch]$SkipRust,
    [switch]$FlashFirmware
)

Set-Location $PSScriptRoot
Write-Host "=== Aetherpose Setup ===" -ForegroundColor Cyan

# run.ps1 與測試先找上層資料夾的 .venv，再找本資料夾的 .venv；這裡用同樣順序，避免重複建立。
$venv = @("$PSScriptRoot\..\.venv", "$PSScriptRoot\.venv") |
    Where-Object { Test-Path "$_\Scripts\python.exe" } | Select-Object -First 1
if (-not $venv) { $venv = "$PSScriptRoot\.venv" }
$python = "$venv\Scripts\python.exe"
$warnings = @()

# ── 1. Python 環境 ────────────────────────────────────────────────────────────
if (-not $SkipPython) {
    Write-Host "`n[1/4] Python 虛擬環境：$venv" -ForegroundColor Yellow
    if (-not (Test-Path $python)) {
        if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
            Write-Host "Python 未安裝，請先安裝 Python 3.11+（64 位元） https://www.python.org/downloads/" -ForegroundColor Red
            exit 1
        }
        python -c "import sys, struct; sys.exit(0 if sys.version_info >= (3, 11) and struct.calcsize('P') == 8 else 1)"
        if ($LASTEXITCODE -ne 0) { Write-Host "需要 Python 3.11+（64 位元）；鎖定的 NumPy／SciPy 套件不支援 Python 3.10。尚未建立環境。" -ForegroundColor Red; exit 1 }
        python -m venv $venv
        if (-not $?) { Write-Host "venv 建立失敗" -ForegroundColor Red; exit 1 }
    }

    & $python -c "import sys, struct; print('Python ' + sys.version.split()[0] + ', ' + str(struct.calcsize('P') * 8) + '-bit'); sys.exit(0 if sys.version_info >= (3, 11) and struct.calcsize('P') == 8 else 1)"
    if ($LASTEXITCODE -ne 0) { Write-Host "現有環境不符合 Python 3.11+（64 位元）。請使用相容的 Python 建立環境；此腳本不刪除現有環境。" -ForegroundColor Red; exit 1 }
    Write-Host "[1/4] 安裝 Python 套件（第一次約 1-2 GB，需要一段時間）..." -ForegroundColor Yellow
    & $python -m pip install --upgrade pip -q
    if ($LASTEXITCODE -ne 0) { Write-Host "pip 更新失敗，停止安裝。" -ForegroundColor Red; exit 1 }
    & $python -m pip install -r frontend\requirements_freeze.txt -r frontend\requirements.txt
    if ($LASTEXITCODE -ne 0) { Write-Host "pip install 失敗" -ForegroundColor Red; exit 1 }
    Write-Host "[1/4] Python 環境完成" -ForegroundColor Green
} else {
    Write-Host "`n[1/4] 跳過 Python（-SkipPython）" -ForegroundColor DarkGray
}

# ── 2. 外部檔案（TransPose、SMPL、權重、DIP-IMU）──────────────────────────────
Write-Host "`n[2/4] 檢查外部檔案..." -ForegroundColor Yellow
if (Test-Path $python) {
    if (-not (Test-Path external_paths.json)) {
        Write-Host "找不到 external_paths.json，使用預設位置 external\。可複製 external_paths.example.json 後填入實際路徑。" -ForegroundColor DarkGray
    }
    & $python frontend\external_paths.py
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[2/4] 外部檔案齊全" -ForegroundColor Green
    } else {
        $warnings += "缺少 TransPose／SMPL 檔案：網頁會顯示「推論錯誤」。在 external_paths.json 填好路徑後執行 python frontend\external_paths.py 確認。"
        Write-Host "[2/4] 缺少必要的外部檔案（見上方 MISSING）" -ForegroundColor Red
    }
} else {
    $warnings += "沒有 Python 環境，無法檢查外部檔案。"
    Write-Host "[2/4] 沒有 Python 環境，略過檢查" -ForegroundColor DarkGray
}

# ── 3. Rust 編譯 ──────────────────────────────────────────────────────────────
if (-not $SkipRust) {
    Write-Host "`n[3/4] 檢查 Rust 工具鏈..." -ForegroundColor Yellow
    if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
        Write-Host "Rust 未安裝，請至 https://rustup.rs/ 安裝後重新執行" -ForegroundColor Red
        exit 1
    }
    Write-Host "[3/4] Rust OK，開始編譯後端（約 2-5 分鐘）..." -ForegroundColor Yellow
    cargo build --release
    if ($LASTEXITCODE -ne 0) { Write-Host "編譯失敗" -ForegroundColor Red; exit 1 }
    Write-Host "[3/4] 後端編譯完成" -ForegroundColor Green
} else {
    Write-Host "`n[3/4] 跳過 Rust 編譯（-SkipRust）" -ForegroundColor DarkGray
}

# ── 4. 刷韌體（選用）────────────────────────────────────────────────────────
if ($FlashFirmware) {
    Write-Host "`n[4/4] 編譯並刷入韌體..." -ForegroundColor Yellow

    # 與 tools/calibrate_tracker.py 相同：先用專案內的 .arduino-cli，再找 PATH；
    # 都沒有時下載到 .arduino-cli（不進 git），之後校正工具也用得到。
    $cliDir = "$PSScriptRoot\.arduino-cli"
    $cliExe = "$cliDir\arduino-cli.exe"
    if (-not (Test-Path $cliExe)) {
        $onPath = Get-Command arduino-cli -ErrorAction SilentlyContinue
        if ($onPath) {
            $cliExe = $onPath.Source
        } else {
            $zip = "$env:TEMP\arduino-cli.zip"
            Invoke-WebRequest -Uri "https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Windows_64bit.zip" `
                -OutFile $zip -UseBasicParsing
            Expand-Archive -Path $zip -DestinationPath $cliDir -Force
        }
    }

    & $cliExe core update-index 2>$null | Out-Null
    & $cliExe core install arduino:mbed_nano 2>$null | Out-Null
    & $cliExe lib install ArduinoBLE Arduino_LSM9DS1 2>$null | Out-Null

    $sketch = "$PSScriptRoot\src\skeleton\tracker_firmware"
    $fqbn   = "arduino:mbed_nano:nano33ble"

    $boards = & $cliExe board list 2>$null | Select-String "Nano 33"
    if (-not $boards) {
        Write-Host "找不到 Arduino Nano 33 BLE，請插上 USB 後重新執行 -FlashFirmware" -ForegroundColor Red
    } else {
        & $cliExe compile --fqbn $fqbn $sketch
        if ($LASTEXITCODE -ne 0) { Write-Host "韌體編譯失敗" -ForegroundColor Red; exit 1 }
        foreach ($line in $boards) {
            $port = ($line -split "\s+")[0]
            Write-Host "  刷韌體 → $port（開機時請保持靜止約 5 秒）" -ForegroundColor Yellow
            & $cliExe upload --fqbn $fqbn --port $port $sketch
            if ($LASTEXITCODE -ne 0) { $warnings += "$port 刷韌體失敗，請重新插拔後再試。" }
        }
        Write-Host "[4/4] 韌體刷新結束" -ForegroundColor Green
    }
} else {
    Write-Host "`n[4/4] 跳過韌體（加 -FlashFirmware 可自動刷）" -ForegroundColor DarkGray
}

# ── 完成 ──────────────────────────────────────────────────────────────────────
if ($warnings) {
    Write-Host "`n=== 完成，但有待處理項目 ===" -ForegroundColor Yellow
    $warnings | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
} else {
    Write-Host "`n=== 完成！===" -ForegroundColor Green
}
Write-Host @"

啟動方式：
  共用主控介面：  .\run.ps1
  Combat 模式：   .\run.ps1 -Combat

檢查外部檔案：  $python frontend\external_paths.py
軟體測試：      powershell -NoProfile -File tests\run_software_checks.ps1

詳細說明見 HANDOFF.md
"@ -ForegroundColor Cyan
