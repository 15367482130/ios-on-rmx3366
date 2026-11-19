@echo off
REM Pure-ASCII batch file: cmd.exe reads .bat with the ANSI codepage, so non-ASCII
REM bytes break its syntax. Chinese text is printed by the Python scripts instead.
title iOS Experience Build - Flash (Windows only)

cd /d "%~dp0"

REM ---- elevate first, so precheck and flashing share one environment ----
net session >nul 2>&1
if errorlevel 1 goto :need_admin
goto :admin_ok

:need_admin
echo Requesting administrator privileges (click YES in UAC)...
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" >nul 2>&1
exit /b

:admin_ok
cd /d "%~dp0"
chcp 65001 >nul

echo.
echo   ============================================================
echo    iOS EXPERIENCE BUILD  -  Chinese UI, no timers, no logs
echo    Flash from pure Windows (no WSL, nothing to install)
echo   ============================================================
echo.

REM ---- pick a Python that has pyusb: the bundled runtime first ----
set "PY=%~dp0runtime\python.exe"
if exist "%PY%" goto :have_python
set "PY=python"
:have_python
set "PYTHONPATH=%~dp0site-packages"
echo Using Python: %PY%
echo.

REM ---- step 0: package precheck (never touches the phone) ----
echo [0/5] Checking the package...
"%PY%" precheck.py
if errorlevel 1 goto :precheck_failed
echo.

REM ---- step 1: is the phone reachable? driver problem or mode problem? ----
echo [1/5] Looking for the phone...
"%PY%" devcheck.py
set "DEV=%ERRORLEVEL%"
if "%DEV%"=="0" goto :dev_ok
if "%DEV%"=="1" goto :ask_driver
echo.
echo   Enter fastboot on the phone and run this again.
echo   Nothing was sent to the phone.
pause
exit /b 2

:ask_driver
echo.
echo   The USB driver is the likely cause. libusb needs the phone bound to
echo   WinUSB (Zadig: Options - List All Devices - the 18d1 device - WinUSB).
echo.
echo   Press ENTER to skip this and continue, or type Y then ENTER to let
echo   this script try Microsoft's WinUSB driver right now.
set "ANS="
set /p "ANS=  Try the driver install? [y/N]: "
if /i not "%ANS%"=="y" goto :dev_ok
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0driver_winusb.ps1"
echo.
echo   (continuing either way - press CTRL+C now if you want to stop)
echo.

:dev_ok
REM ---- step 2: release the device from usbipd, if usbipd is installed ----
where usbipd >nul 2>&1
if errorlevel 1 goto :no_usbipd
echo [2/5] Releasing the device from usbipd...
for /f "tokens=1" %%b in ('usbipd list ^| findstr "18d1"') do (
    echo     unbind %%b
    usbipd unbind --busid %%b >nul 2>&1
)
goto :usbipd_done
:no_usbipd
echo [2/5] usbipd not installed - nothing to release.
:usbipd_done

echo [3/5] Waiting for the device to settle...
timeout /t 3 >nul

REM ---- step 4: flash ----
echo [4/5] Flashing now: loader + 2.7 GB system image + payload.
echo       About 2 minutes. Do NOT unplug the cable.
"%PY%" fb_libusb.py flash loader-logfix.img system.apfs itn-exp.bin
if errorlevel 1 goto :flash_failed

echo.
echo ============================================================
echo   FLASH DONE.
echo    - The phone shows the iOS home screen in 1-2 minutes.
echo    - First boot takes longer: the system image is read from RAM.
echo    - Long-press power to shut down; it stays up as long as you
echo      like (no timers in this build).
echo ============================================================
echo.
pause
exit /b 0

:precheck_failed
echo.
echo   The package is incomplete - copy the whole folder again.
echo   Nothing was sent to the phone.
pause
exit /b 1

:flash_failed
echo.
echo ============================================================
echo   FLASH FAILED. Keep the cable plugged in and send the output
echo   above for diagnosis. Re-running this script is safe.
echo ============================================================
echo.
pause
exit /b 1
