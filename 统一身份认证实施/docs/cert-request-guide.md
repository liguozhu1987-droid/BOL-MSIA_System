# 服务器证书申请指南（Keycloak 入口 · AD CS）

> 依据：`keycloak/keycloak.conf`（hostname=sso.ap.inalfa.local）、`keycloak/clients.md`、门项 G4/U1/U2。
> 适用范围：给 Keycloak 对外入口申请服务器证书。**MSIA/BOL 维持内网 HTTP，不需要证书**。
> 结论先行：整条统一登录链路**只需要 1 张证书**，装在 IIS ARR 的 443 上。

---

## 1. 先回答三个问题

### 1.1 "什么级别"的证书

公网 CA 的 DV/OV/EV 分级**不适用**于企业 CA。AD CS 里没有这套分级，只有"证书模板"之分：

| 维度 | 公网证书 | 本方案（企业 CA） |
|---|---|---|
| 验证级别 | DV / OV / EV | 无此概念，模板+AD 权限即准入 |
| 证书类型 | 按域名数分（单域/多域/通配符） | 同左 |
| 密钥强度 | RSA2048/ECC | **RSA 2048 + SHA-256**（内网标准配置，IIS 兼容性最好） |
| 本方案选型 | — | **Web Server（服务器身份验证）模板** |

关键：扩展密钥用法（EKU）必须是**服务器身份验证**（OID 1.3.6.1.5.5.7.3.1），不能是客户端身份验证或代码签名模板——选错模板浏览器直接报警。

### 1.2 要几张、装在哪

| 系统 | 入口地址 | 协议 | 证书需求 |
|---|---|---|---|
| Keycloak | `sso.ap.inalfa.local:443`（IIS ARR → 127.0.0.1:8443） | HTTPS | **必需，装 IIS ARR** |
| MSIA Report | `172.26.2.203:8078`（现网）/ `msia.ap.inalfa.local`（未来 U1） | HTTP | 不需要（将来若上域名，用通配符覆盖） |
| BOL 管理系统 | 内网地址待定稿（U2/G4） | HTTP | 不需要（同上） |

### 1.3 交付物是什么文件

| 文件 | 内容 | 用途 |
|---|---|---|
| `.csr` | 证书签名请求（公钥+申请信息） | 提交给 CA 的"申请表"（路线 A 生成） |
| `.cer` | 证书本体（公钥+身份+CA 签名） | CA 签发后返回（路线 A 拿这个） |
| `.pfx` | **证书+私钥+证书链**，密码保护 | IIS 导入/迁移（路线 B、IT 代申请拿这个） |

---

## 2. 申请规格单（照此填写或转发 IT）

| 字段 | 推荐值 | 说明 |
|---|---|---|
| 证书模板 | `Web Server`（服务器身份验证） | IT 侧模板名可能显示为"Web 服务器"，同一模板 |
| 通用名称 CN | `sso.ap.inalfa.local` | 仅标识用，**浏览器验的是 SAN** |
| 使用者可选名称 SAN | 见第 3 节三选一 | **必须填**，只填 CN 会被 Chrome/Edge 判不安全 |
| 密钥算法 | RSA | |
| 密钥长度 | 2048 | 内网足够；4096 握手略慢无必要 |
| 签名哈希 | SHA-256 | |
| 加密服务提供程序 | Microsoft RSA SChannel Cryptographic Provider | IIS CSR 向导默认项 |
| EKU / 用途 | 服务器身份验证 | 模板决定，勿选自签名/客户端/代码签名 |
| 私钥可导出 | **仅 .pfx 路线勾选** | CSR 路线（A）不需要，私钥本就在服务器上 |
| 有效期 | 模板默认（常见 1–2 年） | 记到期日，提前 30 天续期 |
| 友好名称 | `sso.ap.inalfa.local` | IIS 证书列表里好认 |
| 组织/单位/城市 | 公司注册名 / IT 部门 / 实际城市 | 部分模板从 AD 自动带，问 IT 即可 |

---

## 3. 域名范围三选一

