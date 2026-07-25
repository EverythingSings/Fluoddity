param(
    [string]$Python = "python",
    [string]$OutputDir = "dist/FluoddityNative",
    [string]$TrialId = "rival_bloom",
    [string]$ConfigPath = "physics_configs/Core/Bubbles.json",
    [switch]$NoSign
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../../..")).Path
$crateManifest = Join-Path $repoRoot "runtime/rust-wgpu-spike/Cargo.toml"
$releaseExe = Join-Path $repoRoot "runtime/rust-wgpu-spike/target/release/fluoddity-wgpu-spike.exe"
$distRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot "dist"))
$packageRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDir))
$distPrefix = $distRoot.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if ($packageRoot -eq $distRoot -or -not $packageRoot.StartsWith($distPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must resolve to a child directory of $distRoot; got $packageRoot"
}
$steamExeName = "XenocultureTrialDish.exe"
$compatExeName = "fluoddity-wgpu-spike.exe"

function Invoke-Step {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "command failed with exit code $LASTEXITCODE"
    }
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
        Write-Warning "No code-signing certificate found; WDAC may block the packaged binary."
        return
    }
    Set-AuthenticodeSignature -FilePath $Path -Certificate $cert -TimestampServer "http://timestamp.digicert.com" | Out-Null
}

function Resolve-FfmpegBundle {
    $command = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        $command = Get-Command ffmpeg -ErrorAction SilentlyContinue
    }
    if ($null -eq $command) {
        throw "FFmpeg with libx264 is required to build the native video-export package."
    }
    $source = $command.Source
    $encoders = & $source -hide_banner -encoders 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0 -or $encoders -notmatch "\blibx264\b") {
        throw "FFmpeg at $source does not expose the required libx264 encoder."
    }
    $bundleRoot = Split-Path (Split-Path $source -Parent) -Parent
    $license = @(
        (Join-Path $bundleRoot "LICENSE"),
        (Join-Path $bundleRoot "LICENSE.txt"),
        (Join-Path $bundleRoot "COPYING.GPLv3")
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $license) {
        throw "Could not find an FFmpeg license beside the selected bundle at $bundleRoot."
    }
    return [pscustomobject]@{
        Source = $source
        License = $license
        Version = (& $source -version | Select-Object -First 1)
    }
}

Push-Location $repoRoot
try {
    $ffmpegBundle = Resolve-FfmpegBundle
    Invoke-Step { & $Python scripts/export_trial_definitions.py --output artifacts/trial_definitions.json }
    Invoke-Step { cargo build --manifest-path $crateManifest --release }

    if (Test-Path $packageRoot) {
        Remove-Item -Recurse -Force $packageRoot
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "artifacts") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "physics_configs/Core") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "steam_input/glyphs") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "third_party/ffmpeg") | Out-Null

    Copy-Item -Force $releaseExe (Join-Path $packageRoot $steamExeName)
    Copy-Item -Force $releaseExe (Join-Path $packageRoot $compatExeName)
    Copy-Item -Force "artifacts/trial_definitions.json" (Join-Path $packageRoot "artifacts/trial_definitions.json")
    Copy-Item -Force "physics_configs/Core/*" (Join-Path $packageRoot "physics_configs/Core")
    Copy-Item -Force $ffmpegBundle.Source (Join-Path $packageRoot "ffmpeg.exe")
    Copy-Item -Force $ffmpegBundle.License (Join-Path $packageRoot "third_party/ffmpeg/LICENSE")
    @"
