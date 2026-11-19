"""通知服务

- 创建站内通知 (CN_AME_MISA_Notification)
- 触发邮件发送 (调用 EmailService)

通知 Type 取值:
  - issue_assigned / issue_overdue / issue_verified
  - review_submitted / review_confirmed
"""
from typing import List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.user import User
from app.services.email_service import EmailService


class NotificationService:
    """通知与邮件触发服务"""

    def __init__(self, db: Session, email_service: Optional[EmailService] = None):
        self.db = db
        self.email_service = email_service

    def create(
        self,
        user_id: int,
        title: str,
        content: str,
        notif_type: str,
        link: Optional[str] = None,
    ) -> Notification:
        """创建站内通知"""
        notif = Notification(
            UserId=user_id,
            Title=title,
            Content=content,
            Type=notif_type,
            Status="unread",
            Link=link,
        )
        self.db.add(notif)
        self.db.commit()
        self.db.refresh(notif)
        return notif

    def create_and_email(
        self,
        user_id: int,
        title: str,
        content: str,
        notif_type: str,
        link: Optional[str] = None,
        template_key: Optional[str] = None,
        context: Optional[dict] = None,
        ref_type: Optional[str] = None,
        ref_id: Optional[int] = None,
    ) -> Notification:
        """创建站内通知并触发邮件

        若用户邮箱存在则发送邮件, 失败不影响站内通知。
        """
        notif = self.create(user_id, title, content, notif_type, link)

        user = self.db.query(User).filter(User.Id == user_id).first()
        if user and user.Email and self.email_service:
            try:
                if template_key and context:
                    subject, body, _ = self.email_service.render_template(template_key, context)
                else:
                    subject, body = title, content
                self.email_service.send_with_retry(
                    to=[user.Email],
                    subject=subject,
                    body=body,
                    db=self.db,
                    template_key=template_key,
                    ref_type=ref_type,
                    ref_id=ref_id,
                )
            except Exception:
                logger.exception("通知邮件发送失败: 用户 {}", user_id)
        return notif

    def create_and_email_group(
        self,
        user_ids: List[int],
        title: str,
        content: str,
        notif_type: str,
        link: Optional[str] = None,
        template_key: Optional[str] = None,
        context: Optional[dict] = None,
        ref_type: Optional[str] = None,
        ref_id: Optional[int] = None,
        skip_user_ids: Optional[List[int]] = None,
    ) -> List[Notification]:
        """群发通知: 每人一条站内通知, 但邮件只合并发送一封

        避免逐人发送导致同一邮箱 (测试模式下所有邮件重定向到同一测试邮箱)
        收到多封重复邮件。邮件收件人为所有有邮箱的用户 (去重)。

        Args:
            user_ids: 通知目标用户列表
            skip_user_ids: 跳过的用户 (如已单独通知过的责任人)
        """
        skip = set(skip_user_ids or [])
        notifs: List[Notification] = []
        emails: List[str] = []
        for uid in user_ids:
            if uid in skip:
                continue
            notif = self.create(uid, title, content, notif_type, link)
            notifs.append(notif)
            user = self.db.query(User).filter(User.Id == uid).first()
            if user and user.Email and user.Email not in emails:
                emails.append(user.Email)

        if emails and self.email_service:
            try:
                if template_key and context:
                    subject, body, _ = self.email_service.render_template(template_key, context)
                else:
                    subject, body = title, content
                self.email_service.send_with_retry(
                    to=emails,
                    subject=subject,
                    body=body,
                    db=self.db,
                    template_key=template_key,
                    ref_type=ref_type,
                    ref_id=ref_id,
                )
            except Exception:
                logger.exception("群发通知邮件发送失败: 用户 {}", user_ids)
        return notifs
