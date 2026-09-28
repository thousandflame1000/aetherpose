# Aether Combat launcher (keep this file ASCII: Windows PowerShell 5.1 misreads
# BOM-less UTF-8). Starts only the services that are not already running:
#   aetherpose.exe  (trackers over BLE -> ws://127.0.0.1:9009)
#   mesh_bridge.py  (TransPose body mesh -> ws://127.0.0.1:9010)
#   http.server     (this folder -> http://127.0.0.1:<Port>/)
# Stop them again with .\stop.ps1
param(
    [int]$Port = 18081,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'

$combat = $PSScriptRoot
$root = Split-Path $combat -Parent
$backend = Join-Path $root 'target\release\aetherpose.exe'
$python = @("$root\..\.venv\Scripts\python.exe", "$root\.venv\Scripts\python.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not (Test-Path $backend)) { throw "Backend not built: $backend (run ..\setup.ps1 or cargo build --release)" }
if (-not $python) { throw "Python venv not found next to aetherpose (run ..\setup.ps1)" }

function Test-Listening([int]$p) {
    [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

function Wait-Listening([int]$p, [int]$seconds, [string]$name, [string]$log) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while (-not (Test-Listening $p)) {
        if ((Get-Date) -gt $deadline) { throw "$name is not listening on port $p after ${seconds}s; see $log" }
        Start-Sleep -Milliseconds 300
    }
}

$viewer = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'imu_axes\.py' }
if ($viewer) {
    Write-Warning 'tools/imu_axes.py is running and may hold a tracker''s BLE link; close it so the backend can connect.'
}

if (Test-Listening 9009) {
    Write-Host 'backend     : already running (9009)'
} else {
    $log = Join-Path $root 'backend_run_stderr.log'
    Start-Process -FilePath $backend -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $root 'backend_run_stdout.log') -RedirectStandardError $log
    Wait-Listening 9009 20 'Backend' $log
    Write-Host "backend     : started (9009), log $log"
}

if (Test-Listening 9010) {
    Write-Host 'mesh_bridge : already running (9010)'
} else {
    $frontend = Join-Path $root 'frontend'
    $log = Join-Path $frontend 'mesh_bridge_stderr.log'
    Start-Process -FilePath $python -ArgumentList '-u', 'mesh_bridge.py' -WorkingDirectory $frontend -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $frontend 'mesh_bridge_stdout.log') -RedirectStandardError $log
    Wait-Listening 9010 90 'mesh_bridge' $log  # loading the TransPose model takes a while
    Write-Host "mesh_bridge : started (9010), log $log"
}

if (Test-Listening $Port) {
    Write-Host "page server : port $Port already in use (assuming it serves this folder)"
} else {
    $log = Join-Path $combat 'http_server.err.log'
    Start-Process -FilePath $python -ArgumentList '-m', 'http.server', $Port, '--bind', '127.0.0.1', '--directory', "`"$combat`"" `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $combat 'http_server.out.log') -RedirectStandardError $log
    Wait-Listening $Port 10 'Page server' $log
    Write-Host "page server : started ($Port)"
}

$url = "http://127.0.0.1:$Port/"
Write-Host "Aether Combat: $url"
if (-not $NoBrowser) { Start-Process $url }