Component: FFmpeg
Packaged executable: ffmpeg.exe
Source executable: $($ffmpegBundle.Source)
Version: $($ffmpegBundle.Version)
Required encoder: libx264
License file: third_party/ffmpeg/LICENSE
Packaged by: runtime/rust-wgpu-spike/scripts/package-windows.ps1
"@ | Set-Content -Encoding UTF8 (Join-Path $packageRoot "third_party/ffmpeg/PROVENANCE.txt")
    Copy-Item -Force "runtime/rust-wgpu-spike/README.md" (Join-Path $packageRoot "README.md")
    Copy-Item -Force "steam_input/README.md" (Join-Path $packageRoot "steam_input/README.md")
    Copy-Item -Force "steam_input/steam_input_manifest.vdf" (Join-Path $packageRoot "steam_input/steam_input_manifest.vdf")
    Copy-Item -Force "steam_input/trial_prompt_glyph_map.json" (Join-Path $packageRoot "steam_input/trial_prompt_glyph_map.json")
    Copy-Item -Force "steam_input/glyphs/*" (Join-Path $packageRoot "steam_input/glyphs")
    Invoke-Step { & $Python scripts/write_steam_input_handoff.py --output (Join-Path $packageRoot "steam_input/steam_input_handoff.md") }
    Sign-IfAvailable -Path (Join-Path $packageRoot $steamExeName)
    Sign-IfAvailable -Path (Join-Path $packageRoot $compatExeName)
    Sign-IfAvailable -Path (Join-Path $packageRoot "ffmpeg.exe")

    @"
param(
    [int]`$Frames = 24,
    [string]`$TrialId = "$TrialId"
)
`$ErrorActionPreference = "Stop"
Set-Location `$PSScriptRoot
.\fluoddity-wgpu-spike.exe --trial artifacts/trial_definitions.json --trial-id `$TrialId --config physics_configs/Core/Bubbles.json --frames `$Frames --out artifacts/wgpu_spike_frame.ppm
"@ | Set-Content -Encoding ASCII (Join-Path $packageRoot "run_headless.ps1")

    @"
