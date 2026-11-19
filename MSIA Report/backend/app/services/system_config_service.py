"""系统配置服务

集中定义所有可在线配置的运行时参数元数据, 提供:
- 配置项元数据 (key, module, default, value_type, display_name, description)
- 类型安全的读取函数 (get_string / get_int / get_float / get_bool)
- 默认配置初始化 (首次启动时自动插入数据库)

配置优先级: 数据库 SystemSetting > config.ini / .env 默认值
修改后立即生效, 无需重启服务 (业务代码每次调用时实时读取)。

模块划分:
- notification: 通知模式 (测试/生产, 测试邮箱)
- smtp: SMTP 邮件服务器配置
- issue_closure: 问题逾期判定 (Deadline 硬边界)
- maintenance_scan: 未维护问题扫描 (Deadline 前 N 天仍未维护时提醒)
- escalation: 问题升级扫描参数
- system: 系统全局配置 (访问地址等)
"""
from typing import Any, Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.system_setting import SystemSetting


# ============================================================
# 配置项元数据定义
# 每个配置项: key -> (module, default_value, value_type, display_name, description, sort_order)
# default_value 为 None 表示从 config.ini 读取 (不硬编码默认值)
# ============================================================
SETTING_DEFINITIONS: dict[str, dict[str, Any]] = {
    # ============ 通知模式模块 ============
    "notification_mode": {
        "module": "notification",
        "default": None,  # 从 settings.NOTIFICATION_MODE 读取
        "value_type": "string",
        "display_name": "通知模式",
        "description": "test=测试模式 (邮件发送到测试邮箱); production=生产模式 (发送给真实责任人)",
        "sort_order": 1,
    },
    "notification_test_recipients": {
        "module": "notification",
        "default": None,  # 从 settings.NOTIFICATION_TEST_RECIPIENTS 读取
        "value_type": "string",
        "display_name": "测试模式邮件接收地址",
        "description": "测试模式下, 所有通知邮件将发送到此地址 (多个用英文逗号分隔)",
        "sort_order": 2,
    },
    # ============ SMTP 邮件服务器模块 ============
    "smtp_host": {
        "module": "smtp",
        "default": None,  # 从 settings.EMAIL_SMTP_HOST 读取
        "value_type": "string",
        "display_name": "SMTP 服务器地址",
        "description": "邮件发送服务器地址 (如 172.19.253.10)",
        "sort_order": 1,
    },
    "smtp_port": {
        "module": "smtp",
        "default": None,  # 从 settings.EMAIL_SMTP_PORT 读取
        "value_type": "int",
        "display_name": "SMTP 端口",
        "description": "邮件发送服务器端口 (通常 25 或 465)",
        "sort_order": 2,
    },
    "smtp_enable_ssl": {
        "module": "smtp",
        "default": None,  # 从 settings.EMAIL_ENABLE_SSL 读取
        "value_type": "bool",
        "display_name": "启用 SSL",
        "description": "是否使用 SSL 加密连接 (true=SMTP_SSL, false=明文 SMTP)",
        "sort_order": 3,
    },
    "smtp_username": {
        "module": "smtp",
        "default": None,  # 从 settings.EMAIL_SMTP_USERNAME 读取
        "value_type": "string",
        "display_name": "SMTP 用户名",
        "description": "SMTP 认证用户名 (内网无认证时留空)",
        "sort_order": 4,
    },
    "smtp_password": {
        "module": "smtp",
        "default": None,  # 从 settings.EMAIL_SMTP_PASSWORD 读取
        "value_type": "string",
        "display_name": "SMTP 密码",
        "description": "SMTP 认证密码 (内网无认证时留空)",
        "sort_order": 5,
    },
    "email_from_address": {
        "module": "smtp",
        "default": None,  # 从 settings.EMAIL_FROM_ADDRESS 读取
        "value_type": "string",
        "display_name": "发件人邮箱",
        "description": "邮件发件人地址 (如 msia-noreply@inalfa.local)",
        "sort_order": 6,
    },
    "email_from_display_name": {
        "module": "smtp",
        "default": None,  # 从 settings.EMAIL_FROM_DISPLAY_NAME 读取
        "value_type": "string",
        "display_name": "发件人显示名",
        "description": "邮件发件人显示名称 (如 MSIA 审核管理系统)",
        "sort_order": 7,
    },
    "email_timeout_ms": {
        "module": "smtp",
        "default": None,  # 从 settings.EMAIL_TIMEOUT_MS 读取
        "value_type": "int",
        "display_name": "邮件发送超时 (毫秒)",
        "description": "SMTP 连接和发送的超时时间, 超时后标记为发送失败",
        "sort_order": 8,
    },
    # ============ 问题逾期判定模块 (Deadline 硬边界规则) ============
    "issue_overdue_exempt_statuses": {
        "module": "issue_closure",
        "default": "closed,pending_verification",
        "value_type": "string",
        "display_name": "逾期豁免状态",
        "description": "这些状态的问题即使超过 Deadline 也不视为逾期 (逗号分隔): closed=已关闭, pending_verification=待审批关闭",
        "sort_order": 1,
    },
    "issue_overdue_effective_from": {
        "module": "issue_closure",
        "default": None,  # 首次读取时自动初始化为次日零点
        "value_type": "string",
        "display_name": "Deadline 逾期规则生效时间",
        "description": "Deadline 逾期判定起始时间 (北京时间, 格式 YYYY-MM-DD HH:MM:SS); 该时间之前不产生逾期判定, 用于存量问题切换保护; 首次使用自动初始化为次日零点",
        "sort_order": 2,
    },
    # ============ 未维护问题扫描模块 ============
    "maintenance_remind_after_workdays": {
        "module": "maintenance_scan",
        "default": 3,
        "value_type": "int",
        "display_name": "提醒提前量 (天)",
        "description": "Deadline 前 N 天仍未维护根本原因/纠正措施时, 开始发送提醒邮件; 与逾期判定同一时间基准",
        "sort_order": 1,
    },
    "maintenance_severity_frequency_h": {
        "module": "maintenance_scan",
        "default": 1,
        "value_type": "int",
        "display_name": "H 级提醒频率 (天)",
        "description": "高严重等级问题的提醒邮件发送间隔 (天)",
        "sort_order": 2,
    },
    "maintenance_severity_frequency_m": {
        "module": "maintenance_scan",
        "default": 1,
        "value_type": "int",
        "display_name": "M 级提醒频率 (天)",
        "description": "中严重等级问题的提醒邮件发送间隔 (天)",
        "sort_order": 3,
    },
    "maintenance_severity_frequency_l": {
        "module": "maintenance_scan",
        "default": 3,
        "value_type": "int",
        "display_name": "L 级提醒频率 (天)",
        "description": "低严重等级问题的提醒邮件发送间隔 (天)",
        "sort_order": 4,
    },
    # ============ 月度待审核项目提醒模块 ============
    "monthly_reminder_enabled": {
        "module": "monthly_reminder",
        "default": True,
        "value_type": "bool",
        "display_name": "启用月度提醒",
        "description": "是否启用每月自动发送待审核项目提醒邮件 (汇总一封, 发给审核员与管理员, 抄送项目负责人与所在工厂 ME 经理)",
        "sort_order": 1,
    },
    "monthly_reminder_day": {
        "module": "monthly_reminder",
        "default": 1,
        "value_type": "int",
        "display_name": "发送日期 (每月几号)",
        "description": "每月第几号发送月度提醒邮件 (1-28, 超过当月天数时不发送该月)",
        "sort_order": 2,
    },
    "monthly_reminder_hour": {
        "module": "monthly_reminder",
        "default": 8,
        "value_type": "int",
        "display_name": "发送小时 (0-23)",
        "description": "月度提醒邮件的发送时刻-小时 (北京时间, 24 小时制)",
        "sort_order": 3,
    },
    "monthly_reminder_minute": {
        "module": "monthly_reminder",
        "default": 10,
        "value_type": "int",
        "display_name": "发送分钟 (0-59)",
        "description": "月度提醒邮件的发送时刻-分钟 (北京时间); 实际触发时刻为该时刻后的最近一次调度检查 (每 5 分钟)",
        "sort_order": 4,
    },
    "monthly_reminder_extra_cc": {
        "module": "monthly_reminder",
        "default": "",
        "value_type": "string",
        "display_name": "额外抄送人员",
        "description": "月度提醒邮件的额外抄送邮箱 (多个用英文逗号分隔, 可选); 默认抄送: 本月项目负责人 + 项目所在工厂 ME 经理 (取问题升级 L2 配置)",
        "sort_order": 5,
    },
    # ============ 系统全局配置模块 ============
    "system_url": {
        "module": "system",
        "default": None,  # 从 settings.SYSTEM_URL 或 CORS_ORIGINS 读取
        "value_type": "string",
        "display_name": "系统访问地址",
        "description": "邮件正文中的 '访问地址' 链接, 应为用户实际可访问的登录页地址 (如 http://172.26.2.203:8078/login)",
        "sort_order": 1,
    },
}


