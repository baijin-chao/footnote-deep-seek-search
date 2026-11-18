@echo off
REM Offline demo: replay a recorded run without network.
REM First record it once while online:
REM   scripts\run.cmd "向量数据库常见的索引类型有哪些？" --mode record --no-cache

setlocal
chcp 65001 >nul
set "ROOT=%~dp0.."
set "QUESTION=向量数据库常见的索引类型有哪些？"

if "%DRA_PYTHON%"=="" set "DRA_PYTHON=C:\Users\baijin-chao\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%DRA_PYTHON%" (
    echo [ERROR] Python not found: %DRA_PYTHON%
    exit /b 1
)

if not exist "%ROOT%\fixtures\llm" (
    echo [ERROR] No recordings found in "%ROOT%\fixtures".
    echo Record once while online, then rerun this script:
    echo   scripts\run.cmd "%QUESTION%" --mode record --no-cache
    exit /b 1
)

set "PYTHONPATH=%ROOT%\vendor;%ROOT%\src"
set "PYTHONIOENCODING=utf-8"

"%DRA_PYTHON%" -m dra "%QUESTION%" --mode mock %*
exit /b %ERRORLEVEL%
