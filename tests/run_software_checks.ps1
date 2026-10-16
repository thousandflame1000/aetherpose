# Complete software verification; no physical trackers required.
param([switch]$Live)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = @((Join-Path $root '..\.venv\Scripts\python.exe'), (Join-Path $root '.venv\Scripts\python.exe')) |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) { throw 'Project Python environment missing. Run setup.ps1 first.' }
function Invoke-Check([string]$Name, [scriptblock]$Action) {
    Write-Host "Checking $Name"
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit $LASTEXITCODE)" }
}
Push-Location $root
try {
    if (Get-Command node -ErrorAction SilentlyContinue) {
        # A syntax error in a page script would otherwise show only as a browser run without a result.
        Invoke-Check 'page script syntax' { foreach ($script in Get-ChildItem webui\*.js) { node --check $script.FullName; if ($LASTEXITCODE -ne 0) { break } } }
    }
    Invoke-Check 'browser' { & $python tests/test_webui_browser.py }
    Invoke-Check 'compact browser' { & $python tests/test_webui_browser.py --size 1000,760 }
    Invoke-Check 'mesh protocol' { & $python tests/test_mesh_bridge_protocol.py }
    Invoke-Check 'pose inference' { & $python tests/test_transpose_mesh.py }
    Invoke-Check 'CPU latency policy' { & $python tests/test_cpu_latency.py }
    Invoke-Check 'page skinning' { & $python tests/test_page_skinning.py }
    Invoke-Check 'pose model online' { & $python tests/test_transpose_online.py }
    Invoke-Check 'body calibration' { & $python tests/test_body_calibration.py }
    Invoke-Check 'WebSocket reconnect' { & $python tests/test_ws_client.py }
    Invoke-Check 'project integration' { & $python tests/test_project_integration.py }
    Invoke-Check 'IMU axes tool' { & $python tests/test_imu_axes.py }
    Invoke-Check 'magnetometer calibration tool' { & $python tests/test_calibrate_tracker.py }
    Invoke-Check 'tracker simulator' { & $python tests/test_simulate_trackers.py }
    Invoke-Check 'experiment evidence' { & $python tests/test_record_experiment.py }
    Invoke-Check 'annotated action evidence' { & $python tests/test_analyze_trials.py }
    Invoke-Check 'environment preflight' { & $python tests/test_check_environment.py }
    Invoke-Check 'source package' { & $python tests/test_package_submission.py }
    Invoke-Check 'performance observer' { & $python tests/test_profile_runtime.py }
    Invoke-Check 'IMU axes page' { & $python tests/test_imu_axes_page.py }
    Invoke-Check 'page server' { & $python tests/test_page_server.py }
    if (Get-Command node -ErrorAction SilentlyContinue) {
        Invoke-Check 'IMU axes page math' { node tests/imu_axes_math_test.cjs }
    } else { Write-Host 'Skipping IMU axes page math (Node.js not installed)' }
    Invoke-Check 'service identity' { powershell -NoProfile -File tests/test_service_identity.ps1 }
    # rustup puts cargo in ~/.cargo/bin, which a non-login shell may not have on PATH.
    $cargo = @((Get-Command cargo -ErrorAction SilentlyContinue).Source, (Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe')) |
        Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if ($cargo) {
        # A separate target folder: the running release backend locks target\release.
        Invoke-Check 'Rust tests' { & $cargo test --quiet --target-dir target_test }
        # Lints, when the clippy component is installed (rustup component add clippy).
        $clippy = $false
        try { & $cargo clippy --version *> $null; $clippy = $LASTEXITCODE -eq 0 } catch { }
        if ($clippy) {
            Invoke-Check 'Rust lints' { & $cargo clippy --quiet --target-dir target_test --all-targets -- -D warnings }
        } else { Write-Host 'Skipping Rust lints (clippy not installed)' }
    } else { Write-Host 'Skipping Rust tests (cargo not found)' }
    Invoke-Check 'whitespace' { git diff --check }
    if ($Live) {
        Invoke-Check 'external files' { & $python frontend/external_paths.py }
        Invoke-Check 'service launcher' { powershell -NoProfile -File run.ps1 -NoBrowser }
        Invoke-Check 'backend initial state' { & $python tests/check_backend_snapshot.py }
        Invoke-Check 'page server API' { & $python tests/check_page_server_live.py }
        Invoke-Check 'OSC output' { & $python tests/check_osc_live.py }
        Invoke-Check 'body calibration commands' { & $python tests/check_bridge_calibration_live.py }
        Invoke-Check 'recording' { & $python tests/check_recording_live.py }
        Invoke-Check 'live browser and all games' { & $python tests/check_webui_live.py }
        Invoke-Check 'live path with simulated trackers' { & $python tests/check_live_trackers.py }
        Invoke-Check 'headset and leg calibration (simulated)' { & $python tests/check_headset_live.py }
    }
    Write-Host 'PASS: software verification completed'
} finally { Pop-Location }
# Native tools may write successful diagnostics to stderr. Make the script's
# result explicit instead of inheriting PowerShell's last stream operation.
exit 0
