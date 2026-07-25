[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$FluoddityArgs
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot "venv\Scripts\python.exe"
$cudaRoot = Join-Path $repoRoot "venv\Lib\site-packages\nvidia\cu13"
$optixHeaders = Join-Path $repoRoot "venv\optix-dev"

if (-not (Test-Path $python) -or -not (Test-Path (Join-Path $optixHeaders "include\optix.h"))) {
    throw "OptiX environment is incomplete. Run scripts\setup_optix_windows.ps1 first."
}

$env:CUDA_PATH = $cudaRoot
$env:OPTIX_PATH = $optixHeaders

Push-Location $repoRoot
try {
    & $python -u main.py @FluoddityArgs
}
finally {
    Pop-Location
}
