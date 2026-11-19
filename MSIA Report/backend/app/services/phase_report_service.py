"""MSIA 阶段审核报告服务

报告格式参照 Excel 模板 "Report MSIA1~5" sheet (同 report.png):
- 头部: 项目关键数据 (Project Key Data) + 里程碑 (Milestones) + MSIA No. + MSIA Result
- High-risk comments (reviewer): 本阶段登记的高风险问题 (Severity/Priority = H) 汇总
- 检查项表格: Item / Request / Result / Comment
  * Result: 该检查项的最新评分 (百分比), 未评分为空
  * Comment: 该检查项下审核员登记的问题逐条列出 (不含证据图片)
- 尾部: Reviewers / Review place / Reviewees / Date
  * Reviewers: 所有提交问题的用户 + 更改分数的用户 (参与评审的审核员)
  * Review place: 从 PhaseReviewMeta 读取 (默认 Teams), 支持在项目管理界面手动维护
  * Reviewees: 项目负责人 (HRDB ownerName)
  * Date: 本阶段最后一个问题提交或评分录入的时间点
- CMC AME 与 Milestones (Inalfa kick-off / Supplier kick-off / Design freeze /
  PVP / Inalfa SOP): 从 PhaseReviewMeta 读取, 审核员在报告弹窗中手动维护
  (两者默认均为空, 仅显示手动维护的值)

数据来源:
- PhaseReviewItem: 各阶段检查项清单
- ReviewRecord: 评分记录 (PlanId + PhaseCode + PhaseReviewItemId)
- Issue: 问题登记 (PlanId + PhaseCode + PhaseReviewItemId)
- HRDB: 项目名称/负责人/里程碑等关键数据
"""
import io
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.check_item import CheckItem
from app.models.issue import Issue
from app.models.phase_review_item import PhaseReviewItem
from app.models.phase_review_meta import PhaseReviewMeta
from app.models.review import ReviewRecord
from app.models.user import User
from app.services.hrdb_query_service import HrdbQueryService
# 复用评审清单接口的 REQUEST 匹配工具, 确保报告与评审界面内容一致 (noqa 规避分层告警)
from app.api.phase_review_items import (  # noqa: E402
    _extract_maturity_100_desc,
    _normalize_name,
    _tokenize,
)

REPORTABLE_REVIEW_STATUSES = ("submitted", "confirmed")

# 中文字体回退 (与 report_service 保持一致)
_CN_FONT = "Helvetica"
try:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for _candidate in (
        "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",    # 黑体
        "C:/Windows/Fonts/simsun.ttc",    # 宋体
    ):
        import os

        if os.path.exists(_candidate):
            pdfmetrics.registerFont(TTFont("CN", _candidate))
            _CN_FONT = "CN"
            break
except Exception:
    pass

# 阶段代码 → 阶段序号
def _phase_no(phase_code: str) -> str:
    """MSIA1 -> 1"""
    return phase_code.replace("MSIA", "").strip()


def _fmt_date(val: Any) -> str:
    """日期格式化 (HRDB 返回 datetime/date/str)"""
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    if hasattr(val, "strftime"):  # date
        return val.strftime("%Y-%m-%d")
    s = str(val)[:10]
    return s.replace("/", "-")


def _fmt_dt(val: Optional[datetime]) -> str:
    """时间点格式化: YYYY-MM-DD HH:MM"""
    if val is None:
        return ""
    return val.strftime("%Y-%m-%d %H:%M")


def _fmt_score(score: Any) -> str:
    """评分 (0~1) -> 百分比整数, 如 0.75 -> '75%'"""
    if score is None:
        return ""
    try:
        return f"{round(float(score) * 100)}%"
    except (ValueError, TypeError):
        return ""


def _user_display(user: Optional[User]) -> str:
    """用户显示名: 优先中文姓名, 回退 DisplayName / Username"""
    if not user:
        return ""
    return user.RealName or user.DisplayName or user.Username or ""


