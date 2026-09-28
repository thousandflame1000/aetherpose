# Stops the services started by run.ps1, found by their listening ports.
param(
    [int]$Port = 18080,
    [switch]$KeepBackend
)
$ports = @($Port, 9010)
if (-not $KeepBackend) { $ports += 9009 }

foreach ($p in $ports) {
    $owners = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    if (-not $owners) { Write-Host "port $p : nothing listening"; continue }
    foreach ($id in $owners) {
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        Write-Host "port $p : stopped $($proc.ProcessName) (pid $id)"
    }
}
