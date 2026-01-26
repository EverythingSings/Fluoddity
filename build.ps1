# Build script for Fluoddity
# This script activates the virtual environment (if needed), runs PyInstaller, and fixes shader paths

Write-Host "=== Fluoddity Build Script ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Check if virtual environment is already activated, if not activate it
if ($env:VIRTUAL_ENV) {
    Write-Host "[1/3] Virtual environment already activated: $env:VIRTUAL_ENV" -ForegroundColor Green
} else {
    Write-Host "[1/3] Activating virtual environment..." -ForegroundColor Yellow
    & ".\Scratch.venv\Scripts\Activate.ps1"
    if (-not $env:VIRTUAL_ENV) {
        Write-Host "Error: Failed to activate virtual environment" -ForegroundColor Red
        exit 1
    }
}

# Step 2: Run PyInstaller
Write-Host "[2/3] Running PyInstaller..." -ForegroundColor Yellow
python -m PyInstaller --clean --noconfirm Fluoddity.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: PyInstaller build failed" -ForegroundColor Red
    exit 1
}

# Step 3: Move shaders folder to correct location
Write-Host "[3/3] Moving shaders folder..." -ForegroundColor Yellow
$shadersSource = "dist\Fluoddity\_internal\shaders"
$shadersDestination = "dist\Fluoddity\shaders"

if (Test-Path $shadersSource) {
    # Remove destination if it exists
    if (Test-Path $shadersDestination) {
        Remove-Item -Recurse -Force $shadersDestination
    }
    # Move shaders folder
    Move-Item -Path $shadersSource -Destination $shadersDestination
    Write-Host "Shaders folder moved successfully" -ForegroundColor Green
} else {
    Write-Host "Warning: Shaders folder not found at $shadersSource" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Build Complete! ===" -ForegroundColor Green
Write-Host "Executable location: dist\Fluoddity\Fluoddity.exe" -ForegroundColor Cyan
Write-Host ""
Write-Host "To test the build, run: .\dist\Fluoddity\Fluoddity.exe" -ForegroundColor Cyan
