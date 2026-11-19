"""邮件服务

- 通过内网 SMTP 发送邮件
- 支持 SSL (SMTP_SSL) 与明文 (SMTP) 两种模式
- 失败重试 (默认 3 次, 指数退避)
- 每封邮件写入 CN_AME_MISA_EmailLog 日志表
- 双格式邮件: 纯文本 + HTML (降低垃圾邮件误判率)

反垃圾邮件优化:
  - 添加 Message-ID / Reply-To / Auto-Submitted 等标准头
  - 同时提供 text/plain 和 text/html 两种 MIME 部分
  - HTML 使用表格布局 + 内联样式 (兼容各邮件客户端)
  - 主题简洁专业, 避免过多特殊符号
  - 不在邮件正文中暴露服务器内部信息
"""
import re
import smtplib
import threading
import time
from datetime import datetime, timezone
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from typing import Dict, List, Optional, Tuple

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.email_log import EmailLog
from app.utils.time import now_cst

# ============================================================
# 邮件模板: {key: (subject_template, text_body_template, html_body_template)}
# ============================================================

# 问题类邮件统一信息块 (新格式)
# 上下文由 app.services.issue_deadline_service.build_issue_email_context(s) 构建:
#   评审日期 = 阶段实际审核完成日期 (HRDB 填报值)
#   整改完成日期 = Deadline (阶段实际审核完成日期 + 10 自然日)
_ISSUE_INFO_BLOCK = (
    "问题编号：{issue_no}\n"
    "评审项目：{project_name}\n"
    "评审阶段：{phase_code}\n"
    "问题项：{item_display}\n"
    "问题描述：{title}\n"
    "严重等级：{severity}\n"
    "评审日期：{review_date}\n"
    "整改完成日期：{deadline}"
)

