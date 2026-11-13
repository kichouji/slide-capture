@echo off
rem Slide Capture launcher: double-click to start (tray app, no console)
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Setting up the Python environment with uv...
    uv sync
    if errorlevel 1 (
        echo Setup failed. Please make sure uv is installed.
        pause
        exit /b 1
    )
)
start "" ".venv\Scripts\pythonw.exe" -m slide_capture
