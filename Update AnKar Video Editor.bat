@echo off
rem ============================================================================================================
rem  Update AnKar Video Editor from a downloaded zip.
rem  Drag the new "AnKar-Video-Editor-X.Y.Z.zip" onto this file - or just double-click it: it then uses the newest
rem  AnKar-Video-Editor-*.zip in this folder or in your Downloads folder.
rem  Replaces the program files only. Your projects, voices, keys, settings and models are kept.
rem ============================================================================================================
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title Update AnKar Video Editor
set "HERE=%~dp0"
set "ZIP=%~1"
if defined ZIP goto :have_zip
for /f "delims=" %%Z in ('dir /b /o-d "%HERE%AnKar-Video-Editor-*.zip" 2^>nul') do if not defined ZIP set "ZIP=%HERE%%%Z"
if defined ZIP goto :have_zip
for /f "delims=" %%Z in ('dir /b /o-d "%USERPROFILE%\Downloads\AnKar-Video-Editor-*.zip" 2^>nul') do if not defined ZIP set "ZIP=%USERPROFILE%\Downloads\%%Z"
if defined ZIP goto :have_zip
echo  No AnKar-Video-Editor-*.zip found here or in Downloads.
echo  Download the new version from the AnKar website, then drag the zip onto this file.
goto :end_fail

:have_zip
if not exist "%ZIP%" goto :nozip
echo.
echo  Updating from: "%ZIP%"
echo  Your projects, voices, keys and settings are kept.
echo.
choice /c YN /m "Continue"
if errorlevel 2 exit /b 0
tasklist /fi "WINDOWTITLE eq AnKar Video Editor*" 2>nul | find /i "cmd.exe" >nul && echo  Close the AnKar Video Editor window first, then run this again. && goto :end_fail

set "TMPX=%HERE%cache\update"
if exist "%TMPX%" rmdir /s /q "%TMPX%"
mkdir "%TMPX%" || goto :fail
tar -xf "%ZIP%" -C "%TMPX%" || goto :fail
if not exist "%TMPX%\app\version.py" goto :notankar
rem copy the new program files over this folder (never the user's folders)
robocopy "%TMPX%" "%HERE%." /E /NFL /NDL /NJH /NJS /NP /XD "%TMPX%\config" "%TMPX%\cache" "%TMPX%\models" "%TMPX%\projects" >nul
if errorlevel 8 goto :fail
rem the demo project only if it isn't there yet
if not exist "%HERE%projects\Demo\project.json" robocopy "%TMPX%\projects\Demo" "%HERE%projects\Demo" /E /NFL /NDL /NJH /NJS /NP >nul
rmdir /s /q "%TMPX%"
echo  Files updated. Now running Setup for the new version...
echo.
call "%HERE%Setup AnKar Video Editor.bat"
exit /b %errorlevel%

:nozip
echo  Can't find "%ZIP%".
goto :end_fail
:notankar
echo  That zip doesn't look like AnKar Video Editor. Nothing was changed.
rmdir /s /q "%TMPX%"
goto :end_fail
:fail
echo  The update did not finish - see the messages above. Your projects are untouched.
:end_fail
echo.
pause
exit /b 1
