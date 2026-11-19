"""统一时间工具: 全系统使用北京时间 (东八区)

背景: SQL Server sysdatetime() 默认值写入数据库服务器本地时间 (北京时间),
而部分 Python 代码曾用 datetime.now(timezone.utc) 写入 UTC 时间, 导致同表
两种口径混杂 (相差 8 小时)。

规则: 所有落库 / 与库内时间比较的 "当前时间" 一律使用 now_cst()。
禁止 datetime.now(timezone.utc) 直接落库 (JWT exp/iat 除外, 其标准要求 UTC)。
"""
from datetime import datetime, timedelta, timezone

# 北京时间 (东八区, 不依赖服务器/数据库时区设置)
CST = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_cst() -> datetime:
    """当前北京时间 (naive datetime, 无时区后缀)

    与 SQL Server sysdatetime() (北京时间) 口径一致, 直接落库安全。
    """
    return datetime.now(CST).replace(tzinfo=None)
