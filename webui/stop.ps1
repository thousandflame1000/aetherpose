# Stops the services started by run.ps1, found by their listening ports.
# Saved as UTF-8 with BOM for Windows PowerShell 5.1; keep the BOM.
param(
    [int]$Port = 18080,
    [switch]$KeepBackend
)
$root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'services.ps1')
$ports = @(@{ Port=$Port; Kind='http' }, @{ Port=9010; Kind='bridge' })
if (-not $KeepBackend) { $ports += @{ Port=9009; Kind='backend' } }

foreach ($service in $ports) {
    $p = $service.Port
    $owners = @(Get-AetherListeners $p)
    if (-not $owners) { Write-Host "連接埠 $p：沒有服務在執行"; continue }
    foreach ($proc in $owners) {
        if (-not (Test-AetherService $proc $service.Kind $root)) {
            Write-Warning "連接埠 $p：不是本專案的程式（pid $($proc.ProcessId)），不關閉"
            continue
        }
        # /T also stops what the service started: a magnetometer calibration run and its arduino-cli
        # would otherwise keep compiling or flashing, holding the COM port, after the services are gone.
        taskkill /T /F /PID $proc.ProcessId *> $null
        if (Get-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue) { Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue }
        Write-Host "連接埠 $p：已關閉 $($proc.Name)（pid $($proc.ProcessId)）"
    }
}
