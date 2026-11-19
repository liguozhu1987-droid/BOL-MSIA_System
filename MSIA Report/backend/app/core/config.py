"""应用配置

配置优先级 (从高到低):
1. 环境变量 (.env)  — 开发环境使用
2. config.ini 文件  — 生产部署使用 (放在可执行程序同目录)

config.ini 中的 sql_driver_version 参数可自动适配 SQL Server 驱动差异:
  - 本地开发环境通常为 17 (ODBC Driver 17 for SQL Server)
  - Windows Server 通常为 18 (ODBC Driver 18 for SQL Server)
"""
import os
import sys
import configparser
from functools import lru_cache
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote_plus

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_config_ini_path() -> Optional[Path]:
    """查找 config.ini 文件位置

    查找顺序:
    1. 可执行程序同目录 (PyInstaller 打包后)
    2. 当前工作目录
    3. backend 目录 (开发环境)
    """
    candidates = []

    # PyInstaller 冻结环境: 可执行程序同目录 + _internal 目录
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / "config.ini")
        # PyInstaller onedir 模式下, 数据文件在 _internal 子目录
        candidates.append(exe_dir / "_internal" / "config.ini")

    # 当前工作目录
    candidates.append(Path.cwd() / "config.ini")

    # backend 目录 (开发环境, config.py 在 app/core/ 下)
    candidates.append(Path(__file__).resolve().parent.parent.parent / "config.ini")

    for p in candidates:
        if p.is_file():
            return p
    return None


def _load_config_ini() -> Optional[configparser.ConfigParser]:
    """加载 config.ini 文件, 返回 configparser 对象

    自动检测文件编码, 兼容以下情况:
    - UTF-8 with BOM (记事本默认)
    - UTF-8 without BOM
    - GBK/GB2312 (Windows 中文系统默认 ANSI 编码)
    """
    ini_path = _get_config_ini_path()
    if ini_path is None:
        return None

    # 读取原始字节, 自动检测编码
    with open(ini_path, "rb") as f:
        raw_bytes = f.read()

    # 按优先级尝试解码: UTF-8 BOM → UTF-8 → GBK
    text = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        # 所有编码都失败, 用 errors="replace" 兜底
        text = raw_bytes.decode("utf-8", errors="replace")

    parser = configparser.ConfigParser()
    parser.read_string(text)
    return parser


def _build_connection_strings(parser: configparser.ConfigParser):
    """根据 config.ini 中的参数自动构建数据库连接串

    支持 sql_driver_version = 17 或 18, 自动适配驱动差异。
    """
    db = parser["database"]

    driver_ver = db.get("sql_driver_version", "17").strip()
    driver_name = f"ODBC Driver {driver_ver} for SQL Server"

    server = db.get("db_server", "").strip()
    db_name = db.get("db_name", "CN_AME").strip()
    db_user = db.get("db_user", "").strip()
    db_password = db.get("db_password", "").strip()
    hrdb_name = db.get("hrdb_name", "HRDB").strip()
    trust_raw = db.get("trust_server_certificate", "true").strip().lower()
    # ODBC 驱动要求 yes/no, 不接受 true/false
    trust_yn = "yes" if trust_raw in {"true", "yes", "1", "on"} else "no"

    # SQLAlchemy 连接串 (密码做 URL 编码)
    password_encoded = quote_plus(db_password)
    database_url = (
        f"mssql+pyodbc://{db_user}:{password_encoded}@{server}/{db_name}"
        f"?driver={quote_plus(driver_name)}&TrustServerCertificate={trust_yn}"
    )

    # pyodbc 原生连接串 (HRDB)
    hrdb_conn_str = (
        f"DRIVER={{{driver_name}}};"
        f"SERVER={server};"
        f"DATABASE={hrdb_name};"
        f"UID={db_user};"
        f"PWD={db_password};"
        f"TrustServerCertificate={trust_yn};"
    )

    return database_url, hrdb_conn_str


