@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================================
REM BOL ��������ƽ̨ - �������ű�
REM
REM ���ܣ���ϵͳ����ɿɲ���� ZIP ѹ����
REM   - �������Դ�롢ǰ�˹��������̬�ļ��������嵥
REM   - �ų������ļ���node_modules��__pycache__��.git�����⻷���ȣ�
REM   - �Զ����ɲ���˵�� README_DEPLOY.txt
REM
REM ʹ�÷�ʽ��package.bat
REM �������Ŀͬ��Ŀ¼�µ� BOL_ϵͳ�����_YYYYMMDD_HHMMSS.zip
REM ============================================================

title BOL ��������ƽ̨ - ���

set "ROOT_DIR=%~dp0"
REM ȥ��ĩβ��б��
set "ROOT_DIR=%ROOT_DIR:~0,-1%"
set "PARENT_DIR=%ROOT_DIR%\.."

REM ���ɴ�ʱ����İ���
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value 2^>nul ^| find "="') do set "DT=%%a"
if "%DT%"=="" (
    set "PKG_NAME=BOLϵͳ�����"
) else (
    set "PKG_NAME=BOLϵͳ�����_%DT:~0,8%_%DT:~8,6%"
)

set "PKG_DIR=%PARENT_DIR%\%PKG_NAME%"
set "ZIP_FILE=%PARENT_DIR%\%PKG_NAME%.zip"

echo ============================================================
echo   BOL ��������ƽ̨ - ������
echo   ����: %PKG_NAME%
echo   ���: %ZIP_FILE%
echo ============================================================
echo.

REM ============================================================
REM ���� 1: ȷ��ǰ���ѹ����;�̬�ļ����ռ�
REM ============================================================
echo [1/4] ���ǰ�˹�������...

if not exist "%ROOT_DIR%\frontend\dist\index.html" (
    echo   [����] ǰ�� dist �����ڣ����ڹ���...
    cd /d "%ROOT_DIR%\frontend"
    if not exist node_modules (
        echo   - ��װǰ������...
        call npm install --silent
    )
    call npm run build
    cd /d "%ROOT_DIR%"
)
echo   - ǰ�˹����������

echo [2/4] ��龲̬�ļ�...
if not exist "%ROOT_DIR%\backend\staticfiles" (
    echo   [����] ��̬�ļ�δ�ռ��������ռ�...
    cd /d "%ROOT_DIR%\backend"
    python manage.py collectstatic --noinput --settings=bol_platform.settings_prod
    cd /d "%ROOT_DIR%"
)
echo   - ��̬�ļ�����
echo.

REM ============================================================
REM ���� 3: ������ʱ���Ŀ¼�������ļ�
REM ============================================================
echo [3/4] �����ļ�����ʱĿ¼...

REM �����ɵ���ʱĿ¼
if exist "%PKG_DIR%" rmdir /s /q "%PKG_DIR%"
mkdir "%PKG_DIR%"

REM ���ƺ�ˣ��ų� __pycache__��.pyc��db.sqlite3��
echo   - ���ƺ�˴���...
xcopy "%ROOT_DIR%\backend" "%PKG_DIR%\backend\" /E /I /Q /Y >nul
REM ���������ļ�
for /d /r "%PKG_DIR%\backend" %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d" 2>nul
)
del /s /q "%PKG_DIR%\backend\*.pyc" >nul 2>&1
REM ɾ�������� SQLite ���ݿ⣨��������ʹ�� SQL Server��
if exist "%PKG_DIR%\backend\db.sqlite3" del /q "%PKG_DIR%\backend\db.sqlite3"

REM ����ǰ�˹�������� dist������ node_modules ��Դ�룩
echo   - ����ǰ�˹�������...
xcopy "%ROOT_DIR%\frontend\dist" "%PKG_DIR%\frontend\dist\" /E /I /Q /Y >nul

REM ����ǰ�� package.json���������ؽ�ǰ��ʹ�ã�
copy "%ROOT_DIR%\frontend\package.json" "%PKG_DIR%\frontend\package.json" >nul
copy "%ROOT_DIR%\frontend\vite.config.js" "%PKG_DIR%\frontend\vite.config.js" >nul
copy "%ROOT_DIR%\frontend\index.html" "%PKG_DIR%\frontend\index.html" >nul

REM ���Ʋ���ű�
copy "%ROOT_DIR%\deploy.bat" "%PKG_DIR%\deploy.bat" >nul
copy "%ROOT_DIR%\stop_prod.bat" "%PKG_DIR%\stop_prod.bat" >nul

REM ������Ŀ˵���ĵ������У�
if exist "%ROOT_DIR%\IE Platform BOL ϵͳʹ��˵��_v01.pptx" (
    copy "%ROOT_DIR%\IE Platform BOL ϵͳʹ��˵��_v01.pptx" "%PKG_DIR%\" >nul
)

echo   - �ļ��������
echo.

REM ============================================================
REM ���� 4: ���ɲ���˵�������
REM ============================================================
echo [4/4] ���ɲ���˵�������...

