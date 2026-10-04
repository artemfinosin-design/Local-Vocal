@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe goto dependencies
set "KARAOKE_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%KARAOKE_PY%" (
  "%KARAOKE_PY%" -m venv .venv
) else (
  where py >nul 2>nul || (echo Install Python 3.11 or 3.12 from python.org & pause & exit /b 1)
  py -3.11 -m venv .venv 2>nul || py -3.12 -m venv .venv
)
if errorlevel 1 (echo Could not create Python environment & pause & exit /b 1)
:dependencies
fc /b requirements.txt .venv\requirements.installed >nul 2>nul
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 (echo Dependency installation failed & pause & exit /b 1)
  copy /y requirements.txt .venv\requirements.installed >nul
)
if "%~1"=="--install-only" exit /b 0
.venv\Scripts\python.exe app.py
if errorlevel 1 pause