def _apply_config_ini_to_env():
    """将 config.ini 中的配置项写入环境变量, 供 pydantic-settings 读取

    仅在环境变量未设置时写入 (不覆盖 .env 或系统环境变量)。
    """
    parser = _load_config_ini()
    if parser is None:
        return

    # 构建数据库连接串
    database_url, hrdb_conn_str = _build_connection_strings(parser)

    env_mapping = {
        "DATABASE_URL": database_url,
        "HRDB_CONNECTION_STRING": hrdb_conn_str,
        "EMAIL_SMTP_HOST": parser.get("mail", "smtp_host", fallback=""),
        "EMAIL_SMTP_PORT": parser.get("mail", "smtp_port", fallback="25"),
        "EMAIL_ENABLE_SSL": parser.get("mail", "enable_ssl", fallback="false"),
        "EMAIL_SMTP_USERNAME": parser.get("mail", "smtp_username", fallback=""),
        "EMAIL_SMTP_PASSWORD": parser.get("mail", "smtp_password", fallback=""),
        "EMAIL_FROM_ADDRESS": parser.get("mail", "from_address", fallback=""),
        "EMAIL_FROM_DISPLAY_NAME": parser.get("mail", "from_display_name", fallback="MSIA 审核管理系统"),
        "EMAIL_TIMEOUT_MS": parser.get("mail", "timeout_ms", fallback="30000"),
        "NOTIFICATION_MODE": parser.get("notification", "mode", fallback="production"),
        "NOTIFICATION_TEST_RECIPIENTS": parser.get("notification", "test_email_recipients", fallback=""),
        "JWT_SECRET_KEY": parser.get("security", "jwt_secret_key", fallback="change-me-in-production"),
        "JWT_ALGORITHM": parser.get("security", "jwt_algorithm", fallback="HS256"),
        "JWT_EXPIRE_MINUTES": parser.get("security", "jwt_expire_minutes", fallback="43200"),
        # 本地登录双轨开关 (P4 单轨切换时置 false)
        "LOCAL_LOGIN_ENABLED": parser.get("security", "local_login_enabled", fallback="true"),
        # 用户同步开关 (T05-R1 #7): HRDB 全量同步 / SSO 中央表派生同步, 建议只开一个
        "HR_SYNC_ENABLED": parser.get("security", "hr_sync_enabled", fallback="true"),
        "SSO_USER_SYNC_ENABLED": parser.get("security", "sso_user_sync_enabled", fallback="false"),
        # OIDC 统一身份认证 (Keycloak), [oidc] 段
        "OIDC_ENABLED": parser.get("oidc", "enabled", fallback="false"),
        "OIDC_ISSUER": parser.get("oidc", "issuer", fallback="https://sso.ap.inalfa.local/realms/inalfa"),
        "OIDC_CLIENT_ID": parser.get("oidc", "client_id", fallback="msia-prod"),
        "OIDC_CLIENT_SECRET": parser.get("oidc", "client_secret", fallback=""),
        "OIDC_REDIRECT_URI": parser.get("oidc", "redirect_uri", fallback="http://172.26.2.203:8078/api/auth/oidc/callback"),
        "OIDC_FRONT_CALLBACK": parser.get("oidc", "front_callback", fallback="/oidc/callback"),
        "OIDC_REQUIRED_GROUP": parser.get("oidc", "required_group", fallback="app-msia"),
        "OIDC_AUTO_CREATE_USER": parser.get("oidc", "auto_create_user", fallback="true"),
        "OIDC_SCOPES": parser.get("oidc", "scopes", fallback="openid profile email"),
        "APP_HOST": parser.get("server", "host", fallback="0.0.0.0"),
        "APP_PORT": parser.get("server", "port", fallback="8000"),
        "CORS_ORIGINS": parser.get("server", "cors_origins", fallback="http://localhost:5173"),
        "SYSTEM_URL": parser.get("server", "system_url", fallback=""),
        "STORAGE_PATH": parser.get("server", "storage_path", fallback="./storage"),
        "MSIA_AUTO_CREATE_TABLES": parser.get("server", "auto_create_tables", fallback="0"),
    }

    for key, value in env_mapping.items():
        # 仅在环境变量未设置时写入 (不覆盖已有的 .env 或系统环境变量)
        if key not in os.environ:
            os.environ[key] = str(value)


# 在模块加载时执行: 将 config.ini 配置注入环境变量
_apply_config_ini_to_env()


