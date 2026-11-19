# -*- coding: utf-8 -*-
"""BOL 管理分析平台 - PyInstaller 打包配置

使用方式：
    cd backend
    pyinstaller bol_server.spec --noconfirm

输出：
    dist/BOLServer/BOLServer.exe          可执行程序
    dist/BOLServer/frontend/dist/         前端构建产物
    dist/BOLServer/staticfiles/           Django 静态文件
"""
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# ============================================================
# 路径定义
# ============================================================
SPEC_DIR = Path(SPECPATH).resolve()  # backend 目录
PROJECT_ROOT = SPEC_DIR.parent        # 项目根目录
FRONTEND_DIST = PROJECT_ROOT / 'frontend' / 'dist'
STATICFILES_DIR = SPEC_DIR / 'staticfiles'

# ============================================================
# 数据文件（datas）
# ============================================================
datas = []

# 1. 前端构建产物（index.html + assets + 静态资源）
# 瘦身说明：staticfiles（Django collectstatic 输出）已包含 frontend/dist 的全部内容，
# 因此打包内部不再重复包含 frontend/dist，仅保留 staticfiles 即可。
# 部署时若想更新前端，可在 exe 同目录放置 frontend/dist 覆盖（可选）。
if FRONTEND_DIST.exists():
    print(f'[spec] 跳过前端 dist（已包含在 staticfiles 中，避免重复）: {FRONTEND_DIST}')
else:
    print(f'[spec][警告] 前端 dist 不存在: {FRONTEND_DIST}')

# 2. Django 收集的静态文件（包含前端构建产物 + admin/rest_framework 静态资源）
if STATICFILES_DIR.exists():
    datas.append((str(STATICFILES_DIR), 'staticfiles'))
    print(f'[spec] 包含静态文件: {STATICFILES_DIR}')
else:
    print(f'[spec][警告] staticfiles 不存在: {STATICFILES_DIR}')

# 3. Django migrations 文件
apps_dir = SPEC_DIR / 'apps'
for app_name in os.listdir(str(apps_dir)):
    mig_dir = apps_dir / app_name / 'migrations'
    if mig_dir.exists() and mig_dir.is_dir():
        datas.append((str(mig_dir), f'apps/{app_name}/migrations'))
        print(f'[spec] 包含 migrations: apps/{app_name}/migrations')

# 4. Django management commands
mgmt_dir = apps_dir / 'users' / 'management'
if mgmt_dir.exists():
    datas.append((str(mgmt_dir), 'apps/users/management'))
    print(f'[spec] 包含 management commands: apps/users/management')

# 4. analytics management commands（改善机会分析周报发送命令）
analytics_mgmt_dir = apps_dir / 'analytics' / 'management'
if analytics_mgmt_dir.exists():
    datas.append((str(analytics_mgmt_dir), 'apps/analytics/management'))
    print(f'[spec] 包含 management commands: apps/analytics/management')

# 4.2 reports management commands（季度/年度报告生成命令 gen_report）
reports_mgmt_dir = apps_dir / 'reports' / 'management'
if reports_mgmt_dir.exists():
    datas.append((str(reports_mgmt_dir), 'apps/reports/management'))
    print(f'[spec] 包含 management commands: apps/reports/management')

# 4.3 reports app 数据文件（echarts.min.js：报告生成时内联进 HTML，
#     report_html.py 通过 Path(__file__).parent 定位，必须随包发布否则生成报告时报错）
echarts_js = apps_dir / 'reports' / 'echarts.min.js'
if echarts_js.exists():
    datas.append((str(echarts_js), 'apps/reports'))
    print(f'[spec] 包含 apps/reports/echarts.min.js')
else:
    print(f'[spec][警告] apps/reports/echarts.min.js 不存在（报告生成将失败）')

