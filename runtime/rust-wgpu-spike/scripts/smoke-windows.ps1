param(
    [string]$TrialPath = "artifacts/trial_definitions.json",
    [string]$TrialId = "rival_bloom",
    [string]$ConfigPath = "physics_configs/Core/Bubbles.json",
    [int]$Frames = 24,
    [int]$MaxWindowFrames = 5,
    [string]$ArtifactsDir = "artifacts/native-wgpu",
    [switch]$SkipWindow,
    [switch]$NoSign
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "../../..")
$crateManifest = Join-Path $repoRoot "runtime/rust-wgpu-spike/Cargo.toml"
$releaseExe = Join-Path $repoRoot "runtime/rust-wgpu-spike/target/release/fluoddity-wgpu-spike.exe"
$artifactRoot = Join-Path $repoRoot $ArtifactsDir
$signedExe = Join-Path $artifactRoot "fluoddity-wgpu-spike.exe"
$frameOut = Join-Path $artifactRoot "wgpu_spike_text_overlay.ppm"
$timingOut = Join-Path $artifactRoot "wgpu_deck_timing_smoke.json"

function Invoke-Step {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "command failed with exit code $LASTEXITCODE"
    }
}

function Invoke-CheckedOutput {
    param([scriptblock]$Command)
    $output = & $Command 2>&1
    $exitCode = $LASTEXITCODE
    $output | ForEach-Object { Write-Host $_ }
    if ($exitCode -ne 0) {
        throw "command failed with exit code $exitCode"
    }
    return [string]::Join("`n", @($output))
}

function Sign-IfAvailable {
    param([string]$Path)
    if ($NoSign) {
        return
    }
    $cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
        Where-Object { $_.Subject -eq "CN=Dissipa Local Developer Code Signing" } |
        Select-Object -First 1
    if ($null -eq $cert) {
        $cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Select-Object -First 1
    }
    if ($null -eq $cert) {
        Write-Warning "No code-signing certificate found; WDAC may block the native binary."
        return
    }
    Set-AuthenticodeSignature -FilePath $Path -Certificate $cert -TimestampServer "http://timestamp.digicert.com" | Out-Null
}

Push-Location $repoRoot
try {
    if (-not (Test-Path $TrialPath)) {
        throw "Missing $TrialPath. Run python scripts/export_trial_definitions.py first."
    }
    New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null

    Invoke-Step { cargo build --manifest-path $crateManifest --release }
    Copy-Item -Force $releaseExe $signedExe
    Sign-IfAvailable -Path $signedExe

    $headlessOutput = Invoke-CheckedOutput {
        & $signedExe `
            --trial $TrialPath `
            --trial-id $TrialId `
            --config $ConfigPath `
            --frames $Frames `
            --out $frameOut
    }
    if ($headlessOutput -notmatch "trial_runtime_state status=1") {
        throw "native headless smoke did not report running trial state"
    }
    if ($headlessOutput -notmatch "active_zones=[1-9]") {
        throw "native headless smoke did not activate any objective zone"
    }
    if ($headlessOutput -notmatch "hazard_rate=0\.0000 boundary_conditions=2 initial_conditions=0 num_cohorts=64 disable_symmetry=false absolute_orientation=0 orientation_mix=1\.000 hue_sensitivity=0\.073 color_by_cohort=false parameter_sweeps_enabled=false") {
        throw "native headless smoke did not load saved boundary/reset/cohort/orientation/appearance settings"
    }

    if (-not $SkipWindow) {
        $windowOutput = Invoke-CheckedOutput {
            & $signedExe `
                --trial $TrialPath `
                --trial-id $TrialId `
                --config $ConfigPath `
                --deck-profile `
                --max-window-frames $MaxWindowFrames `
                --timing-report $timingOut
        }
        if ($windowOutput -notmatch "wgpu_window_timing") {
            throw "native window smoke did not report timing"
        }
        if ($windowOutput -notmatch "hazard_rate=0\.0000 boundary_conditions=2 initial_conditions=0 num_cohorts=64 disable_symmetry=false absolute_orientation=0 orientation_mix=1\.000 hue_sensitivity=0\.073 color_by_cohort=false parameter_sweeps_enabled=false") {
            throw "native window smoke did not load saved boundary/reset/cohort/orientation/appearance settings"
        }
    }

    Write-Host "native_wgpu_smoke=ok"
    Write-Host "native_wgpu_binary=$signedExe"
    Write-Host "native_wgpu_frame=$frameOut"
    if (-not $SkipWindow) {
        Write-Host "native_wgpu_timing=$timingOut"
    }
}
finally {
    Pop-Location
}
