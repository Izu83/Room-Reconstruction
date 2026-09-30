@echo off
rem Decode the Spatial Audio track of data\videos\*.MOV on a free GitHub-hosted Mac (no Mac needed).
rem
rem   1. On github.com create a new EMPTY PRIVATE repository (no README).
rem   2. Run:  decode_spatial_audio_on_github.bat https://github.com/<you>/<repo>.git
rem   3. Open the repository's "Actions" tab, wait for "Decode Spatial Audio" to finish (a few minutes),
rem      open the run and download the "spatial-audio" artifact.
rem   4. Unzip it into data\spatial\ and run reconstruct.bat again.
rem
rem Only the videos, the decoder and the workflow are uploaded. The videos contain the phone's GPS
rem location in their metadata - keep the repository private and delete it afterwards.
setlocal
cd /d "%~dp0"

if "%~1"=="" (
    echo Usage: %~nx0 https://github.com/^<you^>/^<repo^>.git
    exit /b 1
)
where git >nul 2>nul || (echo Git is not installed: https://git-scm.com/download/win & exit /b 1)

set "STAGE=%TEMP%\roomrecon-spatial-upload"
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%\data\videos" "%STAGE%\tools" "%STAGE%\.github\workflows" || exit /b 1
copy /y "data\videos\*.*" "%STAGE%\data\videos\" >nul || (echo No videos in data\videos & exit /b 1)
copy /y "tools\decode_spatial_audio.swift" "%STAGE%\tools\" >nul || exit /b 1
copy /y ".github\workflows\decode-spatial-audio.yml" "%STAGE%\.github\workflows\" >nul || exit /b 1

pushd "%STAGE%"
git init -q -b main || (popd & exit /b 1)
git add -A
for /f "delims=" %%e in ('git config user.email') do set "HAVE_ID=1"
if defined HAVE_ID (
    git commit -q -m "Videos for Spatial Audio decoding"
) else (
    git -c user.name=roomrecon -c user.email=roomrecon@users.noreply.github.com commit -q -m "Videos for Spatial Audio decoding"
)
git remote add origin "%~1"
echo Uploading videos to %~1 ...
git push -u origin main || (popd & echo Upload failed. & exit /b 1)
popd
rmdir /s /q "%STAGE%"

echo.
echo Uploaded. Now open the repository on github.com, go to Actions, wait for "Decode Spatial Audio",
echo download the "spatial-audio" artifact and unzip it into data\spatial\
