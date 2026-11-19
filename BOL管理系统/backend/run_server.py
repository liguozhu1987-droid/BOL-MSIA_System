# -*- coding: utf-8 -*-
"""BOL 管理分析平台 - 生产环境启动脚本

使用 waitress 作为 WSGI 服务器，提供生产级并发处理能力。
前端静态文件由 Django 直接提供（无需 Nginx）。

支持两种运行模式：
  1. 普通模式：python run_server.py
  2. PyInstaller 打包模式：直接运行 exe（自动检测 frozen 环境）

使用方式：
    python run_server.py              # 默认 0.0.0.0:8090
    python run_server.py --port 9000  # 自定义端口
    BOLServer.exe --host 127.0.0.1 --port 8090  # 打包后可执行程序
"""
import os
import sys
import io
import argparse
from pathlib import Path

# ============================================================
# 控制台编码设置（解决 PyInstaller 环境下中文输出 UnicodeEncodeError）
# ============================================================
if sys.platform == 'win32':
    # 强制 stdout/stderr 使用 UTF-8 编码
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, io.UnsupportedOperation):
        # Python < 3.7 或某些环境不支持 reconfigure
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        except Exception:
            pass
    # 设置环境变量，影响 colorama/waitress 等库的输出编码
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')


# ============================================================
# 运行环境检测
# ============================================================
def _is_frozen():
    """检测是否运行在 PyInstaller 打包环境中"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


if _is_frozen():
    # PyInstaller 打包环境
    # _MEIPASS 是 PyInstaller 解压临时目录（包含打包进 exe 的 Python 源码）
    _MEIPASS = Path(sys._MEIPASS)
    # 可执行文件所在目录（外部资源目录）
    APP_DIR = Path(sys.executable).resolve().parent

    # 将 _MEIPASS 加入 sys.path，确保 Django 模块可导入
    sys.path.insert(0, str(_MEIPASS))
    # 将可执行文件目录也加入，便于外部资源访问
    sys.path.insert(0, str(APP_DIR))
else:
    # 普通部署环境
    BASE_DIR = Path(__file__).resolve().parent
    sys.path.insert(0, str(BASE_DIR))
    _MEIPASS = None
    APP_DIR = None

# 设置 Django 配置模块为生产配置
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bol_platform.settings_prod')


def check_prerequisites():
    """检查启动前置条件"""
    errors = []

    if _is_frozen():
        # PyInstaller 环境：检查打包内部和外部资源
        # 前端 dist：优先外部，其次内部（瘦身后可能不存在，由 staticfiles 提供）
        ext_dist = APP_DIR / 'frontend' / 'dist'
        int_dist = _MEIPASS / 'frontend' / 'dist'
        has_frontend_dist = ext_dist.exists() or int_dist.exists()

        # 静态文件：优先外部，其次内部
        # 瘦身后前端构建产物已包含在 staticfiles 中（Django collectstatic 收集）
        ext_static = APP_DIR / 'staticfiles'
        int_static = _MEIPASS / 'staticfiles'
        has_staticfiles = ext_static.exists() or int_static.exists()

        # 只要 staticfiles 存在即可（包含前端构建产物 + admin/rest_framework 静态资源）
        # frontend/dist 是可选的（用于部署时单独更新前端）
        if not has_staticfiles and not has_frontend_dist:
            errors.append('静态文件目录和前端 dist 均不存在（已检查内部和外部路径）')
    else:
        # 普通环境：检查标准路径
        # 支持两种布局：
        #   开发布局：BASE_DIR/../frontend/dist（源码构建产物）
        #   部署包布局：BASE_DIR/staticfiles/index.html（绿色部署包，前端产物已收集）
        frontend_dist = BASE_DIR.parent / 'frontend' / 'dist'
        index_html = frontend_dist / 'index.html'
        static_index = BASE_DIR / 'staticfiles' / 'index.html'
        if not index_html.exists() and not static_index.exists():
            errors.append(
                f'前端未构建：{index_html} 与 {static_index} 均不存在，'
                f'请先执行 cd frontend && npm run build')

        static_root = BASE_DIR / 'staticfiles'
        if not static_root.exists() or not any(static_root.iterdir()):
            errors.append(
                f'静态文件未收集：{static_root} 为空，请执行 '
                f'python manage.py collectstatic --noinput'
            )

    # 检查 waitress 是否安装（PyInstaller 环境下应已打包）
    try:
        import waitress
    except ImportError:
        if _is_frozen():
            errors.append('waitress 模块未正确打包，请重新执行 PyInstaller 打包')
        else:
            errors.append('waitress 未安装，请执行 pip install waitress')

    if errors:
        print('=' * 60)
        print('  [错误] 启动前置条件未满足：')
        for e in errors:
            print(f'    - {e}')
        if not _is_frozen():
            print()
            print('  请按以下步骤修复：')
            print('    1. pip install -r requirements.txt')
            print('    2. cd ../frontend && npm install && npm run build')
            print('    3. cd ../backend && python manage.py collectstatic --noinput')
            print('    4. python manage.py migrate')
        print('=' * 60)
        sys.exit(1)


def check_database_connection():
    """启动时预检数据库连接，提前发现 ODBC 驱动配置问题。

    避免「首个 API 请求时才报错」的体验，启动即可见清晰错误。
    """
    import django
    django.setup()

    from django.db import connections
    from django.db.utils import Error as DbError

    print('-' * 60)
    print('  [数据库连接预检]')
    db_aliases = ['default', 'hrdb'] if 'hrdb' in connections.settings else ['default']
    all_ok = True
    for alias in db_aliases:
        try:
            conn = connections[alias]
            with conn.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
            driver = conn.settings_dict.get('OPTIONS', {}).get('driver', 'N/A')
            print(f'    [OK] {alias}: 连接成功 (ODBC 驱动: {driver})')
        except DbError as e:
            all_ok = False
            driver = connections[alias].settings_dict.get('OPTIONS', {}).get('driver', 'N/A')
            print(f'    [失败] {alias}: {e}')
            print(f'           当前 ODBC 驱动: {driver}')
            # 针对常见 IM002 错误给出明确指引
            err_msg = str(e)
            if 'IM002' in err_msg or 'Data source name not found' in err_msg:
                print()
                print('    >>> ODBC 驱动未找到，请按以下任一方式修复：')
                print(f'        方式1: 在服务器安装 ODBC 驱动 "{driver}"')
                print('        方式2: 复制 db_config.ini.example 为 db_config.ini，')
                print('               修改 driver 值为服务器已安装的驱动，例如：')
                print('               - ODBC Driver 17 for SQL Server')
                print('               - ODBC Driver 18 for SQL Server')
                print('               - SQL Server Native Client 11.0')
                if _is_frozen():
                    print(f'        配置文件位置: {APP_DIR / "db_config.ini"}')
                else:
                    print(f'        配置文件位置: {BASE_DIR / "db_config.ini"}')
                print('        已安装的驱动可通过 ODBC 数据源管理器 (odbcad32.exe) 查看')
        except Exception as e:
            all_ok = False
            print(f'    [失败] {alias}: {type(e).__name__}: {e}')

    if not all_ok:
        print()
        print('  [警告] 部分数据库连接失败，相关 API 将返回 500 错误。')
        print('         系统仍将启动，请按上述提示修复数据库连接。')
    print('-' * 60)


def main():
    parser = argparse.ArgumentParser(description='BOL 管理分析平台 - 生产服务器')
    parser.add_argument('--host', default='0.0.0.0', help='监听地址（默认 0.0.0.0）')
    parser.add_argument('--port', type=int, default=8090, help='监听端口（默认 8090）')
    parser.add_argument('--threads', type=int, default=16, help='线程数（默认 16）')
    args = parser.parse_args()

    check_prerequisites()

    # Django 初始化
    import django
    django.setup()

    # 数据库连接预检（在启动 waitress 前执行）
    # 提前发现 ODBC 驱动配置问题，避免首个 API 请求时才报错
    check_database_connection()

    from django.core.wsgi import get_wsgi_application
    application = get_wsgi_application()

    import waitress

    print('=' * 60)
    print('  BOL 管理分析平台 - 生产服务器')
    print(f'  监听地址: http://{args.host}:{args.port}/')
    print(f'  工作线程: {args.threads}')
    print(f'  配置文件: bol_platform.settings_prod')
    print()
    print('  按 Ctrl+C 停止服务')
    print('=' * 60)

    waitress.serve(
        application,
        host=args.host,
        port=args.port,
        threads=args.threads,
        channel_timeout=120,
        recv_bytes=65536,
        # 仅信任来自回环地址（IIS 反代）注入的 X-Forwarded-Proto，
        # 配合 settings_prod.SECURE_PROXY_SSL_HEADER 还原 https 判定；
        # 非回环来源的同名头会被 waitress 丢弃，防止外部伪造。
        trusted_proxy='127.0.0.1',
        trusted_proxy_headers={'x-forwarded-proto'},
    )


if __name__ == '__main__':
    main()