REM ���� README_DEPLOY.txt
(
echo ============================================================
echo   BOL ��������ƽ̨ - ����˵��
echo   ����ʱ��: %DATE% %TIME%
echo ============================================================
echo.
echo [����Ҫ��]
echo   - Python 3.10+ �������ӵ� PATH��
echo   - Node.js 18+ �����״β�����ؽ�ǰ��ʱ��Ҫ��
echo   - SQL Server ���ݿ����Ȩ�ޣ�HRDB ֻ�� + CMC ��д��
echo   - Windows Server 2016+ �� Windows 10/11
echo.
echo [Ŀ¼�ṹ]
echo   BOLϵͳ�����\
echo     deploy.bat              һ�����������ű�
echo     stop_prod.bat           ֹͣ����ű�
echo     README_DEPLOY.txt       ��˵���ļ�
echo     backend\                ��� Django ����
echo       manage.py
echo       run_server.py         ���������ű���Waitress WSGI��
echo       requirements.txt      Python �����嵥
echo       bol_platform\         Django ��Ŀ����
echo         settings.py         ��������
echo         settings_prod.py    ������������
echo       apps\                 ҵ��ģ��
echo       staticfiles\          �ռ��ľ�̬�ļ�
echo     frontend\               ǰ��
echo       dist\                 ��������ѹ�����ֱ�ӿ��ã�
echo       package.json          �����嵥���ؽ�ǰ��ʱ�ã�
echo       vite.config.js        Vite ����
echo       index.html            ���ģ��
echo.
echo [���ٲ���]
echo   1. ����ѹ������ѹ������������Ŀ¼���� D:\BOLϵͳ\��
echo   2. ˫������ deploy.bat
echo      - �״����л��Զ���װ Python �������ռ���̬�ļ���Ǩ�����ݿ�
echo      - �� frontend\dist �Ѵ�����ֱ��ʹ�ã������Զ�����ǰ��
echo   3. �ȴ��ű�ִ����ɣ����� "����������������" ��ʾ����
echo   4. ��������� http://127.0.0.1:8090/
echo.
echo [�˿�����]
echo   Ĭ�϶˿�: 8090����������ռ�õ� 8000 ��ͻ��
echo   �Զ���˿�:
echo     ��ʽ1: set BOL_PORT=9000 ^&^& deploy.bat
echo     ��ʽ2: cd backend ^&^& python run_server.py --port 9000
echo.
echo [��������]
echo   �״β���:     deploy.bat
echo   ��������:     deploy.bat --skip-build      ������������װ��ǰ�˹�����
echo   ֹͣ����:     stop_prod.bat                 �� Ctrl+C
echo   ��������:     ������ stop_prod.bat�������� deploy.bat
echo.
echo [�״δ�������Ա�˺�]
echo   cd backend
echo   python manage.py createsuperuser --settings=bol_platform.settings_prod
echo   ����ʾ�����û���������
echo.
echo [���ݿ�����]
echo   ��������ͨ�� backend\bol_platform\settings_prod.py �е� DATABASES ����
echo   Ĭ�ϼ̳� settings.py �е� SQL Server ���ã�HRDB + CMC ˫���ݿ⣩
echo   �����޸����ݿ����ӣ��༭ settings_prod.py ��ͨ��������������
echo.
echo [ע������]
echo   1. �״β�������������װ Python ������
echo   2. ���������ܷ��� SQL Server��HRDB �� CMC ���ݿ⣩
echo   3. ����ǽ����� 8090 �˿ڣ����Զ���˿ڣ�
echo   4. �����Թ���ԱȨ������ deploy.bat
echo   5. ������ǰ̨��ʽ���У��رմ��ڼ�ֹͣ�������̨����
echo      ��ʹ�� NSSM �� run_server.py ע��Ϊ Windows ����
echo.
echo [�����Ų�]
echo   - �˿ڱ�ռ��:  �޸� BOL_PORT ���������������� stop_prod.bat ����
echo   - ������װʧ��: �������� Python �汾���ֶ� pip install -r backend\requirements.txt
echo   - ǰ�˹���ʧ��: ��� Node.js �汾���ֶ� cd frontend ^&^& npm install ^&^& npm run build
echo   - ���ݿ�����ʧ��: ��� settings_prod.py �е� DATABASES ���ú�������ͨ��
echo   - ��̬�ļ� 404:  ���� cd backend ^&^& python manage.py collectstatic --noinput
echo.
echo ============================================================
) > "%PKG_DIR%\README_DEPLOY.txt"

echo   - ����˵��������

REM ʹ�� PowerShell ѹ���� zip
echo   - ����ѹ��Ϊ ZIP...
powershell -NoProfile -Command "Compress-Archive -Path '%PKG_DIR%\*' -DestinationPath '%ZIP_FILE%' -Force"

if exist "%ZIP_FILE%" (
    echo   - ������: %ZIP_FILE%
    echo.
    echo ============================================================
    echo   �����������:
    echo   %ZIP_FILE%
    echo.
    echo   ����ʽ: ��ѹ��˫�� deploy.bat
    echo   ������� README_DEPLOY.txt
    echo ============================================================
) else (
    echo   [����] ���ʧ��
)

REM ������ʱĿ¼
if exist "%PKG_DIR%" rmdir /s /q "%PKG_DIR%"

echo.
pause

endlocal