# 4.5 数据库连接配置示例文件（部署时复制为 db_config.ini 并修改）
db_cfg_example = SPEC_DIR / 'db_config.ini.example'
if db_cfg_example.exists():
    datas.append((str(db_cfg_example), '.'))
    print(f'[spec] 包含 db_config.ini.example')
else:
    print(f'[spec][警告] db_config.ini.example 不存在: {db_cfg_example}')

# 5. 收集第三方库的数据文件
datas += collect_data_files('django', include_py_files=False)
datas += collect_data_files('rest_framework', include_py_files=False)
datas += collect_data_files('django_filters', include_py_files=False)

# ============================================================
# 隐藏导入（hiddenimports）
# ============================================================
hiddenimports = []

# Django 核心模块
hiddenimports += collect_submodules('django.contrib')
hiddenimports += collect_submodules('django.utils')
hiddenimports += collect_submodules('django.db.backends')
hiddenimports += collect_submodules('django.templatetags')
hiddenimports += collect_submodules('django.middleware')

# 第三方库
hiddenimports += collect_submodules('rest_framework')
hiddenimports += collect_submodules('corsheaders')
hiddenimports += collect_submodules('django_filters')
hiddenimports += collect_submodules('waitress')
hiddenimports += collect_submodules('openpyxl')

# 邮件 + 定时任务相关
# apscheduler：每周二 12:00 推送改善机会分析周报
# 只收集实际使用的子模块，避免引入 sqlalchemy/mongodb/redis/zookeeper 等不需要的依赖
hiddenimports += [
    'apscheduler',
    'apscheduler.schedulers',
    'apscheduler.schedulers.background',
    'apscheduler.schedulers.blocking',
    'apscheduler.executors',
    'apscheduler.executors.base',
    'apscheduler.executors.pool',
    'apscheduler.jobstores',
    'apscheduler.jobstores.base',
    'apscheduler.jobstores.memory',
    'apscheduler.triggers',
    'apscheduler.triggers.base',
    'apscheduler.triggers.cron',
    'apscheduler.triggers.date',
    'apscheduler.triggers.interval',
    'apscheduler.job',
    'apscheduler.events',
    'apscheduler.util',
    # tzlocal: apscheduler 依赖，用于获取本地时区
    'tzlocal',
]
# email 相关：Django 邮件后端依赖 smtplib + email 包
hiddenimports += collect_submodules('email')
hiddenimports += collect_submodules('email.mime')

# SQL Server 驱动
hiddenimports += collect_submodules('mssql')
hiddenimports += ['pyodbc']

# 统一身份登录 OIDC（Keycloak）：PyJWT + cryptography（RS256 验签, 方案文档第 6 章）
hiddenimports += [
    'jwt',
    'jwt.algorithms',
    'cryptography',
    'cryptography.hazmat.bindings._rust',
]

# 项目本地 apps
hiddenimports += collect_submodules('apps')
hiddenimports += collect_submodules('bol_platform')
# 显式添加 bol_platform 子模块（collect_submodules 可能漏掉未被导入的模块）
hiddenimports += [
    'bol_platform.settings_prod',
    'bol_platform.db_router',
    'bol_platform.exceptions',
    'bol_platform.pagination',
    'bol_platform.asgi',
    'bol_platform.bol_calc',
]

# Django migrations 模块
for app_name in ['actual_ct', 'analytics', 'budget_bol', 'dynamic_bol', 'projects', 'reports', 'tracking', 'users']:
    hiddenimports.append(f'apps.{app_name}.migrations')
    mig_dir = apps_dir / app_name / 'migrations'
    if mig_dir.exists():
        for f in mig_dir.glob('*.py'):
            if f.stem != '__init__':
                hiddenimports.append(f'apps.{app_name}.migrations.{f.stem}')

# management commands
hiddenimports.append('apps.users.management')
hiddenimports.append('apps.users.management.commands')
hiddenimports.append('apps.users.management.commands.create_admin')
# users 状态回写命令（SSO 中央表 -> 本地员工状态, R8）
hiddenimports.append('apps.users.management.commands.sync_sso_status')

