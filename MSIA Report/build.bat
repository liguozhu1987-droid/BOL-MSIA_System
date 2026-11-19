@echo off
chcp 65001 >nul
REM ============================================================
REM MSIA 审核管理系统 - 一键打包脚本
REM
REM 使用方法:
REM   1. 确保已安装 Node.js 和 Python 虚拟环境 (.venv)
REM   2. 双击运行此脚本, 或在命令行执行 build.bat
REM
REM 输出:
REM   backend\dist\msia_server\  (完整部署包)
REM ============================================================

set PROJECT_ROOT=%~dp0
set BACKEND_DIR=%PROJECT_ROOT%backend
set FRONTEND_DIR=%PROJECT_ROOT%frontend
set VENV_PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe

echo ============================================================
echo   MSIA 审核管理系统 - 打包构建
echo ============================================================
echo.

REM ---- 第 1 步: 构建前端 ----
echo [1/3] 构建前端...
cd /d "%FRONTEND_DIR%"
call npm install
if errorlevel 1 (
    echo [ERROR] npm install 失败
    pause
    exit /b 1
)
call npm run build
if errorlevel 1 (
    echo [ERROR] 前端构建失败
    pause
    exit /b 1
)
echo [OK] 前端构建完成
echo.

REM ---- 第 2 步: 安装后端依赖 ----
echo [2/3] 检查后端依赖...
cd /d "%BACKEND_DIR%"
if not exist "%VENV_PYTHON%" (
    echo [ERROR] 未找到虚拟环境: %VENV_PYTHON%
    echo         请先创建: python -m venv "%PROJECT_ROOT%.venv"
    pause
    exit /b 1
)
"%VENV_PYTHON%" -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] 后端依赖安装失败
    pause
    exit /b 1
)
echo [OK] 后端依赖就绪
echo.

REM ---- 第 3 步: PyInstaller 打包 ----
echo [3/3] PyInstaller 打包...
"%VENV_PYTHON%" -m PyInstaller msia_server.spec --noconfirm
if errorlevel 1 (
    echo [ERROR] 打包失败
    pause
    exit /b 1
)
echo [OK] 打包完成
echo.

REM ---- 后处理: 将 config.ini 复制到 exe 同目录 (方便部署时修改) ----
echo [后处理] 复制 config.ini...
copy /Y "%BACKEND_DIR%\config.ini" "%BACKEND_DIR%\dist\msia_server\config.ini" >nul
echo [OK] config.ini 已复制
echo.

REM ---- 完成 ----
echo ============================================================
echo   构建成功!
echo   输出目录: %BACKEND_DIR%\dist\msia_server\
echo.
echo   部署步骤:
echo   1. 将 dist\msia_server\ 整个文件夹复制到目标服务器
echo   2. 编辑 config.ini 修改数据库、邮件等配置
echo   3. 运行 msia_server.exe 启动服务
echo   4. 浏览器访问 http://服务器IP:8000
echo ============================================================
pause
