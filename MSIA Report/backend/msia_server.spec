# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 - MSIA 审核管理系统

打包命令 (在 backend 目录下执行):
    pyinstaller msia_server.spec

输出:
    dist/msia_server/msia_server.exe  (可执行程序)
    dist/msia_server/config.ini       (配置文件, 部署后可修改)

部署时将整个 dist/msia_server/ 文件夹复制到目标服务器。
"""
import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# ============ 路径配置 ============
BACKEND_DIR = os.path.abspath('.')
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
FRONTEND_DIST = os.path.join(PROJECT_DIR, 'frontend', 'dist')

# ============ 收集隐式依赖 ============
# FastAPI / Pydantic / SQLAlchemy 等库有大量动态导入, 需显式收集
hiddenimports = []
hiddenimports += collect_submodules('fastapi')
hiddenimports += collect_submodules('pydantic')
hiddenimports += collect_submodules('pydantic_settings')
hiddenimports += collect_submodules('sqlalchemy')
hiddenimports += collect_submodules('sqlalchemy.dialects')
hiddenimports += collect_submodules('starlette')
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('apscheduler')
hiddenimports += collect_submodules('loguru')
hiddenimports += collect_submodules('reportlab')
hiddenimports += collect_submodules('openpyxl')
hiddenimports += collect_submodules('passlib')
hiddenimports += collect_submodules('jose')

# 确保项目自身模块被收集
# 注意: 不能用 collect_submodules('app') — spec 执行时会导入 site-packages 中
# 同名的错误 'app' 包 (如 django 相关), 导致项目模块丢失。
# 改为遍历 backend/app 目录显式枚举模块名。
for _root, _dirs, _files in os.walk(os.path.join(BACKEND_DIR, 'app')):
    if '__pycache__' in _root:
        continue
    _pkg = os.path.relpath(_root, BACKEND_DIR).replace(os.sep, '.')
    for _f in _files:
        if _f.endswith('.py'):
            _mod = f"{_pkg}.{_f[:-3]}"
            if _mod.endswith('.__init__'):
                _mod = _mod[:-len('.__init__')]
            hiddenimports.append(_mod)
print(f'[INFO] 收集项目模块 {len([h for h in hiddenimports if h.startswith("app.")])} 个')

# ============ 数据文件 ============
datas = []

# 前端构建产物 (如果存在)
if os.path.isdir(FRONTEND_DIST):
    datas.append((FRONTEND_DIST, 'dist'))
    print(f'[INFO] 包含前端构建产物: {FRONTEND_DIST}')
else:
    print(f'[WARN] 前端 dist 目录不存在: {FRONTEND_DIST}')
    print(f'[WARN] 请先在 frontend 目录执行 npm run build')

# config.ini 配置文件 (放在可执行程序同目录, 部署后可修改)
config_ini_path = os.path.join(BACKEND_DIR, 'config.ini')
if os.path.isfile(config_ini_path):
    datas.append((config_ini_path, '.'))
    print(f'[INFO] 包含配置文件: {config_ini_path}')

# ============ Analysis ============
a = Analysis(
    ['run.py'],
    pathex=[BACKEND_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大模块以减小体积
        'tkinter',
        'matplotlib',
        'scipy',
        'numpy',
        'pandas',
        'pytest',
        'IPython',
        'jupyter',
        # 本机环境装有 django, 项目不依赖, 排除避免误打包
        'django',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ============ PYZ ============
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ============ 版本信息资源 (降低杀毒软件误报) ============
# 无版本信息/公司信息的无名 EXE 是启发式杀毒的高危特征, 显式嵌入合法元数据
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo,
    FixedFileInfo,
    StringFileInfo,
    StringTable,
    StringStruct,
    VarFileInfo,
    VarStruct,
)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(1, 0, 0, 0),
        prodvers=(1, 0, 0, 0),
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,  # VFT_APP 应用程序
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringTable('080404b0', [
                StringStruct('CompanyName', 'CN AME Digital OPEX'),
                StringStruct('FileDescription', 'MSIA 审核管理系统服务端'),
                StringStruct('FileVersion', '1.0.0.0'),
                StringStruct('InternalName', 'msia_server'),
                StringStruct('LegalCopyright', 'Copyright (C) 2026 CN AME'),
                StringStruct('OriginalFilename', 'msia_server.exe'),
                StringStruct('ProductName', 'MSIA Audit Management System'),
                StringStruct('ProductVersion', '1.0.0.0'),
            ]),
        ]),
        VarFileInfo([VarStruct('Translation', [2052, 1200])]),
    ],
)

# ============ EXE ============
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='msia_server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX 压缩是杀毒软件误报的首要诱因 (加壳特征), 显式禁用
    upx=False,
    console=True,  # 控制台程序, 方便查看日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可添加 .ico 图标路径
    version=version_info,
)

# ============ COLL (目录模式) ============
# 使用 onedir 模式 (而非 onefile), 启动更快且便于配置文件管理;
# onefile 自解压行为易被杀毒判定为可疑, onedir 更安全
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='msia_server',
)