# config.ini 默认值映射 (key -> settings 属性名)
_CONFIG_INI_MAPPING = {
    "notification_mode": "NOTIFICATION_MODE",
    "notification_test_recipients": "NOTIFICATION_TEST_RECIPIENTS",
    "smtp_host": "EMAIL_SMTP_HOST",
    "smtp_port": "EMAIL_SMTP_PORT",
    "smtp_enable_ssl": "EMAIL_ENABLE_SSL",
    "smtp_username": "EMAIL_SMTP_USERNAME",
    "smtp_password": "EMAIL_SMTP_PASSWORD",
    "email_from_address": "EMAIL_FROM_ADDRESS",
    "email_from_display_name": "EMAIL_FROM_DISPLAY_NAME",
    "email_timeout_ms": "EMAIL_TIMEOUT_MS",
    "system_url": "SYSTEM_URL",
}


def _get_config_ini_default(key: str) -> Any:
    """从 config.ini / .env 读取默认值"""
    attr = _CONFIG_INI_MAPPING.get(key)
    if attr is None:
        return None
    return getattr(settings, attr, None)


def _convert_value(raw_value: str, value_type: str) -> Any:
    """将字符串值转换为目标类型"""
    if raw_value is None:
        return None
    raw_value = raw_value.strip()
    if not raw_value:
        return None
    try:
        if value_type == "int":
            return int(raw_value)
        elif value_type == "float":
            return float(raw_value)
        elif value_type == "bool":
            return raw_value.lower() in ("true", "1", "yes", "on")
        else:
            return raw_value
    except (ValueError, TypeError):
        logger.warning("[系统配置] 值类型转换失败: value={} type={}", raw_value, value_type)
        return None


