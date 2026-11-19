"""迁移: 将 EscalationConfig 表的文本字段从 VARCHAR 改为 NVARCHAR

修复中文乱码问题 (?????) - Remarks, Plant, Level*Recipients 字段
直接使用 pyodbc 连接数据库执行 ALTER (不依赖 app 启动环境)
"""
import pyodbc
from pathlib import Path
import sys

# 读取 .env 获取数据库连接信息 (或使用与 fix_garbled.py 一致的连接串)
ROOT = Path(__file__).resolve().parent.parent

# 使用与 fix_garbled.py 相同的连接信息
CONN = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=IRSCNYTFINEREPORT.ap.inalfa.local;"
    "DATABASE=CN_AME;UID=ytview;PWD=Inalfa@2021;"
    "TrustServerCertificate=yes;"
)

MIGRATIONS = [
    ("CN_AME_MISA_EscalationConfig", "Plant", "NVARCHAR(100)"),
    ("CN_AME_MISA_EscalationConfig", "Level1Recipients", "NVARCHAR(1000)"),
    ("CN_AME_MISA_EscalationConfig", "Level2Recipients", "NVARCHAR(1000)"),
    ("CN_AME_MISA_EscalationConfig", "Level3Recipients", "NVARCHAR(1000)"),
    ("CN_AME_MISA_EscalationConfig", "Remarks", "NVARCHAR(MAX)"),
    ("CN_AME_MISA_EscalationLog", "Recipients", "NVARCHAR(1000)"),
]


def main():
    conn = pyodbc.connect(CONN)
    cur = conn.cursor()

    print("=" * 80)
    print("迁移 Escalation 表文本字段到 NVARCHAR (修复中文乱码)")
    print("=" * 80)

    for table_name, column_name, new_type in MIGRATIONS:
        # 查询当前列类型
        cur.execute(
            "SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = ? AND COLUMN_NAME = ?",
            (table_name, column_name),
        )
        row = cur.fetchone()
        current_type = row[0] if row else None
        print(f"\n[{table_name}].[{column_name}]: 当前类型 = {current_type}")

        if current_type and current_type.lower() in ("nvarchar", "ntext"):
            print("  -> 跳过: 已经是 Unicode 类型")
            continue

        sql = f"ALTER TABLE [{table_name}] ALTER COLUMN [{column_name}] {new_type}"
        print(f"  -> 执行: {sql}")
        try:
            cur.execute(sql)
            conn.commit()
            print("  -> 成功")
        except Exception as e:
            print(f"  -> 失败: {e}")

    # 验证
    print("\n" + "=" * 80)
    print("验证结果")
    print("=" * 80)
    for table_name, column_name, _ in MIGRATIONS:
        cur.execute(
            "SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = ? AND COLUMN_NAME = ?",
            (table_name, column_name),
        )
        row = cur.fetchone()
        t = row[0] if row else "N/A"
        print(f"  [{table_name}].[{column_name}] = {t}")

    conn.close()
    print("\n迁移完成!")


if __name__ == "__main__":
    main()
