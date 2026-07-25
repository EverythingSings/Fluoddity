[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvRoot = Join-Path $repoRoot "venv"
$python = Join-Path $venvRoot "Scripts\python.exe"

if (-not (Test-Path $python)) {
    & py -3.12 -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the Python 3.12 virtual environment."
    }
}

& $python -m pip install --upgrade pip setuptools wheel
& $python -m pip install -r (Join-Path $repoRoot "requirements-optix-windows.txt")

$sitePackages = (& $python -c "import site; print(site.getsitepackages()[-1])").Trim()
$cudaRoot = Join-Path $sitePackages "nvidia\cu13"
$nvcc = Join-Path $cudaRoot "bin\nvcc.exe"
if (-not (Test-Path $nvcc)) {
    throw "The environment-local CUDA compiler was not installed at $nvcc."
}

& $python -c "import optix" 2>$null
if ($LASTEXITCODE -ne 0) {
    $vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) {
        throw "Visual Studio 2022 Build Tools with the C++ workload is required to build PyOptiX."
    }

    $vsRoot = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath).Trim()
    if (-not $vsRoot) {
        throw "Install the Visual Studio 2022 C++ build-tools workload, then rerun this script."
    }

    $vsDevCmd = Join-Path $vsRoot "Common7\Tools\VsDevCmd.bat"
    $cl = Get-ChildItem (Join-Path $vsRoot "VC\Tools\MSVC") -Recurse -Filter cl.exe |
        Where-Object FullName -Match "Hostx64\\x64\\cl.exe$" |
        Sort-Object FullName -Descending |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $cl) {
        throw "MSVC cl.exe was not found under $vsRoot."
    }

    $sdkBin = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Directory |
        Sort-Object Name -Descending |
        Where-Object { Test-Path (Join-Path $_.FullName "x64\rc.exe") } |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $sdkBin) {
        throw "A Windows 10/11 SDK with x64 resource tools is required to build PyOptiX."
    }
    $sdkTools = Join-Path $sdkBin "x64"
    $clForCmake = $cl.Replace("\", "/")

    $buildCommand = @(
        "call `"$vsDevCmd`" -arch=x64",
        "set `"CUDAToolkit_ROOT=$cudaRoot`"",
        "set `"PATH=$sdkTools;$cudaRoot\bin;%PATH%`"",
        "set `"CC=$clForCmake`"",
        "set `"CXX=$clForCmake`"",
        "`"$python`" -m pip install --no-cache-dir pyoptix==9.1.0"
    ) -join " && "

    & cmd.exe /d /c $buildCommand
    if ($LASTEXITCODE -ne 0) {
        throw "PyOptiX failed to build."
    }
}

$optixHeaders = Join-Path $venvRoot "optix-dev"
if (-not (Test-Path (Join-Path $optixHeaders "include\optix.h"))) {
    & git clone --depth 1 https://github.com/NVIDIA/optix-dev.git $optixHeaders
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to clone NVIDIA's public OptiX headers."
    }
}

$env:CUDA_PATH = $cudaRoot
$env:OPTIX_PATH = $optixHeaders
Push-Location $repoRoot
try {
    & $python compile_ptx.py
    if ($LASTEXITCODE -ne 0) {
        throw "Fluoddity's OptiX PTX compilation failed."
    }

    $probeSource = @'
import cupy as cp
from optix_renderer import OptiXSphereRenderer
from optix_pathtracer import PathTracerRenderer

print(f"CUDA device: {cp.cuda.runtime.getDeviceProperties(0)['name'].decode()}")
print(f"OptiX spheres available: {OptiXSphereRenderer.is_available()}")
print(f"OptiX path tracer available: {PathTracerRenderer.is_available()}")
'@
    $probeSource | & $python -
    if ($LASTEXITCODE -ne 0) {
        throw "The CUDA/OptiX runtime probe failed."
    }
}
finally {
    Pop-Location
}

Write-Host "OptiX environment ready. Run scripts\run_optix_windows.ps1"
