"""为 CN_AME_MISA_EscalationLog 表添加 OriginalRecipients 列

用途: 升级日志同时记录实际发送邮箱 (Recipients, 测试模式下为重定向后的
测试邮箱) 与原始策略收件人 (OriginalRecipients), 并通过 EmailLogId 关联邮件日志。
幂等: 列已存在时跳过。

用法 (在 backend 目录下):
    python migrate_escalation_log_columns.py
"""
from sqlalchemy import text

from app.db.session import SessionLocal


def main():
    with SessionLocal() as db:
        exists = db.execute(text(
            "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = 'CN_AME_MISA_EscalationLog' "
            "AND COLUMN_NAME = 'OriginalRecipients'"
        )).first()
        if exists:
            print("列 OriginalRecipients 已存在, 跳过创建")
            return
        db.execute(text(
            "ALTER TABLE CN_AME_MISA_EscalationLog "
            "ADD OriginalRecipients NVARCHAR(1000) NULL"
        ))
        db.commit()
        print("已添加列 OriginalRecipients")


if __name__ == "__main__":
    main()