EMAIL_TEMPLATES: Dict[str, Tuple[str, str, str]] = {
    "issue_assigned": (
        "MSIA 通知: 您有新分派的问题 - {title}",
        # 纯文本
        "您好,\n\n"
        "您被分派了以下问题:\n\n"
        + _ISSUE_INFO_BLOCK + "\n\n"
        "请在整改完成日期前完成整改并申请关闭。\n"
        "访问地址: {system_url}\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        # HTML
        None,  # 使用通用 HTML 模板自动生成
    ),
    "issue_overdue": (
        "MSIA 通知: 问题已逾期 - {title}",
        "您好,\n\n"
        "以下问题已超过整改完成日期, 请尽快处理:\n\n"
        + _ISSUE_INFO_BLOCK + "\n\n"
        "当前状态: {status}\n"
        "访问地址: {system_url}\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        None,
    ),
    "issue_verified": (
        "MSIA 通知: 问题已验证通过 - {title}",
        "您好,\n\n"
        "您提交的问题已验证通过:\n\n"
        + _ISSUE_INFO_BLOCK + "\n\n"
        "验证意见: {verification_comments}\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        None,
    ),
    "issue_maintenance_reminder": (
        "MSIA 通知: 请及时维护问题原因与措施 - {title}",
        "您好 {owner_name},\n\n"
        "您负责的以下问题即将到达整改完成日期, "
        "但尚未维护根本原因 / 纠正措施:\n\n"
        + _ISSUE_INFO_BLOCK + "\n\n"
        "距整改完成日期剩余 {days_to_deadline} 天 (负数表示已过期), "
        "请尽快登录 MSIA 系统维护整改方案并申请关闭。\n"
        "访问地址: {system_url}\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        None,
    ),
    "issue_reopened": (
        "MSIA 通知: 问题已重开 - {title}",
        "您好 {owner_name},\n\n"
        "您负责的以下问题已被审核员重开, 需继续整改:\n\n"
        + _ISSUE_INFO_BLOCK + "\n\n"
        "重开人: {reopen_by}\n"
        "重开原因: {reason}\n\n"
        "请登录系统继续维护整改信息, 完成后再次申请关闭。\n"
        "访问地址: {system_url}\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        None,
    ),
    "review_submitted": (
        "MSIA 通知: 审核记录已提交 - {item_name}",
        "您好,\n\n"
        "审核记录已提交, 等待确认:\n\n"
        "项目: {project_name}\n"
        "阶段: {phase_code}\n"
        "检查项: {item_name}\n"
        "评分: {score}\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        None,
    ),
    "review_confirmed": (
        "MSIA 通知: 审核记录已确认 - {item_name}",
        "您好,\n\n"
        "您的审核记录已被确认:\n\n"
        "项目: {project_name}\n"
        "阶段: {phase_code}\n"
        "检查项: {item_name}\n"
        "评分: {score}\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        None,
    ),
    "user_sync_failed": (
        "MSIA 通知: 用户同步失败",
        "管理员您好,\n\n"
        "用户同步任务执行失败, 请检查系统日志。\n\n"
        "批次号: {batch_id}\n"
        "错误信息: {error_message}\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        None,
    ),
    "escalation_level1": (
        "MSIA 问题逾期提醒 (第 {remind_count} 次) - {title}",
        "您好 {owner_name},\n\n"
        "您负责的以下问题已逾期 {overdue_days} 天 ({overdue_hours} 小时), 整改措施仍未完成:\n\n"
        + _ISSUE_INFO_BLOCK + "\n\n"
        "提醒规则: 逾期处理完成前, 系统将每 {remind_interval_hours} 小时提醒一次。\n"
        "请尽快登录系统完成整改并申请关闭, 避免问题升级至部门经理。\n"
        "访问地址: {system_url}\n\n"
        "──────────────────────────────\n"
        "{escalation_flow}\n"
        "──────────────────────────────\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        None,
    ),
    "escalation_level2": (
        "MSIA 问题升级提醒 (部门经理, 第 {remind_count} 次) - {title}",
        "部门经理您好,\n\n"
        "以下问题已逾期 {overdue_days} 天 ({overdue_hours} 小时), 责任人 {owner_name} 仍未完成整改, 现升级至部门经理级别:\n\n"
        + _ISSUE_INFO_BLOCK + "\n\n"
        "责任人: {owner_name}\n"
        "工厂: {plant}\n\n"
        "提醒规则: 责任人处理完成前, 系统将每 {remind_interval_hours} 小时提醒一次。\n"
        "请协助督促责任人尽快完成整改并关闭问题。\n"
        "访问地址: {system_url}\n\n"
        "──────────────────────────────\n"
        "{escalation_flow}\n"
        "──────────────────────────────\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        None,
    ),
    "escalation_level3": (
        "MSIA 问题升级提醒 (AME Director, 第 {remind_count} 次) - {title}",
        "AME Director 您好,\n\n"
        "以下问题已逾期 {overdue_days} 天 ({overdue_hours} 小时), 责任人 {owner_name} 仍未完成整改, 现升级至 AME Director 级别, 请立即介入处理:\n\n"
        + _ISSUE_INFO_BLOCK + "\n\n"
        "责任人: {owner_name}\n"
        "工厂: {plant}\n\n"
        "提醒规则: 责任人处理完成前, 系统将每 {remind_interval_hours} 小时提醒一次。\n"
        "此问题已长期逾期未关闭, 请安排专人跟进。\n"
        "访问地址: {system_url}\n\n"
        "──────────────────────────────\n"
        "{escalation_flow}\n"
        "──────────────────────────────\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        None,
    ),
    "issue_closure_requested": (
        "MSIA 通知: 问题关闭申请待审批 - {title}",
        "您好,\n\n"
        "责任人 {owner_name} 已提交以下问题的关闭申请, 请尽快登录系统检查问题是否可以关闭:\n\n"
        + _ISSUE_INFO_BLOCK + "\n\n"
        "关闭申请时间: {closure_requested_at}\n"
        "申请人: {requester_name}\n\n"
        "访问地址: {system_url}\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        None,
    ),
    "issue_closure_rejected": (
        "MSIA 通知: 问题关闭申请被驳回 - {title}",
        "您好 {owner_name},\n\n"
        "您提交的以下问题关闭申请已被驳回, 请根据审核意见继续整改:\n\n"
        + _ISSUE_INFO_BLOCK + "\n\n"
        "审批人: {reviewer_name}\n"
        "审核意见: {verification_comments}\n\n"
        "请登录系统继续维护整改方案, 完成后再次申请关闭。\n"
        "访问地址: {system_url}\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        None,
    ),
    "issue_closure_approved": (
        "MSIA 通知: 问题已关闭 - {title}",
        "您好 {owner_name},\n\n"
        "您提交的以下问题关闭申请已通过审批, 问题已关闭:\n\n"
        + _ISSUE_INFO_BLOCK + "\n\n"
        "审批人: {reviewer_name}\n"
        "关闭时间: {closed_at}\n"
        "审核意见: {verification_comments}\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        None,
    ),
    "monthly_review_reminder": (
        "MSIA 月度提醒: {month}月待审核项目 ({count}项)",
        "各位好,\n\n"
        "本月 ({year}年{month}月) 全部 MSIA 待审核项目如下, 请各项目负责人提前安排准备:\n\n"
        "{project_lines}\n\n"
        "提示: 请各项目负责人及时将审核相关资料上传至上述项目标注的 CoE Teams 共享文件目录, "
        "确保评审时资料完整可用。\n"
        "访问地址: {system_url}\n\n"
        "此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。",
        None,
    ),
}