| 方案 | SAN 内容 | 优点 | 缺点 | 建议 |
|---|---|---|---|---|
| 通配符 | `*.ap.inalfa.local` | 一张覆盖 sso/msia/bol 及**未来所有接入系统** | 部分保守 IT 不批 | **首选**（技术交底书面向多系统接入） |
| SAN 多域 | `sso.ap.inalfa.local` + `msia.ap.inalfa.local` + `bol.ap.inalfa.local` | 精确可控 | 加系统要重新签 | 次选 |
| 单域 | `sso.ap.inalfa.local` | 最小申请，最快批 | 未来上域名要重签 | 兜底（先让 SSO 跑起来） |

> 注意：通配符不覆盖 `ap.inalfa.local` 裸域本身（本方案不需要），也不覆盖多级子域（不需要）。

---

## 4. 申请路线

### 路线 A：IIS 生成 CSR + certsrv 提交（推荐）

私钥在 IIS 服务器本地生成、**全程不出服务器**，不需要私钥可导出权限，安全面最小。

1. IIS 管理器 → 选中**服务器节点**（不是站点）→ "服务器证书" → 右侧"**创建证书申请**"；
2. 通用名称填 `sso.ap.inalfa.local`，组织填公司名、组织单位填 IT/信息部；
3. 加密服务提供程序选 `Microsoft RSA SChannel Cryptographic Provider`，位长 `2048`；
4. 保存 CSR：`C:\certreq\sso.csr.txt`（Base64 文本，含 `-----BEGIN CERTIFICATE REQUEST-----`）；
5. 浏览器打开 `https://<CA主机名或IP>/certsrv` → "申请证书" → "高级证书申请" → "**使用 base64 编码的 CMC 或 PKCS #10 提交证书申请**"；
6. 粘贴 CSR 全文 → 证书模板选 `Web Server` → 提交（若 CA 设了"挂起审核"，需 IT 批准后刷新页面下载）；
7. 下载证书：选 **Base64 编码** → `sso.cer`；
8. （仅两级 CA 架构）certsrv 首页 → "下载 CA 证书、证书链或 CRL" → 下载 CA 证书链 → `certlm.msc` → 中间证书颁发机构 → 导入；
9. IIS → "服务器证书" → 右侧"**完成证书申请**" → 选 `sso.cer` → 友好名称 `sso.ap.inalfa.local` → 确定，列表出现该证书（颁发者=企业 CA）即成功；
10. 站点绑定：Default Web Site 或专用站点 → 绑定 `https` / 端口 `443` / 主机名 `sso.ap.inalfa.local` / **勾选"需要服务器名称指示(SNI)"** / 选该证书；
11. ARR 规则：`sso.ap.inalfa.local` → 反代到 `https://127.0.0.1:8443`，转发 `X-Forwarded-Proto: https`、`X-Forwarded-Host: sso.ap.inalfa.local`；
12. DNS：让 IT 加 A 记录 `sso.ap.inalfa.local → IIS 服务器 IP`。

### 路线 B：certsrv 网页直接申请（产出 .pfx）

适合 IT 代申请或需要在别的机器上生成再导入的场景。

1. `https://<CA>/certsrv` → 申请证书 → 高级证书申请 → "**创建并向此 CA 提交申请**"；
2. 证书模板选 `Web Server`；姓名填 `sso.ap.inalfa.local`；
3. 密钥选项：创建新密钥集，**勾选"将密钥标记为可导出"**，2048，SHA-256；
4. 若表单有"使用者可选名称/其他属性"，按第 3 节填 SAN（模板不允许自定义 SAN 时走路线 A，CSR 里天然带 SAN）；
5. 提交 → 安装证书，或"导出"为 `.pfx`（设密码）→ IIS 导入。

### 路线 C：IT 代申请

把第 2 节规格单 + 第 3 节域名方案发给 IT，要求交付：**含完整链、可导出的 `.pfx`（或按路线 A 各步骤协助）**，并告知用途是 IIS 443 绑定。

---

## 5. 与 Keycloak / IIS ARR 的衔接要点

