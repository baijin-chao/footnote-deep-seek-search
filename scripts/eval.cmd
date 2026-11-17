@echo off
REM Run the evaluation suite: scripts\eval.cmd --limit 5
REM All args are forwarded to dra.eval

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

"%DRA_PYTHON%" -m dra.eval %*
exit /b %ERRORLEVEL%
