# -*- coding: utf-8 -*-
"""实测: 1) 归档项目问题清单与详情; 2) 问题管理是否已排除归档项目; 3) 归档项目报告数据"""
import requests

BASE = "http://localhost:8088"
s = requests.Session()
r = s.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "Inalfa2026"}, timeout=15)
token = r.json().get("data", {}).get("access_token") or r.json().get("access_token")
h = {"Authorization": f"Bearer {token}"}

# 1) 归档项目列表
r = s.get(f"{BASE}/api/archive/projects?page=1&page_size=5", headers=h, timeout=60)
items = r.json().get("items", [])
print(f"归档项目列表: {r.status_code} | total={r.json().get('total')}")
archived = {}
for it in items:
    print(f"  planId={it.get('planId')} | {it.get('projectName')} | issue_stats={it.get('issue_stats')}")
    archived[str(it.get('planId'))] = it.get('projectName')

# 2) 取第一个归档项目: 问题清单 (plan_id 过滤)
if archived:
    pid = list(archived.keys())[0]
    r = s.get(f"{BASE}/api/issues?plan_id={pid}&page=1&page_size=50", headers=h, timeout=60)
    res = r.json()
    print(f"\n归档项目 {pid} ({archived[pid]}) 问题清单: {r.status_code} | total={res.get('total')}")
    for it in res.get("items", [])[:5]:
        print(f"  {it.get('IssueNo')} | {it.get('Status')} | {it.get('Title')[:30]} | 关闭时间={it.get('ClosedAt')}")

    # 3) 全量问题列表是否排除了该归档项目
    r = s.get(f"{BASE}/api/issues?page=1&page_size=200", headers=h, timeout=60)
    res = r.json()
    leaked = [it.get('IssueNo') for it in res.get("items", []) if str(it.get('PlanId')) == pid]
    print(f"\n问题管理全量列表: total={res.get('total')} | 归档项目({pid})问题残留: {leaked if leaked else '无(已排除)'}")

    # 4) 统计接口口径
    r = s.get(f"{BASE}/api/issues/stats/summary", headers=h, timeout=60)
    print(f"问题统计(全量排除归档后): {r.status_code} | {r.json()}")

    # 5) 筛选选项中的项目是否已排除归档项目
    r = s.get(f"{BASE}/api/issues/filter-options", headers=h, timeout=60)
    projs = [p.get('label') for p in r.json().get('projects', [])]
    print(f"\n筛选项目选项数: {len(projs)} | 含归档项目: {any(archived[pid].split('(')[0][:6] in (l or '') for l in projs for pid in list(archived)[:1])}")

    # 6) 阶段报告接口 (归档项目复用)
    r = s.get(f"{BASE}/api/projects/{pid}/phase-report/MSIA3", headers=h, timeout=60)
    d = r.json()
    if r.status_code == 200:
        print(f"\n归档项目 {pid} MSIA3 审核报告: {r.status_code} | msia_result={d.get('msia_result')} | items={len(d.get('items', []))}")
    else:
        print(f"\n归档项目 {pid} MSIA3 审核报告: {r.status_code} | {r.text[:120]}")
