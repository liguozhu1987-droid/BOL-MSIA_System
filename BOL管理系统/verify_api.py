# -*- coding: utf-8 -*-
"""验证 BudgetBol API 是否满足用户需求"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000/api"

# 1. 登录获取 token
login_data = json.dumps({"username": "admin", "password": "Admin@123456"}).encode()
req = urllib.request.Request(f"{BASE}/auth/login/", data=login_data,
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req) as resp:
    token = json.loads(resp.read())["token"]
print(f"[OK] 登录成功，token 长度: {len(token)}")

headers = {"Authorization": f"Token {token}"}


def get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


# 2. 验证 filter-options: plant 应该无 "_" 后缀
fo = get("/budget-bol/budget-bol/filter-options/")
print("\n=== filter-options ===")
print(f"fiscal_years: {fo.get('fiscal_years')}")
print(f"plants (raw): {fo.get('plants')}")
plants = fo.get("plants", [])
bad = [p for p in plants if "_" in str(p)]
print(f"plants 含 '_' 后缀: {bad} (应该为空)")
print(f"process_types: {fo.get('process_types')}")

# 3. 验证 Budget Tab 数据（含 CBCO 字段）
budget = get("/budget-bol/budget-bol/?bol_type=BUDGET&fiscal_year=2026")
print("\n=== BUDGET 2026 ===")
print(f"总数: {len(budget)}")
if budget:
    sample = budget[0]
    print(f"首条 project_code={sample.get('project_code')}, plant={sample.get('plant')}")
    print(f"  customer={sample.get('customer')!r}, programs={sample.get('program_description')!r}")
    print(f"  roof_type={sample.get('roof_type')!r}, status={sample.get('status')!r}")
    print(f"  sop={sample.get('sop')!r}, eop={sample.get('eop')!r}")
    # 填充率统计
    filled = sum(1 for x in budget if x.get("customer"))
    print(f"  customer 填充率: {filled}/{len(budget)} ({100*filled/len(budget):.1f}%)")

# 4. 验证 Achievable Tab 数据
ach = get("/budget-bol/budget-bol/?bol_type=ACHIEVABLE&fiscal_year=2026")
print("\n=== ACHIEVABLE 2026 ===")
print(f"总数: {len(ach)}")
if ach:
    sample = ach[0]
    print(f"首条 project_code={sample.get('project_code')}, plant={sample.get('plant')}")
    print(f"  customer={sample.get('customer')!r}, roof_type={sample.get('roof_type')!r}")
    print(f"  sop={sample.get('sop')!r}")
    filled = sum(1 for x in ach if x.get("customer"))
    print(f"  customer 填充率: {filled}/{len(ach)} ({100*filled/len(ach):.1f}%)")

# 5. 验证 Target Tab 数据
tgt = get("/budget-bol/budget-bol/?bol_type=TARGET&fiscal_year=2026")
print("\n=== TARGET 2026 ===")
print(f"总数: {len(tgt)}")
if tgt:
    sample = tgt[0]
    print(f"首条 project_code={sample.get('project_code')}, plant={sample.get('plant')}")
    print(f"  customer={sample.get('customer')!r}, roof_type={sample.get('roof_type')!r}")
    filled = sum(1 for x in tgt if x.get("customer"))
    print(f"  customer 填充率: {filled}/{len(tgt)} ({100*filled/len(tgt):.1f}%)")

# 6. 验证 plant 筛选去后缀匹配
beijing_budget = get("/budget-bol/budget-bol/?bol_type=BUDGET&plant=Beijing")
print("\n=== plant=Beijing 筛选（应匹配 Beijing_IHE 等）===")
print(f"BUDGET Beijing 总数: {len(beijing_budget)}")
if beijing_budget:
    plants_in_result = set(x.get("plant") for x in beijing_budget)
    print(f"结果中实际 plant 值: {plants_in_result}")

print("\n=== 验证完成 ===")
