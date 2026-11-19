"""回填 Issue.OwnerUserName 字段

策略:
1. 查询所有 OwnerUserName 为空的 Issue
2. 通过 PlanId 查询 HRDB 获取 userName_in_charge
3. 同时回填 OwnerUserId (若能匹配本地用户)
"""
import sys
import os

# 添加 backend 到 path
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, backend_dir)

from app.db.session import SessionLocal
from app.models.issue import Issue
from app.models.user import User
from app.services.hrdb_query_service import HrdbQueryService
from app.core.config import settings


def main():
    db = SessionLocal()
    service = HrdbQueryService(settings)
    try:
        # 查询所有未填充 OwnerUserName 的 Issue
        issues = db.query(Issue).filter(
            Issue.OwnerUserName.is_(None),
            Issue.IsDeleted == False,
        ).all()
        print(f"共 {len(issues)} 条 Issue 需要 OwnerUserName 回填")
        updated = 0
        for issue in issues:
            if not issue.PlanId:
                print(f"  Issue Id={issue.Id} ({issue.IssueNo}) 无 PlanId, 跳过")
                continue
            try:
                owner_info = service.query_plan_owner_info(issue.PlanId)
            except Exception as e:
                print(f"  Issue Id={issue.Id} 查询 HRDB 失败: {e}")
                continue
            if not owner_info:
                print(f"  Issue Id={issue.Id} HRDB 未返回数据, 跳过")
                continue

            user_name_in_charge = owner_info.get("userName_in_charge")
            if not user_name_in_charge:
                print(f"  Issue Id={issue.Id} HRDB 无 userName_in_charge, 跳过")
                continue

            # 回填 OwnerUserName
            old_user_name = issue.OwnerUserName
            issue.OwnerUserName = user_name_in_charge

            # 同步回填 OwnerUserId (若未关联本地用户)
            old_user_id = issue.OwnerUserId
            if not issue.OwnerUserId:
                user = db.query(User).filter(User.Username == user_name_in_charge).first()
                if user:
                    issue.OwnerUserId = user.Id

            # 同步回填 OwnerCompany (location)
            old_company = issue.OwnerCompany
            if not issue.OwnerCompany and owner_info.get("location"):
                issue.OwnerCompany = owner_info["location"]

            # 同步回填 OwnerName (中文名)
            old_name = issue.OwnerName
            if not issue.OwnerName:
                resolved = owner_info.get("ownerName")
                if resolved:
                    issue.OwnerName = resolved

            db.commit()
            updated += 1
            print(f"  Issue Id={issue.Id} ({issue.IssueNo}) 已更新:")
            print(f"    OwnerUserName: {old_user_name!r} -> {issue.OwnerUserName!r}")
            print(f"    OwnerUserId:   {old_user_id!r} -> {issue.OwnerUserId!r}")
            print(f"    OwnerName:     {old_name!r} -> {issue.OwnerName!r}")
            print(f"    OwnerCompany:  {old_company!r} -> {issue.OwnerCompany!r}")

        print(f"\n完成: 共更新 {updated} 条 Issue")
    finally:
        db.close()


if __name__ == "__main__":
    main()
