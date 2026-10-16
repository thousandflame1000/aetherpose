# Default entry point: Aetherpose controls and Combat share the browser scene.
param(
    [int]$Port = 18080,
    [switch]$Combat,
    [switch]$NoBrowser,
    [switch]$Restart
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'webui\run.ps1') @PSBoundParameters