# analytics management commands（改善机会分析周报发送命令）
hiddenimports.append('apps.analytics.management')
hiddenimports.append('apps.analytics.management.commands')
hiddenimports.append('apps.analytics.management.commands.send_improvement_report')

# reports management commands（季度/年度报告生成命令）
hiddenimports.append('apps.reports.management')
hiddenimports.append('apps.reports.management.commands')
hiddenimports.append('apps.reports.management.commands.gen_report')


# ============================================================
# 排除模块（减小体积）
# 项目未使用的重型库：scipy(76MB), numpy(26MB), pandas(17MB), PIL(12MB), lxml(6MB)
# 瘦身新增：grpc(10MB), mysql(6.85MB), sqlalchemy, google, yaml, win32com 等
# ============================================================
excludes = [
    # 项目完全未使用的重型科学计算库
    'scipy',
    'numpy',
    'pandas',
    'PIL',
    'Pillow',
    'lxml',
    'matplotlib',
    # Django GIS 模块（依赖 numpy，项目不使用）
    'django.contrib.gis',
    # 测试/文档/开发工具
    'tkinter',
    'pytest',
    'sphinx',
    'docutils',
    'IPython',
    'notebook',
    'jupyter',
    'pip',
    'setuptools',
    'wheel',
    'distutils',
    'unittest',
    'pydoc',
    'doctest',
    'turtledemo',
    # 不需要的网络协议库
    # 注意：smtplib 已移出排除列表，邮件功能（改善机会周报推送）依赖它
    'ftplib',
    'imaplib',
    'poplib',
    'nntplib',
    'telnetlib',
    'xmlrpc',
    # ===== 瘦身新增：项目未使用的第三方库 =====
    # gRPC 及其依赖（10 MB）- 项目不使用 RPC
    'grpc',
    'google',
    'google.protobuf',
    'googleapis',
    # MySQL 客户端（6.85 MB libmysql.dll）- 项目使用 SQL Server
    'mysql',
    'pymysql',
    'MySQLdb',
    # SQLAlchemy ORM（0.41 MB）- 项目使用 Django ORM
    'sqlalchemy',
    # greenlet（0.21 MB）- sqlalchemy 协程依赖
    'greenlet',
    # PyYAML（0.25 MB）- 仅 Django 序列化器惰性使用，项目未用 YAML 格式
    'yaml',
    'PyYAML',
    # Windows COM 自动化（0.2 MB）- 项目不使用 Office/COM 自动化
    'win32com',
    'pythoncom',
    'pywintypes',
    'win32',
    'Pythonwin',
    'pywin32',
    # pyreadline3 - Windows readline 替代，Django/waitress 不需要
    'pyreadline3',
    # 数据库连接池（项目未使用）
    'dbutils',
    # 加密库的冗余部分（保留 django/core/management 加密所需的核心）
    # 注意：不排除整个 cryptography，因为 SSL 可能需要
    # CSV/JSON 已是标准库，无需额外排除
    # 重复的 x64 DLL 由 PyInstaller 自动处理，无需在此指定
]


# ============================================================
# Analysis
# ============================================================
block_cipher = None

a = Analysis(
    ['run_server.py'],
    pathex=[str(SPEC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BOLServer',
    # 版本信息资源：嵌入公司/产品元数据，降低杀毒软件启发式误报概率
    version=str(SPEC_DIR / 'version_info.py'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # 防杀软误报关键项：
    # 1) upx=False —— UPX 加壳是 PyInstaller 程序被误报的首要原因
    # 2) onedir 模式（COLLECT）—— 单文件 exe 自解压行为特征与恶意软件相似，勿改 onefile
    # 3) 不使用任何加壳/加密/混淆（block_cipher=None）
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BOLServer',
)
