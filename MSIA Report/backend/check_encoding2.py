"""关联查询 IssueComment 与 Issue 表, 确认乱码来源"""
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

    print("=" * 90)
    print("查询所有 IssueComment 记录与对应 Issue.Title 对比")
    print("=" * 90)
    cur.execute("""
        SELECT C.Id AS CommentId, C.IssueId, C.AuthorName, C.Content,
               I.IssueNo, I.Title, I.OwnerName, I.Description
        FROM CN_AME_MISA_IssueComment C
        LEFT JOIN CN_AME_MISA_Issue I ON C.IssueId = I.Id
        ORDER BY C.Id
    """)
    rows = cur.fetchall()
    print(f"共 {len(rows)} 条评论")
    for r in rows:
        print(f"\n  CommentId={r.CommentId}, IssueId={r.IssueId}")
        print(f"    AuthorName  = {r.AuthorName!r}")
        print(f"    Comment     = {r.Content!r}")
        print(f"    IssueNo     = {r.IssueNo!r}")
        print(f"    Issue.Title = {r.Title!r}")
        print(f"    Issue.Owner = {r.OwnerName!r}")
        print(f"    Issue.Desc  = {r.Description!r}")

    print()
    print("=" * 90)
    print("测试 SQLAlchemy 模拟插入 - 确认是否为驱动/连接问题")
    print("=" * 90)
    # 模拟 SQLAlchemy 通过 pyodbc 参数化插入 (无 N 前缀)
    test_content = "SQLAlchemy测试: 评审员 缺少GRR数据验证"
    test_author = "评审员"
    # 不带 N 前缀的参数化查询 (模拟 SQLAlchemy 默认行为)
    cur.execute(
        "INSERT INTO CN_AME_MISA_IssueComment "
        "(IssueId, AuthorUserId, AuthorName, Action, Content, FromStatus, ToStatus) "
        "VALUES (?, ?, ?, ?, ?, NULL, ?)",
        (6, 1, test_author, "create", test_content, "open"),
    )
    conn.commit()
    cur.execute("SELECT Id, AuthorName, Content FROM CN_AME_MISA_IssueComment WHERE IssueId = 6 ORDER BY Id DESC")
    rows = cur.fetchall()
    print(f"插入后查询 ({len(rows)} 条):")
    for r in rows[:3]:
        print(f"  Id={r.Id}, AuthorName={r.AuthorName!r}, Content={r.Content!r}")
    # 清理
    cur.execute("DELETE FROM CN_AME_MISA_IssueComment WHERE Content = ?", (test_content,))
    conn.commit()
    print("已清理测试数据")

    conn.close()


if __name__ == "__main__":
    main()
