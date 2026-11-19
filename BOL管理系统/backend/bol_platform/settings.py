# -*- coding: utf-8 -*-
"""
Django settings for bol_platform project.
BOL管理分析平台 - 双数据库配置（HRDB只读 + CMC读写）

支持通过外部配置文件（db_config.ini）覆盖数据库连接参数，
便于部署到不同服务器时切换 ODBC 驱动版本（17/18）等。
"""
import os
import sys
import configparser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-yg+pv150p%_#2l3v5@3$thk!_wssnpe8#5fz%qm)&_k%#7c4u!'

DEBUG = True

ALLOWED_HOSTS = ['*']


# ============================================================
# 数据库连接参数：默认值 + 外部配置文件覆盖
# ============================================================
# 默认值（部署环境）
# 默认使用 ODBC Driver 18（部署服务器已安装的版本）
# 如需切换为 Driver 17，可通过 db_config.ini 覆盖
_DB_DEFAULTS = {
    'host': 'IRSCNYTFINEREPORT.ap.inalfa.local,1433',
    'user': 'sparePartRead',
    # 代码中不写入口令：部署时必须通过 db_config.ini 的 [database] password 提供
    'password': '',
    'driver': 'ODBC Driver 18 for SQL Server',
    'extra_params': 'TrustServerCertificate=yes;Encrypt=no;',
}


def _load_db_config():
    """从外部 db_config.ini 读取数据库连接参数，覆盖默认值。

    配置文件查找顺序：
      1. PyInstaller 环境：可执行文件同目录下的 db_config.ini
      2. 普通环境：backend 目录下的 db_config.ini
      3. 环境变量 BOL_DB_CONFIG 指定的路径

    配置文件格式：
        [database]
        host = server.example.com,1433
        user = dbuser
        password = dbpassword
        driver = ODBC Driver 18 for SQL Server
        extra_params = TrustServerCertificate=yes;Encrypt=no;
    """
    cfg = dict(_DB_DEFAULTS)

    # 候选配置文件路径
    candidates = []
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # PyInstaller 打包环境：可执行文件同目录
        candidates.append(Path(sys.executable).resolve().parent / 'db_config.ini')
    else:
        # 普通环境：backend 目录
        candidates.append(BASE_DIR / 'db_config.ini')

    # 环境变量指定的路径（最高优先级）
    env_path = os.environ.get('BOL_DB_CONFIG')
    if env_path:
        candidates.insert(0, Path(env_path))

    config_file = None
    for p in candidates:
        if p.exists():
            config_file = p
            break

    if config_file:
        try:
            parser = configparser.ConfigParser()
            # 使用 utf-8-sig 自动处理 BOM（用户用记事本另存为可能加 BOM）
            parser.read(str(config_file), encoding='utf-8-sig')
            if parser.has_section('database'):
                for key in cfg.keys():
                    if parser.has_option('database', key):
                        cfg[key] = parser.get('database', key).strip()
            print(f'[settings] 已加载数据库配置: {config_file}')
            print(f'[settings] ODBC 驱动: {cfg["driver"]}')
        except Exception as e:
            print(f'[settings][警告] 读取配置文件失败 {config_file}: {e}')
            print('[settings] 回退到默认数据库参数')
    else:
        print('[settings] 未找到 db_config.ini，使用默认数据库参数')
        print(f'[settings] ODBC 驱动: {cfg["driver"]}')

    return cfg


_db_cfg = _load_db_config()

# SQL Server 连接公共参数
DB_HOST = _db_cfg['host']
DB_USER = _db_cfg['user']
DB_PASSWORD = _db_cfg['password']
DB_OPTIONS = {
    'driver': _db_cfg['driver'],
    # 限制数据库建立连接时的等待，避免 SQL Server 网络异常时占满服务线程。
    'extra_params': (
        _db_cfg['extra_params']
        if 'connection timeout=' in _db_cfg['extra_params'].lower()
        else f"{_db_cfg['extra_params'].rstrip(';')};Connection Timeout=30;"
    ),
}

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # 第三方
    'rest_framework',
    'corsheaders',
    'django_filters',
    # 本项目应用
    'apps.projects',
    'apps.dynamic_bol',
    'apps.budget_bol',
    'apps.actual_ct',
    'apps.tracking',
    'apps.analytics',
    'apps.users',
    'apps.reports',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'bol_platform.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'bol_platform.wsgi.application'

