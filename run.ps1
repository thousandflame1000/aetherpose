Set-Location $PSScriptRoot
$vpy = "$PSScriptRoot\..\venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { $vpy = "$PSScriptRoot\..\..\.venv\Scripts\python.exe" }
if (-not (Test-Path $vpy)) { $vpy = "d:\Download\G_project\G_project\.venv\Scripts\python.exe" }

Get-Process | Where-Object { $_.Name -match "aetherpose|python" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

Start-Process -FilePath "$PSScriptRoot\target\release\aetherpose.exe" -WorkingDirectory $PSScriptRoot -WindowStyle Normal
Start-Sleep -Seconds 3

Start-Process -FilePath $vpy -ArgumentList "main.py" -WorkingDirectory "$PSScriptRoot\frontend" -WindowStyle Normal
