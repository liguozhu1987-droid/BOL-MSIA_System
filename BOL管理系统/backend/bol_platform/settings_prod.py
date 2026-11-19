# -*- coding: utf-8 -*-
"""BOL 管理分析平台 - 生产环境配置

继承基础 settings.py，覆盖以下配置：
  - DEBUG = False（关闭调试模式）
  - 前端静态文件由 Django 直接提供（无需 Vite/Nginx）
  - SPA 路由回退（Vue Router history 模式支持）
  - 安全相关配置
  - 兼容 PyInstaller 打包环境

使用方式：
  设置环境变量 DJANGO_SETTINGS_MODULE=bol_platform.settings_prod
  或在 run_server.py 中指定
"""
import os
import sys
from pathlib import Path

from .settings import *  # noqa: F401,F403 继承基础配置

# ============================================================
# 基础配置
# ============================================================
DEBUG = False

# 允许的主机：生产环境允许所有（内网部署）
ALLOWED_HOSTS = ['*']


# ============================================================
# 运行环境检测：PyInstaller 打包环境 vs 普通部署
# ============================================================
def _is_frozen():
    """检测是否运行在 PyInstaller 打包环境中"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


if _is_frozen():
    # PyInstaller 打包环境
    # _MEIPASS 是 PyInstaller 解压临时目录（包含打包进 exe 的资源）
    _MEIPASS = Path(sys._MEIPASS)
    # 可执行文件所在目录（用于外部资源，如 frontend/dist）
    _APP_DIR = Path(sys.executable).resolve().parent

    # 打包在 exe 内部的资源（Django 源码、migrations 等）
    BASE_DIR = _MEIPASS

    # 前端 dist 优先从外部目录加载（便于更新前端），其次从打包内部加载
    _external_dist = _APP_DIR / 'frontend' / 'dist'
    _internal_dist = _MEIPASS / 'frontend' / 'dist'
    FRONTEND_DIST = _external_dist if _external_dist.exists() else _internal_dist

    # 静态文件目录：优先外部，其次内部
    _external_static = _APP_DIR / 'staticfiles'
    _internal_static = _MEIPASS / 'staticfiles'
    STATIC_ROOT = _external_static if _external_static.exists() else _internal_static
else:
    # 普通部署环境（python run_server.py）
    # 前端 dist 目录（构建后的 Vue 应用）
    FRONTEND_DIST = BASE_DIR.parent / 'frontend' / 'dist'
    # collectstatic 输出目录
    STATIC_ROOT = BASE_DIR / 'staticfiles'


# ============================================================
# 静态文件配置：前端构建产物由 Django 提供
# ============================================================
# 静态文件 URL 前缀
STATIC_URL = 'static/'

# 额外的静态文件目录（前端构建产物）
if FRONTEND_DIST.exists():
    STATICFILES_DIRS = [FRONTEND_DIST]

# 静态文件存储后端：生产环境使用 ManifestStaticFilesStorage（带版本哈希）
# 但前端已自带 hash，这里用默认即可
# STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'

# ============================================================
# 安全配置
# ============================================================
# 反向代理场景：TLS 在 IIS 终结，由 IIS 注入 X-Forwarded-Proto: https。
# 无该请求头时（当前明文直连部署）本配置不生效，不改变现有行为。
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# 内网 HTTP 部署，关闭 HTTPS 相关安全头
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# ============================================================
# 前端 SPA 配置
# ============================================================
# 前端首页文件路径（用于 SPA 路由回退）
# 优先从 frontend/dist 读取；若不存在（瘦身后只保留 staticfiles），则从 STATIC_ROOT 读取
if FRONTEND_DIST.exists():
    FRONTEND_INDEX = FRONTEND_DIST / 'index.html'
elif STATIC_ROOT.exists():
    FRONTEND_INDEX = STATIC_ROOT / 'index.html'
else:
    FRONTEND_INDEX = None

# 登录令牌有效期（生产环境延长至 7 天）
AUTH_TOKEN_EXPIRE_HOURS = 168

# 前端基础 URL（用于邮件链接等，生产环境由实际部署地址决定）
# 可通过环境变量覆盖
FRONTEND_BASE_URL = os.environ.get('BOL_FRONTEND_URL', '')


# ============================================================
# 性能优化：gzip 压缩 + 静态资源长缓存
# ------------------------------------------------------------
# 修复"Edge 等浏览器访问极慢 / 几乎无法进入"问题：
#   根因是首屏静态资源体积过大（含 5.26MB 背景图）、未 gzip、未设置
#   缓存头，导致浏览器冷启动要反复全量下载近 7MB。
#   这里：
#     1. 开启 GZipMiddleware 压缩 HTML/CSS/JS（约省 60-70% 传输）
#     2. 为带版本 hash 的 /assets/ 资源设置 immutable 一年长缓存，
#        浏览器（含 Edge）稳定本地命中，杜绝反复下载
# ============================================================
def static_cache_headers(get_response):
    """为静态资源设置合理的 Cache-Control，避免浏览器反复下载大文件。"""
    def middleware(request):
        response = get_response(request)
        path = request.path
        if path.startswith('/assets/'):
            # 带版本 hash 的构建产物：内容永不改变，immutable 长缓存
            response.setdefault('Cache-Control', 'public, max-age=31536000, immutable')
        elif path.startswith('/fonts/'):
            # 字体文件：极少变更，长缓存
            response.setdefault('Cache-Control', 'public, max-age=31536000, immutable')
        elif path.startswith('/static/'):
            # 非 hash 静态资源（图片等）：7 天，兼顾更新可见性与重复下载
            response.setdefault('Cache-Control', 'public, max-age=604800')
        return response
    return middleware


MIDDLEWARE = [
    'django.middleware.gzip.GZipMiddleware',
    'bol_platform.settings_prod.static_cache_headers',
] + MIDDLEWARE
