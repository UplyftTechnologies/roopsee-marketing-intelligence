@echo off
rem Double-click to start the Roopsee Marketing Intelligence dashboard.
rem Extra options are passed through, e.g.  start.bat --refresh   or   start.bat --no-browser
title Roopsee Marketing Intelligence
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
  python run.py %*
) else (
  where py >nul 2>nul
  if %errorlevel%==0 (
    py run.py %*
  ) else (
    echo.
    echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" in the installer, then double-click start.bat again.
    echo.
    pause
    exit /b 1
  )
)
if errorlevel 1 (
  echo.
  echo The dashboard did not start. Read the message above.
  pause
)