def build_phase_report(
    db: Session,
    settings: Settings,
    plan_id: str,
    phase_code: str,
) -> Dict[str, Any]:
    """构建阶段审核报告数据

    Returns:
        {
            "plan_id", "phase_code", "msia_no", "msia_result",
            "project": {name, no, type, cmc_ame, plant_me, ...},
            "milestones": {plan_date, actual_date, ots, ppap, sop},
            "reviewers": [姓名...], "review_place", "reviewees", "date",
            "high_risk_issues": [{issue_no, title, severity, item_name}],
            "items": [{seq, item_type, item_name, request, result, issues: [...]}],
        }
    """
    plan_id = str(plan_id)

    # ---------- 1. HRDB 项目信息 (失败不阻塞报告生成) ----------
    project: Dict[str, Any] = {
        "name": "", "no": "", "type": "", "cmc_ame": "", "plant_me": "",
        "plant": "", "line": "", "supplier": "",
    }
    milestones: Dict[str, str] = {}
    reviewees = ""
    try:
        hrdb = HrdbQueryService(settings)
        detail = hrdb.query_msia_plan_detail(plan_id)
        if detail and detail.get("plan"):
            plan = detail["plan"]
            project.update({
                "name": plan.get("projectName") or "",
                "no": str(plan.get("orderId") or ""),
                "type": plan.get("projectType") or plan.get("lineType") or "",
                "cmc_ame": "",
                "plant": plan.get("plantName") or "",
                "line": plan.get("lineName") or "",
                "supplier": plan.get("supplerName") or "",
            })
            project["plant_me"] = " / ".join(
                x for x in [plan.get("plantName"), plan.get("lineName")] if x
            )
            reviewees = plan.get("ownerName") or ""
            n = _phase_no(phase_code)
            milestones = {
                "plan_date": _fmt_date(plan.get(f"msia{n}PlanDate")),
                "actual_date": _fmt_date(plan.get(f"msia{n}ActualDate")),
            }
            proj = detail.get("project_basic_info") or {}
            milestones["ots"] = _fmt_date(proj.get("OTS_date"))
            milestones["ppap"] = _fmt_date(proj.get("PPAP_date"))
            milestones["sop"] = _fmt_date(proj.get("SOP_date"))
    except Exception as exc:
        logger.warning("报告查询 HRDB 项目信息失败 plan_id={}: {}", plan_id, exc)

    # ---------- 2. 检查项清单 (报告行) ----------
    items = (
        db.query(PhaseReviewItem)
        .filter(
            PhaseReviewItem.PhaseCode == phase_code,
            PhaseReviewItem.IsDeleted == False,  # noqa: E712
        )
        .order_by(PhaseReviewItem.SortOrder.asc(), PhaseReviewItem.Seq.asc())
        .all()
    )

    # ---------- 2.1 REQUEST 匹配: 与评审界面 REQUEST 列一致 ----------
    # 优先 CheckItemId 精确关联 → 名称匹配 (精确/规范化/包含/token), 取审核标准 100% 档描述
    # 过滤已删除 + 已停用 (IsActive=False) 的审核条款, 与评审清单场景保持一致
    check_items_data = (
        db.query(CheckItem.Id, CheckItem.Name, CheckItem.ScoreOptions, CheckItem.IsActive)
        .filter(
            CheckItem.PhaseCode == phase_code,
            CheckItem.IsDeleted == False,  # noqa: E712
        )
        .all()
    )
    # 仅启用 (IsActive=True) 的 CheckItem 才作为候选池
    active_check_items_data = [row for row in check_items_data if row.IsActive is not False]
    desc_by_check_id: Dict[int, str] = {}
    fuzzy_pool: List[tuple] = []  # (name, norm_name, desc100)
    for cid, name, score_options, _is_active in active_check_items_data:
        d100 = _extract_maturity_100_desc(score_options)
        desc_by_check_id[cid] = d100
        fuzzy_pool.append((name, _normalize_name(name), d100))

    # 自愈过滤: 剔除 CheckItemId 指向已删除/不存在/已停用 审核标准的孤儿条目 (与评审清单一致)
    items = [
        it for it in items
        if not (it.CheckItemId is not None and it.CheckItemId not in desc_by_check_id)
    ]

    def _match_request(it: PhaseReviewItem) -> str:
        """返回该检查项的 REQUEST 内容 (100% 档评分描述; 无则回退原 Request 标记)"""
        if it.CheckItemId is not None:
            desc = desc_by_check_id.get(it.CheckItemId)
            if desc:
                return desc
        target_norm = _normalize_name(it.ItemName)
        target_tokens = _tokenize(it.ItemName)
        # 精确 / 规范化匹配
        for name, norm, desc in fuzzy_pool:
            if (name == it.ItemName or norm == target_norm) and desc:
                return desc
        # 包含匹配
        if target_norm:
            for _, norm, desc in fuzzy_pool:
                if desc and norm and (target_norm in norm or norm in target_norm):
                    return desc
        # Token 集合匹配
        if target_tokens:
            for name, _, desc in fuzzy_pool:
                if desc and target_tokens.issubset(_tokenize(name)):
                    return desc
        return it.Request or ""

    request_by_item_id = {it.Id: _match_request(it) for it in items}

    # ---------- 3. 最新正式评分 (每个检查项取最新 submitted/confirmed 记录) ----------
    subq = (
        db.query(
            ReviewRecord.PhaseReviewItemId,
            sqlfunc.max(ReviewRecord.Id).label("max_id"),
        )
        .filter(
            ReviewRecord.PlanId == plan_id,
            ReviewRecord.PhaseCode == phase_code,
            ReviewRecord.Score.isnot(None),
            ReviewRecord.Status.in_(REPORTABLE_REVIEW_STATUSES),
        )
        .group_by(ReviewRecord.PhaseReviewItemId)
        .subquery()
    )
    latest_reviews = {
        r.PhaseReviewItemId: r
        for r in db.query(ReviewRecord).join(subq, ReviewRecord.Id == subq.c.max_id).all()
    }

    # ---------- 4. 问题登记 (本阶段全部未删除问题) ----------
    issues = (
        db.query(Issue)
        .filter(
            Issue.PlanId == plan_id,
            Issue.PhaseCode == phase_code,
            Issue.IsDeleted == False,  # noqa: E712
        )
        .order_by(Issue.CreatedAt.asc(), Issue.Id.asc())
        .all()
    )

    # 按检查项分组: 优先 PhaseReviewItemId, 回退解析 ItemNo "{phase}-{seq}"
    issues_by_prid: Dict[int, List[Issue]] = defaultdict(list)
    issues_by_seq: Dict[int, List[Issue]] = defaultdict(list)
    for iss in issues:
        if iss.PhaseReviewItemId:
            issues_by_prid[iss.PhaseReviewItemId].append(iss)
        elif iss.ItemNo:
            try:
                seq = int(str(iss.ItemNo).split("-")[-1])
                issues_by_seq[seq].append(iss)
            except (ValueError, IndexError):
                pass

    item_name_by_prid = {i.Id: i.ItemName for i in items}

    def _issue_lines(issue_list: List[Issue]) -> List[Dict[str, Any]]:
        return [
            {
                "issue_no": iss.IssueNo,
                "title": iss.Title,
                "severity": iss.Severity or "",
                "priority": iss.Priority or "",
                "created_by": iss.CreatedBy,
                "created_at": _fmt_dt(iss.CreatedAt),
            }
            for iss in issue_list
        ]

    # ---------- 5. 报告行组装 ----------
    item_rows: List[Dict[str, Any]] = []
    for display_seq, it in enumerate(items, start=1):
        review = latest_reviews.get(it.Id)
        item_issues = issues_by_prid.get(it.Id) or issues_by_seq.get(it.Seq) or []
        item_rows.append({
            "phase_review_item_id": it.Id,
            # 显示序号: 连续编号 1..N (数据库 Seq 可能因条目删除留有空洞)
            "seq": display_seq,
            "item_type": it.ItemType or "",
            "item_name": it.ItemName,
            # Request: 与评审界面 REQUEST 列一致 (100% 档评分标准描述)
            "request": request_by_item_id.get(it.Id, it.Request or ""),
            "result": _fmt_score(review.Score) if review else "",
            "score": float(review.Score) if review and review.Score is not None else None,
            "issues": _issue_lines(item_issues),
        })

    # ---------- 6. Reviewers: 评分用户 + 提问题用户 ----------
    reviewer_ids = set()
    for review in latest_reviews.values():
        if review.ReviewerId:
            reviewer_ids.add(review.ReviewerId)
    # 所有历史评分记录的评分人也计入 (参与评审即算)
    all_scored = (
        db.query(ReviewRecord.ReviewerId)
        .filter(
            ReviewRecord.PlanId == plan_id,
            ReviewRecord.PhaseCode == phase_code,
            ReviewRecord.Score.isnot(None),
        )
        .distinct()
        .all()
    )
    for (uid,) in all_scored:
        if uid:
            reviewer_ids.add(uid)
    for iss in issues:
        if iss.CreatedBy:
            reviewer_ids.add(iss.CreatedBy)

    users = (
        db.query(User).filter(User.Id.in_(reviewer_ids)).all()
        if reviewer_ids
        else []
    )
    # 保持评分时间顺序: 按 Id 排序展示
    users.sort(key=lambda u: u.Id)
    reviewers = [(_user_display(u) or str(u.Id)) for u in users]

    # ---------- 7. Date: 最后一次问题提交或评分录入时间 ----------
    date_points: List[datetime] = []
    for review in latest_reviews.values():
        date_points.append(review.CreatedAt or review.UpdatedAt)
    for iss in issues:
        date_points.append(iss.CreatedAt)
    date_points = [d for d in date_points if d]
    report_date = _fmt_dt(max(date_points)) if date_points else ""

    # ---------- 8. MSIA Result: 阶段平均分 (有分数项的平均) ----------
    scores = [row["score"] for row in item_rows if row["score"] is not None]
    msia_result = f"{sum(scores) / len(scores) * 100:.1f}%" if scores else ""

    # ---------- 9. Review place / CMC AME / Milestones (手动维护, 默认 Teams) ----------
    meta = (
        db.query(PhaseReviewMeta)
        .filter(
            PhaseReviewMeta.PlanId == plan_id,
            PhaseReviewMeta.PhaseCode == phase_code,
        )
        .first()
    )
    review_place = (meta.ReviewPlace if meta and meta.ReviewPlace else "") or "Teams"
    # CMC AME: 默认为空, 仅显示审核员手动维护的值
    if meta and meta.CmcAme:
        project["cmc_ame"] = meta.CmcAme
    # Milestones: 5 个项目里程碑时间点 (HRDB 无此数据, 由 meta 手动维护)
    milestones["inalfa_kickoff"] = (meta.InalfaKickoff if meta else "") or ""
    milestones["supplier_kickoff"] = (meta.SupplierKickoff if meta else "") or ""
    milestones["design_freeze"] = (meta.DesignFreeze if meta else "") or ""
    milestones["pvp"] = (meta.Pvp if meta else "") or ""
    milestones["inalfa_sop"] = (meta.InalfaSop if meta else "") or ""

    # ---------- 10. High-risk comments ----------
    high_risk = [
        {
            "issue_no": iss.IssueNo,
            "title": iss.Title,
            "severity": iss.Severity or "",
            "priority": iss.Priority or "",
            "item_name": item_name_by_prid.get(iss.PhaseReviewItemId, "") if iss.PhaseReviewItemId else "",
        }
        for iss in issues
        if (iss.Severity or "").upper() == "H" or (iss.Priority or "").lower() == "high"
    ]

    return {
        "plan_id": plan_id,
        "phase_code": phase_code,
        "msia_no": _phase_no(phase_code),
        "msia_result": msia_result,
        "project": project,
        "milestones": milestones,
        "reviewers": reviewers,
        "review_place": review_place,
        "reviewees": reviewees,
        "date": report_date,
        "high_risk_issues": high_risk,
        "items": item_rows,
    }


