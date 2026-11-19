"""本地测试脚本

测试内容:
1. 数据库连接 (SQL Server)
2. 邮件发送 (SMTP)
3. Mock 数据构造 (用户 / 项目 / 阶段 / 检查项 / 问题)

用法:
    python test_local.py              # 运行全部测试
    python test_local.py --db         # 仅测试数据库连接
    python test_local.py --email      # 仅测试邮件发送
    python test_local.py --email test@example.com  # 发送到指定地址
    python test_local.py --seed       # 仅构造 mock 数据
"""
import sys
import os

# 确保从 backend 目录运行, 加载 .env
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta, timezone


def print_header(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_ok(msg: str):
    print(f"  [✓] {msg}")


def print_fail(msg: str):
    print(f"  [✗] {msg}")


def print_info(msg: str):
    print(f"  [i] {msg}")


# ---------------------------------------------------------------------------
# 1. 数据库连接测试
# ---------------------------------------------------------------------------
def test_database_connection():
    print_header("测试 1: 数据库连接")
    try:
        import pyodbc
        print_info(f"pyodbc 版本: {pyodbc.version}")
        print_info(f"已安装 ODBC 驱动:")
        for d in pyodbc.drivers():
            print(f"       - {d}")
    except ImportError:
        print_fail("pyodbc 未安装")
        return False
    except Exception as e:
        print_fail(f"ODBC 驱动检查失败: {e}")

    try:
        from app.core.config import settings
        print_info(f"数据库 URL: {settings.DATABASE_URL.split('@')[-1] if '@' in settings.DATABASE_URL else settings.DATABASE_URL}")
    except Exception as e:
        print_fail(f"配置加载失败: {e}")
        return False

    try:
        from app.db.session import engine
        from sqlalchemy import text

        print_info("正在连接 SQL Server ...")
        with engine.connect() as conn:
            # 测试查询
            result = conn.execute(text("SELECT @@VERSION AS version, DB_NAME() AS db_name"))
            row = result.fetchone()
            if row:
                version_str = str(row[0])[:80]
                print_ok(f"数据库连接成功")
                print_info(f"数据库版本: {version_str}...")
                print_info(f"当前数据库: {row[1]}")

            # 查询已有表
            result = conn.execute(text(
                "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_NAME LIKE 'CN_AME_MISA_%' "
                "ORDER BY TABLE_NAME"
            ))
            tables = [r[0] for r in result.fetchall()]
            if tables:
                print_ok(f"已存在 MSIA 系统表 ({len(tables)} 张):")
                for t in tables:
                    print(f"       - {t}")
            else:
                print_info("未发现 MSIA 系统表, 可执行建表脚本或设置 MSIA_AUTO_CREATE_TABLES=1")

        return True
    except Exception as e:
        print_fail(f"数据库连接失败: {e}")
        import traceback
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# 2. 邮件发送测试
# ---------------------------------------------------------------------------
def test_email_send(test_recipient: str = None):
    print_header("测试 2: 邮件发送")
    try:
        from app.core.config import settings
        print_info(f"SMTP 服务器: {settings.EMAIL_SMTP_HOST}:{settings.EMAIL_SMTP_PORT}")
        print_info(f"SSL: {settings.EMAIL_ENABLE_SSL}")
        print_info(f"认证: {'有' if settings.EMAIL_SMTP_USERNAME else '无 (免认证)'}")
        print_info(f"发件人: {settings.EMAIL_FROM_ADDRESS}")
    except Exception as e:
        print_fail(f"配置加载失败: {e}")
        return False

    # 收件人: 命令行参数 > 默认测试地址
    recipient = test_recipient or "test-msia@inalfa.local"
    print_info(f"收件人: {recipient}")

    try:
        from app.services.email_service import EmailService
        svc = EmailService(settings)

        # 先测试模板渲染
        subject, body = svc.render_template("issue_assigned", {
            "title": "测试问题 - 本地环境邮件发送验证",
            "issue_no": "MOCK-001",
            "priority": "high",
            "due_date": "2026-08-20",
        })
        print_ok(f"模板渲染成功, 主题: {subject}")

        body_with_note = body + "\n\n--- 这是来自 MSIA 本地测试脚本的测试邮件, 请勿回复 ---"

        # 尝试多种连接模式: 明文 -> STARTTLS -> SMTP_SSL
        import smtplib
        from email.header import Header
        from email.mime.text import MIMEText
        from email.utils import formataddr, formatdate

        host = settings.EMAIL_SMTP_HOST
        port = settings.EMAIL_SMTP_PORT
        from_addr = settings.EMAIL_FROM_ADDRESS
        from_display = settings.EMAIL_FROM_DISPLAY_NAME
        timeout = max(settings.EMAIL_TIMEOUT_MS / 1000.0, 5.0)

        msg = MIMEText(body_with_note, "plain", "utf-8")
        msg["From"] = formataddr((str(Header(from_display, "utf-8")), from_addr))
        msg["To"] = recipient
        msg["Subject"] = Header(subject, "utf-8")
        msg["Date"] = formatdate(localtime=True)

        modes = [
            ("明文 SMTP (无加密)", "plain"),
            ("STARTTLS (显式加密)", "starttls"),
            ("SMTP_SSL (隐式加密)", "ssl"),
        ]

        for label, mode in modes:
            print_info(f"尝试 {label} -> {host}:{port} ...")
            try:
                if mode == "ssl":
                    with smtplib.SMTP_SSL(host, port, timeout=timeout) as server:
                        server.sendmail(from_addr, [recipient], msg.as_string())
                elif mode == "starttls":
                    with smtplib.SMTP(host, port, timeout=timeout) as server:
                        server.ehlo()
                        try:
                            server.starttls()
                            server.ehlo()
                        except Exception:
                            pass  # 服务器可能不支持 STARTTLS, 继续明文发送
                        server.sendmail(from_addr, [recipient], msg.as_string())
                else:  # plain
                    with smtplib.SMTP(host, port, timeout=timeout) as server:
                        server.ehlo()
                        server.sendmail(from_addr, [recipient], msg.as_string())
                print_ok(f"邮件发送成功 ({label}) -> {recipient}")
                print_info(f"建议: 在 .env 中设置 EMAIL_ENABLE_SSL 对应此模式")
                return True
            except Exception as e:
                print_fail(f"{label} 失败: {e}")

        print_info("所有连接模式均失败, 可能原因: 内网 SMTP 不可达 / 端口被防火墙拦截")
        return False
    except Exception as e:
        print_fail(f"邮件服务初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# 3. Mock 数据构造
# ---------------------------------------------------------------------------
def seed_mock_data():
    print_header("测试 3: 构造 Mock 数据")
    try:
        from app.db.session import SessionLocal, create_tables
        from app.models.user import User
        from app.models.project import Project, Phase
        from app.models.check_item import CheckItem
        from app.models.issue import Issue
        from app.models.notification import Notification
        from app.models.email_log import EmailLog
        from app.core.security import hash_password
    except Exception as e:
        print_fail(f"模块导入失败: {e}")
        return False

    # 先建表 (如果不存在)
    print_info("检查/创建数据库表 ...")
    try:
        create_tables()
        print_ok("表结构已就绪")
    except Exception as e:
        print_fail(f"建表失败: {e}")
        return False

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        # --- 用户 ---
        print_info("构造用户数据 ...")
        users_data = [
            {"Username": "admin", "DisplayName": "系统管理员", "Email": "admin@inalfa.local",
             "Department": "IT", "Role": "admin", "PasswordHash": hash_password("Admin@123")},
            {"Username": "lead_reviewer01", "DisplayName": "张评审", "Email": "zhang.reviewer@inalfa.local",
             "Department": "AME", "Role": "lead_reviewer", "PasswordHash": hash_password("Test@1234")},
            {"Username": "reviewer01", "DisplayName": "李检查", "Email": "li.checker@inalfa.local",
             "Department": "IE", "Role": "reviewer", "PasswordHash": hash_password("Test@1234")},
            {"Username": "reviewee01", "DisplayName": "王项目", "Email": "wang.project@inalfa.local",
             "Department": "Plant ME", "Role": "reviewee", "PasswordHash": hash_password("Test@1234")},
        ]
        user_map = {}
        for ud in users_data:
            existing = db.query(User).filter(User.Username == ud["Username"]).first()
            if existing:
                print_info(f"  用户已存在, 跳过: {ud['Username']}")
                user_map[ud["Username"]] = existing
            else:
                u = User(
                    Username=ud["Username"], DisplayName=ud["DisplayName"], Email=ud["Email"],
                    Department=ud["Department"], Role=ud["Role"],
                    PasswordHash=ud["PasswordHash"], PasswordUpdatedAt=now,
                    Status=1, IsDeleted=False, HrSyncedAt=now,
                )
                db.add(u)
                db.flush()
                user_map[ud["Username"]] = u
                print_ok(f"  创建用户: {ud['Username']} ({ud['DisplayName']})")
        db.commit()

        admin = user_map["admin"]
        lead = user_map["lead_reviewer01"]
        reviewer = user_map["reviewer01"]

        # --- 项目 ---
        print_info("构造项目数据 ...")
        project_code = "MOCK-PROJ-001"
        proj = db.query(Project).filter(Project.Code == project_code).first()
        if proj:
            print_info(f"  项目已存在, 跳过: {project_code}")
        else:
            proj = Project(
                Name="示例项目 - 摩擦系统改型",
                Code=project_code,
                Type="New Product",
                CmcAme="CMC AME 张三",
                PlantMe="Plant ME 李四",
                InalfaKickoff=now - timedelta(days=30),
                SupplierKickoff=now - timedelta(days=25),
                DesignFreeze=now + timedelta(days=60),
                Pvp=now + timedelta(days=120),
                InalfaSop=now + timedelta(days=180),
                Status="in_progress",
                CreatedBy=admin.Id,
                IsDeleted=False,
            )
            db.add(proj)
            db.commit()
            db.refresh(proj)
            print_ok(f"  创建项目: {proj.Name} ({proj.Code})")

        # --- 阶段 (MSIA1 ~ MSIA5) ---
        print_info("构造阶段数据 ...")
        phase_defs = [
            ("MSIA1", "项目启动", "Project Kick-off", "项目计划与团队组建"),
            ("MSIA2", "设计评审", "Design Review", "设计规范与可制造性分析"),
            ("MSIA3", "验证准备", "Verification Preparation", "验证计划与测试用例"),
            ("MSIA4", "生产准备", "Production Preparation", "产线调试与试产"),
            ("MSIA5", "量产发布", "SOP & Ramp-up", "量产爬坡与持续改进"),
        ]
        phase_map = {}
        for code, name, timing, targets in phase_defs:
            ph = db.query(Phase).filter(
                Phase.ProjectId == proj.Id, Phase.Code == code
            ).first()
            if ph:
                print_info(f"  阶段已存在, 跳过: {code}")
                phase_map[code] = ph
            else:
                ph = Phase(
                    ProjectId=proj.Id, Code=code, Name=name,
                    TimingDescription=timing, MainTargets=targets,
                    Status="not_started" if code != "MSIA1" else "in_progress",
                    LeadReviewerId=lead.Id,
                )
                db.add(ph)
                db.flush()
                phase_map[code] = ph
                print_ok(f"  创建阶段: {code} - {name}")
        db.commit()

        # --- 检查项 ---
        print_info("构造检查项数据 ...")
        check_items_data = [
            ("MSIA1", "1.1", "项目启动会议", "确认项目启动会议已召开并记录纪要", True, "lead_reviewer,reviewer", "5-step"),
            ("MSIA1", "1.2", "项目计划与里程碑", "项目计划包含关键里程碑", True, "lead_reviewer,reviewer", "5-step"),
            ("MSIA1", "1.3", "团队组建", "跨职能团队已组建并明确角色职责", False, "lead_reviewer", "3-step"),
            ("MSIA2", "2.1", "设计规范评审", "设计规范已评审并获批", True, "reviewer", "5-step"),
            ("MSIA2", "2.2", "可制造性分析", "已完成可制造性(DFM)分析", True, "reviewer", "4-step"),
        ]
        score_options_map = {
            "5-step": '[{"value":5,"label":"5-完全符合"},{"value":4,"label":"4-轻微差距"},{"value":3,"label":"3-部分符合"},{"value":2,"label":"2-重大差距"},{"value":1,"label":"1-不符合"}]',
            "4-step": '[{"value":4,"label":"4-完全符合"},{"value":3,"label":"3-轻微差距"},{"value":2,"label":"2-重大差距"},{"value":1,"label":"1-不符合"}]',
            "3-step": '[{"value":3,"label":"3-符合"},{"value":2,"label":"2-部分符合"},{"value":1,"label":"1-不符合"}]',
        }
        for phase_code, item_no, name, request, is_key, roles, scale in check_items_data:
            existing = db.query(CheckItem).filter(
                CheckItem.PhaseCode == phase_code, CheckItem.ItemNo == item_no
            ).first()
            if existing:
                continue
            ci = CheckItem(
                PhaseCode=phase_code, ItemNo=item_no, Name=name, Request=request,
                IsKeyItem=is_key, ReviewerRoles=roles,
                ScoreScaleType=scale, ScoreOptions=score_options_map.get(scale, ""),
                Version=1, IsDeleted=False,
            )
            db.add(ci)
        db.commit()
        count_ci = db.query(CheckItem).count()
        print_ok(f"  检查项已就绪 (共 {count_ci} 条)")

        # --- 问题 (Issue) ---
        print_info("构造问题数据 ...")
        issue_no = "MOCK-ISSUE-001"
        existing_issue = db.query(Issue).filter(Issue.IssueNo == issue_no).first()
        if existing_issue:
            print_info(f"  问题已存在, 跳过: {issue_no}")
        else:
            ci = db.query(CheckItem).filter(CheckItem.PhaseCode == "MSIA1", CheckItem.ItemNo == "1.1").first()
            issue = Issue(
                ProjectId=proj.Id,
                PhaseId=phase_map["MSIA1"].Id,
                ItemId=ci.Id if ci else None,
                IssueNo=issue_no,
                Title="项目启动会议纪要缺失",
                Description="MSIA1 阶段启动会议已召开, 但会议纪要未上传至系统, 需补充。",
                OwnerUserId=reviewer.Id,
                OwnerDepartment="IE",
                Priority="high",
                DueDate=now + timedelta(days=7),
                Status="open",
                ClosingStatus="",
                Remarks="mock 数据",
                CreatedBy=admin.Id,
                IsDeleted=False,
            )
            db.add(issue)
            db.commit()
            print_ok(f"  创建问题: {issue_no} - {issue.Title}")

        # --- 通知 ---
        print_info("构造通知数据 ...")
        existing_noti = db.query(Notification).filter(
            Notification.UserId == reviewer.Id, Notification.Title.like("%mock%")
        ).first()
        if not existing_noti:
            noti = Notification(
                UserId=reviewer.Id,
                Title="mock 通知: 您有新的审核任务",
                Content="项目「示例项目 - 摩擦系统改型」MSIA1 阶段有待评审检查项, 请及时处理。",
                Type="review_assigned",
                Status="unread",
                Link="/projects/1/phases/1",
            )
            db.add(noti)
            db.commit()
            print_ok("  创建通知 (1 条)")
        else:
            print_info("  通知已存在, 跳过")

        # --- 汇总 ---
        print_header("Mock 数据构造完成")
        print_ok(f"用户: {db.query(User).count()} 条")
        print_ok(f"项目: {db.query(Project).count()} 条")
        print_ok(f"阶段: {db.query(Phase).count()} 条")
        print_ok(f"检查项: {db.query(CheckItem).count()} 条")
        print_ok(f"问题: {db.query(Issue).count()} 条")
        print_ok(f"通知: {db.query(Notification).count()} 条")
        print_info("")
        print_info("测试账号:")
        print_info("  admin / Admin@123        (管理员)")
        print_info("  lead_reviewer01 / Test@1234  (首席评审)")
        print_info("  reviewer01 / Test@1234      (评审)")
        print_info("  reviewee01 / Test@1234      (被评审)")
        return True
    except Exception as e:
        db.rollback()
        print_fail(f"Mock 数据构造失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    run_all = len(args) == 0 or "--all" in args
    run_db = run_all or "--db" in args
    run_email = run_all or "--email" in args
    run_seed = run_all or "--seed" in args

    # 提取邮件收件人
    email_recipient = None
    if "--email" in args:
        idx = args.index("--email")
        if idx + 1 < len(args) and not args[idx + 1].startswith("--"):
            email_recipient = args[idx + 1]

    print("\n" + "#" * 60)
    print("#  MSIA 审核管理系统 - 本地测试脚本")
    print("#" * 60)

    results = {}
    if run_db:
        results["数据库连接"] = test_database_connection()
    if run_email:
        results["邮件发送"] = test_email_send(email_recipient)
    if run_seed:
        results["Mock 数据"] = seed_mock_data()

    print_header("测试结果汇总")
    for name, ok in results.items():
        status = "通过" if ok else "失败"
        symbol = "✓" if ok else "✗"
        print(f"  [{symbol}] {name}: {status}")

    # 退出码: 全部通过为 0
    all_ok = all(results.values()) if results else False
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
