# Install local vision and the isolated GlobalPose runtime. No system Python changes.
param([switch]$SkipGlobalPose, [switch]$CpuOnly, [string]$RuntimeDirectory)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$external = Join-Path $root 'external'
$python = @((Join-Path $root '..\.venv\Scripts\python.exe'), (Join-Path $root '.venv\Scripts\python.exe')) |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) { throw 'Run setup.ps1 to create the main Python environment first.' }
New-Item -ItemType Directory -Force -Path (Join-Path $external 'vision') | Out-Null
& $python -m pip install 'mediapipe==0.10.32'
if ($LASTEXITCODE -ne 0) { throw 'MediaPipe installation failed.' }
$vision = Join-Path $external 'vision\pose_landmarker_lite.task'
if (-not (Test-Path $vision)) {
    Invoke-WebRequest 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task' -OutFile $vision
}
$fullVision = Join-Path $external 'vision\pose_landmarker_full.task'
if (-not (Test-Path $fullVision)) {
    Invoke-WebRequest 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task' -OutFile $fullVision
}
if ($SkipGlobalPose) { Write-Host 'Vision installed. GlobalPose installation skipped.'; exit 0 }
$runtime = if ($RuntimeDirectory) { [IO.Path]::GetFullPath($RuntimeDirectory) } else { Join-Path $external 'python38' }
$gpPython = Join-Path $runtime 'python.exe'
if (-not (Test-Path $gpPython)) {
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    $archive = Join-Path $external 'python38.zip'
    Invoke-WebRequest 'https://www.python.org/ftp/python/3.8.10/python-3.8.10-embed-amd64.zip' -OutFile $archive
    Expand-Archive -LiteralPath $archive -DestinationPath $runtime -Force
}
Set-Content -LiteralPath (Join-Path $runtime 'python38._pth') -Encoding ascii -Value @('python38.zip','.','Lib/site-packages','import site')
$pipBootstrap = Join-Path $external 'get-pip38.py'
& $gpPython -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
    Invoke-WebRequest 'https://bootstrap.pypa.io/pip/3.8/get-pip.py' -OutFile $pipBootstrap
    & $gpPython $pipBootstrap
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.8 pip bootstrap failed.' }
}
$cuda = -not $CpuOnly -and [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
if ($cuda) { & $gpPython -m pip install 'torch==2.0.1+cu118' --index-url https://download.pytorch.org/whl/cu118 }
else { & $gpPython -m pip install 'torch==2.0.1+cpu' --index-url https://download.pytorch.org/whl/cpu }
if ($LASTEXITCODE -ne 0) { throw 'GlobalPose PyTorch installation failed.' }
# numpy <1.24 retains aliases used by the original chumpy SMPL loader.
& $gpPython -m pip install 'numpy==1.23.5' 'scipy==1.10.1' 'qpsolvers[osqp]==4.3.3' 'chumpy==0.70' 'opencv-python==4.10.0.84' tqdm tensorboard thop 'numpy-quaternion==2023.0.4'
if ($LASTEXITCODE -ne 0) { throw 'GlobalPose dependencies failed.' }
$source = Join-Path $external 'GlobalPose'
if (-not (Test-Path (Join-Path $source 'net.py'))) {
    & git clone https://github.com/Xinyu-Yi/GlobalPose.git $source
    if ($LASTEXITCODE -ne 0) { throw 'GlobalPose download failed.' }
    & git -C $source checkout eef0e3b59b10104a80970261c3ad46d6c4681f29
    if ($LASTEXITCODE -ne 0) { throw 'GlobalPose revision checkout failed.' }
}
$weights = Join-Path $source 'data\weights.pt'
if (-not (Test-Path $weights)) {
    Invoke-WebRequest 'https://github.com/Xinyu-Yi/GlobalPose/raw/page/files/weights.pt' -OutFile $weights
}
$smpl = & $python -c "import sys;sys.path.insert(0,sys.argv[1]);import external_paths;print(external_paths.resolve()[0]['smpl_pkl'])" (Join-Path $root 'frontend')
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $smpl)) { throw 'Set smpl_pkl in external_paths.json to the licensed SMPL model first.' }
New-Item -ItemType Directory -Force -Path (Join-Path $source 'models') | Out-Null
Copy-Item -LiteralPath $smpl -Destination (Join-Path $source 'models\SMPL_male.pkl')
@{globalpose_dir=$source;globalpose_python=$gpPython} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'hybrid_paths.json') -Encoding utf8
Write-Host 'Hybrid installed. Restart the app, then enable vision on the preparation page.'
