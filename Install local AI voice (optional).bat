@echo off
rem ============================================================================================================
rem  Optional: the offline AI voice engine (Chatterbox TTS + Demucs voice isolation), about 2 GB of packages plus
rem  about 2 GB of voice models downloaded on first use. Runs on the CPU. Without it, AI narration uses ElevenLabs.
rem  Everything goes into runtime-tts\ and models\tts\ inside this folder. Nothing is installed on Windows.
rem  Remove it = delete the runtime-tts folder (and models\tts).
rem ============================================================================================================
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title Install local AI voice (optional)
set "HERE=%~dp0"
set "RT=%HERE%runtime-tts"
set "PY=%RT%\python.exe"
set "DL=%HERE%cache\setup"
set "PIP_CACHE_DIR=%HERE%cache\pip"
set "PIP_CONFIG_FILE=NUL"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PIP_NO_INPUT=1"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "PYTHONPATH="
set "PYTHONHOME="
set "HF_HOME=%HERE%models\tts\hf"
set "TORCH_HOME=%HERE%models\tts\torch"
set "PY_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
set "PY_SHA=4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
set "PIP_WHL=pip-26.3-py3-none-any.whl"
set "PIP_URL=https://files.pythonhosted.org/packages/07/25/ee8c38ae72d66b844ce8eb9711ba905dba21ca1a8a0c960057c41cd23337/pip-26.3-py3-none-any.whl"
set "PIP_SHA=f3b60b20ffaadd4415ed7957212a38ac63fa4c5fa375bd0f4a797777940fad13"

echo.
echo  AnKar Video Editor - optional offline AI voice (about 2 GB now, 2 GB more on first use)
echo.
if not exist "%HERE%runtime\python.exe" goto :nosetup
where curl >nul 2>nul || goto :nocurl
where tar >nul 2>nul || goto :nocurl
if not exist "%DL%" mkdir "%DL%"

echo [1/3] Private Python for the voice engine...
if exist "%PY%" goto :py_ok
call :download "%PY_URL%" "%DL%\python.zip" "%PY_SHA%" || goto :fail
if not exist "%RT%" mkdir "%RT%"
tar -xf "%DL%\python.zip" -C "%RT%" || goto :fail
> "%RT%\python312._pth" echo python312.zip
>> "%RT%\python312._pth" echo .
>> "%RT%\python312._pth" echo Lib\site-packages
>> "%RT%\python312._pth" echo ..
>> "%RT%\python312._pth" echo import site
:py_ok
"%PY%" -c "import os, sys; sys.exit(3 if len(os.environ['HERE']) > 90 else 0)" || goto :toolong
"%PY%" -m pip --version >nul 2>nul && goto :pip_ok
call :download "%PIP_URL%" "%DL%\%PIP_WHL%" "%PIP_SHA%" || goto :fail
if not exist "%RT%\Lib\site-packages" mkdir "%RT%\Lib\site-packages"
tar -xf "%DL%\%PIP_WHL%" -C "%RT%\Lib\site-packages" || goto :fail
:pip_ok
echo       OK

echo [2/3] Voice engine packages (PyTorch CPU, Chatterbox; exact versions, checksums verified)...
"%PY%" -m pip install --require-hashes --only-binary=:all: --no-warn-script-location -r "%HERE%requirements-tts-lock.txt" || goto :fail
echo       OK

echo [3/3] Checking...
"%PY%" -c "import torch, chatterbox; print('      torch', torch.__version__, '- OK')" || goto :fail
del /q "%DL%\python.zip" "%DL%\%PIP_WHL%" 2>nul
echo.
echo  Done. In the editor: AI Voice tab - Voice engine - Local. The voice models (about 2 GB)
echo  download the first time you make a voice.
echo.
pause
exit /b 0

:download
echo       downloading %~nx2 ...
curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 -# -o "%~2" "%~1" || goto :dl_fail
call :checksum "%~2" "%~3" && exit /b 0
del /q "%~2" 2>nul
exit /b 1
:dl_fail
echo       Download failed. Check the internet connection and try again.
del /q "%~2" 2>nul
exit /b 1

:checksum
set "GOT="
for /f "skip=1 delims=" %%H in ('certutil -hashfile "%~1" SHA256') do if not defined GOT set "GOT=%%H"
set "GOT=%GOT: =%"
if /i "%GOT%"=="%~2" exit /b 0
echo       The file %~nx1 is not the expected one (checksum mismatch) - it was not used.
exit /b 1

:nosetup
echo  Run "Setup AnKar Video Editor.bat" first.
goto :end_fail
:nocurl
echo  This Windows has no curl/tar (they come with Windows 10 version 1803 and later). Please update Windows.
goto :end_fail
:toolong
echo  This folder's location is too long for Windows (over 90 characters). Move the AnKar folder somewhere shorter.
goto :end_fail
:fail
echo.
echo  The voice engine was not installed - see the messages above. Run this again to continue.
:end_fail
echo.
pause
exit /b 1