# ============================================================
# PDF 生成 (横向 A4, 排版与前端报告弹窗 PhaseReportModal UI 保持一致)
# - 头部三栏: Project Key Data | Milestones | MSIA (对应 UI flex 3:3:1)
# - 高风险区: 红框浅红底 (对应 UI #ffa39e / #fff1f0)
# - 检查项表: Item 26% | Request 34% | Result 10% | Comments 30%
#   内容逐行完整展开, 长文本自动换行, 审核条款与问题不被遮挡
# - 尾部四栏: Reviewers | Review place | Reviewees | Date (对应 UI 3:2.4:2.2:2)
# ============================================================

# 页面与内容区宽度 (横向 A4, 左右 12mm 边距)
_PAGE_W, _PAGE_H = landscape(A4)
CONTENT_W = _PAGE_W - 24 * mm

# 与前端 UI 一致的配色
_PDF_BLUE = colors.HexColor("#4472C4")         # 卡片标题条蓝 (UI #4472C4)
_PDF_BORDER = colors.HexColor("#8EA9DB")       # 卡片边框蓝 (UI #8EA9DB)
_PDF_TEXT = colors.HexColor("#333333")         # 正文
_PDF_SECONDARY = colors.HexColor("#8c8c8c")    # 次要文字 (antd secondary)
_PDF_HR_BORDER = colors.HexColor("#ffa39e")    # 高风险边框 (UI #ffa39e)
_PDF_HR_BG = colors.HexColor("#fff1f0")        # 高风险背景 (UI #fff1f0)
_PDF_NOTE_BORDER = colors.HexColor("#91caff")  # 说明区边框 (antd info Alert)
_PDF_NOTE_BG = colors.HexColor("#e6f4ff")      # 说明区背景 (antd info Alert)
_PDF_TABLE_BORDER = colors.HexColor("#d9d9d9")  # 表格边框 (antd bordered, 打印可读)
_PDF_TH_BG = colors.HexColor("#fafafa")        # 表头背景 (antd #fafafa)
_PDF_TH_TEXT = colors.HexColor("#1f1f1f")      # 表头文字


