@echo off
setlocal
title Hermes Connector Installer

echo Installing Hermes Connector into your local Hermes setup...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "connector_exit=%ERRORLEVEL%"

echo.
if "%connector_exit%"=="0" (
  echo Installation complete. Keep the pairing code above private and paste it into the Chrome extension.
) else (
  echo Installation failed. Open https://corsenai.github.io/hermes-connector/support/ for help.
)
if not defined HERMES_CONNECTOR_NO_PAUSE pause
exit /b %connector_exit%