| 项 | 要求 | 不一致的后果 |
|---|---|---|
| 证书域名 | 必须覆盖 `sso.ap.inalfa.local` | keycloak.conf `hostname-strict=true`，Host 头对不上直接 404 |
| DNS A 记录 | `sso.ap.inalfa.local` 解析到 IIS 服务器 | 证书有效也访问不了 |
| 443 SNI | 新站点绑定必须勾 SNI、填主机名 | 帆软站点已占 443，不勾 SNI 会互相抢流量（必要时给帆软站点也补 SNI） |
| ARR 头转发 | `X-Forwarded-Proto: https`、`X-Forwarded-Host: sso.ap.inalfa.local` | redirect_uri 变 127.0.0.1，OIDC 回调失败（TR12） |
| issuer 口径 | `https://sso.ap.inalfa.local/realms/inalfa` | 两系统 config 的 issuer 必须与此一致 |
| Keycloak 8443 | 本机回环，**自签证书即可**（ARR 不校验）；配置见 `keycloak.conf` 的 `https-certificate-file` 两项 | `http-enabled=false` 下没配证书，Keycloak 起不来 |

设密邮件里的落地链接（account client）也指向 `https://sso.ap.inalfa.local`，域名一致才能不报警、链接不被邮件网关拦。

---

## 6. 验证清单（拿到证书后逐项过）

- [ ] `certlm.msc` → 个人 能看到证书，双击"证书路径"显示**链完整到根**，无黄色警告；
- [ ] 证书"详细信息"→ 使用者可选名称含目标域名，增强型密钥用法=服务器身份验证；
- [ ] 内网任一台电脑浏览器访问 `https://sso.ap.inalfa.local` → 锁标志、无警告；
- [ ] `https://sso.ap.inalfa.local/realms/inalfa/.well-known/openid-configuration` 返回 JSON（OIDC discovery 正常）；
- [ ] `sync_sso_to_keycloak.ps1` 试跑同步（8443 自签，脚本内有跳过开关）；
- [ ] Keycloak admin 控制台 `https://sso.ap.inalfa.local` 可登录；
- [ ] 帆软站点仍正常（SNI 未互相影响）。

## 7. 常见坑（按翻车频率排序）

1. **SAN 没填只填 CN**：Chrome/Edge 58 起只认 SAN，必报警；
2. **私钥没勾"可导出"**：.pfx 路线事后导不出来，只能重签；
3. **证书链不完整**：部分客户端报警，IIS 完成申请前先装中间 CA（certsrv 下载 CA 链）；
4. **443 SNI 冲突**：帆软站点已在 443，新绑定不勾 SNI 会抢默认站点流量；
5. **证书域名与 keycloak.conf hostname 不一致**：OIDC issuer 校验失败，登录链路断；
6. **DNS 没加 A 记录**：证书白申请；
7. **通配符预期错误**：`*.ap.inalfa.local` 不覆盖 `ap.inalfa.local` 裸域；
8. **到期无提醒**：证书 1–2 年到期，台账记到期日，提前 30 天重走申请。

## 8. 到期与续期

到期前 30 天按同一模板重新申请一张（路线 A/B 均可），在 IIS 里换绑（或改 ARR 指向），旧证书删除。台账记录：签发 CA、序列号、SAN 列表、到期日、存放位置（IIS 服务器证书存储）。

---

## 9. 实际环境信息与 ITSM 申请单（2026-11-03）

### 9.1 已确认的环境事实

