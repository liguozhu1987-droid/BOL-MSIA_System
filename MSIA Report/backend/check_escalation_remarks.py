"""检查升级配置表的 Remarks 乱码情况

- 查看当前所有记录的 Remarks 字段
- 如果字段已是 NVARCHAR 但内容是 ????，说明为历史写入时丢失信息 (VARCHAR 时代写入)
- 这种丢失不可逆，需要用户手动重新填写备注内容
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
    print("1) 查询 CN_AME_MISA_EscalationConfig 表所有记录的 Remarks 字段")
    print("=" * 80)
    cur.execute(
        "SELECT Id, Plant, Severity, Remarks, Level1Recipients, Level2Recipients, Level3Recipients "
        "FROM CN_AME_MISA_EscalationConfig ORDER BY Id"
    )
    rows = cur.fetchall()
    bad_ids = []
    for r in rows:
        remarks = r.Remarks or ""
        has_garbled = "?" in remarks
        print(f"\n  Id={r.Id}, Plant={r.Plant}, Severity={r.Severity}")
        print(f"    Remarks         = {remarks!r} (乱码? {'是' if has_garbled else '否'})")
        print(f"    Lv1Recipients   = {r.Level1Recipients!r}")
        print(f"    Lv2Recipients   = {r.Level2Recipients!r}")
        print(f"    Lv3Recipients   = {r.Level3Recipients!r}")
        if has_garbled:
            bad_ids.append(r.Id)

    print("\n" + "=" * 80)
    print("2) 检查列 COLLATION")
    print("=" * 80)
    cur.execute(
        "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, COLLATION_NAME "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_NAME = 'CN_AME_MISA_EscalationConfig' "
        "  AND COLUMN_NAME IN ('Plant','Level1Recipients','Level2Recipients','Level3Recipients','Remarks')"
    )
    for r in cur.fetchall():
        print(
            f"  {r.TABLE_NAME}.{r.COLUMN_NAME}: type={r.DATA_TYPE}({r.CHARACTER_MAXIMUM_LENGTH}), "
            f"collation={r.COLLATION_NAME}"
        )

    if bad_ids:
        print("\n" + "=" * 80)
        print(f"3) 发现 {len(bad_ids)} 条备注含乱码 (? 字符)")
        print("   原因: 历史上这些记录在字段为 VARCHAR 类型时写入，中文编码已丢失，无法自动恢复。")
        print("   处理建议: 在前端编辑页面重新手工填写正确的备注内容后保存即可。")
        print("   受影响 Id: " + ", ".join(str(x) for x in bad_ids))
    else:
        print("\n3) 未检测到备注乱码记录 ✅")

    conn.close()


if __name__ == "__main__":
    main()