param(
    [double]`$Seconds = 10,
    [int]`$Width = 3840,
    [int]`$Height = 2160,
    [int]`$Fps = 60,
    [int]`$Crf = 15,
    [string]`$Preset = "slow",
    [string]`$TrialId = "$TrialId",
    [string]`$ConfigPath = "physics_configs/Core/Bubbles.json",
    [string]`$OutputPath = ""
)
`$ErrorActionPreference = "Stop"
`$callerPath = (Get-Location).Path
Set-Location `$PSScriptRoot
if ([string]::IsNullOrWhiteSpace(`$OutputPath)) {
    `$videoDir = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Fluoddity\Videos"
    New-Item -ItemType Directory -Force -Path `$videoDir | Out-Null
    `$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    `$OutputPath = Join-Path `$videoDir "Xenoculture-`$TrialId-`$timestamp.mp4"
}
elseif (-not [IO.Path]::IsPathRooted(`$OutputPath)) {
    `$OutputPath = [IO.Path]::GetFullPath((Join-Path `$callerPath `$OutputPath))
}
`$outputDir = Split-Path -Parent `$OutputPath
if (`$outputDir) {
    New-Item -ItemType Directory -Force -Path `$outputDir | Out-Null
}
`$reportPath = [IO.Path]::ChangeExtension(`$OutputPath, ".json")
& ".\$steamExeName" --trial artifacts/trial_definitions.json --trial-id `$TrialId --config `$ConfigPath --video-out `$OutputPath --video-report `$reportPath --video-seconds `$Seconds --render-width `$Width --render-height `$Height --video-fps `$Fps --video-crf `$Crf --video-preset `$Preset --ffmpeg ".\ffmpeg.exe"
if (`$LASTEXITCODE -ne 0) {
    exit `$LASTEXITCODE
}
Write-Host "native_video_export=`$OutputPath"
Write-Host "native_video_report=`$reportPath"
"@ | Set-Content -Encoding ASCII (Join-Path $packageRoot "run_export_video.ps1")

    @"
param(
    [int]`$Width = 3840,
    [int]`$Height = 2160,
    [int]`$Fps = 60,
    [int]`$Crf = 15,
    [string]`$Preset = "fast",
    [string]`$TrialId = "$TrialId",
    [string]`$ConfigPath = "physics_configs/Core/Bubbles.json",
    [string]`$OutputPath = ""
)
`$ErrorActionPreference = "Stop"
if (`$Fps -ne 60) {
    throw "run_record_video.ps1 supports only 60 FPS window frame capture. Use run_export_video.ps1 for other frame rates."
}
`$callerPath = (Get-Location).Path
Set-Location `$PSScriptRoot
if ([string]::IsNullOrWhiteSpace(`$OutputPath)) {
    `$videoDir = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Fluoddity\Videos"
    New-Item -ItemType Directory -Force -Path `$videoDir | Out-Null
    `$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    `$OutputPath = Join-Path `$videoDir "Xenoculture-frame-capture-`$TrialId-`$timestamp.mp4"
}
elseif (-not [IO.Path]::IsPathRooted(`$OutputPath)) {
    `$OutputPath = [IO.Path]::GetFullPath((Join-Path `$callerPath `$OutputPath))
}
`$outputDir = Split-Path -Parent `$OutputPath
if (`$outputDir) {
    New-Item -ItemType Directory -Force -Path `$outputDir | Out-Null
}
`$reportPath = [IO.Path]::ChangeExtension(`$OutputPath, ".json")
& ".\$steamExeName" --trial artifacts/trial_definitions.json --trial-id `$TrialId --config `$ConfigPath --window --video-out `$OutputPath --video-report `$reportPath --render-width `$Width --render-height `$Height --video-fps `$Fps --video-crf `$Crf --video-preset `$Preset --ffmpeg ".\ffmpeg.exe"
if (`$LASTEXITCODE -ne 0) {
    exit `$LASTEXITCODE
}
Write-Host "native_window_frame_capture=`$OutputPath"
Write-Host "native_video_report=`$reportPath"
"@ | Set-Content -Encoding ASCII (Join-Path $packageRoot "run_record_video.ps1")

    @"
param(
    [string]`$TrialId = "$TrialId"
)
`$ErrorActionPreference = "Stop"
Set-Location `$PSScriptRoot
.\$steamExeName --trial artifacts/trial_definitions.json --trial-id `$TrialId --config physics_configs/Core/Bubbles.json --window
"@ | Set-Content -Encoding ASCII (Join-Path $packageRoot "run_steam_deck.ps1")

    @"
param(
    [int]`$MaxWindowFrames = 3600,
    [string]`$TrialId = "$TrialId"
)
`$ErrorActionPreference = "Stop"
Set-Location `$PSScriptRoot
.\fluoddity-wgpu-spike.exe --trial artifacts/trial_definitions.json --trial-id `$TrialId --config physics_configs/Core/Bubbles.json --deck-profile --max-window-frames `$MaxWindowFrames --timing-report artifacts/wgpu_deck_timing.json
"@ | Set-Content -Encoding ASCII (Join-Path $packageRoot "run_deck_profile.ps1")

    @"
`$ErrorActionPreference = "Stop"
Set-Location `$PSScriptRoot
.\fluoddity-wgpu-spike.exe --dump-input-contract artifacts/native_input_contract.json
"@ | Set-Content -Encoding ASCII (Join-Path $packageRoot "run_input_contract.ps1")

    @"
param(
    [string]`$TrialId = "$TrialId"
)
`$ErrorActionPreference = "Stop"
Set-Location `$PSScriptRoot
.\fluoddity-wgpu-spike.exe --trial artifacts/trial_definitions.json --trial-id `$TrialId --config physics_configs/Core/Bubbles.json --dump-input-smoke artifacts/native_input_runtime.json
"@ | Set-Content -Encoding ASCII (Join-Path $packageRoot "run_input_runtime.ps1")

    @"
#!/usr/bin/env bash
set -euo pipefail
cd "`$(dirname "`$0")"
MAX_WINDOW_FRAMES="`${MAX_WINDOW_FRAMES:-3600}"
TRIAL_ID="`${TRIAL_ID:-$TrialId}"
exec ./fluoddity-wgpu-spike --trial artifacts/trial_definitions.json --trial-id "`$TRIAL_ID" --config physics_configs/Core/Bubbles.json --deck-profile --max-window-frames "`$MAX_WINDOW_FRAMES" --timing-report artifacts/wgpu_deck_timing.json
"@ | Set-Content -Encoding ASCII (Join-Path $packageRoot "run_deck_profile.sh")

    @"
#!/usr/bin/env bash
set -euo pipefail
cd "`$(dirname "`$0")"
TRIAL_ID="`${TRIAL_ID:-$TrialId}"
if [ ! -x ./XenocultureTrialDish ]; then
  echo "Deck/Linux Steam launch target ./XenocultureTrialDish is missing. Build this package with runtime/rust-wgpu-spike/scripts/package-deck.sh on Linux/Steam Deck." >&2
  exit 2
fi
exec ./XenocultureTrialDish --trial artifacts/trial_definitions.json --trial-id "`$TRIAL_ID" --config physics_configs/Core/Bubbles.json --window
"@ | Set-Content -Encoding ASCII (Join-Path $packageRoot "run_steam_deck.sh")

    @"
#!/usr/bin/env bash
set -euo pipefail
cd "`$(dirname "`$0")"
if [ ! -x ./XenocultureTrialDish ] || [ ! -x ./ffmpeg ]; then
  echo "Deck/Linux video export requires the native package from package-deck.sh, including its static FFmpeg bundle." >&2
  exit 2
fi
TRIAL_ID="`${TRIAL_ID:-$TrialId}"
CONFIG_PATH="`${CONFIG_PATH:-physics_configs/Core/Bubbles.json}"
DURATION_SECONDS="`${DURATION_SECONDS:-10}"
WIDTH="`${WIDTH:-3840}"
HEIGHT="`${HEIGHT:-2160}"
FPS="`${FPS:-60}"
CRF="`${CRF:-15}"
PRESET="`${PRESET:-slow}"
if [ -z "`${OUTPUT_PATH:-}" ]; then
  VIDEO_DIR="`${XDG_VIDEOS_DIR:-`$HOME/Videos}/Fluoddity"
  mkdir -p "`$VIDEO_DIR"
  OUTPUT_PATH="`$VIDEO_DIR/Xenoculture-`$TRIAL_ID-`$(date +%Y-%m-%d_%H-%M-%S).mp4"
fi
REPORT_PATH="`${OUTPUT_PATH%.*}.json"
exec ./XenocultureTrialDish --trial artifacts/trial_definitions.json --trial-id "`$TRIAL_ID" --config "`$CONFIG_PATH" --video-out "`$OUTPUT_PATH" --video-report "`$REPORT_PATH" --video-seconds "`$DURATION_SECONDS" --render-width "`$WIDTH" --render-height "`$HEIGHT" --video-fps "`$FPS" --video-crf "`$CRF" --video-preset "`$PRESET" --ffmpeg ./ffmpeg
"@ | Set-Content -Encoding ASCII (Join-Path $packageRoot "run_export_video.sh")

    @"
#!/usr/bin/env bash
set -euo pipefail
cd "`$(dirname "`$0")"
if [ ! -x ./XenocultureTrialDish ] || [ ! -x ./ffmpeg ]; then
  echo "Deck/Linux video recording requires the native package from package-deck.sh, including its static FFmpeg bundle." >&2
  exit 2
fi
TRIAL_ID="`${TRIAL_ID:-$TrialId}"
CONFIG_PATH="`${CONFIG_PATH:-physics_configs/Core/Bubbles.json}"
WIDTH="`${WIDTH:-3840}"
HEIGHT="`${HEIGHT:-2160}"
FPS="`${FPS:-60}"
CRF="`${CRF:-15}"
PRESET="`${PRESET:-fast}"
if [[ "`$FPS" != "60" ]]; then
  echo "run_record_video.sh supports only 60 FPS window frame capture. Use run_export_video.sh for other frame rates." >&2
  exit 2
fi
if [ -z "`${OUTPUT_PATH:-}" ]; then
  VIDEO_DIR="`${XDG_VIDEOS_DIR:-`$HOME/Videos}/Fluoddity"
  mkdir -p "`$VIDEO_DIR"
  OUTPUT_PATH="`$VIDEO_DIR/Xenoculture-frame-capture-`$TRIAL_ID-`$(date +%Y-%m-%d_%H-%M-%S).mp4"
fi
REPORT_PATH="`${OUTPUT_PATH%.*}.json"
exec ./XenocultureTrialDish --trial artifacts/trial_definitions.json --trial-id "`$TRIAL_ID" --config "`$CONFIG_PATH" --window --video-out "`$OUTPUT_PATH" --video-report "`$REPORT_PATH" --render-width "`$WIDTH" --render-height "`$HEIGHT" --video-fps "`$FPS" --video-crf "`$CRF" --video-preset "`$PRESET" --ffmpeg ./ffmpeg
"@ | Set-Content -Encoding ASCII (Join-Path $packageRoot "run_record_video.sh")

    @"
#!/usr/bin/env bash
set -euo pipefail
cd "`$(dirname "`$0")"
exec ./fluoddity-wgpu-spike --dump-input-contract artifacts/native_input_contract.json
"@ | Set-Content -Encoding ASCII (Join-Path $packageRoot "run_input_contract.sh")

    @"
#!/usr/bin/env bash
set -euo pipefail
cd "`$(dirname "`$0")"
TRIAL_ID="`${TRIAL_ID:-$TrialId}"
exec ./fluoddity-wgpu-spike --trial artifacts/trial_definitions.json --trial-id "`$TRIAL_ID" --config physics_configs/Core/Bubbles.json --dump-input-smoke artifacts/native_input_runtime.json
"@ | Set-Content -Encoding ASCII (Join-Path $packageRoot "run_input_runtime.sh")

    @'
# Fluoddity Native Runtime Package

This is the Rust/wgpu native runtime candidate package.

Steam-facing Windows executable: `XenocultureTrialDish.exe`

Steam Input handoff files are bundled under `steam_input/`.

Run a headless nonblank capture on Windows:

    .\run_headless.ps1

Run the player-facing native Steam/Deck launch on Windows:

    .\run_steam_deck.ps1

Export a silent, deterministic 4K/60 MP4 master on Windows:

    .\run_export_video.ps1 -Seconds 10

Record native window frames until the window closes:

    .\run_record_video.ps1

`run_export_video.ps1` is the preferred master path: it advances the simulation at a fixed 60 Hz regardless of encoding speed. `run_record_video.ps1` captures presented window frames at 60 FPS, advances one 60 Hz trial-time step per redraw, and is not a wall-clock-real-time recorder when encoding cannot sustain the requested rate.

Run a Deck-profile window/timing pass on Windows:

    .\run_deck_profile.ps1

Dump native input mapping/runtime reports on Windows:

    .\run_input_contract.ps1
    .\run_input_runtime.ps1

Run the Deck/Linux timing pass:

    bash run_deck_profile.sh

Run the player-facing native Steam/Deck launch on Deck/Linux:

    bash run_steam_deck.sh

Export or record video on Deck/Linux:

    bash run_export_video.sh
    bash run_record_video.sh

The Deck/Linux package must be built with a redistributable static FFmpeg bundle. FFmpeg provenance and license information are under `third_party/ffmpeg/`.

The Deck/Linux launch wrapper requires the Linux `XenocultureTrialDish` binary generated by `runtime/rust-wgpu-spike/scripts/package-deck.sh`; it does not fall back to the compatibility executable.

Dump native input mapping/runtime reports on Deck/Linux:

    bash run_input_contract.sh
    bash run_input_runtime.sh

The default timing report is `artifacts/wgpu_deck_timing.json`.
'@ | Set-Content -Encoding ASCII (Join-Path $packageRoot "PACKAGE_README.md")

    Write-Host "native_wgpu_package=ok"
    Write-Host "native_wgpu_package_dir=$packageRoot"
    Write-Host "native_wgpu_package_binary=$(Join-Path $packageRoot $steamExeName)"
    Write-Host "native_wgpu_package_ffmpeg=$(Join-Path $packageRoot 'ffmpeg.exe')"
}
finally {
    Pop-Location
}
