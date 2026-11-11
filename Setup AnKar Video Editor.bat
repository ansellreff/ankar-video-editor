@echo off
rem ============================================================================================================
rem  Setup AnKar Video Editor - run once after unzipping (and again after each update).
rem  Everything goes INSIDE this folder: its own portable Python (runtime\), the packages, the subtitle model
rem  (models\). Nothing is installed on Windows: no admin rights, no registry, no PATH changes, no services.
rem  Uninstall = delete this folder.
rem ============================================================================================================
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title Setup AnKar Video Editor
set "HERE=%~dp0"
set "RT=%HERE%runtime"
set "PY=%RT%\python.exe"
set "DL=%HERE%cache\setup"
rem keep pip and Python away from anything outside this folder
set "PIP_CACHE_DIR=%HERE%cache\pip"
set "PIP_CONFIG_FILE=NUL"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PIP_NO_INPUT=1"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "PYTHONPATH="
set "PYTHONHOME="

rem ---- pinned downloads (official sources) + their SHA-256 checksums --------------------------------------
set "PY_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
set "PY_SHA=4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
set "PIP_WHL=pip-26.3-py3-none-any.whl"
set "PIP_URL=https://files.pythonhosted.org/packages/07/25/ee8c38ae72d66b844ce8eb9711ba905dba21ca1a8a0c960057c41cd23337/pip-26.3-py3-none-any.whl"
set "PIP_SHA=f3b60b20ffaadd4415ed7957212a38ac63fa4c5fa375bd0f4a797777940fad13"
set "WH_URL=https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium-q5_0.bin"
set "WH_SHA=19fea4b380c3a618ec4723c3eef2eb785ffba0d0538cf43f8f235e7b3b34220f"
set "WH_FILE=%HERE%models\ggml-medium-q5_0.bin"

echo.
echo  ==========================================================
echo    AnKar Video Editor - Setup
echo    Everything stays inside this folder:
echo    "%HERE%"
echo  ==========================================================
echo.

where curl >nul 2>nul || goto :nocurl
where tar >nul 2>nul || goto :nocurl
if not exist "%DL%" mkdir "%DL%"
if not exist "%HERE%models" mkdir "%HERE%models"

rem ---- 1. portable Python ---------------------------------------------------------------------------------
echo [1/5] Private Python 3.12 (official portable version from python.org)...
if exist "%PY%" goto :py_ok
call :download "%PY_URL%" "%DL%\python.zip" "%PY_SHA%" || goto :fail
if not exist "%RT%" mkdir "%RT%"
tar -xf "%DL%\python.zip" -C "%RT%" || goto :fail
rem the ._pth file decides where this Python looks for code: its own files, its packages, and this app folder
> "%RT%\python312._pth" echo python312.zip
>> "%RT%\python312._pth" echo .
>> "%RT%\python312._pth" echo Lib\site-packages
>> "%RT%\python312._pth" echo ..
>> "%RT%\python312._pth" echo import site
:py_ok
"%PY%" -c "import sys; assert sys.version_info[:2] == (3, 12)" || goto :pybroken
rem Windows limits file paths to 260 characters (more needs admin rights); some package files need ~160 of them
"%PY%" -c "import os, sys; sys.exit(3 if len(os.environ['HERE']) > 90 else 0)" || goto :toolong
echo       OK

rem ---- 2. pip (the package installer) ---------------------------------------------------------------------
echo [2/5] Package installer (pip)...
"%PY%" -m pip --version >nul 2>nul && goto :pip_ok
call :download "%PIP_URL%" "%DL%\%PIP_WHL%" "%PIP_SHA%" || goto :fail
rem a wheel is a zip: unpacking it into the private Python's packages folder installs pip there
if not exist "%RT%\Lib\site-packages" mkdir "%RT%\Lib\site-packages"
tar -xf "%DL%\%PIP_WHL%" -C "%RT%\Lib\site-packages" || goto :fail
"%PY%" -m pip --version >nul || goto :fail
:pip_ok
echo       OK

rem ---- 3. packages (exact versions, each file checked against its SHA-256) -----------------------------------
echo [3/5] Packages (about 250 MB the first time; exact versions, checksums verified)...
"%PY%" -m pip install --require-hashes --only-binary=:all: --no-warn-script-location --disable-pip-version-check -r "%HERE%requirements-lock.txt" || goto :fail
echo       OK

rem ---- 4. subtitle model ----------------------------------------------------------------------------------
echo [4/5] Subtitle model (Whisper medium, 539 MB, from Hugging Face)...
if exist "%WH_FILE%" call :checksum "%WH_FILE%" "%WH_SHA%" && goto :wh_ok
call :download "%WH_URL%" "%WH_FILE%.part" "%WH_SHA%" || goto :wh_fail
move /y "%WH_FILE%.part" "%WH_FILE%" >nul
:wh_ok
echo       OK
goto :selftest
:wh_fail
echo       Could not get the subtitle model. Everything else works; run Setup again later for auto captions.

rem ---- 5. self-test ---------------------------------------------------------------------------------------
:selftest
echo [5/5] Checking that everything works...
for %%D in (config projects cache) do if not exist "%HERE%%%D" mkdir "%HERE%%%D"
"%PY%" -m scripts.selftest || goto :fail
del /q "%DL%\python.zip" "%DL%\%PIP_WHL%" 2>nul

echo.
echo  ==========================================================
echo    Ready!  Double-click  "Start AnKar Video Editor.bat"
echo    (the first time, open API Keys in the menu bar to create
echo     your password and add your Claude / ElevenLabs keys)
echo  ==========================================================
echo.
pause
exit /b 0

rem ============================================================================================================
:download  url  target  sha256
echo       downloading %~nx2 ...
curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 -# -o "%~2" "%~1" || goto :dl_fail
call :checksum "%~2" "%~3" && exit /b 0
del /q "%~2" 2>nul
exit /b 1

:dl_fail
echo       Download failed. Check the internet connection and run Setup again.
del /q "%~2" 2>nul
exit /b 1

:checksum  file  sha256
set "GOT="
for /f "skip=1 delims=" %%H in ('certutil -hashfile "%~1" SHA256') do if not defined GOT set "GOT=%%H"
set "GOT=%GOT: =%"
if /i "%GOT%"=="%~2" exit /b 0
echo       The file %~nx1 is not the expected one (checksum mismatch) - it was not used.
exit /b 1

:nocurl
echo  This Windows has no curl/tar (they come with Windows 10 version 1803 and later). Please update Windows.
goto :end_fail
:toolong
echo.
echo  This folder's location is too long for Windows (over 90 characters):
echo  "%HERE%"
echo  Move the whole folder somewhere shorter, for example  C:\AnKar  or  Documents\AnKar Video Editor,
echo  then run Setup again.
goto :end_fail
:pybroken
echo  The private Python in runtime\ does not start. Delete the "runtime" folder and run Setup again.
echo  (If Windows Smart App Control blocked it, the message above says so.)
goto :end_fail
:fail
echo.
echo  Setup did not finish - see the messages above. Fix the problem and run Setup again;
echo  it continues where it stopped.
:end_fail
echo.
pause
exit /b 1