# ============================================================
# HTML 邮件模板 (内联样式, 兼容 Outlook / 网页邮箱 / 移动端)
# ============================================================

def _build_html_email(
    subject: str,
    body_text: str,
    system_url: str = "",
) -> str:
    """将纯文本正文转为专业 HTML 邮件

    采用表格布局 + 内联样式, 确保在各邮件客户端中一致渲染。
    """
    import html as _html

    # 将纯文本转为 HTML 安全文本 (保留换行)
    safe_body = _html.escape(body_text)
    # 将 "访问地址: xxx" 转为可点击链接
    if system_url:
        safe_body = safe_body.replace(
            f"访问地址: {system_url}",
            f'访问地址: <a href="{_html.escape(system_url)}" style="color:#0050D3;text-decoration:none;">{_html.escape(system_url)}</a>',
        )
    # 换行转 <br>
    safe_body = safe_body.replace("\n", "<br>\n")

    return f"""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_html.escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background-color:#F0F5FA;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#F0F5FA;padding:24px 0;">
<tr>
<td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#FFFFFF;border-radius:4px;overflow:hidden;box-shadow:0 2px 8px rgba(0,80,211,0.06);">

<!-- 顶部色条 -->
<tr>
<td style="height:4px;background:linear-gradient(90deg,#0050D3 0%,#00B4D8 100%);font-size:0;line-height:0;">&nbsp;</td>
</tr>

<!-- 标题区 -->
<tr>
<td style="padding:24px 32px 16px 32px;border-bottom:1px solid #EEF2F7;">
<div style="font-size:18px;font-weight:600;color:#0F172A;letter-spacing:0.3px;">MSIA 审核管理系统</div>
<div style="font-size:12px;color:#64748B;margin-top:4px;">Manufacturing System Implementation Audit</div>
</td>
</tr>

<!-- 正文区 -->
<tr>
<td style="padding:24px 32px;font-size:14px;line-height:1.7;color:#334155;">
{safe_body}
</td>
</tr>

<!-- 底部区 -->
<tr>
<td style="padding:16px 32px 24px 32px;border-top:1px solid #EEF2F7;">
<div style="font-size:11px;color:#94A3B8;line-height:1.6;">
此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。<br>
如需帮助, 请联系系统管理员。
</div>
</td>
</tr>

</table>
</td>
</tr>
</table>
</body>
</html>"""


