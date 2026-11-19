"""迁移: 将 EscalationConfig 表的文本字段从 VARCHAR 改为 NVARCHAR

修复中文乱码问题 (?????) - Remarks, Plant, Level*Recipients 字段
"""
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import engine  # noqa: E402


# 需要迁移的表和列: (表名, 列名, 新类型)
MIGRATIONS = [
    ("CN_AME_MISA_EscalationConfig", "Plant", "NVARCHAR(100)"),
    ("CN_AME_MISA_EscalationConfig", "Level1Recipients", "NVARCHAR(1000)"),
    ("CN_AME_MISA_EscalationConfig", "Level2Recipients", "NVARCHAR(1000)"),
    ("CN_AME_MISA_EscalationConfig", "Level3Recipients", "NVARCHAR(1000)"),
    ("CN_AME_MISA_EscalationConfig", "Remarks", "NVARCHAR(MAX)"),
    ("CN_AME_MISA_EscalationLog", "Recipients", "NVARCHAR(1000)"),
]


def migrate() -> None:
    print("[migrate-escalation] 开始: 将 Escalation 表文本字段从 VARCHAR 改为 NVARCHAR (修复中文乱码)")
    with engine.begin() as conn:
        for table_name, column_name, new_type in MIGRATIONS:
            result = conn.execute(
                text(
                    "SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = :t AND COLUMN_NAME = :c"
                ),
                {"t": table_name, "c": column_name},
            )
            current_type = result.scalar()
            print(f"[migrate] {table_name}.{column_name}: 当前类型={current_type}")

            if current_type and current_type.lower() in ("nvarchar", "ntext"):
                print(f"[migrate]   跳过: 已经是 Unicode 类型")
                continue

            sql = f"ALTER TABLE [{table_name}] ALTER COLUMN [{column_name}] {new_type}"
            print(f"[migrate]   执行: {sql}")
            try:
                conn.execute(text(sql))
                print(f"[migrate]   成功")
            except Exception as e:
                print(f"[migrate]   失败: {e}")

    print("[migrate-escalation] 迁移完成")


if __name__ == "__main__":
    migrate()
