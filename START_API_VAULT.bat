@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Da RoastBox - API & Auth Setup Vault
cd /d "%~dp0"
if errorlevel 1 (
  echo Cannot open the project folder. Extract the entire ZIP first.
  pause
  exit /b 1
)
if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY_EXE=%~dp0.venv\Scripts\python.exe"
) else if exist "%~dp0runtime\windows-x64\python\python.exe" (
  set "PY_EXE=%~dp0runtime\windows-x64\python\python.exe"
) else (
  echo Virtual environment not found. Run launch.bat or install.bat first to set up Python.
  pause
  exit /b 1
)
echo Starting Da RoastBox API & Auth Setup Vault at http://127.0.0.1:8090 ...
start "" "http://127.0.0.1:8090"
"%PY_EXE%" "%~dp0scripts\key_setup_server.py"
pause