| 事实 | 来源 | 影响 |
|---|---|---|
| 企业 CA 已存在：`ap-SRV-APSH-PKI-01-CA-1` | 现网证书签发者 | "有没有企业 CA"问题有答案，按现有 CA 申请即可 |
| CA 为 **AD CS 企业 CA**（Issuer DN 含 `DC=local,DC=inalfa,DC=ap`；带 Microsoft Template 扩展；CDP/AIA 均走 AD LDAP 内网发布） | FNR 证书文件解析 | 根证书已随 AD GPO 分发（现网无浏览器警告即证）；certsrv 入口应为 `https://SRV-APSH-PKI-01.ap.inalfa.local/certsrv`（若装了 Web Enrollment） |
| 公司使用 **Venafi** 管理证书生命周期 | IT 申请单模板 | 证书可能由 Venafi 自动签发/推送/续期；需先确认 IIS 服务器是否已纳入 Venafi |
| FNR（FineReport）证书已解析：CN=`SRV-APSH-FNR-1P`，O=`Inalfa-roofsystems`，OU=`ICT`，C=CN/ST=Shanghai，RSA2048/SHA256，**SAN 仅 `SRV-APSH-FNR-1P` 和 `SRV-APSH-FNR-1P.AP.INALFA.LOCAL`**（裸主机名 + FQDN，无友好域名），EKU=客户端+服务器身份验证，模板 OID `1.3.6.1.4.1.311.21.8.13432777.13574192.6048166.15200517.11483974.67.13277543.14704384`，2024-12-11→**2026-12-11 到期**（2 年） | 用户导出证书文件（openssl/certutil 解析） | **FNR 按裸服务器名访问，通配符覆盖不了裸主机名 → 策略 B 排除**；FNR 到期续期由 IT 按原模板原 SAN 单独处理，与本次申请解耦 |
| IIS 443 已被既有站点（帆软）占用 | 本方案既定 | 新绑定必须 SNI + 主机名 |
| **部署服务器确认**：`IRSCnKettle01.ap.inalfa.local`（Computer name `IRSCnKettle01`，域成员 `ap.inalfa.local`，即原 Kettle 所在服务器） | 用户提供系统属性截图 | Keycloak 部署目标机；证书绑定、Venafi 归属、DNS 指向全部落到这台机。域成员身份 = CA 根证书信任已就绪（GPO），certsrv/CSR 路线可用 |

### 9.2 提交给 ITSM 的申请单（按本方案填写）

| 字段 | 填什么 |
|---|---|
| 请求类型 | Service Request（服务请求），非 Incident |
| 协议 / 认证方式（如表单有此项） | **OIDC**（授权码流 + PKCE S256）。Keycloak 为 OIDC Provider，MSIA/BOL 为 Relying Party；**不涉及 SAML**——两个系统均无 SAML SP 组件，Keycloak 侧也未配 SAML client |
| 主题 | 为统一身份认证（SSO）Keycloak 服务申请 TLS 证书：CN=`sso.ap.inalfa.local`（内网 HTTPS 入口） |
| 用途 | IIS ARR 443 绑定，Keycloak 26 对外唯一入口（OIDC issuer `https://sso.ap.inalfa.local/realms/inalfa`）；OIDC 登录、设密邮件链接、admin 控制台均依赖此域名 HTTPS；后续同机 MSIA/BOL 等系统复用。**Keycloak 部署于 `IRSCnKettle01.ap.inalfa.local`（域成员）** |
| 证书主体 | CN=`sso.ap.inalfa.local`（现网证书 CN 用服务器名如 `SRV-APSH-FNR-1P`；本证书建议直接用域名作 CN，关键是 SAN 必须含 `sso.ap.inalfa.local`） |
| SAN 列表 | `sso.ap.inalfa.local`（必需）；`msia.ap.inalfa.local`、`bol.ap.inalfa.local`（同机规划中）；**如政策允许请直接签通配符 `*.ap.inalfa.local`**，一次覆盖现有与未来系统。FNR 证书按裸服务器名访问、不在本证书覆盖范围，本次不涉及替换 |
| 模板 | 与 `SRV-APSH-FNR-1P` 相同模板（其 EKU 已含客户端+服务器身份验证，SAN 可自定义）；若 IT 侧模板名不同，退而求其次选 Web Server（服务器身份验证） |
| 签发 CA | `ap-SRV-APSH-PKI-01-CA-1`（与现网在用证书一致） |
| 组织 / 单位 | O=`Inalfa-roofsystems`，OU=`ICT`（与现网证书一致，CA 团队可能按模板自动带） |
| 目标服务器 | `IRSCnKettle01.ap.inalfa.local`（域成员 `ap.inalfa.local`；Venafi 纳入判断、.pfx 导入都针对这台机） |
| 密钥与哈希 | RSA 2048，SHA-256（如公司有标准按其标准） |
| 私钥 | 需可在 `IRSCnKettle01` 上导入绑定；**是否由 Venafi 推送：请确认该服务器是否已纳入 Venafi**——已纳入则走 Venafi 自动签发+续期（私钥不需导出）；未纳入则请提供可导出的 `.pfx`（含完整证书链） |
| 绑定方式 | IIS + ARR 部署于 `IRSCnKettle01`（2026-11-03 定稿；该机默认无 IIS 角色，需 IT 先安装 IIS + ARR + URL Rewrite）；443 无既有占用，直接绑 `sso.ap.inalfa.local`，通配符证书一张覆盖 |
| DNS 配合 | 需 IT 同步加 A 记录：`sso.ap.inalfa.local → IRSCnKettle01 的内网 IP`（IP 待补充）；否则证书有效也解析不到 |
| 期望完成 | Keycloak 上线前（建议 2026-11 月底前）。本证书为新证书，**不依赖** FNR 证书 2026-12-11 到期日——FNR 按裸服务器名访问，通配符覆盖不了它，其续期由 IT 按原模板原 SAN 单独处理（策略 A 已定稿） |
| 审批人 | 直属主管 |
| 附件 | ① FNR 证书解析结果（证明已核对 SAN、确认不冲突）；② 本申请单 |

