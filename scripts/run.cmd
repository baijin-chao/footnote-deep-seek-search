@echo off
REM Launch the CLI: scripts\run.cmd "your research question"
REM Works without PowerShell execution policy.

setlocal
chcp 65001 >nul
set "ROOT=%~dp0.."

if "%DRA_PYTHON%"=="" set "DRA_PYTHON=C:\Users\baijin-chao\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%DRA_PYTHON%" (
    echo [ERROR] Python not found: %DRA_PYTHON%
    echo Set DRA_PYTHON to your python.exe path
    exit /b 1
)

set "PYTHONPATH=%ROOT%\vendor;%ROOT%\src"
set "PYTHONIOENCODING=utf-8"

"%DRA_PYTHON%" -m dra %*
exit /b %ERRORLEVEL%
