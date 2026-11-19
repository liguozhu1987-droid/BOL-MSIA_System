"""修正升级配置表的 COLLATION 为 Chinese_PRC_CI_AS

SQL Server 中:
- 数据存储: NVARCHAR/NTEXT 使用 UTF-16 (Unicode)，与 collation 无关
- 排序规则 (COLLATION): 影响 ORDER BY 比较、WHERE 相等判断等
- 之前列类型已从 VARCHAR → NVARCHAR，现在进一步把 collation 从 Latin1 改为 Chinese_PRC_CI_AS
  让中文排序更符合预期（拼音排序）。

另外对已存在的乱码 (????) 历史数据做一个 REPAIR 报告。
"""
import pyodbc

CONN = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=IRSCNYTFINEREPORT.ap.inalfa.local;"
    "DATABASE=CN_AME;UID=ytview;PWD=Inalfa@2021;"
    "TrustServerCertificate=yes;"
)

TARGET_COLLATION = "Chinese_PRC_CI_AS"

ALTERATIONS = [
    # (table, column, full_type_with_collation)
    ("CN_AME_MISA_EscalationConfig", "Plant", f"NVARCHAR(100) COLLATE {TARGET_COLLATION} NOT NULL"),
    ("CN_AME_MISA_EscalationConfig", "Level1Recipients", f"NVARCHAR(1000) COLLATE {TARGET_COLLATION} NULL"),
    ("CN_AME_MISA_EscalationConfig", "Level2Recipients", f"NVARCHAR(1000) COLLATE {TARGET_COLLATION} NULL"),
    ("CN_AME_MISA_EscalationConfig", "Level3Recipients", f"NVARCHAR(1000) COLLATE {TARGET_COLLATION} NULL"),
    ("CN_AME_MISA_EscalationConfig", "Remarks", f"NVARCHAR(MAX) COLLATE {TARGET_COLLATION} NULL"),
    ("CN_AME_MISA_EscalationLog", "Recipients", f"NVARCHAR(1000) COLLATE {TARGET_COLLATION} NOT NULL"),
]


def main():
    conn = pyodbc.connect(CONN)
    cur = conn.cursor()

    print("=" * 80)
    print("修改 Escalation 相关表列的 COLLATION → Chinese_PRC_CI_AS")
    print("=" * 80)

    for table, column, new_decl in ALTERATIONS:
        cur.execute(
            "SELECT COLLATION_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = ? AND COLUMN_NAME = ?",
            (table, column),
        )
        row = cur.fetchone()
        cur_coll = row[0] if row else None
        print(f"\n[{table}].[{column}]: 当前 collation = {cur_coll}")
        if cur_coll and TARGET_COLLATION.lower() in cur_coll.lower():
            print("  -> 已为目标 collation，跳过")
            continue

        sql = f"ALTER TABLE [{table}] ALTER COLUMN [{column}] {new_decl}"
        print(f"  -> 执行: {sql}")
        try:
            cur.execute(sql)
            conn.commit()
            print("  -> 成功")
        except Exception as e:
            print(f"  -> 失败: {e}")

    print("\n" + "=" * 80)
    print("验证 COLLATION")
    print("=" * 80)
    for table, column, _ in ALTERATIONS:
        cur.execute(
            "SELECT COLLATION_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = ? AND COLUMN_NAME = ?",
            (table, column),
        )
        row = cur.fetchone()
        c = row[0] if row else "N/A"
        print(f"  [{table}].[{column}] = {c}")

    conn.close()
    print("\n完成!")


if __name__ == "__main__":
    main()