# ============================================================
# 类型安全的读取函数
# ============================================================

def _get_raw_setting(db: Session, key: str) -> Optional[SystemSetting]:
    """查询数据库中的设置记录 (不转换类型)"""
    return db.query(SystemSetting).filter(SystemSetting.SettingKey == key).first()


def get_string(db: Session, key: str, default: Optional[str] = None) -> Optional[str]:
    """读取字符串配置

    优先级: 数据库 > default 参数 > config.ini > 元数据默认值
    """
    row = _get_raw_setting(db, key)
    if row and row.SettingValue and row.SettingValue.strip():
        return row.SettingValue.strip()
    if default is not None:
        return default
    meta = SETTING_DEFINITIONS.get(key, {})
    if meta.get("default") is not None:
        return str(meta["default"])
    ini_default = _get_config_ini_default(key)
    if ini_default is not None:
        return str(ini_default)
    return None


def set_string(db: Session, key: str, value: str) -> None:
    """写入字符串配置 (存在则更新, 不存在则按元数据新建)

    仅修改对象, 不提交事务; 调用方负责 commit
    """
    row = _get_raw_setting(db, key)
    if row:
        row.SettingValue = value
        return
    meta = SETTING_DEFINITIONS.get(key, {})
    db.add(SystemSetting(
        SettingKey=key,
        SettingValue=value,
        DisplayName=meta.get("display_name"),
        Description=meta.get("description"),
        Module=meta.get("module"),
        ValueType=meta.get("value_type", "string"),
        SortOrder=meta.get("sort_order", 0),
    ))


