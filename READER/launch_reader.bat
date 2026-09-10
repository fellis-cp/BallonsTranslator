@echo off
rem Launcher script for BalloonsTranslator Manga Reader (Windows)

set SCRIPT_DIR=%~dp0
set WORKSPACE_DIR=%SCRIPT_DIR%..

if "%PYTHON%"=="" (
    if exist "%WORKSPACE_DIR%\.venv\Scripts\python.exe" (
        set PYTHON=%WORKSPACE_DIR%\.venv\Scripts\python.exe
    ) else (
        set PYTHON=python
    )
)

"%PYTHON%" "%SCRIPT_DIR%launch_reader.py" %*