def _score_text_color(score: Any) -> str:
    """与前端 scoreTextColor 一致: 100% 深绿 / 75% 深黄 / 其余深橙红"""
    if score is None:
        return "#bfbfbf"
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "#bfbfbf"
    if s >= 0.9995:
        return "#008A00"
    if s >= 0.7495:
        return "#A89000"
    return "#E85C00"


def _sev_color(sev: Any) -> str:
    """严重度颜色: H 红 / M 橙 / L 蓝 (与 UI Tag 色一致)"""
    s = (sev or "").upper()
    if s == "H":
        return "#ff4d4f"
    if s == "M":
        return "#fa8c16"
    if s == "L":
        return "#1677ff"
    return "#8c8c8c"


def _result_color(result_str: str) -> str:
    """'62.3%' -> scoreTextColor(0.623)"""
    try:
        return _score_text_color(float(str(result_str).rstrip("%")) / 100)
    except (TypeError, ValueError):
        return "#bfbfbf"


def _pdf_styles() -> Dict[str, ParagraphStyle]:
    """PDF 段落样式 (字号按 UI px ≈ 0.75pt 换算)"""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("RptTitle2", parent=base["Normal"], fontName=_CN_FONT, fontSize=12, leading=16, alignment=1, textColor=_PDF_TEXT),
        "subtitle": ParagraphStyle("RptSub2", parent=base["Normal"], fontName=_CN_FONT, fontSize=9, leading=12, alignment=1, textColor=_PDF_SECONDARY),
        "panel_title": ParagraphStyle("RptPanel2", parent=base["Normal"], fontName=_CN_FONT, fontSize=9, leading=12, textColor=colors.white),
        "kv": ParagraphStyle("RptKv2", parent=base["Normal"], fontName=_CN_FONT, fontSize=9, leading=13, textColor=_PDF_TEXT),
        "msia": ParagraphStyle("RptMsia2", parent=base["Normal"], fontName=_CN_FONT, fontSize=9, leading=15, alignment=1, textColor=_PDF_TEXT),
        "body": ParagraphStyle("RptBody2", parent=base["Normal"], fontName=_CN_FONT, fontSize=9, leading=12.5, textColor=_PDF_TEXT),
        "small": ParagraphStyle("RptSmall2", parent=base["Normal"], fontName=_CN_FONT, fontSize=8, leading=11, textColor=_PDF_TEXT),
        "th": ParagraphStyle("RptTh2", parent=base["Normal"], fontName=_CN_FONT, fontSize=9, leading=12, textColor=_PDF_TH_TEXT),
        "phase": ParagraphStyle("RptPhase2", parent=base["Normal"], fontName=_CN_FONT, fontSize=10, leading=13, textColor=_PDF_TEXT),
        "note": ParagraphStyle("RptNote2", parent=base["Normal"], fontName=_CN_FONT, fontSize=8, leading=11.5, textColor=_PDF_TEXT),
    }


