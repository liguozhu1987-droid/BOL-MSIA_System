"""阶段评审检查项路由 (MSIA Report MSIA1~5 评审清单)

接口前缀: /api/phase-review-items
"""
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.check_item import CheckItem
from app.models.phase_review_item import PhaseReviewItem
from app.models.user import User

router = APIRouter(prefix="/api/phase-review-items", tags=["阶段评审检查项"])


def _extract_maturity_100_desc(score_options_json: str | None) -> str:
    """从 CheckItem.ScoreOptions JSON 中提取 100% 档的 desc"""
    if not score_options_json:
        return ""
    try:
        opts = json.loads(score_options_json)
        if not isinstance(opts, list):
            return ""
        for opt in opts:
            if isinstance(opt, dict) and opt.get("score") == 1.0:
                return str(opt.get("desc") or "")
        return ""
    except (json.JSONDecodeError, TypeError):
        return ""


def _extract_all_score_options(score_options_json: str | None) -> list[dict] | None:
    """从 CheckItem.ScoreOptions JSON 中提取全部 7 档评分描述

    返回格式: [{score: 0.0, desc: "..."}, {score: 0.25, desc: "..."}, ...]
    若无数据返回 None
    """
    if not score_options_json:
        return None
    try:
        opts = json.loads(score_options_json)
        if not isinstance(opts, list) or not opts:
            return None
        # 提取 score 和 desc, 过滤无效条目
        result = []
        for opt in opts:
            if isinstance(opt, dict) and "score" in opt:
                result.append({
                    "score": opt.get("score"),
                    "desc": str(opt.get("desc") or ""),
                })
        return result if result else None
    except (json.JSONDecodeError, TypeError):
        return None


def _normalize_name(name: str) -> str:
    """规范化名称用于模糊匹配: 去除所有非字母数字字符, 转小写"""
    if not name:
        return ""
    # 只保留字母和数字, 转小写
    s = re.sub(r"[^a-zA-Z0-9]", "", name).lower()
    return s


def _tokenize(name: str) -> set[str]:
    """将名称拆分为 token 集合 (小写, 去除空 token 和过短 token)"""
    if not name:
        return set()
    # 按非字母数字分割
    tokens = re.split(r"[^a-zA-Z0-9]+", name.lower())
    # 过滤空 token 和单字符 token (如 & 等)
    return {t for t in tokens if len(t) >= 2}


def _fuzzy_match_desc(
    target_name: str,
    check_items: list[tuple[str, str, str]],
) -> str:
    """模糊匹配: 在 [(name, normalized_name, desc)] 中找最佳匹配

    匹配策略 (按优先级):
      1. 精确匹配 (原始名称)
      2. 规范化后精确匹配
      3. 一方包含另一方 (规范化后)
      4. Token 集合匹配 (目标名称的所有 token 都在候选名称中)
    """
    if not target_name:
        return ""
    target_norm = _normalize_name(target_name)
    target_tokens = _tokenize(target_name)

    # 1. 精确匹配
    for name, _, desc in check_items:
        if name == target_name:
            return desc

    # 2. 规范化后精确匹配
    for _, norm_name, desc in check_items:
        if norm_name == target_norm:
            return desc

    # 3. 模糊包含匹配 (一方包含另一方)
    for _, norm_name, desc in check_items:
        if not norm_name or not target_norm:
            continue
        if target_norm in norm_name or norm_name in target_norm:
            return desc

    # 4. Token 集合匹配 (目标名称所有 token 都在候选名称的 token 集合中)
    if target_tokens:
        for name, _, desc in check_items:
            candidate_tokens = _tokenize(name)
            if target_tokens.issubset(candidate_tokens):
                return desc

    return ""


