# Aetherpose 一鍵環境建立腳本
# 在 aetherpose 資料夾內執行：  .\setup.ps1
# 選用參數：
#   -SkipPython   跳過 Python 環境建立
#   -SkipRust     跳過 Rust 編譯
#   -FlashFirmware 自動下載 arduino-cli 並刷韌體

param(
    [switch]$SkipPython,
    [switch]$SkipRust,
    [switch]$FlashFirmware
)

Set-Location $PSScriptRoot
Write-Host "=== Aetherpose Setup ===" -ForegroundColor Cyan

# ── 1. Python venv ────────────────────────────────────────────────────────────
if (-not $SkipPython) {
    Write-Host "`n[1/3] 建立 Python 虛擬環境..." -ForegroundColor Yellow

    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Host "Python 未安裝，請先安裝 Python 3.10+  https://www.python.org/downloads/" -ForegroundColor Red
        exit 1
    }

    python -m venv .venv
    if (-not $?) { Write-Host "venv 建立失敗" -ForegroundColor Red; exit 1 }

    Write-Host "[1/3] 安裝 Python 套件（約 1-2 GB，需要一段時間）..." -ForegroundColor Yellow
    .\.venv\Scripts\python.exe -m pip install --upgrade pip -q
    .\.venv\Scripts\python.exe -m pip install -r frontend\requirements_freeze.txt
    if (-not $?) { Write-Host "pip install 失敗" -ForegroundColor Red; exit 1 }
    Write-Host "[1/3] Python 環境完成" -ForegroundColor Green
} else {
    Write-Host "`n[1/3] 跳過 Python（-SkipPython）" -ForegroundColor DarkGray
}

# ── 2. Rust 編譯 ──────────────────────────────────────────────────────────────
if (-not $SkipRust) {
    Write-Host "`n[2/3] 檢查 Rust 工具鏈..." -ForegroundColor Yellow
    if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
        Write-Host "Rust 未安裝，請至 https://rustup.rs/ 安裝後重新執行" -ForegroundColor Red
        exit 1
    }
    Write-Host "[2/3] Rust OK，開始編譯後端（約 2-5 分鐘）..." -ForegroundColor Yellow
    cargo build --release
    if (-not $?) { Write-Host "編譯失敗" -ForegroundColor Red; exit 1 }
    Write-Host "[2/3] 後端編譯完成" -ForegroundColor Green
} else {
    Write-Host "`n[2/3] 跳過 Rust 編譯（-SkipRust）" -ForegroundColor DarkGray
}

# ── 3. 刷韌體（選用）────────────────────────────────────────────────────────
if ($FlashFirmware) {
    Write-Host "`n[3/3] 下載 arduino-cli 並刷韌體..." -ForegroundColor Yellow

    $cliDir = "$env:TEMP\arduino-cli"
    $cliExe = "$cliDir\arduino-cli.exe"

    if (-not (Test-Path $cliExe)) {
        $zip = "$env:TEMP\arduino-cli.zip"
        Invoke-WebRequest -Uri "https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Windows_64bit.zip" `
            -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $cliDir -Force
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
        foreach ($line in $boards) {
            $port = ($line -split "\s+")[0]
            Write-Host "  刷韌體 → $port" -ForegroundColor Yellow
            & $cliExe upload --fqbn $fqbn --port $port $sketch 2>&1 | Select-String "Done|Error"
        }
        Write-Host "[3/3] 韌體刷新完成" -ForegroundColor Green
    }
} else {
    Write-Host "`n[3/3] 跳過韌體（加 -FlashFirmware 可自動刷）" -ForegroundColor DarkGray
}

# ── 完成 ──────────────────────────────────────────────────────────────────────
Write-Host "`n=== 完成！===" -ForegroundColor Green
Write-Host @"

啟動方式：
  終端 1（後端）：  .\target\release\aetherpose.exe
  終端 2（前端）：  cd frontend ; ..\.venv\Scripts\python.exe main.py

刷韌體：
  .\setup.ps1 -FlashFirmware

詳細說明見 HANDOFF.md
"@ -ForegroundColor Cyan
