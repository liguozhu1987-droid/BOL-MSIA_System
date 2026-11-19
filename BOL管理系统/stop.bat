@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM BOL 管理分析平台 - 一键停止脚本
REM ============================================================

title BOL 管理分析平台 - 停止器

echo ============================================================
echo   BOL 管理分析平台 - 停止所有服务
echo ============================================================
echo.

set "ANY_KILLED=0"

REM 停止后端 (端口 8000)
echo [1/2] 停止后端服务...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING" 2^>nul') do (
    if not "%%a"=="" (
        taskkill /PID %%a /F >nul 2>&1
        echo   - 已终止进程 PID: %%a (端口 8000)
        set "ANY_KILLED=1"
    )
)
if "!ANY_KILLED!"=="0" echo   - 后端未运行

REM 停止前端 (端口 5173)
set "FE_KILLED=0"
echo [2/2] 停止前端服务...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING" 2^>nul') do (
    if not "%%a"=="" (
        taskkill /PID %%a /F >nul 2>&1
        echo   - 已终止进程 PID: %%a (端口 5173)
        set "FE_KILLED=1"
    )
)
if "!FE_KILLED!"=="0" echo   - 前端未运行

REM 同时关闭弹出的服务窗口
taskkill /FI "WINDOWTITLE eq BOL 后端服务*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq BOL 前端服务*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq BOL-Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq BOL-Frontend*" /F >nul 2>&1

echo.
echo ============================================================
echo   所有服务已停止
echo ============================================================
pause

endlocal
