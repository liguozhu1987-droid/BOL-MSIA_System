# Realm `inalfa` 配置清单（Keycloak **25.0.6** 口径）

> 依据《统一身份认证实施方案_MSIA与BOL系统.md》7.1/12.4 节。
> 可粘贴的 kcadm 命令与逐字段取值见 `docs/keycloak-realm-clients-init.md` 清单 B；本文保留为配置语义说明。
> 本文为管理台逐项配置清单；建议配置导出后随周备份一并归档（`C:\sso\kc-export`）。
> 所有配置变更须记录变更人与时间，纳入 7.5 备份策略。

## 1. SMTP（本环境既定：25 端口无认证无 TLS）

| 项 | 值 | 说明 |
|---|---|---|
| Host | `172.19.253.10` | 与 MSIA `config.ini [mail]` 同一中继 |
| Port | `25` | 无认证 |
| Authentication | **OFF** | 无密码 |
| SSL | **OFF** | 不开 |
| StartTLS | **OFF** | 不开 |
| From | `ap_sso@inalfa.com` | 正式服务参数（以交底书 §9.5 为准；原 `sso-notify@inalfa.local` 作废） |
| From Display Name | `Inalfa AME系统统一身份认证` | 邮件显示名 |
| Envelope From | `ap_sso@inalfa.com` | 同 From |

**配置后必须执行**：
1. 管理台 Test connection（显示成功仅代表握手通，不代表不被判垃圾）；
2. 用 Forgot password 对 1 个测试账号实发一封，确认送达且不在垃圾箱；
3. 全员邀请设密前，先小范围（≤3 人）验证送达率。

> ⚠️ 无认证中继可伪造发件人：对用户的防钓鱼宣讲口径统一为"链接域名必为
> `sso.ap.inalfa.local`，任何其他域名的'设密邮件'都是钓鱼"。

## 2. 登录与注册策略

| 项 | 值 | 说明 |
|---|---|---|
| User registration | **OFF** | 用户只能来自同步（R6：禁止自助注册） |
| Forgot password | **ON** | 自助重置（G1）；无邮箱用户除外，见第 2.1 节 |
| Login with email | OFF | 统一用 username 登录（与两系统口径一致） |
| **Duplicate emails** | **OFF（2026-11-02 调整）** | **邮箱暂不用管理**：允许空邮箱/重复邮箱（中央表 email 唯一索引已同步降级为普通索引） |
| Verify email | OFF（本期） | 邮箱来自名单实测但非受管属性；降低设密摩擦 |
| Require Terms Of Service | OFF | 内部系统 |

### 2.1 无邮箱用户兜底流程（不走邮件邀请）

> 背景：用户确认"邮箱暂不用管理"（fine_user 的 email 列是测试邮箱）。AD 名单/实测中
> 确实没有邮箱的用户（如 BOL 本地无邮箱账号），Keycloak 侧按以下流程处理：

1. 同步脚本（sync_sso_to_keycloak.ps1）发现 email 为空：**跳过 execute-actions-email 邀请**，并在 SyncLog 中记录告警（含用户名清单）；
2. Keycloak 管理员在控制台为该用户**代设初始密码**（Credentials → Set password，Temporary=ON）；
3. 同时给用户加 **UPDATE_PASSWORD required action**（Details → Required actions，或用户面板强制）；
4. 用户**首次登录**用初始密码登入后，被强制改密（required action 生效）；
5. 管理员将初始密码通过**线下安全渠道**（当面/电话）告知用户，不得走邮件；
6. `pwd_set` 回写：用户完成改密后 requiredActions 不再含 UPDATE_PASSWORD，下次同步自动回写 `pwd_set=1`。

## 3. 密码策略（Credentials → Password policy）