@router.get("", summary="阶段评审检查项列表 (按 PhaseCode 过滤)")
def list_phase_review_items(
    phase_code: str = Query(..., description="阶段代码, 如 MSIA1"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """按阶段代码返回评审检查项清单 (来自 Report MSIA1~5 sheet)

    附加字段:
      - Maturity100Desc: 对应审核标准中 100% 评分档的描述要求
      - ScoreOptions: 本检查项专属 7 档评分标准 [{score, desc}, ...]
    (通过 PhaseCode + ItemName 模糊关联 CheckItem 表)
    """
    query = db.query(PhaseReviewItem).filter(
        PhaseReviewItem.PhaseCode == phase_code,
        PhaseReviewItem.IsDeleted == False,  # noqa: E712
    )
    query = query.order_by(PhaseReviewItem.Seq, PhaseReviewItem.SortOrder)
    items = query.all()

    # 批量查询 CheckItem, 构建 [(name, normalized_name, desc_100, score_options_list)]
    # 过滤已删除 + 已停用 (IsActive=False) 的审核条款: 停用后不进入项目评审打分场景
    check_items_data = (
        db.query(CheckItem.Id, CheckItem.Name, CheckItem.ScoreOptions, CheckItem.IsActive)
        .filter(
            CheckItem.PhaseCode == phase_code,
            CheckItem.IsDeleted == False,  # noqa: E712
        )
        .all()
    )
    # 仅启用 (IsActive=True) 的 CheckItem 才进入打分场景候选池
    active_check_items_data = [row for row in check_items_data if row.IsActive is not False]
    # 按 CheckItemId 索引: id → (desc_100, all_score_options)
    check_item_by_id: dict[int, tuple[str, list[dict] | None]] = {}
    # 构建模糊匹配用的列表: (name, norm_name, desc_100, all_score_options)
    check_items = []
    for cid, name, score_options, _is_active in active_check_items_data:
        d100 = _extract_maturity_100_desc(score_options)
        allopts = _extract_all_score_options(score_options)
        check_item_by_id[cid] = (d100, allopts)
        check_items.append((name, _normalize_name(name), d100, allopts))

    # 自愈过滤: 剔除 CheckItemId 指向已删除/不存在/已停用 审核标准的孤儿条目
    # (确保审核标准库删除或停用后评审清单在任何情况下都不再显示, 不依赖删除时的联动是否执行)
    items = [
        it for it in items
        if not (it.CheckItemId is not None and it.CheckItemId not in check_item_by_id)
    ]

    # 返回字典列表, 附加 Maturity100Desc 和 ScoreOptions (模糊匹配)
    result: list[dict[str, Any]] = []
    for display_seq, it in enumerate(items, start=1):
        row = {c.name: getattr(it, c.name) for c in it.__table__.columns}
        # 模糊匹配: 找到对应的 CheckItem, 提取 100% 描述和全部评分选项
        matched_desc = ""
        matched_score_options = None
        target_norm = _normalize_name(it.ItemName)
        target_tokens = _tokenize(it.ItemName)

        # 优先: 通过 CheckItemId 显式关联 (审核标准模块联动产生的条目)
        explicit_match = False
        if it.CheckItemId and it.CheckItemId in check_item_by_id:
            matched_desc, matched_score_options = check_item_by_id[it.CheckItemId]
            explicit_match = True

        if not explicit_match:
            # 1. 精确匹配
            # 2. 规范化匹配
            # 3. 包含匹配
            # 4. Token 匹配
            for name, norm_name, desc_100, all_opts in check_items:
                if name == it.ItemName or norm_name == target_norm:
                    matched_desc = desc_100
                    matched_score_options = all_opts
                    break
            if not matched_desc:
                for _, norm_name, desc_100, all_opts in check_items:
                    if norm_name and target_norm and (target_norm in norm_name or norm_name in target_norm):
                        matched_desc = desc_100
                        matched_score_options = all_opts
                        break
            if not matched_desc and target_tokens:
                for name, _, desc_100, all_opts in check_items:
                    candidate_tokens = _tokenize(name)
                    if target_tokens.issubset(candidate_tokens):
                        matched_desc = desc_100
                        matched_score_options = all_opts
                        break

        row["Maturity100Desc"] = matched_desc
        row["ScoreOptions"] = matched_score_options
        # 显示序号: 按当前排序连续编号 1..N (数据库 Seq 可能因删除条目留有空洞)
        row["Seq"] = display_seq
        result.append(row)
    return result


@router.get("/{item_id}", summary="阶段评审检查项详情")
def get_phase_review_item(item_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    item = db.query(PhaseReviewItem).filter(
        PhaseReviewItem.Id == item_id,
        PhaseReviewItem.IsDeleted == False,  # noqa: E712
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="检查项不存在")
    return item
