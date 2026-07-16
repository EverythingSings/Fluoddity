@echo off
setlocal enabledelayedexpansion
REM ============================================================================
REM  flip_stereo.bat - batch swap the left/right eyes of side-by-side stereo.
REM
REM  Drop this file into a folder full of stereo .mp4 / .png files and
REM  double-click it. Every video and image in the SAME folder as this .bat is
REM  eye-swapped (crop each half, hstack in the opposite order) and written to a
REM  ".\Flipped" subfolder with the same filename. Use it to convert wall-eye
REM  (parallel) stereo to cross-eye, or vice versa.
REM
REM  Requires ffmpeg on PATH (https://ffmpeg.org/download.html).
REM
REM  NOTE: it assumes every .mp4/.png here is genuine side-by-side stereo. A mono
REM  file in this folder will get its halves swapped too, so keep only stereo
REM  files alongside this script.
REM ============================================================================

REM Operate on the folder this .bat lives in, regardless of where it's launched.
cd /d "%~dp0"

REM Same filter graph the app uses.
set "FILTER=[0:v]split[a][b]; [a]crop=iw/2:ih:0:0[right]; [b]crop=iw/2:ih:iw/2:0[left]; [left][right]hstack"

where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo Error: ffmpeg was not found on your PATH.
    echo Install it from https://ffmpeg.org/download.html and try again.
    echo.
    pause
    exit /b 1
)

set "OUT=%~dp0Flipped"
set /a converted=0
set /a failed=0
set /a found=0

REM --- Videos: keep audio + a matching-quality re-encode --------------------
for %%F in ("*.mp4") do (
    set /a found+=1
    if not exist "%OUT%" mkdir "%OUT%"
    echo Flipping: %%~nxF
    ffmpeg -y -i "%%F" -filter_complex "%FILTER%" -c:v libx264 -crf 18 -c:a copy "%OUT%\%%~nxF" <nul >nul 2>&1
    if errorlevel 1 (
        echo   ^^! ffmpeg failed for %%~nxF ^(skipped^)
        set /a failed+=1
    ) else (
        set /a converted+=1
    )
)

REM --- Images: just re-encode ------------------------------------------------
for %%F in ("*.png") do (
    set /a found+=1
    if not exist "%OUT%" mkdir "%OUT%"
    echo Flipping: %%~nxF
    ffmpeg -y -i "%%F" -filter_complex "%FILTER%" "%OUT%\%%~nxF" <nul >nul 2>&1
    if errorlevel 1 (
        echo   ^^! ffmpeg failed for %%~nxF ^(skipped^)
        set /a failed+=1
    ) else (
        set /a converted+=1
    )
)

echo.
if %found%==0 (
    echo No .mp4 or .png files found next to this script.
) else (
    echo Done: %converted% converted, %failed% failed.
    echo Output folder: %OUT%
)
echo.
pause