> **工单类目说明（2026-11-03）**：用户实际挂在 ITSM 的 SSO 类目下（该类目带 OIDC/SAML 协议下拉，选 **OIDC**）。若该 SSO 类目覆盖平台基础设施申请（证书/DNS/部署），一张工单全涵盖即可；**若 SSO 类目仅面向"业务系统接入统一认证"**，证书会被路由到错误的处理团队——此时在工单描述首行注明"本次为 SSO 平台自身基础设施申请（Keycloak 入口证书），非业务系统接入"，或拆分为两张工单（接入类 + 证书类）。

### 9.3 结论与剩余确认项

**策略已定稿：A（只申请 SSO 证书，不碰 FNR）**

依据：FNR 证书 SAN 只有裸主机名 `SRV-APSH-FNR-1P` 和 FQDN `SRV-APSH-FNR-1P.AP.INALFA.LOCAL`，通配符 `*.ap.inalfa.local` 覆盖前者之外的所有子域但**覆盖不了裸主机名**，且无法确认用户是否在用裸名书签——替换它风险大于收益。FNR 2026-12-11 到期是 IT 的常规续期事项，按原模板原 SAN 重签即可，与本项目时间线解耦。

剩余 3 个确认项：

1. **IIS 服务器是否在 Venafi 管理范围**：决定交付路线（Venafi 自动推送+续期 vs 手工 `.pfx`）；
2. **通配符审批**：多数公司对通配符管得严，理由写"统一身份认证平台 + 多系统同机部署，一张覆盖所有接入系统"；若只批单域/SAN 列表也能接受（先 sso，后追加）；
3. **到期日登记**：有效期按现网惯例 2 年，SSO 证书预计 2028 年底到期，登记台账。

**技术核对结论（无需行动）**：
- SNI 共存无风险：客户端访问 `SRV-APSH-FNR-1P[.ap.inalfa.local]` 时发送的 SNI 与 `sso.ap.inalfa.local` 不匹配，IIS 回落到 FNR 的默认/非 SNI 绑定；我们的 SNI 绑定只捕获 `sso.ap.inalfa.local`。加绑定后仍建议回归验证一次 FNR；
- CDP/AIA 走 AD LDAP 内网发布，域内机器吊销检查天然可达，无需额外配置；
- **未来可选优化**：2026-12 月 FNR 续期时，可建议 IT 把 FNR 迁到友好域名（如 `finereport.ap.inalfa.local`）并改用我们的通配符证书，届时全部 Web 服务统一在 `*.ap.inalfa.local` 之下管理。
