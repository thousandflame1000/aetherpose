@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0AetherPose.exe" (
  start "" "%~dp0AetherPose.exe"
  exit /b 0
)
set "AETHER_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%AETHER_PYTHON%" set "AETHER_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if not exist "%AETHER_PYTHON%" (
  echo This is the source edition. For one-click use, download the Windows ZIP:
  echo https://github.com/thousandflame1000/aetherpose/releases
  echo Developers: run setup.ps1 and tools\setup_hybrid.ps1 -SkipGlobalPose first.
  pause
  exit /b 1
)
"%AETHER_PYTHON%" "%~dp0packaging\launcher.py"
if errorlevel 1 pause
