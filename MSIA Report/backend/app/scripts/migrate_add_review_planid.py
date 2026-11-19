"""迁移脚本: 为 CN_AME_MISA_ReviewRecord 表添加 PlanId 列

运行方式:
    cd backend
    C:\\python\\python.exe -m app.scripts.migrate_add_review_planid
"""
from sqlalchemy import text

from app.db.session import engine


def migrate() -> None:
    print("[migrate] 开始: 为 CN_AME_MISA_ReviewRecord 添加 PlanId 列")
    with engine.begin() as conn:
        # 检查列是否已存在
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = 'CN_AME_MISA_ReviewRecord' AND COLUMN_NAME = 'PlanId'"
            )
        )
        exists = result.scalar()

        if exists:
            print("[migrate] 跳过: PlanId 列已存在")
        else:
            print("[migrate] 添加 PlanId 列 (NVARCHAR(100), NULL)")
            conn.execute(
                text(
                    "ALTER TABLE [CN_AME_MISA_ReviewRecord] ADD [PlanId] NVARCHAR(100) NULL"
                )
            )
            print("[migrate] 创建索引 IX_ReviewRecord_PlanId")
            conn.execute(
                text(
                    "CREATE INDEX [IX_ReviewRecord_PlanId] "
                    "ON [CN_AME_MISA_ReviewRecord] ([PlanId])"
                )
            )
            print("[migrate] 成功: PlanId 列已添加")

    print("[migrate] 迁移完成")


if __name__ == "__main__":
    migrate()
