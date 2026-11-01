param([int]$Port=18082,[string]$DataDirectory,[string]$StaticDirectory)
$ErrorActionPreference='Stop'
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$listener=Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if($listener){
 $owner=Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
 if($owner.CommandLine -match 'hybrid_simulation[\\/]server\.py') {Write-Host "Simulation already running: http://127.0.0.1:$Port/";exit 0}
 throw "Port $Port is occupied by another application; choose a different -Port."
}
$settings=@{}
$config=Join-Path $root 'simulation_paths.json'
if(Test-Path -LiteralPath $config){$settings=Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json}
if(-not $DataDirectory){$DataDirectory=if($settings.data_dir){$settings.data_dir}else{Join-Path $root 'external\hybrid_simulation'}}
if(-not $StaticDirectory){$StaticDirectory=if($settings.static_dir){$settings.static_dir}else{Join-Path $PSScriptRoot 'web'}}
if(-not(Test-Path -LiteralPath (Join-Path $DataDirectory 'truth.npz'))){throw 'Simulation data missing. Run build_dataset.py --output-dir PATH first.'}
$python=@((Join-Path $root '..\.venv\Scripts\python.exe'),(Join-Path $root '.venv\Scripts\python.exe')) | Where-Object {Test-Path -LiteralPath $_} | Select-Object -First 1
if(-not $python){throw 'Project Python environment missing.'}
New-Item -ItemType Directory -Path $StaticDirectory -Force | Out-Null
$sourceWeb=Join-Path $PSScriptRoot 'web'
if([IO.Path]::GetFullPath($sourceWeb) -ne [IO.Path]::GetFullPath($StaticDirectory)){
 foreach($asset in Get-ChildItem -LiteralPath $sourceWeb -File){Copy-Item -LiteralPath $asset.FullName -Destination (Join-Path $StaticDirectory $asset.Name) -Force}
}
foreach($document in @(@('EXPERIMENT.md','report.md'),@('README.md','README.md'))){
 $source=Join-Path $PSScriptRoot $document[0]
 if(Test-Path -LiteralPath $source){Copy-Item -LiteralPath $source -Destination (Join-Path $StaticDirectory $document[1]) -Force}
}
foreach($mode in @('clear','occluded')){
 $movie=Join-Path $DataDirectory "$mode\camera.mp4"
 if(Test-Path -LiteralPath $movie){Copy-Item -LiteralPath $movie -Destination (Join-Path $StaticDirectory "$mode.mp4") -Force}
}
Write-Host "Simulation: http://127.0.0.1:$Port/ (Ctrl+C to stop)"
& $python (Join-Path $PSScriptRoot 'server.py') --data-dir $DataDirectory --static-dir $StaticDirectory --port $Port
exit $LASTEXITCODE
