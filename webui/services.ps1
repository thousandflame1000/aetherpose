# Shared service identity checks. Saved as UTF-8 with BOM for Windows PowerShell 5.1; keep the BOM.
function Test-AetherService($Process, [string]$Kind, [string]$ProjectRoot) {
    if (-not $Process) { return $false }
    $command = [string]$Process.CommandLine
    switch ($Kind) {
        'backend' { return $Process.ExecutablePath -eq (Join-Path $ProjectRoot 'target\release\aetherpose.exe') }
        'bridge' {
            $path = Join-Path $ProjectRoot 'frontend\mesh_bridge.py'
            return $command -match ('(?:^|\s)"' + [regex]::Escape($path) + '"(?:\s|$)')
        }
        'http' {
            $server = Join-Path $ProjectRoot 'webui\server.py'
            if ($command -match ('(?:^|\s)"' + [regex]::Escape($server) + '"(?:\s|$)')) { return $true }
            return Test-AetherLegacyHttp $Process $ProjectRoot
        }
    }
    return $false
}

function Get-AetherListeners([int]$Port) {
    $ownerIds = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($ownerId in $ownerIds) {
        Get-CimInstance Win32_Process -Filter "ProcessId=$ownerId" -ErrorAction SilentlyContinue
    }
}

function Test-AetherPort([int]$Port, [string]$Kind, [string]$ProjectRoot) {
    $listeners = @(Get-AetherListeners $Port)
    foreach ($listener in $listeners) {
        if (-not (Test-AetherService $listener $Kind $ProjectRoot)) {
            throw "連接埠 $Port 被其他程式占用（pid $($listener.ProcessId)）。請關掉它，或用 -Port 換一個頁面連接埠。"
        }
    }
    return $listeners.Count -gt 0
}

# The plain `python -m http.server` page server used before webui\server.py
# (no local tool API). Still recognised so it can be stopped or replaced.
function Test-AetherLegacyHttp($Process, [string]$ProjectRoot) {
    if (-not $Process) { return $false }
    $command = [string]$Process.CommandLine
    $path = Join-Path $ProjectRoot 'webui'
    return $command -match '(?:^|\s)-m\s+http\.server\s' -and
        $command -match ('--directory\s+"' + [regex]::Escape($path) + '"(?:\s|$)')
}