# ============================================================
# 数据库配置：双库
#   - default (CMC)：新平台读写库，存放 Budget BOL / 传感器缓存 / 跟踪记录 / 改善计划
#   - hrdb (HRDB)：只读，访问现有动态BOL系统数据
# ============================================================
DATABASES = {
    'default': {
        'ENGINE': 'mssql',
        'NAME': 'CMC',
        'HOST': DB_HOST,
        'USER': DB_USER,
        'PASSWORD': DB_PASSWORD,
        'OPTIONS': DB_OPTIONS,
    },
    'hrdb': {
        'ENGINE': 'mssql',
        'NAME': 'HRDB',
        'HOST': DB_HOST,
        'USER': DB_USER,
        'PASSWORD': DB_PASSWORD,
        'OPTIONS': DB_OPTIONS,
        'TEST': {
            'MIGRATE': False,
        },
    },
}

# 数据库路由：HRDB 的模型只读，CMC 的模型可读写
DATABASE_ROUTERS = ['bol_platform.db_router.BolDbRouter']

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# 前端构建产物目录（collectstatic 会从此目录收集前端 JS/CSS/图片等）
# collectstatic 执行时会把 frontend/dist 的内容复制到 STATIC_ROOT
FRONTEND_DIST = BASE_DIR.parent / 'frontend' / 'dist'
if FRONTEND_DIST.exists():
    STATICFILES_DIRS = [FRONTEND_DIST]

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ============================================================
# REST Framework
# ============================================================
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'bol_platform.pagination.CustomPageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'apps.users.authentication.EmployeeTokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'apps.users.permissions.IsAuthenticatedEmployee',
    ],
    'EXCEPTION_HANDLER': 'bol_platform.exceptions.custom_exception_handler',
}

# ============================================================
# 认证配置
# ============================================================
AUTH_TOKEN_EXPIRE_HOURS = 168          # 登录令牌有效期（7 天）
PASSWORD_RESET_EXPIRE_HOURS = 1        # 密码重置令牌有效期（1 小时）
FRONTEND_BASE_URL = 'http://127.0.0.1:5173'

# ============================================================
# 邮件配置：公司内部邮件服务器（172.19.253.10:25，SSL 无密码）
# 支持 db_config.ini [email] 段覆盖
# ============================================================
_EMAIL_DEFAULTS = {
    'host': '172.19.253.10',
    'port': '25',
    'use_ssl': 'True',
    'use_tls': 'False',
    'user': '',
    'password': '',
    'from_email': 'BOL管理系统 <bol-system@inalfa.local>',
    'admin_email': '',
}

def _load_email_config():
    """从 db_config.ini [email] 段读取邮件配置，覆盖默认值"""
    cfg = dict(_EMAIL_DEFAULTS)
    candidates = []
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        candidates.append(Path(sys.executable).resolve().parent / 'db_config.ini')
    else:
        candidates.append(BASE_DIR / 'db_config.ini')
    env_path = os.environ.get('BOL_DB_CONFIG')
    if env_path:
        candidates.insert(0, Path(env_path))

    for p in candidates:
        if p.exists():
            try:
                parser = configparser.ConfigParser()
                # 使用 utf-8-sig 自动处理 BOM（与 _load_db_config 一致）
                parser.read(str(p), encoding='utf-8-sig')
                if parser.has_section('email'):
                    for key in cfg.keys():
                        if parser.has_option('email', key):
                            cfg[key] = parser.get('email', key).strip()
                print(f'[settings] 已加载邮件配置: {p}')
            except Exception as e:
                print(f'[settings][警告] 读取邮件配置失败: {e}')
            break
    return cfg

_email_cfg = _load_email_config()

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = _email_cfg['host']
EMAIL_PORT = int(_email_cfg['port'])
EMAIL_USE_SSL = _email_cfg['use_ssl'].lower() in ('true', '1', 'yes')
EMAIL_USE_TLS = _email_cfg['use_tls'].lower() in ('true', '1', 'yes')
EMAIL_HOST_USER = _email_cfg['user']
EMAIL_HOST_PASSWORD = _email_cfg['password']
DEFAULT_FROM_EMAIL = _email_cfg['from_email']

# 管理员邮箱（接收改善分析报告，多个用逗号分隔）
ADMIN_EMAIL = _email_cfg['admin_email']

