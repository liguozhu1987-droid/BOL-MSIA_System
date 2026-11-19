# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置

生成 MSIABackend.exe, 通过 COLLECT 打包到 dist/MSIABackend/ 目录。

用法:
    cd backend
    pyinstaller build.spec
"""
import os

block_cipher = None

# 应用根目录 (build.spec 所在目录)
APP_DIR = os.path.abspath(os.path.dirname(SPEC))

# 数据文件: app 源码目录、.env 配置、依赖清单
datas = [
    ('app', 'app'),
]

# 若 .env 存在则一并打包
_env_path = os.path.join(APP_DIR, '.env')
if os.path.exists(_env_path):
    datas.append(('.env', '.'))

binaries = []

# PyInstaller 无法自动发现的隐式导入
hiddenimports = [
    'pyodbc',
    'sqlalchemy.dialects.mssql.pyodbc',
    'sqlalchemy.dialects.mssql.base',
    'sqlalchemy.dialects.mssql.information_schema',
    'passlib.handlers.bcrypt',
    'bcrypt',
    'apscheduler.schedulers.background',
    'apscheduler.executors.pool',
    'apscheduler.triggers.cron',
    'apscheduler.triggers.date',
    'apscheduler.jobstores.memory',
    'apscheduler.jobstores.sqlalchemy',
    'reportlab',
    'reportlab.platypus',
    'openpyxl',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'email.mime.multipart',
    'email.mime.text',
]

a = Analysis(
    ['run.py'],
    pathex=[APP_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 使用 COLLECT 模式: 生成 dist/MSIABackend/ 目录, 内含 MSIABackend.exe
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MSIABackend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MSIABackend',
)
