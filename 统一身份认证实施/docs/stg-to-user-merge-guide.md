# StgAdUser → CN_AME_SSO_User 合并：现状诊断与自动化方案

> 适用对象：负责把 1000+ 条 AD 名单落进中央人员表的运维/实施人员（不需要熟悉 T-SQL）。
> 配套脚本：[05_merge_stg_to_user.sql](../scripts/sql/05_merge_stg_to_user.sql)
> 编写日期：2026-11-09　｜　全程只读调查，未修改任何生产数据、未修改任何既有脚本

---

## 1. 结论速览（先看这 5 条）

| # | 结论 | 依据 |
|---|---|---|
| 1 | **仓库里原本没有独立的 Stg → 主表合并脚本**。合并逻辑只内嵌在 PowerShell 里，本次新建 `05_merge_stg_to_user.sql` | 见 §2 资产清单 |
| 2 | **13 条 = 种子数据的 13 人，不是抽样，也不是合并失败后的残留** | `03_seed_users.sql` 共 13 个 INSERT；交底书 L707 写“首版中央人员表种子（去重后 13 人）” |
| 3 | **主因：合并步骤从未执行过**（不是“没有实现”，是“实现了没跑”） | 交底书 L26 “待办：…人员 MERGE…”、L418 “人员 MERGE … 待执行” |
| 4 | **Stg 里有 1000+ 是正常的**：Stg 是每日清空重灌的暂存快照，灌数（LOAD）和合并（MERGE）在脚本里是两段，LOAD 成功、MERGE 没跑，就会长成“Stg 有、主表没有”的样子 | `sync_ad_to_sso.ps1` L364-L424（LOAD）/ L426-L483（MERGE） |
| 5 | **首次真正跑 MERGE 之前必须先过“登录名撞人”闸门**，否则整条 MERGE 会因唯一键冲突整体回滚，等于白跑 | `04_flip_manual_source.sql` L24-L36 已把该场景标为“危险项” |
| 6 | 首次现场执行的预期结果：**新增 1000+ 在册人员 + 把名单外的 3 个测试账号置 `status=0`**（这是 04 脚本设计的自动化效果，不是故障） | `04_flip_manual_source.sql` L48-L51、L73-L75 |

---

## 2. 现有资产清单（仓库实况）

### 2.1 五张表（DDL 以 [01_create_sso_tables.sql](../scripts/sql/01_create_sso_tables.sql) 为准）