class Settings(BaseSettings):
    """应用全局配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # 主数据库 (SQLAlchemy 连接串)
    DATABASE_URL: str

    # HR 数据库 (pyodbc 原生连接串, 用于用户同步)
    HRDB_CONNECTION_STRING: str

    # 邮件 SMTP
    EMAIL_SMTP_HOST: str = "172.19.253.10"
    EMAIL_SMTP_PORT: int = 25
    EMAIL_ENABLE_SSL: bool = True
    EMAIL_SMTP_USERNAME: str = ""
    EMAIL_SMTP_PASSWORD: str = ""
    EMAIL_FROM_ADDRESS: str = "msia-noreply@inalfa.local"
    EMAIL_FROM_DISPLAY_NAME: str = "MSIA 审核管理系统"
    EMAIL_TIMEOUT_MS: int = 30000

    # 通知模式 (test=测试模式, 所有邮件发送到测试邮箱; production=生产模式, 发送给真实责任人)
    NOTIFICATION_MODE: str = "production"
    # 测试模式下的邮件接收地址 (逗号分隔)
    NOTIFICATION_TEST_RECIPIENTS: str = ""

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 43200  # 30 天, 支持登录保持功能

    # 本地登录双轨开关 (P4 单轨切换时置 false: 本地账密登录/改密全部关闭)
    LOCAL_LOGIN_ENABLED: bool = True

    # 用户同步开关 (T05-R1 #7, [security] 段)
    # HR_SYNC_ENABLED: 每周 HRDB fine_user 全量同步 (会禁用 HR 缺失用户, ~4275 人)
    # SSO_USER_SYNC_ENABLED: 每日 06:30 从 CN_AME_SSO_User 派生同步
    #   (只更新命中的本地用户, 不新建、不禁用未命中 —— 中央表仅 13 人,
    #    双轨期误开全量同步会造成批量误禁用事故, 二者建议只开一个)
    HR_SYNC_ENABLED: bool = True
    SSO_USER_SYNC_ENABLED: bool = False

    # OIDC 统一身份认证 (Keycloak, 方案文档第 5 章)
    # Keycloak 未部署前 OIDC_ENABLED 保持 False, 系统行为与改造前完全一致
    OIDC_ENABLED: bool = False
    OIDC_ISSUER: str = "https://sso.ap.inalfa.local/realms/inalfa"
    OIDC_CLIENT_ID: str = "msia-prod"
    OIDC_CLIENT_SECRET: str = ""
    OIDC_REDIRECT_URI: str = "http://172.26.2.203:8078/api/auth/oidc/callback"
    # 前端 OIDC 回调页路由 (一次性码 otk 在此换本地 JWT)
    OIDC_FRONT_CALLBACK: str = "/oidc/callback"
    # 准入组: token groups claim 不含该值 → 403 未开通
    OIDC_REQUIRED_GROUP: str = "app-msia"
    # 本地用户表未命中时是否按最低权限 (reviewee) 自动建档
    OIDC_AUTO_CREATE_USER: bool = True
    OIDC_SCOPES: str = "openid profile email"

    # 文件存储
    STORAGE_PATH: str = "./storage"

    # CORS (逗号分隔字符串, 通过 cors_origins_list 属性获取列表)
    CORS_ORIGINS: str = "http://localhost:5173"

    # 系统访问 URL (用于邮件正文中的 "访问地址" 链接, 与 CORS 解耦)
    # 为空时回退到 CORS_ORIGINS 的第一个值
    SYSTEM_URL: str = ""

    # 应用监听
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    @property
    def cors_origins_list(self) -> List[str]:
        """将逗号分隔的 CORS_ORIGINS 字符串拆分为列表"""
        if not self.CORS_ORIGINS:
            return []
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def effective_system_url(self) -> str:
        """邮件正文中展示的系统访问地址

        优先级: SYSTEM_URL > CORS_ORIGINS 第一项 > 默认本地地址
        """
        if self.SYSTEM_URL and self.SYSTEM_URL.strip():
            return self.SYSTEM_URL.strip()
        if self.CORS_ORIGINS and self.CORS_ORIGINS.strip():
            return self.CORS_ORIGINS.split(",")[0].strip()
        return "http://localhost:5173"

    @property
    def is_notification_test_mode(self) -> bool:
        """是否为测试通知模式 (邮件发送到测试邮箱, 而非真实收件人)"""
        return (self.NOTIFICATION_MODE or "").strip().lower() == "test"

    @property
    def notification_test_recipients_list(self) -> List[str]:
        """测试模式下的邮件接收地址列表"""
        if not self.NOTIFICATION_TEST_RECIPIENTS:
            return []
        return [r.strip() for r in self.NOTIFICATION_TEST_RECIPIENTS.split(",") if r.strip()]

    @field_validator("EMAIL_ENABLE_SSL", mode="before")
    @classmethod
    def parse_bool(cls, v):
        """兼容字符串布尔值"""
        if isinstance(v, str):
            return v.strip().lower() in {"1", "true", "yes", "on"}
        return v


@lru_cache
def get_settings() -> Settings:
    """获取配置单例 (缓存)"""
    return Settings()


settings = get_settings()
