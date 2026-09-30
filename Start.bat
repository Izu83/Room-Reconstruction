@echo off
rem Room Reconstruction - double-click to start.
rem   Start.bat                  menu
rem   Start.bat file1 folder2    reconstruct straight away from these recordings (drag-and-drop works)
setlocal EnableExtensions
cd /d "%~dp0"
title Room Reconstruction

rem ---- private Python environment in .venv (created once) ----
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto :have_venv
echo.
echo   First start: preparing Python. This takes a minute...
call :find_python
if errorlevel 1 goto :no_python
"%BASE_PY%" -m venv .venv
if errorlevel 1 goto :fail
:have_venv
if exist ".venv\installed.txt" goto :ready
echo   Installing packages...
"%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :fail
copy /y requirements.txt ".venv\installed.txt" >nul
:ready

rem ---- recordings dropped onto Start.bat: reconstruct them right away ----
if not "%~1"=="" (
    "%PY%" -m roomrecon %*
    if errorlevel 1 goto :fail
    call :open_result
    pause
    goto :eof
)

:menu
cls
echo.
echo   ROOM RECONSTRUCTION FROM AUDIO
echo   ==============================
echo.
echo   Recordings go in  data\videos   (.MOV / .MP4 / .WAV)
echo.
echo   [1]  Reconstruct the room
echo   [2]  Open the last result
echo   [3]  Calibrate with a measured room
echo   [4]  Decode iPhone Spatial Audio on GitHub (no Mac needed)
echo   [5]  Help
echo   [Q]  Quit
echo.
choice /c 12345Q /n /m "  Choose: "
if errorlevel 6 goto :eof
if errorlevel 5 goto :help
if errorlevel 4 goto :decode
if errorlevel 3 goto :calibrate
if errorlevel 2 goto :open
goto :run

:run
echo.
"%PY%" -m roomrecon
if errorlevel 1 (
    echo.
    echo   Something went wrong - see the message above.
    pause
    goto :menu
)
call :open_result
pause
goto :menu

:open
call :open_result
if not exist "output\room_3d.html" pause
goto :menu

:calibrate
echo.
echo   Compares the analysis with data\ground_truth\room_coordinates.txt
echo   and saves corrections to config\calibration.json.
echo.
echo   Normally only corrections that work for any room are kept.
echo   Answer Y only if you will analyse MORE recordings of this SAME room:
echo   then the room's measured size is copied into the model.
echo.
choice /c NY /n /m "  Copy this room's size into the model? [N/Y]: "
set "EXTRA="
if errorlevel 2 set "EXTRA=--same-room"
echo.
"%PY%" -m roomrecon calibrate %EXTRA%
if errorlevel 1 (
    pause
    goto :menu
)
call :open_result
pause
goto :menu

:decode
echo.
echo   Uploads data\videos to a GitHub repository, where a free cloud Mac decodes
echo   the Spatial Audio track. Create an EMPTY PRIVATE repository on github.com first.
echo   The videos contain the phone's GPS location - keep the repository private.
echo.
set "REPO="
set /p "REPO=  Repository URL (empty = back): "
if "%REPO%"=="" goto :menu
call "tools\decode_spatial_audio_on_github.bat" "%REPO%"
pause
goto :menu

:help
cls
echo.
echo   HOW TO USE
echo   ----------
echo   1. Record claps and yells in the room with an iPhone (Spatial Audio on) or any recorder.
echo      Best results: sharp sounds (balloon pops) made close to the microphone, several spots.
echo   2. Put the files in data\videos
echo   3. Choose [1]. The 3D view opens in your browser; everything is saved in the output folder:
echo        room_3d.html   interactive 3D view
echo        report.png     charts
echo        summary.txt    all numbers in text
echo.
echo   Optional
echo   - Measured room and positions in data\ground_truth\room_coordinates.txt enable
echo     the accuracy check and calibration [3].
echo   - Decoded Spatial Audio (data\spatial\*_foa.wav) adds 3D directions [4].
echo.
echo   Details: README.md
echo.
pause
goto :menu

rem ---------------------------------------------------------------- helpers
:open_result
if exist "output\room_3d.html" (
    start "" "output\room_3d.html"
) else (
    echo   No result yet - choose [1] first.
)
exit /b 0

:find_python
set "BASE_PY="
for %%C in ("python" "py -3") do (
    if not defined BASE_PY (
        for /f "delims=" %%E in ('%%~C -c "import sys; print(sys.executable if sys.version_info >= (3, 10) else '')" 2^>nul') do set "BASE_PY=%%E"
    )
)
if not defined BASE_PY exit /b 1
exit /b 0

:no_python
echo.
echo   Python 3.10 or newer is needed: https://www.python.org/downloads/
echo   During installation tick "Add python.exe to PATH", then start this again.
echo.
pause
exit /b 1

:fail
echo.
echo   Setup failed - see the message above.
pause
exit /b 1