# ============================================================
# 认证功能开关 + 统一身份登录 (OIDC) 配置 (方案文档 6.2)
# 优先级: 环境变量 (OIDC_*/CORS_ALLOWED_ORIGINS) > db_config.ini > 代码默认值
# ============================================================
# 默认值 (双轨期安全值: Keycloak 未部署完成时 OIDC_ENABLED=False,
# 系统行为与改造前完全一致; 部署完成后改 db_config.ini 即可, 无需改代码)
_AUTH_DEFAULTS = {
    # [auth] 功能开关
    'self_registration_enabled': 'False',     # R7: 关闭自助注册 (影子账号最大来源)
    'local_auth_enabled': 'True',             # 双轨开关: 本地账密登录 (P4 单轨时置 false)
    'password_self_service_enabled': 'True',  # R14: 密码自助服务 (改密/找回/重置)
    'sso_status_sync_enabled': 'True',        # 每小时从中央表回写员工状态 (R8 核心)
    'sso_status_sync_hours': '1',             # 状态回写频率 (小时)
    # [oidc] 统一身份登录 (Keycloak)
    'oidc_enabled': 'False',
    'oidc_issuer': 'https://sso.ap.inalfa.local/realms/inalfa',
    'oidc_client_id': 'bol-prod',
    'oidc_client_secret': '',
    # 回调地址必须与 Keycloak bol-prod 的 Valid redirect URIs 精确一致;
    # BOL 对外 URL 待确认 (方案文档 U2), 暂按 waitress 默认端口占位
    'oidc_redirect_uri': 'http://127.0.0.1:8090/api/auth/oidc/callback',
    'oidc_front_callback': '/oidc/callback',
    'oidc_required_group': 'app-bol',
    'oidc_auto_create_user': 'True',
    'oidc_scopes': 'openid profile email',
    # CORS 白名单 (逗号分隔); 留空 = 允许全部 (内网开发默认, 与改造前一致)
    'cors_allowed_origins': '',
}

# [oidc] 段 (db_config.ini) 键名 -> _AUTH_DEFAULTS 配置项 (去 oidc_ 前缀, 与 MSIA 风格一致)
_OIDC_KEY_MAP = {
    'enabled': 'oidc_enabled',
    'issuer': 'oidc_issuer',
    'client_id': 'oidc_client_id',
    'client_secret': 'oidc_client_secret',
    'redirect_uri': 'oidc_redirect_uri',
    'front_callback': 'oidc_front_callback',
    'required_group': 'oidc_required_group',
    'auto_create_user': 'oidc_auto_create_user',
    'scopes': 'oidc_scopes',
}

# 环境变量覆盖 (优先级: 环境变量 > db_config.ini > 代码默认值)
# 变量名与 MSIA app/core/config.py 的 OIDC_* 保持同名
_AUTH_ENV_MAP = {
    'oidc_enabled': 'OIDC_ENABLED',
    'oidc_issuer': 'OIDC_ISSUER',
    'oidc_client_id': 'OIDC_CLIENT_ID',
    'oidc_client_secret': 'OIDC_CLIENT_SECRET',
    'oidc_redirect_uri': 'OIDC_REDIRECT_URI',
    'oidc_front_callback': 'OIDC_FRONT_CALLBACK',
    'oidc_required_group': 'OIDC_REQUIRED_GROUP',
    'oidc_auto_create_user': 'OIDC_AUTO_CREATE_USER',
    'oidc_scopes': 'OIDC_SCOPES',
    'cors_allowed_origins': 'CORS_ALLOWED_ORIGINS',
}

_BOOL_CONFIG_KEYS = {'oidc_enabled', 'oidc_auto_create_user'}
_BOOL_TOKENS = {'true', '1', 'yes', 'on', 'false', '0', 'no', 'off'}


def _apply_env_overrides(cfg):
    """用环境变量覆盖认证配置 (空值/非法布尔值不覆盖, 保持文件或默认行为)"""
    for cfg_key, env_name in _AUTH_ENV_MAP.items():
        raw = os.environ.get(env_name)
        if raw is None or not str(raw).strip():
            continue
        value = str(raw).strip()
        if cfg_key in _BOOL_CONFIG_KEYS and value.lower() not in _BOOL_TOKENS:
            print(f'[settings][警告] 环境变量 {env_name}={raw!r} 不是合法布尔值, 已忽略')
            continue
        cfg[cfg_key] = value
    return cfg


