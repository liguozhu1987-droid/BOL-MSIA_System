"""迁移: 为 Issue 表新增 OwnerCompany 列 (责任人所属公司)

运行: python -m app.scripts.add_owner_company
"""
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import engine  # noqa: E402


def migrate() -> None:
    print("[migrate] 开始: 为 CN_AME_MISA_Issue 添加 OwnerCompany 列")
    with engine.begin() as conn:
        # 检查列是否已存在
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = 'CN_AME_MISA_Issue' AND COLUMN_NAME = 'OwnerCompany'"
            )
        )
        if result.scalar():
            print("[migrate] 跳过: OwnerCompany 列已存在")
            return

        sql = "ALTER TABLE [CN_AME_MISA_Issue] ADD [OwnerCompany] NVARCHAR(200) NULL"
        print(f"[migrate] 执行: {sql}")
        conn.execute(text(sql))
        print("[migrate] 成功: OwnerCompany 列已添加")

        # 创建索引便于按公司筛选
        idx_sql = "CREATE INDEX IX_CN_AME_MISA_Issue_OwnerCompany ON [CN_AME_MISA_Issue] ([OwnerCompany])"
        print(f"[migrate] 执行: {idx_sql}")
        try:
            conn.execute(text(idx_sql))
            print("[migrate] 成功: 索引已创建")
        except Exception as e:
            print(f"[migrate] 索引创建失败 (可忽略): {e}")

    print("[migrate] 迁移完成")


if __name__ == "__main__":
    migrate()
