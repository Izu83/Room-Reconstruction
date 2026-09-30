@echo off
rem Room reconstruction from audio.
rem   reconstruct.bat                   -> every recording in data\audios (extracted from data\videos if needed)
rem   reconstruct.bat file1 folder2 ... -> the given .wav / .mov / .mp4 files or folders (drag-and-drop works)
rem   extra options: --no-calibration, --truth file.txt, --use-modes  (python -m roomrecon --help)
setlocal
cd /d "%~dp0"

where python >nul 2>nul || (echo Python 3.10+ is required: https://www.python.org/ & pause & exit /b 1)
python -c "import numpy, scipy, matplotlib, av" >nul 2>nul || (
    echo Installing Python packages...
    python -m pip install -r requirements.txt || (pause & exit /b 1)
)

python -m roomrecon %* || (pause & exit /b 1)
if exist "output\room_3d.html" start "" "output\room_3d.html"
pause
