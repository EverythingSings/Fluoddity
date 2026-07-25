param(
    [ValidateRange(1, 10000)]
    [int]$Iterations = 40,

    [ValidateRange(1, 3600)]
    [int]$SecondsPerIteration = 15,

    [ValidateRange(0, 1000000)]
    [int]$StartIndex = 0,

    [string]$OutputDir = "artifacts/unique_iterations",
    [string]$PythonExecutable = "",
    [string]$PreferencesPath = "",
    [string]$VideoDir = "",

    [ValidateRange(1, 300)]
    [int]$LaunchDelaySeconds = 7
)

$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$DefaultConfig = Join-Path $Root 'physics_configs/Core/_Default.json'
$SimPath = Join-Path $Root 'sim.py'
$OutputPath = if ([IO.Path]::IsPathRooted($OutputDir)) {
    [IO.Path]::GetFullPath($OutputDir)
} else {
    [IO.Path]::GetFullPath((Join-Path $Root $OutputDir))
}

if ([string]::IsNullOrWhiteSpace($PreferencesPath)) {
    $PreferencesPath = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Fluoddity/preferences.config'
}
$PreferencesPath = [IO.Path]::GetFullPath($PreferencesPath)

if ([string]::IsNullOrWhiteSpace($VideoDir)) {
    $VideoDir = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Fluoddity/Videos'
}
$VideoDir = [IO.Path]::GetFullPath($VideoDir)

if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $venvCandidates = @(
        (Join-Path $Root '.venv/Scripts/python.exe'),
        (Join-Path $Root 'venv/Scripts/python.exe')
    )
    $PythonExecutable = $venvCandidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
        $PythonExecutable = (Get-Command python -ErrorAction Stop).Source
    }
}

foreach ($requiredPath in @($DefaultConfig, $SimPath, $PreferencesPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file not found: $requiredPath"
    }
}
if (-not (Test-Path -LiteralPath $VideoDir -PathType Container)) {
    throw "Video directory not found: $VideoDir"
}
New-Item -ItemType Directory -Force -Path $OutputPath | Out-Null

$presets = @(
    Get-ChildItem (Join-Path $Root 'physics_configs') -Recurse -Filter '*.json' |
        Where-Object { $_.Name -ne '_Default.json' } |
        Sort-Object FullName
)
if ($presets.Count -eq 0) {
    throw 'No physics presets were found.'
}

$defaultConfigBytes = [IO.File]::ReadAllBytes($DefaultConfig)
$preferenceBytes = [IO.File]::ReadAllBytes($PreferencesPath)
$simBytes = [IO.File]::ReadAllBytes($SimPath)
$utf8NoBom = [Text.UTF8Encoding]::new($false)
$rng = [Random]::new(73191)
for ($skip = 0; $skip -lt $StartIndex; $skip++) {
    $null = $rng.NextDouble()
}

if (-not ([Management.Automation.PSTypeName]'FluoddityKeys').Type) {
    Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class FluoddityKeys {
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
 [DllImport("user32.dll")] public static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
 public static void Tap(byte key) { keybd_event(key,0,0,UIntPtr.Zero); keybd_event(key,0,2,UIntPtr.Zero); }
}
'@
}

try {
    for ($i = 0; $i -lt $Iterations; $i++) {
        $captureIndex = $StartIndex + $i + 1
        $preset = $presets[($captureIndex - 1) % $presets.Count]
        $config = Get-Content $preset.FullName -Raw | ConvertFrom-Json
        $config.settings.rule_seed = [double]($rng.NextDouble() * 10000.0)
        [IO.File]::WriteAllText(
            $DefaultConfig,
            ($config | ConvertTo-Json -Depth 20),
            $utf8NoBom
        )

        $prefix = "unique-$('{0:D3}' -f $captureIndex)"
        $prefs = Get-Content $PreferencesPath -Raw | ConvertFrom-Json
        $prefs.filename_prefix = $prefix
        [IO.File]::WriteAllText(
            $PreferencesPath,
            ($prefs | ConvertTo-Json -Depth 20),
            $utf8NoBom
        )

        $gravity = -0.00008 - ((($captureIndex - 1) % 7) * 0.00007)
        $gravityString = $gravity.ToString(
            'G17',
            [Globalization.CultureInfo]::InvariantCulture
        )
        $sim = [IO.File]::ReadAllText($SimPath)
        $gravityPattern = "GRAVITY', \(0\.0, -[0-9.eE+-]+, 0\.0\)"
        $gravityRegex = [regex]::new($gravityPattern)
        if (-not $gravityRegex.IsMatch($sim)) {
            throw 'Could not locate the GRAVITY uniform assignment in sim.py.'
        }
        $sim = $gravityRegex.Replace(
            $sim,
            "GRAVITY', (0.0, $gravityString, 0.0)",
            1
        )
        [IO.File]::WriteAllText($SimPath, $sim, $utf8NoBom)

        $proc = Start-Process $PythonExecutable -ArgumentList 'main.py' -WorkingDirectory $Root -PassThru
        Start-Sleep -Seconds $LaunchDelaySeconds
        $proc.Refresh()
        [FluoddityKeys]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
        Start-Sleep -Milliseconds 400
        [FluoddityKeys]::Tap(0x50)
        Start-Sleep -Seconds $SecondsPerIteration
        if (-not $proc.HasExited) {
            [FluoddityKeys]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
            [FluoddityKeys]::Tap(0x1B)
            Start-Sleep -Seconds 2
        }
        if (-not $proc.HasExited) {
            $proc.Kill()
            $proc.WaitForExit(5000) | Out-Null
        }

        $latest = Get-ChildItem $VideoDir -Filter "$prefix-*.mp4" |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if (-not $latest) {
            Write-Warning "No recording produced for iteration $captureIndex ($prefix); skipping this preset."
            continue
        }

        $outputName = "iteration-$('{0:D3}' -f $captureIndex)-$($preset.BaseName).mp4"
        Copy-Item $latest.FullName (Join-Path $OutputPath $outputName) -Force
    }
}
finally {
    [IO.File]::WriteAllBytes($DefaultConfig, $defaultConfigBytes)
    [IO.File]::WriteAllBytes($PreferencesPath, $preferenceBytes)
    [IO.File]::WriteAllBytes($SimPath, $simBytes)
}