class EmailService:
    """邮件发送服务

    SMTP 配置支持在线修改:
    - __init__ 从 config.ini 读取默认值 (启动时)
    - _resolve_smtp_config 从数据库 SystemSetting 读取最新配置 (每次发送时)
    - 修改后下次发送邮件立即生效, 无需重启服务
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        # config.ini 默认值 (数据库无记录时回退使用)
        self.host = settings.EMAIL_SMTP_HOST
        self.port = settings.EMAIL_SMTP_PORT
        self.enable_ssl = settings.EMAIL_ENABLE_SSL
        self.username = settings.EMAIL_SMTP_USERNAME
        self.password = settings.EMAIL_SMTP_PASSWORD
        self.from_address = settings.EMAIL_FROM_ADDRESS
        self.from_display = settings.EMAIL_FROM_DISPLAY_NAME
        self.timeout_ms = settings.EMAIL_TIMEOUT_MS

    # ---- 短窗口防重 (类级共享, 跨请求实例生效) ----
    # 同一 (模板, 关联对象, 归一化主题) 的邮件在窗口内只发送一次,
    # 防止并发请求 / 重复触发导致同一邮箱收到多封重复邮件。
    _DEDUP_WINDOW_SECONDS: float = 60.0
    _recent_send_keys: Dict[str, float] = {}
    _recent_send_lock = threading.Lock()

    @staticmethod
    def _normalize_subject_for_dedup(subject: str) -> str:
        """归一化主题用于防重比较: 去除 [TEST] / [测试副本] 等场景前缀"""
        s = subject or ""
        while True:
            new = re.sub(r"^(\[TEST\]\s*|\[测试副本\]\s*)", "", s)
            if new == s:
                break
            s = new
        return s.strip()

    def _dedup_check_and_register(self, key: str) -> bool:
        """检查并登记防重键

        Returns:
            True: 窗口内已发送过 (重复, 应跳过)
            False: 首次发送 (已登记, 发送失败时会撤销登记以便重试)
        """
        now = time.time()
        with EmailService._recent_send_lock:
            # 顺带清理过期条目, 防止字典无限增长
            expired = [
                k for k, ts in EmailService._recent_send_keys.items()
                if now - ts > EmailService._DEDUP_WINDOW_SECONDS
            ]
            for k in expired:
                EmailService._recent_send_keys.pop(k, None)
            last_ts = EmailService._recent_send_keys.get(key)
            if last_ts is not None and now - last_ts < EmailService._DEDUP_WINDOW_SECONDS:
                # 刷新时间, 避免连续重复请求穿透窗口
                EmailService._recent_send_keys[key] = now
                return True
            EmailService._recent_send_keys[key] = now
            return False

    @staticmethod
    def _dedup_unregister(key: str) -> None:
        """撤销防重登记 (发送失败时调用, 保证重试机制可用)"""
        with EmailService._recent_send_lock:
            EmailService._recent_send_keys.pop(key, None)

    def _resolve_smtp_config(self, db: Optional[Session]) -> dict:
        """从数据库读取 SMTP 配置 (每次发送邮件时调用)

        优先级: 数据库 SystemSetting > config.ini 默认值
        修改后立即生效, 无需重启服务。

        Returns:
            dict: {host, port, enable_ssl, username, password, from_address, from_display, timeout_ms}
        """
        config = {
            "host": self.host,
            "port": self.port,
            "enable_ssl": self.enable_ssl,
            "username": self.username,
            "password": self.password,
            "from_address": self.from_address,
            "from_display": self.from_display,
            "timeout_ms": self.timeout_ms,
        }
        if db is None:
            return config
        try:
            from app.services.system_config_service import (
                get_string, get_int, get_bool,
            )
            host = get_string(db, "smtp_host")
            if host:
                config["host"] = host
            port = get_int(db, "smtp_port")
            if port:
                config["port"] = port
            enable_ssl = get_bool(db, "smtp_enable_ssl")
            if enable_ssl is not None:
                config["enable_ssl"] = enable_ssl
            username = get_string(db, "smtp_username")
            if username is not None:
                config["username"] = username
            password = get_string(db, "smtp_password")
            if password is not None:
                config["password"] = password
            from_address = get_string(db, "email_from_address")
            if from_address:
                config["from_address"] = from_address
            from_display = get_string(db, "email_from_display_name")
            if from_display:
                config["from_display"] = from_display
            timeout_ms = get_int(db, "email_timeout_ms")
            if timeout_ms:
                config["timeout_ms"] = timeout_ms
        except Exception:
            # 数据库查询失败时使用 config.ini 默认值, 保证业务不中断
            pass
        return config

    # ---- 模板渲染 ----

    def render_template(self, template_key: str, context: Dict[str, object]) -> Tuple[str, str, str]:
        """根据模板键与上下文渲染邮件主题、纯文本正文、HTML 正文

        Args:
            template_key: 模板键 (见 EMAIL_TEMPLATES)
            context: 占位符上下文字典
        Returns:
            (subject, text_body, html_body)
        Raises:
            KeyError: 模板键不存在
        """
        if template_key not in EMAIL_TEMPLATES:
            raise KeyError(f"未知邮件模板: {template_key}")
        subject_tpl, text_tpl, html_tpl = EMAIL_TEMPLATES[template_key]
        # 用 str() 兜底, 避免 None 占位导致 KeyError
        safe_ctx = {k: ("" if v is None else str(v)) for k, v in context.items()}
        subject = subject_tpl.format(**safe_ctx)
        text_body = text_tpl.format(**safe_ctx)
        # 从 context 中提取 system_url (如果有)
        system_url = safe_ctx.get("system_url", "")
        if html_tpl:
            html_body = html_tpl.format(**safe_ctx)
        else:
            html_body = _build_html_email(subject, text_body, system_url)
        return subject, text_body, html_body

    # ---- 发送 ----

    @staticmethod
    def _fill_send_result(
        result: Optional[Dict[str, object]],
        log_id: Optional[int],
        actual_to: List[str],
        original_to: List[str],
        is_test_mode: bool,
    ) -> None:
        """填充邮件发送结果 (调用方传入 result dict 时用于获取发送详情)

        Keys:
            log_id: EmailLog.Id (无日志记录时为 None)
            actual_to: 实际发送收件人 (测试模式重定向后的测试邮箱)
            original_to: 原始收件人 (测试模式重定向前)
            is_test_mode: 本次发送是否处于测试模式
        """
        if result is None:
            return
        result["log_id"] = log_id
        result["actual_to"] = list(actual_to or [])
        result["original_to"] = list(original_to or [])
        result["is_test_mode"] = is_test_mode

    def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        db: Optional[Session] = None,
        template_key: Optional[str] = None,
        ref_type: Optional[str] = None,
        ref_id: Optional[int] = None,
        skip_dedup: bool = False,
        result: Optional[Dict[str, object]] = None,
    ) -> bool:
        """发送单封邮件 (含日志记录)

        Args:
            to: 收件人列表
            subject: 主题
            body: 正文 (纯文本, 将自动生成 HTML 版本)
            cc: 抄送列表
            db: 数据库会话, 用于写日志
            template_key: 模板键
            ref_type / ref_id: 关联业务对象
            skip_dedup: 跳过短窗口防重检查 (管理员手动重发时使用)
            result: 可选, 传出发送详情 (log_id/actual_to/original_to/is_test_mode)
        Returns:
            True 发送成功, False 失败

        通知模式:
            - production (生产模式): 邮件发送给真实收件人 (to/cc)
            - test (测试模式): 邮件重定向到 NOTIFICATION_TEST_RECIPIENTS,
              主题加 [TEST] 前缀, 正文末尾追加原收件人信息 (便于验证时识别)
        """
        if not to:
            logger.warning("邮件发送取消: 收件人为空")
            self._fill_send_result(result, None, [], [], False)
            return False

        # 收件人去重 (保持原顺序, 过滤空值)
        to = list(dict.fromkeys([t.strip() for t in to if t and t.strip()]))
        if cc:
            cc = list(dict.fromkeys([c.strip() for c in cc if c and c.strip()]))
        if not to:
            logger.warning("邮件发送取消: 收件人为空")
            self._fill_send_result(result, None, [], [], False)
            return False

        # 查询运行时通知模式 (数据库 SystemSetting 优先, 其次 config.ini 默认值)
        is_test_mode, test_recipients = self._resolve_notification_mode(db)

        # ---- 短窗口防重检查 ----
        # 同一 (模板, 关联对象, 归一化主题) 的邮件在窗口内只发送一次:
        # - 生产模式: 额外区分收件人 (发给不同人的邮件互不影响)
        # - 测试模式: 不区分收件人 (所有邮件重定向到同一测试邮箱,
        #   同类邮件即使原收件人不同也会变成重复邮件)
        normalized_subject = self._normalize_subject_for_dedup(subject)
        dedup_key = f"{template_key}|{ref_type}|{ref_id}|{normalized_subject}"
        if not is_test_mode:
            dedup_key += "|" + ",".join(sorted(to))
        is_duplicate = False if skip_dedup else self._dedup_check_and_register(dedup_key)

        # 测试模式: 重定向收件人 + 标识前缀 + 原收件人备注
        original_to = list(to)
        original_cc = list(cc) if cc else []
        if is_test_mode:
            if test_recipients:
                # 测试邮箱去重 (保持原顺序)
                test_recipients = list(dict.fromkeys(
                    [r.strip() for r in test_recipients if r and r.strip()]
                ))
                logger.warning(
                    "[通知测试模式] 邮件重定向: 原收件人={} 原抄送={} -> 测试邮箱={}",
                    original_to, original_cc, test_recipients,
                )
                to = test_recipients
                cc = []  # 测试模式不抄送原 cc, 避免泄露给真实用户
                subject = f"[TEST] {subject}"
                body = (
                    f"{body}\n\n"
                    f"---------- 测试模式说明 ----------\n"
                    f"此邮件为测试模式发送, 实际收件人已被替换为测试邮箱。\n"
                    f"原收件人: {', '.join(original_to)}\n"
                    f"原抄送: {', '.join(original_cc) if original_cc else '无'}\n"
                )
            else:
                logger.warning(
                    "[通知测试模式] 未配置测试邮箱, 邮件将不发送 (原收件人={})",
                    original_to,
                )
                self._dedup_unregister(dedup_key)
                self._fill_send_result(result, None, [], original_to, True)
                return False

        # 重复邮件: 记录日志后跳过 (返回 True, 视为已发送避免上层重试)
        if is_duplicate:
            logger.warning(
                "邮件防重: {}s 内已发送过相同邮件, 跳过本次发送 (主题='{}', 收件人={})",
                EmailService._DEDUP_WINDOW_SECONDS, subject, to,
            )
            log = self._create_log(to, cc, subject, body, template_key, ref_type, ref_id)
            log.Status = "skipped_duplicate"
            try:
                if db is not None:
                    db.add(log)
                    db.commit()
                else:
                    from app.db.session import SessionLocal

                    with SessionLocal() as session:
                        session.add(log)
                        session.commit()
            except Exception:
                logger.exception("邮件防重日志写入失败")
            self._fill_send_result(
                result, getattr(log, "Id", None), to, original_to, is_test_mode,
            )
            return True

        # 自动生成 HTML 版本
        html_body = _build_html_email(subject, body)

        log = self._create_log(to, cc, subject, body, template_key, ref_type, ref_id)
        # 测试模式: 记录原始收件人, 便于审计
        if is_test_mode and (original_to or original_cc):
            log.ErrorMessage = (
                f"[test-mode] original_to={','.join(original_to)}; "
                f"original_cc={','.join(original_cc) if original_cc else ''}"
            )[:2000]
        if db is not None:
            db.add(log)
            db.commit()
            db.refresh(log)
        else:
            from app.db.session import SessionLocal

            with SessionLocal() as session:
                session.add(log)
                session.commit()
                session.refresh(log)

        try:
            self._smtp_send(to, subject, body, html_body, cc, db)
            log.Status = "sent"
            log.SentAt = now_cst()
            logger.info("邮件发送成功 -> {} 主题='{}'", to, subject)
            ok = True
        except Exception as exc:
            # 发送失败: 撤销防重登记, 保证 send_with_retry 重试可用
            if not skip_dedup:
                self._dedup_unregister(dedup_key)
            log.Status = "failed"
            if not log.ErrorMessage:
                log.ErrorMessage = str(exc)[:2000]
            else:
                # 保留测试模式的原收件人信息, 追加错误信息
                log.ErrorMessage = (log.ErrorMessage + " | " + str(exc))[:2000]
            logger.exception("邮件发送失败 -> {}", to)
            ok = False

        if db is not None:
            db.add(log)
            db.commit()
        else:
            from app.db.session import SessionLocal

            with SessionLocal() as session:
                session.merge(log)
                session.commit()
        self._fill_send_result(
            result, getattr(log, "Id", None), to, original_to, is_test_mode,
        )
        return ok

    def send_with_retry(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        db: Optional[Session] = None,
        template_key: Optional[str] = None,
        ref_type: Optional[str] = None,
        ref_id: Optional[int] = None,
        skip_dedup: bool = False,
        result: Optional[Dict[str, object]] = None,
    ) -> bool:
        """带重试的邮件发送 (指数退避)

        result (可选): 传出发送详情, 保留最后一次尝试的结果
        (log_id/actual_to/original_to/is_test_mode, 见 send_email)
        """
        last_ok = False
        for attempt in range(1, max_retries + 1):
            ok = self.send_email(
                to, subject, body, cc=cc, db=db,
                template_key=template_key, ref_type=ref_type, ref_id=ref_id,
                skip_dedup=skip_dedup, result=result,
            )
            if ok:
                return True
            last_ok = ok
            if attempt < max_retries:
                wait = backoff_seconds * (2 ** (attempt - 1))
                logger.info("第 {} 次重试将在 {}s 后进行", attempt, wait)
                time.sleep(wait)
        return last_ok

    # ---- 内部 ----

    def _smtp_send(
        self,
        to: List[str],
        subject: str,
        body_text: str,
        body_html: str,
        cc: Optional[List[str]],
        db: Optional[Session] = None,
    ) -> None:
        """通过 SMTP 实际发送邮件 (双格式: 纯文本 + HTML)

        每次发送时从数据库读取最新 SMTP 配置, 修改后立即生效。
        """
        # 从数据库读取最新 SMTP 配置 (回退到 config.ini 默认值)
        cfg = self._resolve_smtp_config(db)

        msg = MIMEMultipart("alternative")
        # 标准邮件头
        msg["From"] = formataddr((str(Header(cfg["from_display"], "utf-8")), cfg["from_address"]))
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = Header(subject, "utf-8")
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=cfg["from_address"].split("@")[-1] if "@" in cfg["from_address"] else "localhost")
        msg["MIME-Version"] = "1.0"
        msg["Reply-To"] = cfg["from_address"]
        msg["Auto-Submitted"] = "auto-generated"
        msg["X-Auto-Response-Suppress"] = "All"
        msg["X-MSIA-System"] = "MSIA-Audit-v1.0"
        msg["Organization"] = "MSIA Audit System"

        # 纯文本版本 (放在第一个, 优先级低, 兼容旧客户端)
        text_part = MIMEText(body_text, "plain", "utf-8")
        msg.attach(text_part)

        # HTML 版本 (放在第二个, 优先级高, 现代客户端显示)
        html_part = MIMEText(body_html, "html", "utf-8")
        msg.attach(html_part)

        timeout = max(cfg["timeout_ms"] / 1000.0, 5.0)
        all_recipients = list(to) + (cc or [])

        if cfg["enable_ssl"]:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=timeout) as server:
                if cfg["username"]:
                    server.login(cfg["username"], cfg["password"])
                server.sendmail(cfg["from_address"], all_recipients, msg.as_string())
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=timeout) as server:
                server.ehlo()
                if cfg["username"]:
                    server.login(cfg["username"], cfg["password"])
                server.sendmail(cfg["from_address"], all_recipients, msg.as_string())

    def _create_log(
        self,
        to: List[str],
        cc: Optional[List[str]],
        subject: str,
        body: str,
        template_key: Optional[str],
        ref_type: Optional[str],
        ref_id: Optional[int],
    ) -> EmailLog:
        return EmailLog(
            ToAddress=",".join(to),
            CcAddress=",".join(cc) if cc else None,
            Subject=subject,
            Body=body,
            TemplateKey=template_key,
            RefType=ref_type,
            RefId=ref_id,
            Status="queued",
        )

    def _resolve_notification_mode(
        self,
        db: Optional[Session],
    ) -> Tuple[bool, List[str]]:
        """解析运行时通知模式

        优先级:
        1. 数据库 SystemSetting 表 (管理员可在线切换, 立即生效)
        2. config.ini / 环境变量 (settings.NOTIFICATION_MODE, 启动时读取)

        Returns:
            (is_test_mode, test_recipients)
            - is_test_mode: True=测试模式, False=生产模式
            - test_recipients: 测试模式下的邮件接收地址列表
        """
        # 默认值: 来自 config.ini
        is_test = self.settings.is_notification_test_mode
        recipients = self.settings.notification_test_recipients_list

        # 尝试从数据库读取运行时设置 (覆盖默认值)
        if db is not None:
            try:
                from app.models.system_setting import SystemSetting

                rows = (
                    db.query(SystemSetting)
                    .filter(
                        SystemSetting.SettingKey.in_([
                            "notification_mode",
                            "notification_test_recipients",
                        ])
                    )
                    .all()
                )
                for row in rows:
                    if row.SettingKey == "notification_mode" and row.SettingValue:
                        is_test = (row.SettingValue.strip().lower() == "test")
                    elif row.SettingKey == "notification_test_recipients" and row.SettingValue:
                        recipients = [
                            r.strip() for r in row.SettingValue.split(",") if r.strip()
                        ]
            except Exception as exc:
                # 数据库查询失败 (如表不存在), 回退到 config.ini 默认值
                logger.debug("查询运行时通知模式失败, 使用 config.ini 默认值: {}", exc)

        return is_test, recipients
