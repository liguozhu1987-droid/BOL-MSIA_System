"""迁移: 为 User 表新增 RealName 列, 并从 DisplayName 括号内中文提取初始值

运行: python -m app.scripts.add_user_realname
"""
import re
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import engine  # noqa: E402

# 提取 DisplayName 中括号内中文 (如 "LF01047(路玉龙)Yulong Lu" -> "路玉龙")
_CN_IN_PARENS_RE = re.compile(r"\(([^)]*[\u4e00-\u9fff][^)]*)\)")


def _extract_cn_name(display_name: str | None) -> str | None:
    if not display_name:
        return None
    matches = _CN_IN_PARENS_RE.findall(display_name)
    if matches:
        return matches[0]
    return None


def migrate() -> None:
    print("[migrate] 开始: 为 CN_AME_MISA_User 添加 RealName 列并回填")
    with engine.begin() as conn:
        # 1. 检查列是否已存在
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = 'CN_AME_MISA_User' AND COLUMN_NAME = 'RealName'"
            )
        )
        if result.scalar():
            print("[migrate] 跳过: RealName 列已存在")
        else:
            sql = "ALTER TABLE [CN_AME_MISA_User] ADD [RealName] NVARCHAR(100) NULL"
            print(f"[migrate] 执行: {sql}")
            conn.execute(text(sql))
            print("[migrate] 成功: RealName 列已添加")

            # 创建索引
            idx_sql = "CREATE INDEX IX_CN_AME_MISA_User_RealName ON [CN_AME_MISA_User] ([RealName])"
            try:
                conn.execute(text(idx_sql))
                print("[migrate] 成功: 索引 IX_CN_AME_MISA_User_RealName 已创建")
            except Exception as e:
                print(f"[migrate] 索引创建失败 (可忽略): {e}")

        # 2. 回填 RealName (从 DisplayName 提取括号内中文)
        rows = conn.execute(
            text("SELECT Id, DisplayName FROM [CN_AME_MISA_User] WHERE RealName IS NULL")
        ).fetchall()

        updated = 0
        for row in rows:
            user_id = row[0]
            display_name = row[1]
            real_name = _extract_cn_name(display_name)
            if real_name:
                conn.execute(
                    text("UPDATE [CN_AME_MISA_User] SET RealName = :rn WHERE Id = :id"),
                    {"rn": real_name, "id": user_id},
                )
                updated += 1

        print(f"[migrate] 成功: 从 DisplayName 回填 RealName 共 {updated} 条 (总扫描 {len(rows)} 条)")

    print("[migrate] 迁移完成")


if __name__ == "__main__":
    migrate()