| 项 | 值 |
|---|---|
| Minimum length | 10 |
| Not username | ON |
| Not email | ON |
| Uppercase / Lowercase / Digit / Special | 各至少 1（与 Keycloak 默认策略一致） |
| Password expiration | **OFF** | 不强制定期过期（内部系统，方案文档 7.1） |
| Force pre-hashed password | OFF | 本期无哈希导入 |

> ⚠️ **与统一初始密码的冲突（M07）**：当前统一初始密码**不含特殊字符**。若本表 `Special（specialChars）≥1` 已在 realm 生效，批量 `reset-password` 会被拒（`invalid password`）。执行批量设密前必须先用 `kcadm get realms/inalfa --fields passwordPolicy` 核对实际值；若确有 `specialChars`，先按《方案A落地清单》S01 的说明更换初始密码。

## 4. 暴力破解防护（Realm settings → Security defenses）

| 项 | 值 |
|---|---|
| Brute force detection | ON |
| Failure factor | 5（5 次失败） |
| Wait increment | 900 秒（15 分钟） |
| Max login wait | 15 分钟 |
| Quick login check | ON |

## 5. 会话与令牌（Realm settings → Sessions / Tokens）

| 项 | 值 | 说明 |
|---|---|---|
| Idle session timeout | **1 天（86400 秒）** | 2026-11-09 现场决定，覆盖原 8 小时，原值作废；加长不踢已登录用户 |
| Max session lifespan | **7 天（604800 秒）** | 同上，覆盖原 12 小时 |
| Access Token Lifespan | 15 分钟 | |
| **Action Token Lifespan** | **3 天（4320 分钟）** | ⚠️ 默认仅 5 分钟，execute-actions-email 发出的设密链接会失效；本期"3 天有效"靠此项落地（P1 实测） |
| SSO Session Idle | **1 天** | 与 Idle 一致 |
| SSO Session Max | **7 天** | |

## 6. 事件与审计（Realm settings → Events）

| 项 | 值 |
|---|---|
| User events | ON，保留 90 天（LOGIN/LOGOUT/LOGIN_ERROR/UPDATE_PASSWORD 等） |
| Admin events | ON，保留 180 天 |
| 事件监听 | 默认 jboss-logging（写日志文件，随 keycloak.log 归档） |

## 7. 准入组（Groups）

| 组名 | 用途 | 说明 |
|---|---|---|
| `app-msia` | MSIA 准入 | 成员登录 MSIA 时 token `groups` claim 含该值；MSIA 后端校验（T02） |
| `app-bol` | BOL 准入 | 同上，BOL 后端校验（T03） |
| `/users`（默认） | 所有同步用户默认所属 | 无需额外组 |

**成员首批**（13 人种子 → 按台账首批授权分组）：
- `app-msia`：admin、ligu、yangli1、yaole、zhangya4、fansh1、luyu、zhangp2、zhangpe、zhaop3、abelmi2（11 人，即 PermLedger 中 system_code='msia' 的名单）
- `app-bol`：admin、ligu、yaole、zhangya4、chenca、libi2、zhaop3（7 人，即 PermLedger 中 system_code='bol' 的名单）
- 后续随台账变更手工维护（台账线上化 R19 为 P2）

## 8. Required Actions

| 项 | 值 | 说明 |
|---|---|---|
| UPDATE_PASSWORD | 设为可被 execute-actions-email 触发 | 新人邀请设密、复职重邀 |
| VERIFY_EMAIL | OFF | 见第 2 节 |
| Update Profile | OFF | 资料由中央表同步维护，不让用户自改 |

## 9. 本地化与主题（可选）

- Display name：`inalfa`
- 登录页标题建议注明"统一身份认证（MSIA / BOL）"，降低钓鱼辨识成本
- 支持语言：简体中文 + English（默认按浏览器）

## 10. 配置导出与备份

```bat
C:\keycloak\bin\kc.bat export --dir C:\sso\kc-export --realm inalfa
```
每周日 02:00 由计划任务 SSO_KC_Export 执行；导出的 JSON 纳入 7.5 备份策略。
