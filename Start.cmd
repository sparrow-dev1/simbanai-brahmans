@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0.runtime;%PYTHONPATH%"
echo Simbanai Brahmans: http://127.0.0.1:5000
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" serve.py
) else (
  python serve.py
)
if errorlevel 1 (
  echo Server could not start. Install requirements.txt and check database configuration.
  pause
)
endlocal
