@echo off
rem Stops the dashboard server (only the one started from this folder).
cd /d "%~dp0"
powershell -NoProfile -Command "$root = (Get-Location).Path; $p = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'mi\.cli serve' -and $_.CommandLine -like ('*' + $root + '*') }; if ($p) { $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Write-Host 'Dashboard stopped.' } else { Write-Host 'The dashboard is not running.' }"
ping -n 3 127.0.0.1 >nul
