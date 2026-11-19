"""诊断数据库中文乱码问题

检查内容:
1. CN_AME_MISA_IssueComment 表 Content 字段的排序规则
2. CN_AME_MISA_Issue 表 Title/Description 等字段排序规则
3. CN_AME_MISA_User 表 DisplayName/RealName 等字段排序规则
4. 查询当前所有问题评论中含 ? 的乱码记录
5. 测试 NVARCHAR 字面量写入中文
"""
import pyodbc

CONN = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=IRSCNYTFINEREPORT.ap.inalfa.local;"
    "DATABASE=CN_AME;UID=ytview;PWD=Inalfa@2021;"
    "TrustServerCertificate=yes;"
)


def main():
    conn = pyodbc.connect(CONN)
    cur = conn.cursor()

    print("=" * 70)
    print("1. 检查 CN_AME_MISA_IssueComment 表字段排序规则")
    print("=" * 70)
    cur.execute("""
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_SET_NAME, COLLATION_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'CN_AME_MISA_IssueComment'
        ORDER BY ORDINAL_POSITION
    """)
    for row in cur.fetchall():
        print(f"  {row.COLUMN_NAME:20s} | {row.DATA_TYPE:15s} | {row.CHARACTER_SET_NAME or '-':10s} | {row.COLLATION_NAME or '-'}")

    print()
    print("=" * 70)
    print("2. 检查 CN_AME_MISA_Issue 表字段排序规则")
    print("=" * 70)
    cur.execute("""
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_SET_NAME, COLLATION_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'CN_AME_MISA_Issue'
        AND DATA_TYPE IN ('nvarchar', 'varchar', 'ntext', 'text')
        ORDER BY ORDINAL_POSITION
    """)
    for row in cur.fetchall():
        print(f"  {row.COLUMN_NAME:20s} | {row.DATA_TYPE:15s} | {row.CHARACTER_SET_NAME or '-':10s} | {row.COLLATION_NAME or '-'}")

    print()
    print("=" * 70)
    print("3. 检查 CN_AME_MISA_User 表字段排序规则")
    print("=" * 70)
    cur.execute("""
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_SET_NAME, COLLATION_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'CN_AME_MISA_User'
        AND DATA_TYPE IN ('nvarchar', 'varchar', 'ntext', 'text')
        ORDER BY ORDINAL_POSITION
    """)
    for row in cur.fetchall():
        print(f"  {row.COLUMN_NAME:20s} | {row.DATA_TYPE:15s} | {row.CHARACTER_SET_NAME or '-':10s} | {row.COLLATION_NAME or '-'}")

    print()
    print("=" * 70)
    print("4. 检查数据库与服务器默认排序规则")
    print("=" * 70)
    cur.execute("SELECT SERVERPROPERTY('Collation') AS ServerCollation, DATABASEPROPERTYEX('CN_AME', 'Collation') AS DbCollation")
    row = cur.fetchone()
    print(f"  服务器排序规则: {row.ServerCollation}")
    print(f"  数据库排序规则: {row.DbCollation}")

    print()
    print("=" * 70)
    print("5. 查询 IssueComment 中含乱码 (?) 的记录")
    print("=" * 70)
    cur.execute("""
        SELECT Id, IssueId, AuthorName, Action, Content, CreatedAt
        FROM CN_AME_MISA_IssueComment
        WHERE Content LIKE '%?%' OR AuthorName LIKE '%?%'
        ORDER BY Id DESC
    """)
    rows = cur.fetchall()
    print(f"  共 {len(rows)} 条含 ? 的评论")
    for r in rows[:10]:
        print(f"  Id={r.Id}, IssueId={r.IssueId}, AuthorName={r.AuthorName!r}, Action={r.Action}, Content={r.Content!r}")

    print()
    print("=" * 70)
    print("6. 查询 Issue 表中含乱码 (?) 的记录")
    print("=" * 70)
    cur.execute("""
        SELECT Id, IssueNo, Title, Description, OwnerName, OwnerCompany
        FROM CN_AME_MISA_Issue
        WHERE Title LIKE '%?%' OR Description LIKE '%?%' OR OwnerName LIKE '%?%'
           OR OwnerCompany LIKE '%?%'
        ORDER BY Id DESC
    """)
    rows = cur.fetchall()
    print(f"  共 {len(rows)} 条含 ? 的问题")
    for r in rows[:10]:
        print(f"  Id={r.Id}, IssueNo={r.IssueNo}, Title={r.Title!r}, OwnerName={r.OwnerName!r}, OwnerCompany={r.OwnerCompany!r}")

    print()
    print("=" * 70)
    print("7. 查询 User 表中含乱码 (?) 的记录")
    print("=" * 70)
    cur.execute("""
        SELECT Id, Username, DisplayName, RealName, Department
        FROM CN_AME_MISA_User
        WHERE DisplayName LIKE '%?%' OR RealName LIKE '%?%' OR Department LIKE '%?%'
        ORDER BY Id DESC
    """)
    rows = cur.fetchall()
    print(f"  共 {len(rows)} 条含 ? 的用户")
    for r in rows[:10]:
        print(f"  Id={r.Id}, Username={r.Username!r}, DisplayName={r.DisplayName!r}, RealName={r.RealName!r}, Department={r.Department!r}")

    print()
    print("=" * 70)
    print("8. 测试 NVARCHAR 字面量写入中文 (回滚)")
    print("=" * 70)
    test_content = "测试中文: 评审员 缺少GRR数据验证"
    cur.execute(
        "INSERT INTO CN_AME_MISA_IssueComment "
        "(IssueId, AuthorUserId, AuthorName, Action, Content, FromStatus, ToStatus) "
        "VALUES (?, ?, N'admin', N'comment', ?, NULL, N'open')",
        (6, 1, test_content),
    )
    conn.commit()
    cur.execute("SELECT Id, Content FROM CN_AME_MISA_IssueComment WHERE IssueId = 6 ORDER BY Id DESC")
    rows = cur.fetchall()
    print("插入后查询:")
    for r in rows[:3]:
        print(f"  Id={r.Id}, Content={r.Content!r}")
    # 清理测试数据
    cur.execute("DELETE FROM CN_AME_MISA_IssueComment WHERE Content = ?", (test_content,))
    conn.commit()
    print("已清理测试数据")

    conn.close()


if __name__ == "__main__":
    main()
