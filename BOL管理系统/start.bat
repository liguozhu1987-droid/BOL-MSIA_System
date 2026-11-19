@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================================
REM BOL 管理分析平台 - 一键启动脚本
REM 解决三个核心问题:
REM   1. 端口被占用 - 先清理旧进程
REM   2. 工作目录错误 - 自动切换到正确目录
REM   3. PowerShell 语法差异 - 使用标准 cmd 语法
REM ============================================================

title BOL 管理分析平台 - 启动器

echo ============================================================
echo   BOL 管理分析平台 - 一键启动脚本
echo   前端: http://127.0.0.1:5173/
echo   后端: http://127.0.0.1:8000/
echo ============================================================
echo.

REM 项目根目录 (脚本所在目录)
set "ROOT_DIR=%~dp0"
set "BACKEND_DIR=%ROOT_DIR%backend"
set "FRONTEND_DIR=%ROOT_DIR%frontend"

REM ============================================================
REM 步骤 1: 清理旧进程 (避免端口占用)
REM ============================================================
echo [1/4] 清理旧进程...

REM 清理 8000 端口 (后端)
set "BACKEND_CLEANED=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING" 2^>nul') do (
    if not "%%a"=="" (
        taskkill /PID %%a /F >nul 2>&1
        set "BACKEND_CLEANED=1"
    )
)
if "!BACKEND_CLEANED!"=="1" (
    echo   - 已清理后端旧进程 (端口 8000)
) else (
    echo   - 后端端口 8000 空闲
)

REM 清理 5173 端口 (前端)
set "FRONTEND_CLEANED=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING" 2^>nul') do (
    if not "%%a"=="" (
        taskkill /PID %%a /F >nul 2>&1
        set "FRONTEND_CLEANED=1"
    )
)
if "!FRONTEND_CLEANED!"=="1" (
    echo   - 已清理前端旧进程 (端口 5173)
) else (
    echo   - 前端端口 5173 空闲
)

REM 等待端口释放
timeout /t 2 /nobreak >nul
echo.

REM ============================================================
REM 步骤 2: 检查依赖
REM ============================================================
echo [2/4] 检查依赖...

REM 检查 Python
where python >nul 2>&1
if errorlevel 1 (
    echo   [错误] 未找到 Python, 请安装 Python 3.10+ 并添加到 PATH
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo   - %PY_VER%

REM 检查 Node.js
where node >nul 2>&1
if errorlevel 1 (
    echo   [错误] 未找到 Node.js, 请安装 Node.js 18+ 并添加到 PATH
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do set "NODE_VER=%%v"
echo   - Node.js %NODE_VER%

REM 检查后端目录
if not exist "%BACKEND_DIR%\manage.py" (
    echo   [错误] 未找到 backend\manage.py, 请确认脚本位于项目根目录
    pause
    exit /b 1
)

REM 检查前端目录
if not exist "%FRONTEND_DIR%\package.json" (
    echo   [错误] 未找到 frontend\package.json, 请确认脚本位于项目根目录
    pause
    exit /b 1
)
echo   - 项目结构检查通过
echo.

REM ============================================================
REM 步骤 3: 启动后端 (Django)
REM ============================================================
echo [3/4] 启动后端服务 (Django)...
start "BOL-Backend" /D "%BACKEND_DIR%" cmd /k "title BOL 后端服务 && python manage.py runserver 0.0.0.0:8000 --noreload"
echo   - 后端已在新窗口启动: http://127.0.0.1:8000/

REM 等待后端初始化
echo   - 等待后端初始化...
timeout /t 4 /nobreak >nul
echo.

REM ============================================================
REM 步骤 4: 启动前端 (Vite)
REM ============================================================
echo [4/4] 启动前端服务 (Vite)...
start "BOL-Frontend" /D "%FRONTEND_DIR%" cmd /k "title BOL 前端服务 && npm run dev"
echo   - 前端已在新窗口启动: http://127.0.0.1:5173/

REM 等待前端初始化
echo   - 等待前端初始化...
timeout /t 3 /nobreak >nul
echo.

REM ============================================================
REM 启动完成
REM ============================================================
echo ============================================================
echo   启动完成!
echo.
echo   前端: http://127.0.0.1:5173/
echo   后端: http://127.0.0.1:8000/admin/
echo.
echo   关闭服务: 直接关闭弹出的两个命令行窗口
echo   重启服务: 重新运行本脚本 (会自动清理旧进程)
echo ============================================================
echo.
echo 按任意键打开浏览器访问系统...
pause >nul

REM 自动打开浏览器
start http://127.0.0.1:5173/

endlocal
