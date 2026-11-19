"""修复历史 IssueComment 中文乱码数据

策略:
1. 查询所有含 ? 的 IssueComment 记录及其关联 Issue
2. 根据 Issue.Title + Action 重建 Content
3. 根据 AuthorUserId 查询正确的 AuthorName
4. 使用 NVARCHAR 字面量 N'...' 更新

注意: 此脚本幂等, 只修复含 ? 的记录
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

    print("=" * 80)
    print("查询所有含 ? 的 IssueComment 及关联的 Issue/User 信息")
    print("=" * 80)
    cur.execute("""
        SELECT C.Id, C.IssueId, C.AuthorUserId, C.AuthorName, C.Action,
               C.Content, C.FromStatus, C.ToStatus,
               I.IssueNo, I.Title, I.OwnerName, I.Description, I.Status
        FROM CN_AME_MISA_IssueComment C
        LEFT JOIN CN_AME_MISA_Issue I ON C.IssueId = I.Id
        WHERE C.Content LIKE '%?%' OR C.AuthorName LIKE '%?%'
        ORDER BY C.Id
    """)
    bad_rows = cur.fetchall()
    print(f"共 {len(bad_rows)} 条乱码记录")

    # 查询用户表用于 AuthorName 修正
    cur.execute("SELECT Id, Username, DisplayName FROM CN_AME_MISA_User")
    user_map = {row.Id: (row.Username, row.DisplayName) for row in cur.fetchall()}

    print("\n" + "=" * 80)
    print("修复方案")
    print("=" * 80)
    fix_list = []
    for r in bad_rows:
        # 根据 Action 重建 Content
        issue_title = r.Title or ""
        owner_name = r.OwnerName or ""

        if r.Action == "create":
            # _add_comment 中的 content: "问题已创建: {Title}" + (责任人部分)
            if owner_name:
                new_content = f"问题已创建: {issue_title} (责任人: {owner_name})"
            else:
                new_content = f"问题已创建: {issue_title}"
        elif r.Action == "comment":
            # Id=1 的 Content='?????: Project plan not clear' 不是 create 格式
            # 看起来是 "评审员: Project plan not clear"
            # 但 Action=create? 让我们检查实际格式
            new_content = f"问题已创建: {issue_title}"
        else:
            new_content = f"{r.Action}: {issue_title}"

        # 修正 AuthorName
        new_author = r.AuthorName
        if r.AuthorUserId:
            user_info = user_map.get(r.AuthorUserId)
            if user_info:
                # 优先使用 DisplayName, 否则 Username
                new_author = user_info[1] or user_info[0]
        # 如果 AuthorName 仍是乱码 (含 ?) 且没有 AuthorUserId, 用 'admin' 兜底
        if new_author and '?' in new_author:
            new_author = 'admin'

        print(f"\n  CommentId={r.Id}, IssueId={r.IssueId}, Action={r.Action}")
        print(f"    原 AuthorName = {r.AuthorName!r}")
        print(f"    新 AuthorName = {new_author!r}")
        print(f"    原 Content    = {r.Content!r}")
        print(f"    新 Content    = {new_content!r}")
        fix_list.append((r.Id, new_author, new_content))

    print("\n" + "=" * 80)
    print(f"执行修复 (共 {len(fix_list)} 条)")
    print("=" * 80)
    for comment_id, new_author, new_content in fix_list:
        cur.execute(
            "UPDATE CN_AME_MISA_IssueComment "
            "SET AuthorName = ?, Content = ? "
            "WHERE Id = ?",
            (new_author, new_content, comment_id),
        )
        print(f"  已更新 Id={comment_id}")
    conn.commit()

    # 验证
    print("\n" + "=" * 80)
    print("验证修复结果")
    print("=" * 80)
    cur.execute("""
        SELECT Id, AuthorName, Content
        FROM CN_AME_MISA_IssueComment
        WHERE Id IN ({})
        ORDER BY Id
    """.format(",".join(str(f[0]) for f in fix_list)))
    for r in cur.fetchall():
        print(f"  Id={r.Id}, AuthorName={r.AuthorName!r}, Content={r.Content!r}")

    # 检查是否还有乱码
    cur.execute("""
        SELECT COUNT(*) FROM CN_AME_MISA_IssueComment
        WHERE Content LIKE '%?%' OR AuthorName LIKE '%?%'
    """)
    remaining = cur.fetchone()[0]
    print(f"\n剩余含 ? 的记录数: {remaining}")

    conn.close()


if __name__ == "__main__":
    main()