| 表 | 仓库 DDL 位置 | 角色 |
|---|---|---|
| `CN_AME_SSO_StgAdUser` | [L17 起](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/sql/01_create_sso_tables.sql#L17-L35) | AD 名单**着陆区**。每日先 `DELETE` 全清再灌当日名单，是“当日快照”，**不是事实来源** |
| `CN_AME_SSO_User` | [L37 起](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/sql/01_create_sso_tables.sql#L37-L75) | **中央人员唯一事实来源**。`employee_no` 稳定主键、`login_name` = Keycloak username |
| `CN_AME_SSO_UserMap` | [L78 起](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/sql/01_create_sso_tables.sql#L78-L94) | 跨系统账号对照：同一个人的“业务系统本地用户名”与“中央工号”对齐 |
| `CN_AME_SSO_SyncLog` | [L97 起](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/sql/01_create_sso_tables.sql#L97-L113) | 两类同步的执行台账（`phase` = LOAD / MERGE / KC / KC_EMERGENCY） |
| `CN_AME_SSO_PermLedger` | [L116 起](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/sql/01_create_sso_tables.sql#L116-L132) | 权限台账（谁-哪个系统-什么角色-谁授的），纯人工维护，不参与自动化 |

### 2.2 列与约束（仓库 DDL 原文要点）

**StgAdUser**：`employee_no`(NOT NULL)、`login_name`、`display_name`、`email`、`mobile`、`dept_code`、`dept_name`、`title`、`status`(1/0)、`ad_object_guid`、`loaded_at`。
只有普通索引 `IX_CN_AME_SSO_StgAdUser_EmpNo`，**没有主键、没有唯一约束** → 重复工号可以灌进来（这会让 MERGE 直接报错）。

**User**：
- 主键 `id`（自增）
- `UQ_CN_AME_SSO_User_EmpNo` UNIQUE(employee_no)、`UQ_CN_AME_SSO_User_Login` UNIQUE(login_name)
- 过滤唯一索引 `UX_CN_AME_SSO_User_Guid`（`ad_object_guid` 非空时唯一）
- `email`：2026-11-02 起**已降级为普通索引**，允许空/重复（文件 L63-L66 有注释）
- `source` 只能是 `AD` / `MANUAL`（CHECK 约束）；`MANUAL` = 例外手工，AD 同步不覆盖、不停用
- 审计列：`created_at`、`updated_at`、`source`、`synced_at` —— **批次号没有**，本次脚本新增 `last_batch_no`

**UserMap**：`UQ_CN_AME_SSO_UserMap_SysLocal` UNIQUE(system_code, local_username)；`employee_no` 逻辑关联 `User`，但**全库无外键**（实施方案 L384 明确写“无外键”）。

### 2.3 脚本与文档（读写位置）

| 资产 | 对这三张表做了什么 |
|---|---|
| [sync_ad_to_sso.ps1](../scripts/powershell/sync_ad_to_sso.ps1) | ① [L364 起](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/powershell/sync_ad_to_sso.ps1#L364-L424) `Invoke-StageLoad`：`DELETE` 全清 Stg + `SqlBulkCopy` 灌当日名单；② [L426 起](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/powershell/sync_ad_to_sso.ps1#L426-L483) `Invoke-MergeCentralUser`：内嵌 MERGE 写 `User`；③ [L553](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/powershell/sync_ad_to_sso.ps1#L553-L563) 先 LOAD、[L563](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/powershell/sync_ad_to_sso.ps1#L553-L563) 再合并；④ 全程写 `SyncLog` |
| [sync_sso_to_keycloak.ps1](../scripts/powershell/sync_sso_to_keycloak.ps1) | [L361-L362](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/powershell/sync_sso_to_keycloak.ps1#L361-L362) 全量读 `User`；[L379-L450](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/powershell/sync_sso_to_keycloak.ps1#L379-L450) 幂等建号/整对象 PUT；[L419-L424](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/powershell/sync_sso_to_keycloak.ps1#L419-L424) 回写 `kc_user_id`；[L490-L505](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/powershell/sync_sso_to_keycloak.ps1#L490-L505) 回写 `pwd_set`。**不读 UserMap** |
| [disable_user_now.ps1](../scripts/powershell/disable_user_now.ps1) | [L297](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/powershell/disable_user_now.ps1#L297) 应急停号：只把 `status` 置 0，不动其它字段。**注意**：它停的号次日可能被 MERGE 复活，必须同步通知 IT 从名单移除（实施方案 L546 有同样提示） |
| [03_seed_users.sql](../scripts/sql/03_seed_users.sql) | 一次性插 13 人（`source='MANUAL'`）、2 条 UserMap、18 条 PermLedger |
| [04_flip_manual_source.sql](../scripts/sql/04_flip_manual_source.sql) | 只把 `source` 从 `MANUAL` 改 `AD`；L24-L36 是合并的“危险项”预检；L48-L51 预演首次 MERGE 会停用哪些人；L106-L125 是合并后核对 |
| [90_usermap_backfill.sql](../scripts/sql/90_usermap_backfill.sql) | UserMap 对账 + 回填模板（C 段整段注释，需人工确认后执行） |
| [91_usermap_integrity_checks.sql](../scripts/sql/91_usermap_integrity_checks.sql) | 九组只读校验；L187-L194 查中央表登录名大小写重复；L231-L248 查 Stg 与主表差集 |
| **Stg → 主表合并脚本** | **原本不存在**。合并逻辑只内嵌在 ps1 里；本次新增 [05_merge_stg_to_user.sql](../scripts/sql/05_merge_stg_to_user.sql) |

---

## 3. 全链路数据流

```
AD 域控（IT，仅提供名单，不给 LDAP/密码）
   │  ① 人工/半自动 投递 CSV：ad_users_yyyyMMdd.csv（列 userName,realName,email,mobile,enable,employeeNo）
   ▼
C:\sso\import  ──06:00 计划任务 SSO_AD_Import（需现场确认是否已建）
   │  ② sync_ad_to_sso.ps1：清洗 → 防错检查 → DELETE + BulkCopy
   ▼
CN_AME_SSO_StgAdUser（每日快照，1000+ 行）
   │  ③ ★MERGE★（Stg → User）
   ▼
CN_AME_SSO_User（中央人员唯一事实来源）
   │  ④ sync_sso_to_keycloak.ps1（Admin REST，幂等）
   ▼
Keycloak realm inalfa（username = login_name，初始密码另由管理员批量代设）
   │  ⑤ OIDC 授权码流，取 preferred_username + groups
   ▼
MSIA / BOL 后端身份解析：
   groups 准入 → CN_AME_SSO_UserMap(system_code + local_username) → 回落 preferred_username → 本地用户表 → 自动建档
   ▼
各系统本地凭证（MSIA 本地 JWT / BOL AuthToken）→ 下游鉴权链路原样不动
```

### 3.1 各表在链路中的职责

| 表 | 职责 | 谁会写 |
|---|---|---|
| StgAdUser | 只做“当日名单的缓冲区 + 防错检查对象”。**可以被随意清空重灌**，丢了不影响历史 | 只有 LOAD 步骤 |
| User | 决定“系统里应该有哪些人、谁在职”。Keycloak 建号名单完全由它派生 | MERGE（AD 路径）、`kc_user_id`/`pwd_set` 回写（KC 路径）、03/04 手工脚本 |
| UserMap | 只在**业务系统登录时**解决“中央身份 → 本地账号”的翻译问题。它不参与 Keycloak 建号 | 人工（90 脚本 C 段模板） |
| SyncLog | 每天“跑没跑、成没成、增改停多少”的唯一凭据 | 两个 ps1 + 05 脚本 |
| PermLedger | 授权审计台账 | 人工 |

### 3.2 链路上现在**没有自动化**的环节

| # | 环节 | 现状 | 证据 |
|---|---|---|---|
| 1 | IT 投递名单 CSV | 人工/半自动，投递方式“待书面约定”；脚本只能检测“当日文件不存在”并回退昨日 + 告警 | 实施方案 L127、`sync_ad_to_sso.ps1` 的 `Import-AdRows`（L257 起） |
| 2 | **Stg → User 合并** | **有实现、无独立脚本、无一次成功执行记录** | 交底书 L26 / L418 |
| 3 | 计划任务 `SSO_AD_Import` | 是否已创建并每日执行 **需现场确认**（`schtasks /query /tn "SSO_AD_Import"`） | 交底书 L713 把它列为验收项，未写“已完成” |
| 4 | UserMap 灌数 | 纯手工：模板整段注释，逐条人工确认后打开 | `90_usermap_backfill.sql` C 段（L105 起） |
| 5 | PermLedger 维护 | 无任何脚本，只有首批 18 行 | `03_seed_users.sql` L148-L246 |
| 6 | 首次密码设置 | 管理员批量代设统一初始密码（手工/半脚本），不依赖邮件 | 交底书 L120、落地清单 M07 |
| 7 | Keycloak 与中央表的**对账** | 1000+ Keycloak 用户是一次性**手工批量导入**（只有 username/email、无密码），与中央表没有自动差异比对；两边现在只靠 `username` 松耦合 | 交底书 L24、`sync_sso_to_keycloak.ps1` L379-L390（`username exact=true`） |

> 关于第 7 条是好消息的部分：批量导入的用户后续被 `sync_sso_to_keycloak.ps1` 按 `username exact=true` 命中，走“GET 整对象 → 改 → PUT”，**不会重复建号**。所以 MERGE 之后补跑 KC 同步是安全的、幂等的。

---

## 4. “1000 多条只进来 13 条”的真实原因

### 4.1 13 这个数字本身就是证据

`03_seed_users.sql` 从头到尾只有 13 个 `IF NOT EXISTS … INSERT`（admin、ligu、yangli1、yaole、zhangya4、fansh1、luyu、zhangp2、zhangpe、zhaop3、abelmi2、chenca、libi2），文件头写“共 13 人”，交底书 L707 写“首版中央人员表种子（去重后 13 人）”。
主表正好 13 条 → **主表内容 = 种子批次，AD 合并批次没有落进去**。这不是巧合，也不是“抽样验证”。

### 4.2 五种可能性逐项排查

| 可能性 | 判定 | 依据 |
|---|---|---|
| A. 主表只由人工或单条接口写入 | **不成立**。写主表一共 5 条路径：03 种子（13 个 `INSERT`，人工一次性）、04 改 `source`（人工一次性）、`sync_ad_to_sso.ps1` 的 MERGE（自动）、`sync_sso_to_keycloak.ps1` 两处回写（`kc_user_id` / `pwd_set`，自动）、`disable_user_now.ps1` 应急停号（手工、只改 `status`）。没有“单条写入接口” | 全仓库检索 `INSERT/UPDATE/MERGE dbo.CN_AME_SSO_User` 只命中这 5 处 |
| B. 合并步骤从未执行，或只手工试过 | **成立，且是主因** | 交底书 L26 “待办：…人员 MERGE”；L418 “人员 MERGE｜04 就绪，待执行”；05 脚本本次才建 |
| C. 导入脚本只写 Stg 不写主表 | **设计上不成立，但现象上成立**。ps1 的 LOAD 与 MERGE 在同一脚本里先后执行；一旦在 LOAD 之后、MERGE 之前退出（防错检查 `exit 1`、凭据/网络异常、被人 `Ctrl+C`），就会留下“Stg 有 1000+、主表没动”的中间态 | `sync_ad_to_sso.ps1` L553 先 LOAD、L563 才 MERGE；L543-L546 的 ABORTED 分支写日志后 `exit 1`，**不会执行 MERGE** |
| D. 约束冲突导致整批回滚 | **若将来直接跑，这是必踩的坑**。MERGE 是单条语句，撞 `UQ_CN_AME_SSO_User_Login` 会整条回滚 → 一行都进不去 | `04_flip_manual_source.sql` L24-L36 原文：“若此处非 0 行，转换后 MERGE 的 INSERT 会撞 UQ_CN_AME_SSO_User_Login 直接报错” |
| E. 只是抽样验证了 13 个人 | **不成立**。13 是种子口径全量，抽样不会正好等于 `03` 文件里的 13 行 | §4.1 |

### 4.3 判定结论（按证据强度）

1. **确定主因（B）**：合并从未成功执行。Stg 有 1000+ 只说明 LOAD 跑过（或有人手工灌过 Stg），而 LOAD 全程不碰 `User`（`Invoke-StageLoad` 只 `DELETE`/`BulkCopy` Stg 表）。
2. **伴随现象（C）**：LOAD 与 MERGE 虽然同一脚本，但中间有“防错中止”和异常出口，因此“Stg 已灌、主表没合并”是脚本结构允许出现的正常中间态，不需要解释成 bug。
3. **潜在阻断（D）**：一旦真跑，工号口径不对齐会直接撞唯一键。必须先过脚本里的闸门 4（见 §5.7、§9），否则等于白跑一趟。
4. **已排除（A/E）**。

### 4.4 文档口径里还有一处相互冲突的表述（这是“没跑”的助推剂）

- [交底书](../统一身份认证技术交底书_MSIA与BOL实施实录.md#L83-L85) §4.2 原文：“**定期作业只写暂存表，不直接写中央人员表**”。
- 同一份文档 [§5.1](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证技术交底书_MSIA与BOL实施实录.md#L107-L109) 的数据流原文：“`StgAdUser` → 防错检查 → **MERGE 到 `CN_AME_SSO_User`** → Keycloak 同步”。

§4.2 讲的是“IT 侧定期作业的写入边界”（只允许写 Stg，不许直写主表），并不是“SSO 同步脚本不做 MERGE”；但字面读起来很容易被理解成“合并这一步不用做/不该做”。叠加 L26、L418 都把 MERGE 列为待办，最可能的执行事实是：**灌数通了、合并被当成“下一步”一直搁置**。

建议把 §4.2 改成“IT 侧定期作业只写暂存表；暂存表 → 中央人员表的合并由 `05_merge_stg_to_user.sql` 负责”以免后续再次误读（**本次未改动该文档**）。

### 4.5 13 条的 source 现状：证据指向“已转 AD”

交底书 L74 写“种子 13 人已建档；**2026-11-03 起 source 统一为 `AD`**”，L24 也写“MANUAL 种子用户已转 `AD`（04_flip_manual_source.sql）”。`04` 脚本本身也留了副作用预告（L73-L75）：转换后“不在 AD 名单里的账号会在下次 MERGE 被置 status=0”，并明确 L48-L51 的预期是**3 个测试账号**（lead_reviewer01 / reviewer01 / reviewee01）被自动停用——这正是“测试账号不纳入 SSO”的自动化执行。

所以首次 MERGE 的预期结果是：**新增 1000+ 在册人员、把名单外的 3 个测试账号置 `status=0`**。执行前用一条只读查询确认现状（不同口径会改变首次执行的风险等级）：

```sql
-- 只读。全 AD → 首次 MERGE 会停用名单外账号；全 MANUAL → 13 条原样保留
SELECT source, status, COUNT(*) AS cnt
FROM dbo.CN_AME_SSO_User
GROUP BY source, status
ORDER BY source, status;
```

> 无论哪种口径，05 脚本干跑都会把“将停用名单”打印出来（脚本输出 5.2 段），必须让业务先过目再改成 `@Execute=1`。

---

## 5. 自动化合并方案设计

> 实现全部落在 [05_merge_stg_to_user.sql](../scripts/sql/05_merge_stg_to_user.sql)，逐条对应下列设计点。

### 5.1 幂等 upsert

- 用 `MERGE`，匹配键 `employee_no`（与实施方案 4.3 一致），**两侧都先用 `LOWER(LTRIM(RTRIM()))` 归一后比较**——生产排序规则若是 `_CS`，`LIGU` 与 `ligu` 精确比较不命中，会被当成新人并绕过唯一键建出第二个账号。
- 三段动作：`WHEN MATCHED`（有差异才 UPDATE）／`WHEN NOT MATCHED BY TARGET`（INSERT）／`WHEN NOT MATCHED BY SOURCE`（停用）。
- 幂等的判据：同一份 Stg 连跑两次，第二次的 `added=0`、`updated=0`、`disabled=0`（`last_batch_no` 也不会变，因为没有行被改写）。
- **为什么匹配键是工号而不是登录名**：登录名会变（改名、拼音重排），工号稳定；且 04 脚本的回退方案就是以工号对齐。

### 5.2 登录名归一（必须归一的三条理由）

归一口径：`LOWER(LTRIM(RTRIM(去掉 "DOMAIN\" 前缀)))`，与 `90_usermap_backfill.sql` L12-L16、`91` 第 5 节完全一致。

| 理由 | 具体后果（不是理论风险） |
|---|---|
| `DOMAIN\ligu` 形式 | Keycloak username 不接受反斜杠，不剥离会建出无法登录的账号 |
| 库排序规则 CI/CS 差异 | CS 库下唯一键拦不住 `Zhangy4` 与 `zhangy4` → 同一人两个账号。仓库已有实证：BOL `Yaolei` vs MSIA `yaole`、BOL `Zhangy4` vs MSIA `zhangya4`（`03_seed_users.sql` L131-L145） |
| Keycloak 查找是 `exact=true` | 大小写不一致就查不到旧账号，每次同步都“新建”，越跑越多 |

### 5.3 大小写重复建档的处理

分两层，**都不做自动合并**（与 `91` 第 4.2 节“不要批量自动合并”的既有口径一致）：

1. **名单侧**：归一后按 `employee_no` / `login_name` 分区去重，保留一条（规则：在职优先 → 工号字典序 → 行序），其余进拒绝集并打印。确定性规则，不会出现“今天留 A、明天留 B”。
2. **主表侧**：脚本第 2.x 节 + `91` 第 6 节查出“仅大小写不同的多行”时只告警，输出清单交人工裁决（保留有业务数据/有密码的那条）。
3. **写入侧**：INSERT 一律写 `LOWER` 值，所以**不会再产生新的大小写重复**。

### 5.4 必填字段缺失

| 字段 | 缺失时 |
|---|---|
| `login_name` | **整行拒绝**（空登录名无法建 Keycloak 账号），记入拒绝集，不中断整批 |
| `employee_no` | 回落为登录名（沿用 ps1 的“12.3 修订”口径，L321-L324） |
| 姓名/邮箱/手机/部门/职务 | 允许为空；**UPDATE 时用 `COALESCE` 保留主表已有值**，不会被空值冲掉（邮箱策略“暂不用管理”，只增不减） |
| `ad_object_guid` | 允许为空（现有灌数恒写 NULL） |
| 超长（登录名 >64、工号 >32） | 拒绝，避免被静默截断成两个不同的人 |

### 5.5 离职：禁用而不是删除

`WHEN NOT MATCHED BY SOURCE AND t.status = 1 AND t.source <> 'MANUAL'` → `UPDATE status = 0`。
不删除的原因：`UserMap`、`PermLedger`、Keycloak 账号、`SyncLog` 都以 `employee_no` 逻辑关联，物理删除会产生孤儿数据，也丢失“曾经是谁”的审计。
额外保护：`source='MANUAL'` 的行永不被自动停用（例外手工账号不会被 AD 名单误杀）。

### 5.6 审计列

| 列 | 何时写 |
|---|---|
| `created_at` | INSERT 时 = 批次时间，之后永不改 |
| `updated_at` | 每次 UPDATE |
| `synced_at` | 每次被 AD 批次改写（含停用），是“新鲜度监控”依据 |
| `source` | `AD` / `MANUAL` |
| `last_batch_no`（**本次新增**） | 形如 `20261109-061012`（UTC）。按批次号可一条 SQL 拉出“这一批动了哪些人” |

> 若生产不允许新增列，把脚本里 3 处 `last_batch_no` 赋值删掉即可，合并结果不受影响，只丢批次追溯。

### 5.7 事务、批量与性能

- **事务边界**：抢应用锁 → `BEGIN TRAN` → MERGE → 提交前自检（实际影响行数必须等于预览）→ 写 `SyncLog` → `COMMIT`。任一步失败走 `CATCH`：`ROLLBACK` → 在事务**外**补写一条 ERROR 日志 → 重新抛错。
- **并发互斥**：`sp_getapplock('CN_AME_SSO_User_MERGE', Exclusive, Transaction, 0)`，第二个批次拿不到锁就立刻退出，不会两批互相踩。
- **批量大小**：1000 级数据单批即可（实测毫秒到秒级）。上万级也无需分批；若将来到十万级，再按 `employee_no` 前缀或 `TOP (5000)` 循环分批，此时才需要按批提交——**当前不要提前引入，会破坏“全批原子”的语义**。
- **防错闸门**（任一命中直接中止，不写业务数据）：有效行为 0／行数骤降 >30%／停用占比 >10%／登录名撞人／中央表存在仅大小写不同的重复工号。

### 5.8 执行日志与重试

- 日志写入已有的 `CN_AME_SSO_SyncLog`（`phase='MERGE'`），与 ps1 共用一张表，实施方案 5.4 的监控 SQL 直接能看，不用改监控。
- **重试策略**：脚本幂等，所以重试 = 原样重跑。建议计划任务“失败后每 10 分钟重试，最多 3 次”，而不是在 T-SQL 内写循环——循环重试会把一个本可直接失败的脏批次反复撞。
- 中止/失败三种状态：`ABORTED`（闸门拦下，数据本身有问题）、`ERROR`（运行期异常）、`OK`。监控只看“当天有没有 `phase='MERGE' AND status='OK'`”。

---

## 6. 执行前置：只读核对生产实际结构

> 仓库 DDL 可能与生产不一致（有人手工改过表、或建库脚本只跑了一部分）。**先跑本节，全部符合预期再跑第 7 节。**
> 这些语句全部只读，可在任意有五表 SELECT 权限的账号执行。

```sql
USE CN_AME;

-- 6.1 库排序规则：CS=区分大小写（唯一键拦不住大小写重复），CI=不区分
SELECT name, collation_name, compatibility_level FROM sys.databases WHERE name = 'CN_AME';
-- 期望：能查到一行；collation_name 记下来（CI/CS 决定 §5.3 的严格程度）

-- 6.2 User 的唯一约束与索引是否真实存在
SELECT i.name AS index_name, i.is_unique, i.type_desc, c.name AS key_column
FROM sys.indexes i
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns c        ON c.object_id  = i.object_id AND c.column_id = ic.column_id
WHERE i.object_id = OBJECT_ID('dbo.CN_AME_SSO_User') AND ic.is_included_column = 0
ORDER BY i.name, ic.key_ordinal;
-- 期望：能看到 UQ_CN_AME_SSO_User_EmpNo、UQ_CN_AME_SSO_User_Login 两个 is_unique=1

-- 6.3 Stg 是否有唯一约束（仓库 DDL 没有，只有普通索引）
SELECT i.name, i.is_unique, i.type_desc
FROM sys.indexes i
WHERE i.object_id = OBJECT_ID('dbo.CN_AME_SSO_StgAdUser') AND i.type > 0;
-- 期望：is_unique 全为 0 → 依赖 05 脚本的“名单侧去重”，不能省

-- 6.4 列是否齐全（对照 01 脚本）
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME IN ('CN_AME_SSO_StgAdUser','CN_AME_SSO_User','CN_AME_SSO_UserMap')
ORDER BY TABLE_NAME, ORDINAL_POSITION;
-- 期望：与 §2.2 列清单一致；缺列/多列都要先对齐

-- 6.5 四表行数（确认“Stg 一千多、User 13”的现状）
SELECT (SELECT COUNT(*) FROM dbo.CN_AME_SSO_StgAdUser)  AS stg_rows,
       (SELECT COUNT(*) FROM dbo.CN_AME_SSO_User)       AS user_rows,
       (SELECT COUNT(*) FROM dbo.CN_AME_SSO_UserMap)    AS map_rows,
       (SELECT COUNT(*) FROM dbo.CN_AME_SSO_PermLedger) AS perm_rows;

-- 6.6 ★合并到底跑过没有（最关键的一条）
SELECT TOP 20 id, phase, src_rows, added, updated, disabled, reactivated, status, message, run_at
FROM dbo.CN_AME_SSO_SyncLog ORDER BY id DESC;
-- 期望：有 phase='LOAD' status='OK' 的记录（说明灌数跑过）；
--       若一条 phase='MERGE' 都没有 → 合并从未执行；若有 MERGE/ERROR → 合并跑过但失败了

-- 6.7 13 条的来源分布（决定首次合并会不会停用测试账号，见 §4.4）
SELECT source, status, COUNT(*) AS cnt FROM dbo.CN_AME_SSO_User GROUP BY source, status ORDER BY source, status;

-- 6.8 ★撞人预检★：名单登录名在中央表已存在、但工号不同
SELECT LOWER(LTRIM(RTRIM(CASE WHEN CHARINDEX('\', s.login_name) > 0
            THEN SUBSTRING(s.login_name, CHARINDEX('\', s.login_name)+1, 4000)
            ELSE s.login_name END)))      AS stg_login,
       s.employee_no AS stg_emp, u.employee_no AS central_emp, u.source, u.status
FROM dbo.CN_AME_SSO_StgAdUser s
JOIN dbo.CN_AME_SSO_User u
  ON LOWER(u.login_name) = LOWER(LTRIM(RTRIM(CASE WHEN CHARINDEX('\', s.login_name) > 0
            THEN SUBSTRING(s.login_name, CHARINDEX('\', s.login_name)+1, 4000)
            ELSE s.login_name END)))
WHERE LOWER(LTRIM(RTRIM(u.employee_no))) <> LOWER(LTRIM(RTRIM(ISNULL(s.employee_no, '')));
-- 期望：0 行。非 0 行时不要硬跑，按 §9 的三选一处理

-- 6.8b 中央表自身是否有“仅大小写不同的重复工号”（只有 _CS 排序规则下才可能出现）
--      有的话下面的合并会命中两行并整体失败，必须先人工裁决
SELECT LOWER(LTRIM(RTRIM(employee_no))) AS emp_lower, COUNT(*) AS cnt
FROM dbo.CN_AME_SSO_User
GROUP BY LOWER(LTRIM(RTRIM(employee_no)))
HAVING COUNT(*) > 1;
-- 期望：空

-- 6.9 名单侧脏数据：工号/登录名重复、残留域前缀
SELECT COUNT(*) AS total,
       COUNT(*) - COUNT(DISTINCT LOWER(LTRIM(RTRIM(employee_no)))) AS dup_empno,
       COUNT(*) - COUNT(DISTINCT LOWER(LTRIM(RTRIM(login_name))) ) AS dup_login,
       SUM(CASE WHEN CHARINDEX('\', login_name) > 0 THEN 1 ELSE 0 END) AS has_domain_prefix
FROM dbo.CN_AME_SSO_StgAdUser;
-- 期望：dup_empno=0、dup_login=0；has_domain_prefix 有值也正常（05 会剥离）

-- 6.10 我的账号有没有写权限
SELECT HAS_PERMS_BY_NAME('dbo.CN_AME_SSO_User', 'OBJECT', 'INSERT') AS can_insert,
       HAS_PERMS_BY_NAME('dbo.CN_AME_SSO_User', 'OBJECT', 'UPDATE') AS can_update,
       HAS_PERMS_BY_NAME('dbo.CN_AME_SSO_StgAdUser', 'OBJECT', 'SELECT') AS can_read_stg;
-- 期望：1/1/1。sso_sync_svc 已按 02_grants.sql L63-L67 授五表 DML
```

**另需在操作系统侧确认（不是 SQL）**：

```powershell
schtasks /query /tn "SSO_AD_Import" /v /fo LIST     # 计划任务是否存在、上次运行结果、下次运行时间
Get-ChildItem C:\sso\import\ad_users_*.csv | Sort-Object LastWriteTime -Descending | Select-Object -First 3
Get-Content C:\sso\logs\sync_ad_to_sso_$(Get-Date -Format yyyyMMdd).log -Tail 30
```

> 拿不准的现场值请在文档里标“需现场确认”，不要用默认值假装验证过（本项目既有约束）。

---

## 7. 小白版执行步骤（照着做）

### 第 0 步：备份（5 分钟，强烈建议）

```sql
-- 用 ytview 或有 CREATE TABLE 权限的账号执行；只读快照，不动原表
SELECT * INTO dbo.CN_AME_SSO_User_bak_20261109 FROM dbo.CN_AME_SSO_User;
SELECT COUNT(*) AS bak_rows FROM dbo.CN_AME_SSO_User_bak_20261109;   -- 应等于 13
```

> 若不允许建备份表，至少把 §6.5、§6.7 的输出截图存档，并导出 `SELECT employee_no, login_name, source, status FROM dbo.CN_AME_SSO_User` 为 CSV。

### 第 1 步：确认前置查询全部符合预期

跑 §6 的 6.1–6.10 + PowerShell 三行。**任何一项与“期望”不符就停**，按 §11 排查。

### 第 2 步：干跑（不写数据）

**先选执行方式**（两种都可以，A 更稳）：

| 方式 | 怎么做 | 适用 |
|---|---|---|
| A 整篇执行（推荐） | 打开文件后直接 `F5`，**不要只选中某几行** | 首次上线、怕漏节 |
| B 分段执行 | 从第 3 节开始逐节选中执行，顺序 3 → 4 → 5 → 6 | 只想重跑某一节 |

方式 B 有两个硬条件，违反了会报“未找到 #norm / #plan”：
1. **同一个 SSMS 窗口、同一条连接**，不要关窗口、不要重连（`#norm`/`#reject`/`#plan` 是临时表，只在本会话存在）；
2. 不能跳节；重跑第 3 节后必须重新跑 4 → 5 → 6（第 3 节会重建 `#norm` 并清掉旧 `#plan`）。

具体操作：

1. SSMS 连接 `IRSCNYTFINEREPORT.ap.inalfa.local` → 数据库 `CN_AME`（用 `ytview`，第 0 节 DDL 需要 ALTER）。
2. 打开 `统一身份认证实施\scripts\sql\05_merge_stg_to_user.sql`。
3. 确认**第 6 节**的 `DECLARE @Execute BIT = 0;`（全脚本只有这一个开关；第 5 节永远是只读预览，改它不会写库）。
4. `F5` 整份执行（或按方式 B 逐节执行到位）。

看这五段输出（在“消息”和“结果”两个页签里）：

| 输出 | 看什么 | 正常的样子 |
|---|---|---|
| 2.4 四表行数 | `stg_rows` / `user_rows` | `stg_rows` ≈ 1000+，`user_rows` = 13 |
| 3.4 归一化结果 | `stg_effective_rows` / `rejected_rows` | 前者 ≈ 1000+，后者 0（非 0 见 5.3） |
| 5.1 合并预览 | `would_insert` / `would_update` / `would_disable` / `prev_rows` | `would_insert` ≈ 1000-13；`would_disable` 0 或 3（测试账号） |
| 5.2 将停用的账号 | 名单里有哪些人会被停用 | 只有名单外的人，**不能出现在职真人** |
| 末尾 | “预览结束（未写入任何数据）” + “第 6 节未执行（@Execute = 0）” | 两行都出现，才算真干跑 |

### 第 3 步：正式执行（只跑第 6 节）

1. 把**第 6 节**的 `@Execute` 改成 `1`。
2. 只选中第 6 节执行（`#norm` / `#plan` 还在会话里，不要关 SSMS）。
   > 若中途关过窗口或重连，必须从第 3 节重新跑到第 5 节再来第 6 节，否则会报“未找到 #norm”。
3. 看 6.6 输出：`added`、`updated`、`disabled`、`batch_no`；`added` 应接近 5.1 的 `would_insert`。
   若报“提交前自检失败”，说明预览之后有人动了 Stg，已自动回滚，重跑第 3→5 节即可。

### 第 4 步：核对

```sql
-- 总数应变成 1000+（≈ 原 13 + 新增）
SELECT COUNT(*) AS user_total,
       SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) AS active_total,
       SUM(CASE WHEN source = 'AD' THEN 1 ELSE 0 END) AS from_ad
FROM dbo.CN_AME_SSO_User;

-- 本批次动了哪些人
SELECT COUNT(*) AS touched FROM dbo.CN_AME_SSO_User WHERE last_batch_no = N'<第3步的 batch_no>';

-- 日志
SELECT TOP 5 id, phase, src_rows, added, updated, disabled, status, message, run_at
FROM dbo.CN_AME_SSO_SyncLog ORDER BY id DESC;
-- 期望：最新一条 phase='MERGE', status='OK'
```

### 第 5 步：串行补跑 Keycloak 同步

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File C:\sso\scripts\sync_sso_to_keycloak.ps1 `
  -LogDirectory C:\sso\logs
```

> 幂等：已批量导入的账号会按 username 命中 → 整对象 PUT 更新，不会重复建号。
> 完成后核对 `SELECT COUNT(*) FROM dbo.CN_AME_SSO_User WHERE kc_user_id IS NULL;` 期望为 0。

### 第 6 步：UserMap 灌数（详见 §8 顺序说明）

按 [90_usermap_backfill.sql](../scripts/sql/90_usermap_backfill.sql) 的 F 段查未覆盖清单 → C 段模板逐条登记 → 跑 [91](../scripts/sql/91_usermap_integrity_checks.sql) 九组校验。

### 第 7 步：固化到每日任务

| 时间 | 动作 |
|---|---|
| 06:00 | `SSO_AD_Import`（LOAD + 内嵌 MERGE + KC 串联，现有 ps1） |
| 06:10 | 建议改为独立任务跑 `05_merge_stg_to_user.sql`（`sqlcmd -i ... -b`），失败重试 3 次 / 每 10 分钟。**注意**：`@Execute` 默认是 0，定时任务必须先把第 6 节改成 `1`，否则每天只会预览、不写库（若想用 `sqlcmd -v Execute=1` 传参，得把那行改成 `DECLARE @Execute BIT = $(Execute);`，本脚本未做该改动） |
| 06:20 | KC 同步 |
| 每天 | 监控：`phase='MERGE' AND status='OK'` 当日必须有一条；`status='ABORTED'/'ERROR'` 必须有人处理 |

> 长期建议（**本次未改动**）：把 ps1 里 L426-L483 的内嵌 MERGE 换成调用 05 脚本，避免两套合并逻辑漂移（见 §10 R4）。

---

## 8. 顺序依赖：合并 / KC 同步 / UserMap

```
[必须最先] 第 0 节 DDL（last_batch_no）
      │
      ▼
[前置] Stg 有当日名单（LOAD；由 ps1 或 IT 直接灌）
      │
      ▼
[关键路径] ★ MERGE（05 脚本）★ ──── 主表从 13 条变成 1000+ 条
      │
      ├──────────────► KC 同步（sync_sso_to_keycloak.ps1）
      │                  依赖：主表有人（读 User 全量）
      │                  不依赖：UserMap（脚本完全不读它）
      │
      └──────────────► UserMap 灌数（90 脚本 C 段）
                         依赖：主表 employee_no 已存在（模板里有 EXISTS 校验）
                         依赖：MSIA/BOL 本地账号已存在（否则映射指向空气）
                         不依赖：KC 同步
                              │
                              ▼
                    首次 OIDC 登录联调（两者缺一不可）
```

| 关系 | 结论 | 依据 |
|---|---|---|
| MERGE ↔ KC 同步 | MERGE **必须**先完成。先跑 KC 同步只会把 13 人同步进 Keycloak | `sync_sso_to_keycloak.ps1` L361-L362 只读 `CN_AME_SSO_User` |
| MERGE ↔ UserMap | MERGE **必须**先完成。UserMap 的 `employee_no` 要指向已存在的中央用户 | `90_usermap_backfill.sql` L118-L136 的模板带 `EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no=...)` |
| KC 同步 ↔ UserMap | **无依赖，可并行** | KC 脚本不读 UserMap；UserMap 只被业务系统登录时用 |
| UserMap ↔ 业务系统 | UserMap 必须在**首次 OIDC 登录之前**完成 | 缺失时业务侧按 `login_name` 自动建档 → 产生重复低权限账号（`91` 文件头 L5-L9） |
| 首次密码 | 在 KC 建号之后、登录之前 | 落地清单 M07；与本文三条链路无数据依赖 |

**一句话**：MERGE 是唯一的“必须第一个做”。KC 同步与 UserMap 相互独立，但都必须在“让真人登录”之前完成；顺序上先 KC（让账号存在），再 UserMap（让账号对上本地人）。

---

## 9. 撞人（闸门 4 不通过）的三选一处理

当 §6.8 查出“名单登录名在中央表已存在、但工号不同”，说明同一个登录名对应了两个工号口径（典型：种子里 `employee_no=login_name`，而 AD 名单里 `employeeNo` 是真工号）。**三种处理，按代价从低到高**：

1. **让 IT 修名单**（最干净）：AD 导出的 `employeeNo` 与登录名口径不一致时，由 IT 在 CSV 里同时给出稳定工号和登录名。
2. **以 AD 为准对齐中央表工号**（需人工确认后执行，且要先备份）：

```sql
-- [需人工确认后执行] 逐条确认后打开；一次只处理一个登录名，不要批量
UPDATE dbo.CN_AME_SSO_User
SET employee_no = N'<AD 里的真工号>', updated_at = SYSUTCDATETIME()
WHERE login_name = N'<登录名>';
-- 注意：UserMap / PermLedger 都按 employee_no 关联，改工号前先查这两张表有没有用到旧工号
SELECT * FROM dbo.CN_AME_SSO_UserMap    WHERE employee_no = N'<旧工号>';
SELECT * FROM dbo.CN_AME_SSO_PermLedger WHERE employee_no = N'<旧工号>';
```

3. **确认是同一人后走“停旧建新”**（`User` 的唯一约束逼出来的既有口径）：把旧行 `status=0` 且 `source='MANUAL'`（保护起来不再被 AD 改），让 AD 名单新建新行；随后 KC 侧禁用旧号、UserMap 指向新工号。

> **不要**为了“先跑通”去删唯一约束。`UQ_CN_AME_SSO_User_Login` 是防止一人两号最后一道闸门。

---

## 10. 风险与遗留（都已在仓库里找到证据）

| # | 风险 | 说明 | 建议 |
|---|---|---|---|
| R1 | `pwd_set` 可能被误标为 1 | `sync_sso_to_keycloak.ps1` L490-L505 的判定依据是“`requiredActions` 里没有 `UPDATE_PASSWORD`”，而不是“Keycloak 侧真的有密码”。批量导入的 1000+ 用户**既无密码也无 required action**，同步一轮就会被标成“已设密” | 上线前把这一条改为“查询 KC 用户是否已设密”，或本轮先不依赖 `pwd_set`；**需现场确认** |
| R2 | Stg 无唯一约束 | 手工/其它程序灌入重复工号会让 MERGE 报“同一行被多次更新”整体失败 | 05 脚本已在名单侧去重并记录拒绝行，不依赖 Stg 约束 |
| R3 | `ad_object_guid` 恒为空 | 现有灌数固定写 `DBNull`，所以“工号复用 → 两个人被合并成一个人”**当前没有防护** | 让 IT 在名单里补 GUID 后才可启用；否则靠 30%/10% 闸门兜底 |
| R4 | 两套 MERGE 实现漂移 | ps1 内嵌版无事务、无批次号、无撞人闸门；05 版有。今天改一处明天改另一处，行为会分叉 | 后续让 ps1 直接调用 05（本次**未改动** ps1） |
| R5 | 13 条的 `source` 现状未确认 | 全 `MANUAL` 还是全 `AD`，决定首次合并是否停用测试账号 | 先跑 §6.7 |
| R6 | 中央表停用 → Keycloak 停用之间存在窗口 | MERGE 只改中央表；Keycloak 要等 KC 同步跑完才禁用。中间窗口内离职者仍可能登录 | MERGE 与 KC 同步串成一条任务链（现状 ps1 已串联；单独跑 05 时必须紧接着跑 KC） |
| R7 | 名单被裁剪会误停用 | “不在名单即停用”依赖名单完整性；若某天 IT 只投递了在册子集，会大面积停用 | 已有 30% 骤降 / 10% 停用占比双闸门；首次执行务必人工过目停用名单 |

---

## 11. 常见失败与排查

| 现象 | 最可能原因 | 怎么办 |
|---|---|---|
| 报 `Msg 102 Incorrect syntax near ';'`，紧接着 `Msg 137 Must declare the scalar variable "@src_rows"` | 旧版脚本第 3.2 节少一个右括号：`LEN(LOWER(LTRIM(RTRIM(CASE…END)))` 只有 3 层，应为 4 层。**2026-11-09 已修复**（现为 `END)))) > 64`）。另外，单独选中第 3 节执行也一定会报 137——`@src_rows` 是别的批里的变量 | 确认手上脚本是修复版（搜 `END)))) > 64`）；优先整篇执行 |
| 报 `未找到临时表 #norm` / `未找到临时表 #plan`（错误号 51010 / 51011） | 分段执行时跳节、换过 SSMS 窗口/连接，或重跑第 3 节后直接跳到第 6 节 | 同一窗口按 3 → 4 → 5 → 6 顺序重跑；不要关窗口 |
| 报 `缺少列 CN_AME_SSO_User.last_batch_no` | 第 0 节 DDL 没跑成功（当前账号无 ALTER 权限） | 换 `ytview`/DBA 跑整份一次；或删掉 3 处 `last_batch_no` 赋值 |
| 报 `登录名撞人 N 条` | 工号口径不一致（种子里工号=登录名） | 按 §9 三选一 |
| 报 `行数骤降` | 当日名单不完整或 Stg 被手工清过 | 找 IT 确认投递；确认无误后人工放宽 `@RowDropAbortRatio` 再跑 |
| 报 `停用占比过高` | 名单只含在职子集，或整个部门数据缺失 | 同上，**不要**为了跑通直接抬高阈值 |
| 报 `另一个合并批次正在运行` | 上一次批次没提交完（锁未释放） | 等 1 分钟重试；持续出现查 `sys.dm_tran_locks` 有无残留事务 |
| 报 `中央表存在仅大小写不同的重复工号` | `_CS` 排序规则下的历史遗留（同一工号存了 `LIGU` 和 `ligu` 两行） | 用 `91_usermap_integrity_checks.sql` 第 6 节定位，人工裁决保留哪一条（优先留 `kc_user_id` 有值/有密码/有业务数据的那条），**不要自动合并** |
| 报唯一键冲突（`UQ_CN_AME_SSO_User_Login` / `_EmpNo`） | 归一化没覆盖到的脏数据，或并发写入 | 查 §6.9；确认后把冲突行给 IT 修 |
| 提交前自检失败 | 合并期间有人改动了 Stg | 重跑干跑确认数字，再重跑正式 |
| 合并成功但 Keycloak 没有新用户 | KC 同步没跑或令牌/证书问题 | 单独跑 `sync_sso_to_keycloak.ps1` 看日志；见 `docs/keycloak-msia-sso-guide-for-beginners.md` |
| 用户能登 Keycloak 但业务系统里是新建的低权限号 | UserMap 没登记 | 跑 `91` 第 4 节，按 `90` C 段补映射 |

---

## 12. 待现场确认清单（不要用默认值假验证）

| 项 | 核查方式 | 影响 |
|---|---|---|
| 生产 `CN_AME` 排序规则 CI/CS | §6.1 | 大小写重复会不会被唯一键拦住 |
| 两个唯一约束是否真实存在 | §6.2 | 缺失时闸门 4 是唯一防线 |
| `last_batch_no` 是否允许新增 | 第 0 节执行结果 | 不允许则删 3 处赋值 |
| AD 名单 `employeeNo` 口径（真工号 or 登录名） | §6.9 + 找 IT 确认 | 决定是否会撞人 |
| 13 条 `source` 现状 | §6.7 | 首次合并是否停用测试账号 |
| 计划任务 `SSO_AD_Import` 是否存在 | `schtasks /query` | 决定“每天到底有没有自动跑” |
| `pwd_set` 语义是否可靠 | 抽 1 个批量导入用户在 Keycloak 控制台看是否有密码 | 决定要不要先修 R1 |
| Keycloak 现有用户数 | 控制台 Users 列表底部计数 | 与主表对账的基线 |

---

## 13. 存储过程与定时作业

> 工件：[06_merge_stg_to_user_proc.sql](../scripts/sql/06_merge_stg_to_user_proc.sql)（过程）
> ｜[07_merge_job_setup.sql](../scripts/sql/07_merge_job_setup.sql)（授权 + Agent 作业）

> **最容易看错的一点（务必先读）**：`EXEC` 的返回结果是「**本次运行的那一行**」，永远只有 1 行，且每次调用的 `run_id` 都不同。**它不是历史**。查历史必须查表：
>
> ```sql
> SELECT TOP 30 run_id, run_at, batch_no, executed, gate_status, added, updated, disabled
> FROM dbo.CN_AME_SSO_MergeRun
> ORDER BY run_id DESC;
> ```
>
> 连跑三次就该看到三行（三次调用的 `run_id` 各不相同）。**同一秒内点了两次**：第二次会在入口被 `51009` 拒绝且不落行，所以正常情况下不会出现两行同 `batch_no`；若历史数据里已经有两行 `batch_no` 相同、`run_at` 同秒，那是**两次独立调用**（旧版过程或显式传同一 `@BatchNo`），不是一次插了两行（判读方法见 §13.7.8）。

### 13.1 05 脚本与存储过程的关系

| | [05_merge_stg_to_user.sql](../scripts/sql/05_merge_stg_to_user.sql) | `dbo.usp_SSO_MergeStgToUser`（06） |
|---|---|---|
| 定位 | **人工验证 / 参考实现**。按 `GO` 分 7 节，适合第一次上线时逐段看输出、逐段确认 | **生产入口**。单批、可参数化，供 SQL Server Agent 每日调用 |
| 执行方式 | SSMS 打开整篇或按 3 → 4 → 5 → 6 分段；开关是第 6 节的 `DECLARE @Execute BIT = 0`（要改脚本本体） | `EXEC ... @Execute = 0/1`，开关是入参，**不改脚本** |
| 输出 | 多段 `SELECT`（行数、预览、被停用明细、拒绝明细…） | **单一汇总结果集（1 行 = 本次运行记录，`run_id` 在最前）** |
| 日志 | 写 `SyncLog`（phase=MERGE）；不落明细表 | 写 `SyncLog`（phase=MERGE）+ 每次运行落 1 行 `CN_AME_SSO_MergeRun`（见 §13.7） |
| 逻辑 | 归一化、拒绝集、5 道闸门、MERGE、停用、审计字段、单事务、`sp_getapplock` | **完全一致**（逐段移植，阈值同为 30% / 10%） |

两版共用同一把应用锁资源名 `CN_AME_SSO_User_MERGE`，**不会同时跑**：手工跑 05 时作业会因拿不到锁而失败（反之亦然），这是有意的互斥。

**首次上线仍建议先跑 05**：它的分段输出能让人看到“将停用谁”“拒绝了哪些行”，比只看 1 行汇总更有判断依据。确认无误后再交给定时作业。

### 13.2 过程签名与两种模式

```sql
EXEC CN_AME.dbo.usp_SSO_MergeStgToUser
     @Execute        = 0,      -- 0=干跑（默认）；1=实跑
     @BatchNo        = NULL,   -- 空=自动生成 yyyyMMdd-HHmmss（UTC）
     @SampleMax      = 50,     -- 汇总里 reject_sample 最多列多少条拒绝样本
     @StgWaitSeconds = 2;      -- Stg 装载稳定性预检采样间隔（0=跳过；见 §13.7.9）
```

- **干跑（`@Execute = 0`）**：只读 Stg 与主表，算归一化/拒绝/5 道闸门/预览，返回 1 行；**不写业务表、不写 SyncLog**，唯一写入是往 `CN_AME_SSO_MergeRun` 追加 1 行运行记录（见 §13.7）。闸门不通过也不报错，用 `gate_status = 'ABORT'` + `gate_reason` 体现。
- **实跑（`@Execute = 1`）**：闸门不通过 → 先落 1 行运行记录（`ABORT`）+ 写 `SyncLog(ABORTED)`，再 `THROW`（作业显示失败）；通过则在单事务内 MERGE，并在同一事务里落 1 行运行记录（`OK`）；任何运行期错误 `ROLLBACK` 后在事务外落 1 行运行记录（`ERROR`）+ 失败日志，再 `THROW`，不会随回滚消失。
- **返回只有 1 行**：结果集只含本次那一行（`run_id` 在最前），**不是历史**；查历史查表并 `ORDER BY run_id DESC`（§13.7.8）。
- **每次调用只落 1 行**：四条终止路径（干跑 / ABORT / 成功 / ERROR）互斥，路径之间没有“继续往下走”的穿透（§13.7.8 有逐路径核对表）。
- **同一秒重复提交会被拒（`51009`）**：自动批次号按秒生成，同一秒内的第二次调用会撞同一 `batch_no`；过程在计算前直接 `THROW 51009` 且**不落行**，避免“一次提交、两行记录”被误读（§13.7.7）。


汇总结果集字段：

| 字段 | 含义 |
|---|---|
| `run_id` | 本次运行记录在 `CN_AME_SSO_MergeRun` 中的主键（放在最前，便于直接回查） |
| `batch_no` | 本次批次号；审计列 `CN_AME_SSO_User.last_batch_no` 用的就是它 |
| `gate_status` / `gate_reason` | `OK` 或 `ABORT` 及原因（行数为 0 / 骤降 / 停用占比 / 撞人 / 大小写重复工号） |
| `stg_effective_rows` / `rejected_rows` | 归一化后有效行、被拒绝行 |
| `would_insert` / `would_update` / `would_disable` | 干跑算出的预期影响行数 |
| `added` / `updated` / `disabled` / `reactivated` | 实跑的实际影响行数（干跑时全为 0） |
| `manual_protected` | 被 `source='MANUAL'` 保护、本次不动的人数 |

> 为什么干跑也要算 `would_*`：实跑的“提交前自检”要用这组数字与 MERGE 实际影响行数比对，防止预览之后有人改了 Stg。过程内保证同一口径。

### 13.3 部署与挂作业（照做即可）

1. **建过程**：SSMS 打开 06 整篇执行（需要 `CREATE PROCEDURE` 权限，通常 `ytview`/DBA）。
   文件顶部“第 0 节”会先建运行记录表 `CN_AME_SSO_MergeRun`（已存在则跳过）；过程内还有一份同样的兜底 DDL，即使漏跑第 0 节也能首次执行。
   业务表不需要本过程做 DDL：前提是 05 的**第 0 节**已跑过（`last_batch_no` 已存在），缺列会直接 `THROW 51000` 提示。
2. **干跑确认**：`EXEC CN_AME.dbo.usp_SSO_MergeStgToUser @Execute = 0;`
   期望 `gate_status = 'OK'`，`would_*` 与 05 第 5 节预览的数字一致。
3. **手工实跑一次**：`EXEC CN_AME.dbo.usp_SSO_MergeStgToUser @Execute = 1;`
   期望 `gate_status='OK'`，`added` 与名单人数吻合；再查 `SyncLog` 最新一条 `phase='MERGE' AND status='OK'`。
4. **授权**：改 07 第 1 段的 `@JobLogin`（作业运行账号），整段执行。
   只需 `GRANT EXECUTE`：过程与表同库、同属 `dbo`，走**所有权链**，不需要给表授 `INSERT/UPDATE`。若将来把表挪到别的 schema/属主，所有权链会断，才需要补表级权限。
5. **建作业**：改 07 第 2 段的 `@JobOwner`（与 `@JobLogin` 保持一致），执行后作业 `SSO_Merge_StgToUser` 与计划 `SSO_Merge_Daily_0200` 建好。
6. **验证作业**：`EXEC msdb.dbo.sp_start_job @job_name = N'SSO_Merge_StgToUser';` 然后看 07 第 3 段的历史查询或 SSMS 作业活动监视器。

> **频率**：07 里默认“每日 02:00”（`@freq_type=4`、`@active_start_time=020000`，服务器本地时间），**这只是占位值**。离职账号多久失效还没定，正式频率请改 07 第 2.4 段的 `sp_add_schedule` 参数，或用 07 末尾的 `sp_update_schedule` 示例改，不要沿用默认值上线。

### 13.4 作业失败怎么查（作业历史 / SyncLog / MergeRun 三处对齐）

| 看哪里 | 看什么 | 判读 |
|---|---|---|
| **`msdb` 作业历史** | 步骤 1 是否红色失败；消息里是否有 `Msg 51001/51002/51003/51000/51006/51007/51008/51009` | 能看到**错误号与原因**，但看不到过程返回的结果集（TSQL 步骤只记录 PRINT/错误） |
| **`CN_AME_SSO_SyncLog`** | 最新一条 `phase='MERGE'` 的 `status` 与 `message` | `OK`=成功入库；`ABORTED`=闸门拦下（`message` 含原因与 batch=…）；`ERROR`=运行期错误已整体回滚 |
| **`CN_AME_SSO_MergeRun`** | 最新 `run_id` 的 `gate_status` 与各明细列 | 每次运行都有一行（含干跑/中止/报错），能看到“当时算出了多少行”，并据 `run_id` 与该次 SyncLog 对齐（见 §13.7） |

```sql
-- 一条 SQL 同时看“作业有没有跑”和“跑成了什么”
SELECT TOP 5 id, phase, src_rows, added, updated, disabled, status, message, run_at
FROM dbo.CN_AME_SSO_SyncLog WHERE phase = N'MERGE' ORDER BY id DESC;
```

常见错误号：

| 错误号 | 含义 | 处理 |
|---|---|---|
| 51000 | 缺 `last_batch_no` 列 | 用 `ytview`/DBA 跑 05 第 0 节 |
| 51001 | 闸门不通过 | 看 `gate_reason`；按 §9 / §11 处理，**不要抬阈值蒙过去** |
| 51002 | 没抢到合并锁 | 另一个批次在跑（有人手工跑 05，或上一次没提交完）→ 等一会儿再手工触发 |
| 51003 | 提交前自检失败 | 预览后 Stg 被人改动 → 重跑干跑再实跑 |
| 51004 | `@BatchNo` 超过 32 字符 | 换短批次号或留空自动生成 |
| 51006 | 该 `@BatchNo` 已被历史批次用过 | 换一个，或留空 |
| 51007 | 检测到外层事务（`@@TRANCOUNT > 0`） | 在事务外调用；会话开了 `IMPLICIT_TRANSACTIONS` 时先 `SET IMPLICIT_TRANSACTIONS OFF` |
| 51008 | Stg 在 6 秒内持续变化，疑似正在装载 | 等 AD 名单 LOAD 完成后再跑；合并与装载**不可并行**（§13.7.9） |
| 51009 | 同一秒内已存在相同自动批次号的运行记录 | 疑似重复提交（连按两次执行 / 手工与作业同时触发）→ 确认后重试；确需同秒连跑，显式传不同的 `@BatchNo` |
| 51020 / 51021 | 07 授权段：账号不存在 / 过程不存在 | 先建账号、先执行 06 |

### 13.5 与 05 的差异（都是新增能力，不是改逻辑）

1. **批次号可外部传入**，因此新增“批次号唯一性”前置校验（51006）——05 的批次号是内部生成的，不存在这个场景。
2. **干跑不写 SyncLog、不改业务表**：05 的第 5 节本来就是只读预览，过程把这个约束固化进代码；干跑唯一的写入是运行记录表（§13.7）。
3. **闸门在事务之前**：闸门阶段尚未写入任何业务数据，所以“无需回滚”；实跑时由代码写 `ABORTED` 日志后 `THROW`，保证作业失败可见。真正的数据写入仍是一个单事务，出错整体回滚。
4. **不对业务表做 DDL**（唯一的 DDL 是缺表时自建运行记录表）、不改写 `login_name`、不动 `MANUAL` 行、离职只停用不删除——与 05 完全一致。
5. **外层事务守卫（51007）**：05 是人工脚本，没人会在 `BEGIN TRAN` 里跑；过程要给作业调用，必须保证运行记录不会被外层回滚吞掉，所以入口先查 `@@TRANCOUNT`。
6. **Stg 装载稳定性预检（51008）**：05 靠人工挑时间跑，天然避开装载窗口；过程要能定时跑，必须自己识别“正在装载”（§13.7.9）。
7. **同秒重复提交防护（51009）**：自动批次号精度是秒，同一秒内的第二次调用会生成相同的 `batch_no`；过程入口按“本表是否已有该批次号”判定并拒绝（不落行），避免两行共用同一批次号被误读成“一次调用插了两次”。

### 13.6 05 的已知缺陷（本轮按要求**未修改** 05）

| # | 现象 | 影响 | 建议 |
|---|---|---|---|
| D1 | 第 3.1 节在 `WHERE` 里过滤了 `LEN(工号) <= 32`，但第 3.2 节的拒绝集只记录“登录名为空/超长”，**工号超长的行被静默丢弃** | `rejected_rows` 少算，问题行查不到 | 两版都应把工号超长也写入拒绝集（一行 SQL 的改动） |
| D2 | 闸门 2 的基准取 `phase IN ('MERGE','LOAD')` 的最近一条 `src_rows`，LOAD 记的是原始行数、MERGE 记的是归一后行数，两个分母混用 | 判据不稳，可能误报“行数骤降” | 统一只与 `phase='MERGE'` 的 `src_rows` 比；或改用 MergeRun 的 `stg_effective_rows` |
| D3 | 05 第 6 节的开关是脚本内的 `DECLARE @Execute BIT` | 定时任务直接用 05 必须改文件，且改完容易忘 | 生产改用 06 过程（入参开关），05 只用于首次验证 |

**D2 什么时候会误判**（这次 2851 vs 2851 恰好相等，所以没暴露）：

- LOAD 的 `src_rows` = 从 CSV 灌进 Stg 的**原始行数**（`sync_ad_to_sso.ps1` L553-L558，取 `$clean.Rows.Count` 前清洗、但未做库内归一化）。
- MERGE 的 `src_rows` = **归一化 + 去重 + 拒绝之后**的有效行数。
- 如果上一次日志恰好是 `phase='LOAD'`（例如当天只跑了 LOAD、合并没跑），基准就是“原始行数”；而下一次合并读到的是“归一后行数”。两者之差 = 被拒绝 + 仅大小写重复被去重的行。
- 例：AD 给 3000 行原始，其中 400 行登录名为空/超长被拒绝、再 200 行大小写重名被去重 → 归一后 2400。`2400 < 3000 × 0.70 = 2100`？不成立，但若拒绝+去重达到 900 行（30%），就会**误报骤降并 ABORT**，而实际上名单只少了几个人。
- 反过来也会漏判：上次是 LOAD 的 2400（原始），本次归一后 1700，表面降 29% 不报，实际有效行降 29% 同样不报——阈值只是个粗筛。
- 根治方向（待你确认后再改 05 与 06）：闸门基准只取 `phase='MERGE'` 的 `src_rows`，或直接取 `CN_AME_SSO_MergeRun` 里最近一条 `executed=1 AND gate_status='OK'` 的 `stg_effective_rows`（后者与新表口径完全一致，推荐）。**本轮未改代码，保持两版一致。**

以上三点在 06 中**保持与 05 一致**（D1/D2 为口径一致性，D3 由过程本身解决），待你确认后再两处同步修。

### 13.7 运行记录表 `CN_AME_SSO_MergeRun`（每次运行落一行）

> 工件：[06_merge_stg_to_user_proc.sql](../scripts/sql/06_merge_stg_to_user_proc.sql) 顶部“第 0 节”（建表）、同文件“附录 A”（历史查询与保留策略示例）

#### 13.7.1 命名理由

| 选择 | 理由 |
|---|---|
| 前缀 `CN_AME_SSO_` | 与 `CN_AME_SSO_User`、`StgAdUser`、`UserMap`、`SyncLog`、`PermLedger` 同一前缀，库里一眼能辨明属于同一套 SSO 资产，按前缀查询/授权也方便 |
| 后缀 `MergeRun` | 记录粒度是“一次合并运行、一行”，与 `SyncLog`（一次事件一行）在语义上区分开；不叫 `...Log` 是为了不与 `SyncLog` 混淆 |
| 放 `dbo` | 与其它五张表同 schema、同属主；过程与表同库，走所有权链，作业账号只需 `EXECUTE` |

#### 13.7.2 列：一组汇总 + 一组环境信息

| 组 | 列 | 说明 |
|---|---|---|
| 汇总（过程结果集原样） | `batch_no`、`executed`、`gate_status`、`gate_reason`、`stg_effective_rows`、`rejected_rows`、`disabled_rows_in_source`、`manual_protected`、`would_insert`、`would_update`、`would_disable`、`added`、`updated`、`disabled`、`reactivated`、`prev_success_rows`、`computed_at` | 与过程返回列逐列对应，字段顺序不变 |
| 环境（过程自动填） | `run_id`（`BIGINT IDENTITY` 主键）、`run_at`、`run_by`、`host_name`、`reject_sample`（`NVARCHAR(MAX)`，`reason + 空格 + 登录名`、以竖线连接的样本） | `run_at` 默认 `SYSUTCDATETIME()`、`run_by` 默认 `SUSER_SNAME()`、`host_name` 默认 `HOST_NAME()` |

`computed_at`（计算时刻）与 `run_at`（落库时刻）分开保留：两者差得越大，说明本次 MERGE 越慢，便于排查长事务。

`run_id` 是 `BIGINT IDENTITY(1,1)` **自增主键**，过程**从不给它赋值**（只在写入后用 `SCOPE_IDENTITY()` 取回本次值）。它只需要“每行唯一、可按大小排序”，**不需要改，也不要改成复合主键或手工编号**。`DELETE` / 事务回滚造成的号段空洞是正常现象（只有 `TRUNCATE` 才会从 1 重来），不能据此判断“丢了记录”。

#### 13.7.3 什么时候写（只有 INSERT，从不 UPDATE / MERGE）

| 触发 | `executed` | `gate_status` | 说明 |
|---|---|---|---|
| 干跑结束 | 0 | `OK` / `ABORT` | 不碰业务表与 SyncLog，唯一写入就是这行 |
| 实跑闸门不通过 | 1 | `ABORT` | 落行 → 写 `SyncLog(ABORTED)` → `THROW 51001` |
| 实跑成功 | 1 | `OK` | 与 MERGE 同一事务：COMMIT 一起可见，ROLLBACK 一起消失 |
| 实跑运行期错误 | 1 | `ERROR` | 事务已回滚，在 `CATCH` 里于事务外落行 → 写 `SyncLog(ERROR)` → `THROW`；嵌套 `TRY/CATCH` 保证“记录失败”不会掩盖原始错误 |
| Stg 装载未稳定（51008） | 0 / 1 | `ERROR` | 预检阶段就终止：落行 → 写 `SyncLog(ERROR)` → `THROW`，**不做归一化、不做闸门判定** |
| 前置校验失败（51000 / 51006） | 0 / 1 | `ERROR` | 尚未开始计算，数字列留空，`gate_reason` 写原因 |
| 外层事务（51007） | — | 不落行 | 记录逃不出调用方事务，直接拒绝（§13.7.7） |
| `@BatchNo` 超长（51004） | — | 不落行 | 超长值装不进 `batch_no NVARCHAR(32)`，属调用参数错误 |
| 自动批次号同秒重复（51009） | — | 不落行 | 参数级拒绝，避免两行共用同一 `batch_no`（§13.7.7） |

只追加、不回写，所以每行都是不可变的运行事实；要“纠正”只能再跑一次、留一条新行。

#### 13.7.4 与 `SyncLog` 的分工（同一事实不重复记）

| | `CN_AME_SSO_MergeRun` | `CN_AME_SSO_SyncLog` |
|---|---|---|
| 粒度 | 每次运行 1 行（含干跑、含失败尝试） | 每个事件 1 行（`phase` = LOAD / MERGE / KC / KC_EMERGENCY） |
| 记什么 | **明细数字**：源行、拒绝、预期 `would_*` 与实跑实际值 | **成败与异常**：`status`（OK / ABORTED / ERROR）与 `message` 文本 |
| 用途 | 趋势、对账、连续失败判断、运行审计 | 统一监控与告警，与其它 phase 同表比较 |
| 关联方式 | 自己的 `run_id` | `message` 里带 `run_id=…` 与 `batch=…` |

一句话：**`SyncLog` 回答“成没成、为什么”，`MergeRun` 回答“这次到底动了多少行”**。MergeRun 不写状态文本，SyncLog 不写明细列。

#### 13.7.5 查询示例

最近 30 次（干跑与实跑都在）：

```sql
SELECT TOP 30
       run_id,
       CAST(((run_at AT TIME ZONE 'UTC') AT TIME ZONE 'China Standard Time') AS DATETIME2(0)) AS run_at_local,
       batch_no, executed, gate_status,
       stg_effective_rows, rejected_rows, added, updated, disabled, reactivated,
       would_insert, would_update, would_disable, run_by, host_name
FROM dbo.CN_AME_SSO_MergeRun
ORDER BY run_id DESC;
```

实跑趋势（近 30 天，看人数与新增/停用是否平稳）：

```sql
SELECT CAST(((run_at AT TIME ZONE 'UTC') AT TIME ZONE 'China Standard Time') AS DATE) AS run_date_local,
       COUNT(*)    AS runs_per_day,
       MAX(run_id) AS last_run_id
FROM dbo.CN_AME_SSO_MergeRun
WHERE executed = 1
  AND run_at >= DATEADD(DAY, -30, SYSUTCDATETIME())   -- 过滤仍按 UTC，与存储口径一致
GROUP BY CAST(((run_at AT TIME ZONE 'UTC') AT TIME ZONE 'China Standard Time') AS DATE)
ORDER BY run_date_local DESC;
```

连续失败检测（最近 5 次实跑里有几次非 OK）：

```sql
SELECT COUNT(*) AS fails_in_last5,
       CASE WHEN COUNT(*) >= 3 THEN N'需人工介入' ELSE N'可观察' END AS verdict
FROM (SELECT TOP 5 gate_status FROM dbo.CN_AME_SSO_MergeRun
      WHERE executed = 1 ORDER BY run_id DESC) t
WHERE gate_status <> N'OK';
```

> 三条都在 06 的“附录 A”里，已注释掉，取消注释即可执行。

#### 13.7.6 保留策略（可选，不建定时清理）

- 量级：每日 1 次运行约 1 行，一年不到 400 行；只有反复干跑调试才会快速累积。
- 本仓库**不提供定时清理作业**，也不替你决定保留多久；确需清理时，由管理员手工执行附录 A.5 的示例。
- 两种口径（二选一，不要同时上）：
  - **按行数**保留最近 N 条（推荐，不受时区/时钟影响）：删除“最近 N 条的最小 `run_id`”之前的行，分批 500 条。
  - **按天**保留 180 天：`DELETE ... WHERE run_at < DATEADD(DAY, -180, SYSUTCDATETIME())`，同样分批。
- 清理前先导出 CSV 备份：这是运行审计，删掉无法从别处恢复。本表 `run_at` / `computed_at` 都是 **UTC**，比较时用 `SYSUTCDATETIME()`，不要混用 `GETDATE()`（差 8 小时）。

#### 13.7.7 什么时候**不会**留下记录（别把“没行”当成丢数据）

| 情形 | 现象 | 设计原因 |
|---|---|---|
| 外层事务（51007） | 报错，表里无新行 | `INSERT` 无法逃出调用方事务；过程宁可拒绝，也不写一条随时会消失的记录。会话开了 `SET IMPLICIT_TRANSACTIONS ON` 时同样命中，先关掉再调用 |
| `@BatchNo` 超过 32 字符（51004） | 报错，表里无新行 | 超长值写不进 `batch_no NVARCHAR(32)`，属调用参数错误，不是运行事实 |
| 自动批次号同秒重复（51009） | 报错，表里无新行 | 同一秒内的第二次提交在入口被拒，避免两行共用同一 `batch_no` 被误读成“一次插了两次” |
| 调用方没有 `EXECUTE` 权限 | 报错，表里无新行 | 过程根本没执行 |
| 运行记录写入本身失败（锁/磁盘满） | 原始错误照常抛出，先出现 `PRINT '[警告] 失败记录写入也失败了'` | `ERROR` 路径用嵌套 `TRY/CATCH` 保护落行；落行失败不掩盖原始错误，但这一行确实不存在 |
| 成功路径的 `OK` 行随事务回滚 | 看不到该行，但会多一行 `ERROR` | `OK` 行与 MERGE 同一事务；没提交就没有“成功事实”，`CATCH` 会在事务外补记 `ERROR` |
| 运行记录表被人手工清空 / 删表 | 历史行消失 | 第 0 节与过程内兜底 DDL 都只做 `IF OBJECT_ID(...) IS NULL CREATE TABLE`，**从不 DROP / TRUNCATE**；少行只可能来自人工操作或 §13.7.6 的保留策略 |

判读顺序：**先看错误号**，再判断是不是设计上的“不落行”；`51004 / 51007 / 51009` 三种情况本来就不会有记录。

#### 13.7.8 一次调用一行：逐路径核对与连跑判读

**为什么能保证“一次调用只插一行、只做一次闸门判定”**：四条终止路径互斥，且全部是单向的。

| 终止路径 | `INSERT` 位置 | 是否在事务内 | 结束方式 |
|---|---|---|---|
| 干跑 | 第 4 节，`@Execute = 0` 分支 | 否（无事务） | 插入后 `RETURN`，后面代码都不执行 |
| 实跑 ABORT | 第 5 节开头（异常闸门判定之后） | **否**（`BEGIN TRANSACTION` 还没开始） | 插入 → 写 `SyncLog(ABORTED)` → `THROW 51001`，必然进不了 `BEGIN TRY` |
| 实跑 OK | 第 5.5 步（MERGE 与提交前自检之后） | **是** | 插入 → 写 `SyncLog(OK)` → `COMMIT` |
| 实跑 ERROR | `CATCH` 内、`ROLLBACK` 之后 | **否** | 插入 → 写 `SyncLog(ERROR)` → `THROW` |
| 前置失败（51000/51006/51008） | 对应校验段 | 否 | 插入 → `THROW` |

过程体内**没有** `WHILE`/`GOTO`/递归自调用（唯一的新循环是 §13.7.9 的 Stg 预检采样，它只读 Stg、不写任何表），也没有 `INSERT ... EXEC`。因此“同一次调用插两行”在代码上不成立。

**连跑的三种判读**：

- 一次调用 = 1 行；同一秒内的第二次调用会被 `51009` 拒掉。
- 若看到两行 `batch_no` 相同、`run_at` 同秒：这不是一次调用插了两次，而是**两次独立调用**（旧版过程，或显式传入了同一 `@BatchNo`）。用 `run_by`/`host_name` 区分调用源：`ytview` = 人工，`sso_sync_svc` = 作业。
- `run_id` 出现空洞（如 12 之后跳到 15）：`DELETE`、回滚或 identity 缓存造成，属正常；只有 `TRUNCATE` 才会重新从 1 开始。

**自验方法（清空 → 只跑一条 EXEC → 必须 1 行）**，脚本见 06 附录 A.6：

```sql
-- 1) 备份后清空（DELETE 不重置 identity）
SELECT * INTO dbo.CN_AME_SSO_MergeRun_bak FROM dbo.CN_AME_SSO_MergeRun;
DELETE FROM dbo.CN_AME_SSO_MergeRun;

-- 2) 只执行这一条，且只按一次 F5
EXEC CN_AME.dbo.usp_SSO_MergeStgToUser @Execute = 1;

-- 3) 期望 1；等于 2 才说明“一次调用插了两行”
SELECT COUNT(*) AS rows_after_one_exec FROM dbo.CN_AME_SSO_MergeRun;
```

> **清空 `MergeRun` 不会重置闸门基线**：`prev_success_rows` 取自 `CN_AME_SSO_SyncLog`（`phase IN ('MERGE','LOAD') AND status='OK'` 的最近一条 `src_rows`），与本表无关。想“从零重试”让闸门安静下来，必须一并处理 `SyncLog` 里的成功记录（例如只保留一条基准、或把当天 `MERGE` 成功行标为 `status='ABORTED'`），否则仍然会拿昨天的 2851 去比：
>
> ```sql
> -- 看清当前基线来源
> SELECT TOP 1 id, phase, src_rows, status, run_at
> FROM dbo.CN_AME_SSO_SyncLog
> WHERE phase IN (N'MERGE', N'LOAD') AND status = N'OK' AND src_rows IS NOT NULL AND src_rows > 0
> ORDER BY id DESC;
> ```

#### 13.7.9 时间戳口径与“合并 vs 装载”并发约束

**时间戳现状**：`run_at`、`computed_at`、`batch_no` 全部是 **UTC**（`SYSUTCDATETIME()`），所以本地 14:55 会显示成 06:55。两个方案：

| | 方案 A：存 UTC，查询时转（**默认实现**） | 方案 B：直接存服务器本地时间 |
|---|---|---|
| 写入 | `SYSUTCDATETIME()`（现状，无需改表） | 改默认值 / 过程变量为 `SYSDATETIME()` |
| 读取 | 查询加 `AT TIME ZONE`（§13.7.5 已改） | 直接读，最直观 |
| 风险 | 查询忘记转会看错 8 小时；依赖 SQL 2016+ 的 `AT TIME ZONE` | 服务器换时区/迁移后，历史行语义随机器漂移，新旧数据不可比；有夏令时的区域还会出现重复/缺口 |
| 跨时区协作 | 全球统一，可换算 | 需先问“这是哪台机器的时间” |
| 结论 | **采用**（本仓库所有表都是 UTC，保持一致） | 不采用 |

标准写法（两步，缺一不可）：

```sql
CAST(((run_at AT TIME ZONE 'UTC') AT TIME ZONE 'China Standard Time') AS DATETIME2(0)) AS run_at_local
```

第一个 `AT TIME ZONE 'UTC'` 是“声明这个值属于 UTC”，第二个才是“转换到中国标准时间”；只写一个会得到带偏移的 `datetimeoffset`，直接比较/展示仍会踩坑。

**合并与装载不可同时进行（运维约束）**：

- 装载端是 `DELETE FROM dbo.CN_AME_SSO_StgAdUser` + `SqlBulkCopy`，**两步之间没有任何锁**；合并端只对 MERGE 加 `sp_getapplock`，挡不住装载窗口。中途读 Stg 会看到 0/1/部分行，进而被“行数骤降”闸门拦下（实测 `stg_effective_rows = 1`、`would_disable = 2729` 的那次就是这样）。
- 过程侧的对策是 **0.2 预检（51008）**：默认每 2 秒采样一次 `COUNT(*)` 与 `MAX(loaded_at)`，连续两次一致才继续，最多 3 轮（约 6 秒）；仍变化就落一行 `ERROR` 后 `THROW 51008`，**不会**带着半成品去做闸门判定。`@StgWaitSeconds = 0` 可关闭预检（只建议在确知无装载时用）。
- 预检是“尽力而为”，不是锁。要真正互斥，建议装载端在 `Invoke-StageLoad` 前后也拿同一把应用锁（资源名与合并完全相同；本轮**未改** ps1，只给片段）：

```sql
-- 装载前（ps1 中 DELETE 之前）
EXEC sp_getapplock @Resource = N'CN_AME_SSO_User_MERGE', @LockMode = N'Exclusive',
                   @LockOwner = N'Session', @LockTimeout = 0;

-- 装载完成（BulkCopy 之后）
EXEC sp_releaseapplock @Resource = N'CN_AME_SSO_User_MERGE', @LockOwner = N'Session';
```

> 若账号报 `sp_getapplock` 权限错误，请让 DBA 确认该账号在 `CN_AME` 中可执行 `sp_getapplock` / `sp_releaseapplock`。
>
> 调度层面的约束同样成立：**合并作业必须排在 LOAD 成功之后**（看 `SyncLog` 最新 `phase='LOAD' AND status='OK'` 的 `run_at` 即可判断装载是否已完成），两者不要共用同一时间窗。
