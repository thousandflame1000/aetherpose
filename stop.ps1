# Stops the services started by run.ps1 (page server, mesh_bridge, backend).
param(
    [int]$Port = 18080,
    [switch]$KeepBackend
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'webui\stop.ps1') @PSBoundParameters