def _kv_para(label: str, value: str, st: Dict[str, ParagraphStyle]) -> Paragraph:
    """卡片内的 标签/值 行 (灰色标签 + 深色值)"""
    return Paragraph(
        f'<font color="#8c8c8c">{_escape(label)}</font>&nbsp;&nbsp;{_escape(value) if value else "-"}',
        st["kv"],
    )


def _header_table(report: Dict[str, Any], is_combined: bool, st: Dict[str, ParagraphStyle]) -> Table:
    """头部三栏 (UI flex 3:3:1): Project Key Data | Milestones | MSIA

    单表格 + SPAN 实现: 三个面板共享同一组行, 外框高度天然一致、底边对齐;
    MSIA 内容跨全部数据行并垂直居中 (对应 UI 卡片拉伸等高效果)。
    """
    proj = report["project"]
    left_rows = [
        ("Project name", proj.get("name", "")),
        ("Project No.", proj.get("no", "")),
        ("Project type", proj.get("type", "")),
        ("CMC AME", proj.get("cmc_ame", "")),
        ("Plant ME", proj.get("plant_me", "")),
    ]
    ms = report.get("milestones", {})
    # Milestones: 5 个项目里程碑时间点 (单阶段/合并模式统一, 审核员手动维护)
    mid_rows = [
        ("1. Inalfa kick-off", ms.get("inalfa_kickoff", "")),
        ("2. Supplier kick-off", ms.get("supplier_kickoff", "")),
        ("3. Design freeze", ms.get("design_freeze", "")),
        ("4. PVP", ms.get("pvp", "")),
        ("5. Inalfa SOP", ms.get("inalfa_sop", "")),
    ]
    result_color = (
        _result_color(report.get("msia_result", ""))
        if is_combined
        else "#2E5CE6"  # UI 单阶段 MSIA Result 固定蓝
    )
    gap = 2 * mm
    unit = (CONTENT_W - 2 * gap) / 7
    n_body = max(len(left_rows), len(mid_rows))

    # MSIA 卡片内容 (编号 + 平均分, 跨行垂直居中)
    msia_content = Paragraph(
        f'<font color="#8c8c8c" size="8">MSIA No.</font><br/>'
        f'<font size="14"><b>{_escape(str(report["msia_no"]))}</b></font><br/>'
        f'<font color="#8c8c8c" size="8">MSIA Result</font><br/>'
        f'<font size="13" color="{result_color}"><b>{_escape(report.get("msia_result", "")) or "None"}</b></font>',
        st["msia"],
    )

    # 标题行: [左标题, 间隔, 中标题, 间隔, MSIA标题]
    data: List[List[Any]] = [[
        Paragraph("<b>Project Key Data</b>", st["panel_title"]), "",
        Paragraph("<b>Milestones</b>", st["panel_title"]), "",
        Paragraph("<b>MSIA</b>", st["panel_title"]),
    ]]
    # 数据行: 左/中面板逐行排布; MSIA 内容放在首个数据行并 SPAN 到末行
    for i in range(n_body):
        left_cell = _kv_para(left_rows[i][0], left_rows[i][1], st) if i < len(left_rows) else ""
        mid_cell = _kv_para(mid_rows[i][0], mid_rows[i][1], st) if i < len(mid_rows) else ""
        data.append([left_cell, "", mid_cell, "", msia_content if i == 0 else ""])

    tbl = Table(data, colWidths=[3 * unit, gap, 3 * unit, gap, unit])
    tbl.setStyle(TableStyle([
        # MSIA 内容跨全部数据行, 垂直居中
        ("SPAN", (4, 1), (4, -1)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("VALIGN", (4, 1), (4, -1), "MIDDLE"),
        # 三个面板标题条 (蓝底白字)
        ("BACKGROUND", (0, 0), (0, 0), _PDF_BLUE),
        ("BACKGROUND", (2, 0), (2, 0), _PDF_BLUE),
        ("BACKGROUND", (4, 0), (4, 0), _PDF_BLUE),
        ("LINEBELOW", (0, 0), (0, 0), 0.75, _PDF_BORDER),
        ("LINEBELOW", (2, 0), (2, 0), 0.75, _PDF_BORDER),
        ("LINEBELOW", (4, 0), (4, 0), 0.75, _PDF_BORDER),
        # 三个面板外框: 共享同一组行 -> 高度一致, 底边对齐
        ("BOX", (0, 0), (0, -1), 0.75, _PDF_BORDER),
        ("BOX", (2, 0), (2, -1), 0.75, _PDF_BORDER),
        ("BOX", (4, 0), (4, -1), 0.75, _PDF_BORDER),
        ("FONTNAME", (0, 0), (-1, -1), _CN_FONT),
        # 左/中面板内边距
        ("LEFTPADDING", (0, 0), (0, -1), 8),
        ("RIGHTPADDING", (0, 0), (0, -1), 6),
        ("LEFTPADDING", (2, 0), (2, -1), 8),
        ("RIGHTPADDING", (2, 0), (2, -1), 6),
        # MSIA 列内边距
        ("LEFTPADDING", (4, 0), (4, -1), 4),
        ("RIGHTPADDING", (4, 0), (4, -1), 4),
        # 间隔列零内边距
        ("LEFTPADDING", (1, 0), (1, -1), 0),
        ("RIGHTPADDING", (1, 0), (1, -1), 0),
        ("LEFTPADDING", (3, 0), (3, -1), 0),
        ("RIGHTPADDING", (3, 0), (3, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return tbl


def _hr_table(high_risk_issues: List[Dict[str, Any]], is_combined: bool, st: Dict[str, ParagraphStyle]) -> Table:
    """高风险区: 红框浅红底 (UI #ffa39e / #fff1f0), 每条问题整行完整显示"""
    if high_risk_issues:
        lines = []
        for hr in high_risk_issues:
            sev = (hr.get("severity") or hr.get("priority") or "H").upper()
            parts = [f'<font color="{_sev_color(sev)}"><b>[{sev}]</b></font> {_escape(hr["title"])}']
            if is_combined and hr.get("phase_code"):
                parts.append(f'<font color="#722ed1">[{_escape(hr["phase_code"])}]</font>')
            if hr.get("item_name"):
                parts.append(f'<font color="#8c8c8c">- {_escape(hr["item_name"])}</font>')
            parts.append(f'<font color="#8c8c8c">({_escape(hr["issue_no"])})</font>')
            lines.append(" ".join(parts))
        body = "<br/>".join(lines)
    else:
        body = '<font color="#8c8c8c">无高风险问题</font>'
    data = [
        [Paragraph('<font color="#cf1322"><b>High-risk comments (reviewer):</b></font>', st["small"])],
        [Paragraph(body, st["small"])],
    ]
    tbl = Table(data, colWidths=[CONTENT_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _PDF_HR_BG),
        ("BOX", (0, 0), (-1, -1), 0.75, _PDF_HR_BORDER),
        ("FONTNAME", (0, 0), (-1, -1), _CN_FONT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return tbl


def _item_table(items: List[Dict[str, Any]], st: Dict[str, ParagraphStyle]) -> Table:
    """检查项表格: Item 26% | Request 34% | Result 10% | Comments 30% (与 UI 列宽一致)
    Request 长文本自动换行; Comments 每条问题独立整行, 完整展开不截断"""
    cols = [CONTENT_W * 0.26, CONTENT_W * 0.34, CONTENT_W * 0.10, CONTENT_W * 0.30]
    rows = [[
        Paragraph("<b>Item</b>", st["th"]),
        Paragraph("<b>Request</b>", st["th"]),
        Paragraph("<b>Result</b>", st["th"]),
        Paragraph("<b>Comments</b>", st["th"]),
    ]]
    for row in items:
        item_html = _escape(row["item_name"])
        request_html = _escape(row.get("request") or "") or '<font color="#bfbfbf">-</font>'
        if row.get("result"):
            result_html = f'<font color="{_score_text_color(row.get("score"))}"><b>{row["result"]}</b></font>'
        else:
            result_html = '<font color="#bfbfbf">-</font>'
        if row.get("issues"):
            comment_parts = []
            for iss in row["issues"]:
                sev = (iss.get("severity") or iss.get("priority") or "?").upper()
                comment_parts.append(
                    f'<font color="{_sev_color(sev)}"><b>[{sev}]</b></font> '
                    f'{_escape(iss["title"])} <font color="#8c8c8c">({_escape(iss["issue_no"])})</font>'
                )
            comment_html = "<br/>".join(comment_parts)
        else:
            comment_html = '<font color="#bfbfbf">-</font>'
        rows.append([
            Paragraph(item_html, st["body"]),
            Paragraph(request_html, st["small"]),
            Paragraph(result_html, st["body"]),
            Paragraph(comment_html, st["small"]),
        ])
    tbl = Table(rows, colWidths=cols, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _PDF_TH_BG),
        ("FONTNAME", (0, 0), (-1, -1), _CN_FONT),
        ("GRID", (0, 0), (-1, -1), 0.5, _PDF_TABLE_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return tbl


def _footer_table(reviewers: List[str], place: str, reviewees: str, date: str, st: Dict[str, ParagraphStyle]) -> Table:
    """尾部四栏: Reviewers | Review place | Reviewees | Date (UI 3fr:2.4fr:2.2fr:2fr)"""
    gap = 2 * mm
    unit = (CONTENT_W - 3 * gap) / 9.6
    cells = [
        (3.0, "Reviewers:", " / ".join(reviewers) if reviewers else ""),
        (2.4, "Review place:", place or ""),
        (2.2, "Reviewees:", reviewees or ""),
        (2.0, "Date:", date or ""),
    ]
    inner_tables: List[Any] = []
    widths: List[float] = []
    for i, (fr, label, value) in enumerate(cells):
        w = fr * unit
        widths.append(w)
        data = [
            [Paragraph(f'<font color="#8c8c8c" size="8">{_escape(label)}</font>', st["small"])],
            [Paragraph(_escape(value) if value else "-", st["body"])],
        ]
        t = Table(data, colWidths=[w])
        t.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.75, _PDF_BORDER),
            ("FONTNAME", (0, 0), (-1, -1), _CN_FONT),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        inner_tables.append(t)
        if i < len(cells) - 1:
            inner_tables.append("")
            widths.append(gap)
    outer = Table([inner_tables], colWidths=widths)
    outer.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return outer


def _note_table(st: Dict[str, ParagraphStyle]) -> Table:
    """底部说明区 (对应 UI info Alert)"""
    text = (
        "Request 列为该检查项的审核标准要求 (100% 档评分描述); Result 列为检查项最新评分 (未评分为空); "
        "Comments 列为该检查项下审核员登记的问题; Reviewers 为参与评审 (提交问题/评分) 的用户; "
        "Date 为最后一次提交问题或评分的时间。"
    )
    tbl = Table([[Paragraph(text, st["note"])]], colWidths=[CONTENT_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _PDF_NOTE_BG),
        ("BOX", (0, 0), (-1, -1), 0.75, _PDF_NOTE_BORDER),
        ("FONTNAME", (0, 0), (-1, -1), _CN_FONT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return tbl


def _phase_header(sr: Dict[str, Any], st: Dict[str, ParagraphStyle]) -> Paragraph:
    """合并报告阶段头: 蓝色阶段号 + 平均分 (对应 UI Tag + 平均分)"""
    if sr.get("msia_result"):
        color = _result_color(sr["msia_result"])
        avg = f'&nbsp;&nbsp;<font color="{color}">平均分: {_escape(sr["msia_result"])}</font>'
    else:
        avg = ""
    return Paragraph(f'<font color="#1677ff"><b>{_escape(sr["phase_code"])}</b></font>{avg}', st["phase"])


def _title_block(report: Dict[str, Any], st: Dict[str, ParagraphStyle]) -> List[Any]:
    """标题区: 主标题 + 副标题 (UI 居中样式)"""
    return [
        Paragraph("Manufacturing System Implementation Assessment Report", st["title"]),
        Paragraph(f'{_escape(report["phase_code"])} Review Report', st["subtitle"]),
        Spacer(1, 3 * mm),
    ]


def generate_phase_report_pdf(report: Dict[str, Any]) -> bytes:
    """单阶段报告 PDF (排版与前端报告弹窗 UI 一致, 内容完整展开不截断)"""
    phase_code = report["phase_code"]
    st = _pdf_styles()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"MSIA Assessment Report - {phase_code}",
    )

    elements: List[Any] = []
    # 标题区
    elements.extend(_title_block(report, st))
    # 头部三栏: Project Key Data | Milestones | MSIA
    elements.append(_header_table(report, False, st))
    elements.append(Spacer(1, 3 * mm))
    # 高风险区
    elements.append(_hr_table(report["high_risk_issues"], False, st))
    elements.append(Spacer(1, 3 * mm))
    # 检查项表格 (完整展开)
    elements.append(_item_table(report["items"], st))
    elements.append(Spacer(1, 3 * mm))
    # 尾部四栏
    elements.append(_footer_table(report["reviewers"], report["review_place"], report["reviewees"], report["date"], st))
    elements.append(Spacer(1, 3 * mm))
    # 底部说明
    elements.append(_note_table(st))

    doc.build(elements)
    logger.info(
        "生成阶段审核报告 PDF: plan={} phase={} items={}",
        report["plan_id"], phase_code, len(report["items"]),
    )
    return buffer.getvalue()


def build_combined_report(
    db: Session,
    settings: Settings,
    plan_id: str,
    phase_codes: list[str],
) -> Dict[str, Any]:
    """构建多阶段合并审核报告 (MSIA1+MSIA2+MSIA3 汇总)

    - 头部 (Project Key Data + Milestones) 合并: 取第一个阶段的项目信息 + 三个阶段的计划/实际日期
    - High-risk comments 合并: 三个阶段的所有高风险问题汇总
    - 检查项表格: 按阶段竖直叠加, 每个阶段保留独立表头和尾部 (Reviewers/Review place/Reviewees/Date)
    - MSIA Result: 三个阶段各自平均分取算数平均
    """
    plan_id = str(plan_id)
    sub_reports: List[Dict[str, Any]] = []
    for code in phase_codes:
        try:
            r = build_phase_report(db, settings, plan_id, code)
            sub_reports.append(r)
        except Exception as exc:
            logger.warning("合并报告: 构建阶段 {} 报告失败: {}", code, exc)

    if not sub_reports:
        return {
            "plan_id": plan_id,
            "phase_code": "+".join(phase_codes),
            "msia_no": "+".join(_phase_no(c) for c in phase_codes),
            "msia_result": "",
            "project": {"name": "", "no": "", "type": "", "cmc_ame": "", "plant_me": "", "plant": "", "line": "", "supplier": ""},
            "milestones": {},
            "reviewers": [],
            "review_place": "",
            "reviewees": "",
            "date": "",
            "high_risk_issues": [],
            "items": [],
            "sub_reports": [],
        }

    # 合并头部: 项目信息取第一个, 里程碑取第一个阶段 (项目级数据, 各阶段一致)
    first = sub_reports[0]
    milestones: Dict[str, str] = dict(first.get("milestones", {}))

    # 合并高风险问题
    high_risk: List[Dict[str, Any]] = []
    for sr in sub_reports:
        for hr in sr.get("high_risk_issues", []):
            hr["phase_code"] = sr["phase_code"]
            high_risk.append(hr)

    # 合并 Reviewers (去重)
    reviewers_set: list[str] = []
    for sr in sub_reports:
        for r in sr.get("reviewers", []):
            if r not in reviewers_set:
                reviewers_set.append(r)

    # Reviewees / Date
    reviewees = first.get("reviewees", "")
    all_dates: List[str] = []
    for sr in sub_reports:
        if sr.get("date"):
            all_dates.append(sr["date"])
    report_date = max(all_dates) if all_dates else ""

    # MSIA Result: 三个阶段平均分的算数平均
    phase_avg_scores: List[float] = []
    for sr in sub_reports:
        items = sr.get("items", [])
        scores = [row["score"] for row in items if row.get("score") is not None]
        if scores:
            phase_avg_scores.append(sum(scores) / len(scores))
    if phase_avg_scores:
        combined_result = sum(phase_avg_scores) / len(phase_avg_scores)
        msia_result = f"{combined_result * 100:.1f}%"
    else:
        msia_result = ""

    return {
        "plan_id": plan_id,
        "phase_code": "+".join(phase_codes),
        "msia_no": "+".join(_phase_no(c) for c in phase_codes),
        "msia_result": msia_result,
        "project": first.get("project", {}),
        "milestones": milestones,
        "reviewers": reviewers_set,
        "review_place": "",
        "reviewees": reviewees,
        "date": report_date,
        "high_risk_issues": high_risk,
        "items": [],  # 合并模式不使用扁平 items, 用 sub_reports
        "sub_reports": sub_reports,
    }


def generate_combined_report_pdf(report: Dict[str, Any]) -> bytes:
    """合并报告 PDF (排版与前端合并报告弹窗 UI 一致, 各阶段竖直叠加, 内容完整展开)"""
    sub_reports = report.get("sub_reports", [])
    phase_codes = report["phase_code"]
    st = _pdf_styles()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"MSIA Assessment Report - {phase_codes}",
    )

    elements: List[Any] = []
    # 标题区
    elements.extend(_title_block(report, st))
    # 头部三栏 (合并模式: Milestones 列出各阶段 plan/actual)
    elements.append(_header_table(report, True, st))
    elements.append(Spacer(1, 3 * mm))
    # 合并高风险区 (带阶段标识)
    elements.append(_hr_table(report["high_risk_issues"], True, st))
    elements.append(Spacer(1, 3 * mm))

    # 各阶段: 阶段头 + 检查项表格 + 尾部四栏 (与 UI 一致, 表格内容完整展开)
    for sr in sub_reports:
        elements.append(_phase_header(sr, st))
        elements.append(Spacer(1, 1.5 * mm))
        elements.append(_item_table(sr["items"], st))
        elements.append(Spacer(1, 2 * mm))
        elements.append(_footer_table(sr["reviewers"], sr["review_place"], sr["reviewees"], sr["date"], st))
        elements.append(Spacer(1, 4 * mm))

    # 底部说明
    elements.append(_note_table(st))

    doc.build(elements)
    logger.info("生成合并审核报告 PDF: plan={} phases={} sub_reports={}", report["plan_id"], phase_codes, len(sub_reports))
    return buffer.getvalue()


def _escape(text: str) -> str:
    """reportlab Paragraph XML 转义"""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
