@echo off
rem Calibrate against a room with known geometry (data\ground_truth\room_coordinates.txt).
rem   calibrate.bat               -> general corrections that transfer to other rooms (distance scale)
rem   calibrate.bat --same-room   -> also copy this room's size into the priors (same-room re-analysis only)
rem Writes config\calibration.json, which reconstruct.bat then uses automatically.
setlocal
cd /d "%~dp0"

where python >nul 2>nul || (echo Python 3.10+ is required: https://www.python.org/ & pause & exit /b 1)
python -c "import numpy, scipy, matplotlib, av" >nul 2>nul || python -m pip install -r requirements.txt

python -m roomrecon calibrate %* || (pause & exit /b 1)
if exist "output\room_3d.html" start "" "output\room_3d.html"
pause
