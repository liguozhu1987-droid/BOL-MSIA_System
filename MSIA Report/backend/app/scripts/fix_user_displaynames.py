"""修复用户表中 DisplayName 含 ? (中文乱码) 的记录

策略:
1. 对于 HR 中存在的用户: 从 HR 重新读取 realName 覆盖
2. 对于 HR 中不存在的种子用户 (lead_reviewer01 等): 手动设置正确的 DisplayName
3. 对于其他无法修复的用户: 清空 DisplayName (回退到 Username 显示)
"""
import sys
from pathlib import Path

import pyodbc

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User


# 种子用户 (非 HR 同步) 的正确 DisplayName
SEED_USER_DISPLAY_NAMES = {
    "lead_reviewer01": "首席评审",
    "reviewer01": "评审员",
    "reviewee01": "被评审",
}


def fetch_hr_realnames() -> dict[str, str]:
    """从 HR fine_user 表批量读取 userName -> realName 映射"""
    mapping: dict[str, str] = {}
    sql = "SELECT userName, realName FROM [HRDB].[dbo].[fine_user] WHERE userName IS NOT NULL"
    with pyodbc.connect(settings.HRDB_CONNECTION_STRING) as conn:
        cursor = conn.cursor()
        cursor.execute(sql)
        for row in cursor.fetchall():
            username = (row[0] or "").strip()
            realname = row[1] or ""
            if username and realname:
                mapping[username] = realname
    return mapping


def fix() -> None:
    print("[fix] 开始修复 DisplayName 中文乱码")
    db = SessionLocal()
    try:
        # 1. 从 HR 读取 userName -> realName 映射
        hr_names = fetch_hr_realnames()
        print(f"[fix] 从 HR 读取到 {len(hr_names)} 个用户名映射")

        # 2. 查找所有 DisplayName 含 ? 的用户
        corrupted_users = db.query(User).filter(User.DisplayName.like("%?%")).all()
        print(f"[fix] 发现 {len(corrupted_users)} 个 DisplayName 含 ? 的用户")

        fixed_from_hr = 0
        fixed_from_seed = 0
        cleared = 0

        for u in corrupted_users:
            if u.Username in hr_names:
                # 从 HR 修复
                new_name = hr_names[u.Username]
                if "?" in new_name:
                    # HR 数据本身也乱码, 清空 DisplayName (回退到 Username)
                    print(f"[fix] Id={u.Id} Username={u.Username}: HR 数据也乱码, 清空 DisplayName (HR值: '{new_name}')")
                    u.DisplayName = None
                    cleared += 1
                else:
                    print(f"[fix] Id={u.Id} Username={u.Username}: 从 HR 修复 '{u.DisplayName}' -> '{new_name}'")
                    u.DisplayName = new_name
                    fixed_from_hr += 1
            elif u.Username in SEED_USER_DISPLAY_NAMES:
                # 种子用户手动修复
                new_name = SEED_USER_DISPLAY_NAMES[u.Username]
                print(f"[fix] Id={u.Id} Username={u.Username}: 种子用户修复 '{u.DisplayName}' -> '{new_name}'")
                u.DisplayName = new_name
                fixed_from_seed += 1
            else:
                # 无法修复, 清空 DisplayName (回退到 Username 显示)
                print(f"[fix] Id={u.Id} Username={u.Username}: 无法修复, 清空 DisplayName (原值: '{u.DisplayName}')")
                u.DisplayName = None
                cleared += 1

        db.commit()
        print(f"[fix] 修复完成: HR修复={fixed_from_hr}, 种子修复={fixed_from_seed}, 清空={cleared}")
    finally:
        db.close()


if __name__ == "__main__":
    fix()