def _load_auth_config():
    """从外部 db_config.ini 读取 [auth] / [oidc] 段, 覆盖认证配置默认值

    配置文件查找顺序与 _load_db_config 一致:
      1. PyInstaller 环境: 可执行文件同目录下的 db_config.ini
      2. 普通环境: backend 目录下的 db_config.ini
      3. 环境变量 BOL_DB_CONFIG 指定的路径

    优先级: 环境变量 (见 _AUTH_ENV_MAP) > 本文件 > _AUTH_DEFAULTS。
    环境变量为空或布尔值非法时不覆盖 (行为与仅读文件一致)。

    键名约定 (与 MSIA config.ini 风格一致):
      - [auth] 段键名与配置项一致 (self_registration_enabled 等)
      - [oidc] 段键名为配置项去 oidc_ 前缀 (enabled/issuer/client_id 等),
        通过 _OIDC_KEY_MAP 映射, 避免配置项前缀泄漏到配置文件
    """
    cfg = dict(_AUTH_DEFAULTS)

    candidates = []
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        candidates.append(Path(sys.executable).resolve().parent / 'db_config.ini')
    else:
        candidates.append(BASE_DIR / 'db_config.ini')
    env_path = os.environ.get('BOL_DB_CONFIG')
    if env_path:
        candidates.insert(0, Path(env_path))

    for p in candidates:
        if not p.exists():
            continue
        try:
            parser = configparser.ConfigParser()
            # 使用 utf-8-sig 自动处理 BOM (用户用记事本另存为可能加 BOM)
            parser.read(str(p), encoding='utf-8-sig')
            # [auth] 段: 键名直配
            if parser.has_section('auth'):
                for key in cfg.keys():
                    if not key.startswith('oidc_') and parser.has_option('auth', key):
                        cfg[key] = parser.get('auth', key).strip()
            # [oidc] 段: 去前缀键名 -> 配置项映射
            if parser.has_section('oidc'):
                for ini_key, cfg_key in _OIDC_KEY_MAP.items():
                    if parser.has_option('oidc', ini_key):
                        cfg[cfg_key] = parser.get('oidc', ini_key).strip()
            print(f'[settings] 已加载认证配置: {p}')
        except Exception as e:
            print(f'[settings][警告] 读取认证配置失败 {p}: {e}')
        break
    return _apply_env_overrides(cfg)


def _as_bool(value, default=False):
    """配置值转布尔 (与 _load_email_config 的口径一致)"""
    if value is None:
        return default
    return str(value).strip().lower() in ('true', '1', 'yes', 'on')


_auth_cfg = _load_auth_config()

# ---- 功能开关 (双轨期, 方案文档 8.1 开关矩阵) ----
SELF_REGISTRATION_ENABLED = _as_bool(_auth_cfg['self_registration_enabled'], False)
LOCAL_AUTH_ENABLED = _as_bool(_auth_cfg['local_auth_enabled'], True)
PASSWORD_SELF_SERVICE_ENABLED = _as_bool(_auth_cfg['password_self_service_enabled'], True)
SSO_STATUS_SYNC_ENABLED = _as_bool(_auth_cfg['sso_status_sync_enabled'], True)
try:
    SSO_STATUS_SYNC_HOURS = max(1, int(_auth_cfg['sso_status_sync_hours']))
except (TypeError, ValueError):
    SSO_STATUS_SYNC_HOURS = 1

# ---- 统一身份登录 (Keycloak OIDC, 方案文档第 6 章) ----
OIDC_ENABLED = _as_bool(_auth_cfg['oidc_enabled'], False)
OIDC_ISSUER = _auth_cfg['oidc_issuer']
OIDC_CLIENT_ID = _auth_cfg['oidc_client_id']
OIDC_CLIENT_SECRET = _auth_cfg['oidc_client_secret']
OIDC_REDIRECT_URI = _auth_cfg['oidc_redirect_uri']
OIDC_FRONT_CALLBACK = _auth_cfg['oidc_front_callback']
OIDC_REQUIRED_GROUP = _auth_cfg['oidc_required_group']
OIDC_AUTO_CREATE_USER = _as_bool(_auth_cfg['oidc_auto_create_user'], True)
OIDC_SCOPES = _auth_cfg['oidc_scopes']

# 定时任务开关（生产环境启用）
SCHEDULER_ENABLED = True

# CORS：默认内网放行全部 (与改造前一致); 配置 [auth] cors_allowed_origins
# (或环境变量 CORS_ALLOWED_ORIGINS, 逗号分隔) 后收紧为显式白名单
_cors_raw = _auth_cfg.get('cors_allowed_origins', '')
CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_raw.split(',') if o.strip()]
CORS_ALLOW_ALL_ORIGINS = not CORS_ALLOWED_ORIGINS
CORS_ALLOW_CREDENTIALS = True

# BOL 计算参数（1+1/15 中的 1/15 是间接人员系数）
BOL_INDIRECT_RATIO = 1.0 / 15.0

# ============================================================
# 传感器采集系统 API 配置
# ============================================================
SENSOR_API_BASE_URL = 'http://10.1.1.100:8080'  # 传感器API地址（待确认）
SENSOR_API_KEY = ''  # API密钥（如有）
SENSOR_FETCH_TIMEOUT = 30  # 拉取超时秒数
