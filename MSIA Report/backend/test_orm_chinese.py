"""测试通过 SQLAlchemy ORM 写入中文到 IssueComment, 确认是否复现乱码"""
import sys
import os

# 确保使用 UTF-8 输出
sys.stdout.reconfigure(encoding='utf-8')

# 添加 backend 到 path
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, backend_dir)

from app.db.session import SessionLocal, engine
from app.models.issue import Issue
from app.models.issue_comment import IssueComment
from app.models.user import User
from sqlalchemy import text

def main():
    print("=" * 70)
    print("测试 SQLAlchemy ORM 写入中文")
    print("=" * 70)

    db = SessionLocal()
    try:
        # 查询一个已存在的 Issue
        issue = db.query(Issue).filter(Issue.Id == 6).first()
        if not issue:
            print("找不到 Issue Id=6")
            return
        print(f"找到 Issue: Id={issue.Id}, Title={issue.Title!r}, OwnerName={issue.OwnerName!r}")

        # 查询 admin 用户
        admin = db.query(User).filter(User.Username == 'admin').first()
        if admin:
            print(f"找到 admin: Id={admin.Id}, DisplayName={admin.DisplayName!r}")
        else:
            print("找不到 admin 用户")

        # 测试1: 通过 ORM 写入带中文的评论
        test_content = "ORM测试: 评审员 缺少GRR数据验证"
        comment = IssueComment(
            IssueId=issue.Id,
            AuthorUserId=admin.Id if admin else 1,
            AuthorName="评审员测试",
            Action="comment",
            Content=test_content,
            FromStatus=None,
            ToStatus="open",
        )
        db.add(comment)
        db.commit()
        db.refresh(comment)
        print(f"\n写入后: Id={comment.Id}, AuthorName={comment.AuthorName!r}, Content={comment.Content!r}")

        # 重新查询验证
        db.expire_all()
        comment2 = db.query(IssueComment).filter(IssueComment.Id == comment.Id).first()
        print(f"重新查询: Id={comment2.Id}, AuthorName={comment2.AuthorName!r}, Content={comment2.Content!r}")

        # 清理
        db.delete(comment2)
        db.commit()
        print("已清理测试数据")

        # 测试2: 直接查询乱码记录 Id=4
        print("\n" + "=" * 70)
        print("查询乱码记录 Id=4")
        print("=" * 70)
        bad = db.query(IssueComment).filter(IssueComment.Id == 4).first()
        if bad:
            print(f"Id={bad.Id}")
            print(f"AuthorName = {bad.AuthorName!r}")
            print(f"Content    = {bad.Content!r}")
            print(f"Action     = {bad.Action!r}")

        # 测试3: 查询对应的 Issue
        print("\n查询对应 Issue Id=6")
        print("=" * 70)
        iss = db.query(Issue).filter(Issue.Id == 6).first()
        if iss:
            print(f"Title       = {iss.Title!r}")
            print(f"Description = {iss.Description!r}")
            print(f"OwnerName   = {iss.OwnerName!r}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
