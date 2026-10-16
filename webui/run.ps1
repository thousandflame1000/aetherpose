# Aetherpose web UI launcher. Saved as UTF-8 with BOM: Windows PowerShell 5.1
# misreads BOM-less UTF-8, so keep the BOM when editing. Starts only the
# services that are not running yet:
#   aetherpose.exe  (trackers over BLE -> ws://127.0.0.1:9009)
#   mesh_bridge.py  (TransPose body mesh -> ws://127.0.0.1:9010)
#   server.py       (this folder + local tool API -> http://127.0.0.1:<Port>/)
# All modes use one URL; -Combat opens it on the 對打 tab. Stop with .\stop.ps1
param(
    [int]$Port = 18080,
    [switch]$Combat,
    [switch]$NoBrowser,
    [switch]$Restart   # stop the running services first, e.g. after updating the code
)
$ErrorActionPreference = 'Stop'
if ($Restart) { & (Join-Path $PSScriptRoot 'stop.ps1') -Port $Port }

$webui = $PSScriptRoot
$root = Split-Path $webui -Parent
. (Join-Path $webui 'services.ps1')
if ($Port -lt 1024 -or $Port -gt 65535 -or $Port -in @(9009, 9010)) { throw '頁面連接埠必須在 1024-65535 之間，且不能是 9009 或 9010。' }
$backend = Join-Path $root 'target\release\aetherpose.exe'
$python = @("$root\..\.venv\Scripts\python.exe", "$root\.venv\Scripts\python.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not (Test-Path $backend)) { throw "後端還沒編譯：$backend（請執行 ..\setup.ps1 或 cargo build --release）" }
if (-not $python) { throw "找不到 aetherpose 旁邊的 Python 環境（請執行 ..\setup.ps1）" }
# Every service writes its output to aetherpose\logs.
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null
# Check every port before starting any service.
$backendRunning = Test-AetherPort 9009 'backend' $root
$bridgeRunning = Test-AetherPort 9010 'bridge' $root
$httpRunning = Test-AetherPort $Port 'http' $root

function Test-Listening([int]$p) {
    [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

function Wait-Listening([int]$p, [int]$seconds, [string]$name, [string]$log) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while (-not (Test-Listening $p)) {
        if ((Get-Date) -gt $deadline) { throw "$name 在 ${seconds} 秒內沒有開始監聽連接埠 $p，請看 $log" }
        Start-Sleep -Milliseconds 300
    }
}

$viewer = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'imu_axes\.py' -and $_.CommandLine -notmatch '--ws' }
if ($viewer) {
    Write-Warning 'tools/imu_axes.py 正透過藍牙連著追蹤器，可能占住它；請先關掉，後端才能連線。'
}

# A backend older than its Rust source would run outdated code after an update.
$sources = @(Get-ChildItem (Join-Path $root 'src') -Recurse -Filter *.rs) +
    @(Get-Item (Join-Path $root 'Cargo.toml'), (Join-Path $root 'Cargo.lock') -ErrorAction SilentlyContinue)
$newestSource = ($sources | Measure-Object LastWriteTime -Maximum).Maximum
$backendStale = $newestSource -gt (Get-Item $backend).LastWriteTime
if ($backendRunning) {
    Write-Host '後端：已在執行（連接埠 9009）'
    if ($backendStale) { Write-Warning '後端程式碼比執行中的版本新：用 .\run.ps1 -Restart 重新編譯並啟動。' }
} else {
    if ($backendStale) {
        # rustup puts cargo in ~/.cargo/bin, which a non-login shell may not have on PATH.
        $cargo = @((Get-Command cargo -ErrorAction SilentlyContinue).Source, (Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe')) |
            Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
        if ($cargo) {
            Write-Host '後端：程式碼比執行檔新，重新編譯中（cargo build --release）…'
            Push-Location $root
            try { & $cargo build --release --quiet } finally { Pop-Location }
            if ($LASTEXITCODE -ne 0) { throw '後端編譯失敗，請看上方的錯誤訊息。' }
        } else {
            Write-Warning '後端程式碼比執行檔新，但找不到 cargo：先啟動舊版（安裝 Rust 後執行 cargo build --release）。'
        }
    }
    $log = Join-Path $logs 'backend.err.log'
    Start-Process -FilePath $backend -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs 'backend.out.log') -RedirectStandardError $log
    Wait-Listening 9009 20 '後端' $log
    Write-Host "後端：已啟動（連接埠 9009），記錄檔 $log"
}

if ($bridgeRunning) {
    Write-Host '姿態服務：已在執行（連接埠 9010）'
} else {
    $frontend = Join-Path $root 'frontend'
    $log = Join-Path $logs 'mesh_bridge.err.log'
    Start-Process -FilePath $python -ArgumentList '-u', "`"$(Join-Path $frontend 'mesh_bridge.py')`"" -WorkingDirectory $frontend -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs 'mesh_bridge.out.log') -RedirectStandardError $log
    Wait-Listening 9010 90 '姿態服務 mesh_bridge' $log  # loading the TransPose model takes a while
    Write-Host "姿態服務：已啟動（連接埠 9010），記錄檔 $log"
}

if ($httpRunning) {
    # The older plain http.server has no local tool API: replace it with webui\server.py.
    $legacy = @(Get-AetherListeners $Port | Where-Object { Test-AetherLegacyHttp $_ $root })
    foreach ($proc in $legacy) { Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue }
    if ($legacy) {
        $deadline = (Get-Date).AddSeconds(5)
        while ((Test-Listening $Port) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
        Write-Host '頁面伺服器：換掉舊的 http.server'
        $httpRunning = $false
    }
}
if ($httpRunning) {
    Write-Host "頁面伺服器：已在執行（連接埠 $Port）"
} else {
    $log = Join-Path $logs 'http_server.err.log'
    Start-Process -FilePath $python -ArgumentList '-u', "`"$(Join-Path $webui 'server.py')`"", '--port', $Port `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'http_server.out.log') -RedirectStandardError $log
    Wait-Listening $Port 10 '頁面伺服器' $log
    Write-Host "頁面伺服器：已啟動（連接埠 $Port）"
}

$url = "http://127.0.0.1:$Port/"
if ($Combat) { $url += '#combat' }  # the page opens the 對打 tab, then drops the #combat
Write-Host "Aetherpose 介面：$url"
if (-not $NoBrowser) { Start-Process $url }
