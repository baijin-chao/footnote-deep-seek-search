@echo off
REM Check whether docs are in sync with code.
setlocal
chcp 65001 >nul
set "ROOT=%~dp0.."

if "%DRA_PYTHON%"=="" set "DRA_PYTHON=C:\Users\baijin-chao\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%DRA_PYTHON%" (
    echo [ERROR] Python not found: %DRA_PYTHON%
    exit /b 1
)

set "PYTHONPATH=%ROOT%\vendor;%ROOT%\src"
set "PYTHONIOENCODING=utf-8"

"%DRA_PYTHON%" "%ROOT%\scripts\check_docs.py"
exit /b %ERRORLEVEL%