def get_int(db: Session, key: str, default: Optional[int] = None) -> Optional[int]:
    """读取整数配置"""
    row = _get_raw_setting(db, key)
    if row and row.SettingValue and row.SettingValue.strip():
        val = _convert_value(row.SettingValue, "int")
        if val is not None:
            return val
    if default is not None:
        return default
    meta = SETTING_DEFINITIONS.get(key, {})
    if meta.get("default") is not None:
        return int(meta["default"])
    ini_default = _get_config_ini_default(key)
    if ini_default is not None:
        try:
            return int(ini_default)
        except (ValueError, TypeError):
            return None
    return None


def get_float(db: Session, key: str, default: Optional[float] = None) -> Optional[float]:
    """读取浮点数配置"""
    row = _get_raw_setting(db, key)
    if row and row.SettingValue and row.SettingValue.strip():
        val = _convert_value(row.SettingValue, "float")
        if val is not None:
            return val
    if default is not None:
        return default
    meta = SETTING_DEFINITIONS.get(key, {})
    if meta.get("default") is not None:
        return float(meta["default"])
    return None


def get_bool(db: Session, key: str, default: Optional[bool] = None) -> Optional[bool]:
    """读取布尔配置"""
    row = _get_raw_setting(db, key)
    if row and row.SettingValue and row.SettingValue.strip():
        val = _convert_value(row.SettingValue, "bool")
        if val is not None:
            return val
    if default is not None:
        return default
    meta = SETTING_DEFINITIONS.get(key, {})
    if meta.get("default") is not None:
        return bool(meta["default"])
    ini_default = _get_config_ini_default(key)
    if ini_default is not None:
        return bool(ini_default)
    return None


def get_effective_value(db: Session, key: str) -> Any:
    """获取配置的有效值 (带类型转换), 用于需要类型安全读取的场景

    自动根据 SETTING_DEFINITIONS 中的 value_type 进行转换。
    """
    meta = SETTING_DEFINITIONS.get(key, {})
    value_type = meta.get("value_type", "string")

    row = _get_raw_setting(db, key)
    if row and row.SettingValue and row.SettingValue.strip():
        val = _convert_value(row.SettingValue, value_type)
        if val is not None:
            return val

    # 回退到默认值
    if meta.get("default") is not None:
        return meta["default"]
    ini_default = _get_config_ini_default(key)
    if ini_default is not None:
        return _convert_value(str(ini_default), value_type) if ini_default is not None else None
    return None


def init_default_settings(db: Session) -> int:
    """初始化默认配置 (仅在数据库无记录时插入)

    在应用启动时调用, 确保所有配置项都有数据库记录,
    前端可直接展示和编辑。

    Returns:
        新插入的配置项数量
    """
    inserted = 0
    for key, meta in SETTING_DEFINITIONS.items():
        existing = _get_raw_setting(db, key)
        if existing:
            # 已存在, 但补充 Module/ValueType/SortOrder (兼容旧数据)
            updated = False
            if not existing.Module and meta.get("module"):
                existing.Module = meta["module"]
                updated = True
            if not existing.ValueType:
                existing.ValueType = meta.get("value_type", "string")
                updated = True
            if existing.SortOrder is None:
                existing.SortOrder = meta.get("sort_order", 0)
                updated = True
            if not existing.DisplayName and meta.get("display_name"):
                existing.DisplayName = meta["display_name"]
                updated = True
            if not existing.Description and meta.get("description"):
                existing.Description = meta["description"]
                updated = True
            if updated:
                db.add(existing)
            continue

        # 计算初始值: 元数据 default > config.ini
        default_val = meta.get("default")
        if default_val is None:
            ini_default = _get_config_ini_default(key)
            default_val = str(ini_default) if ini_default is not None else ""

        row = SystemSetting(
            SettingKey=key,
            SettingValue=str(default_val) if default_val is not None else "",
            DisplayName=meta.get("display_name"),
            Description=meta.get("description"),
            Module=meta.get("module"),
            ValueType=meta.get("value_type", "string"),
            SortOrder=meta.get("sort_order", 0),
        )
        db.add(row)
        inserted += 1

    if inserted > 0:
        db.commit()
        logger.info("[系统配置] 初始化默认配置: 新增 {} 项", inserted)
    return inserted
