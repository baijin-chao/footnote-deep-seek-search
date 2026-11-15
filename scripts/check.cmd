@echo off
REM Check .env configuration and API connectivity.

setlocal
chcp 65001 >nul
set "ROOT=%~dp0.."

if "%DRA_PYTHON%"=="" set "DRA_PYTHON=C:\Users\baijin-chao\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%DRA_PYTHON%" (
    echo [ERROR] Python not found: %DRA_PYTHON%
    exit /b 1
)

set "PYTHONPATH=%ROOT%\vendor;%ROOT%\src"
"%DRA_PYTHON%" "%ROOT%\scripts\check_env.py"
exit /b %ERRORLEVEL%
