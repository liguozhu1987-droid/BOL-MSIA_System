# 应用侧证书信任配置（MSIA / BOL → Keycloak）

> 适用：两系统后端通过 `https://sso.ap.inalfa.local` 访问 Keycloak（discovery、token、JWKS）。
> 代码现状：BOL `apps/users/oidc.py` 与 MSIA `app/core/oidc.py` 均使用 **stdlib `urllib` + 默认 SSL 上下文**，
> 默认 **校验证书链与主机名**；未提供 `verify=False` 开关，也不应新增。
> 自签/内部 CA 未受信时的现象：`ssl.SSLCertVerificationError: CERTIFICATE_VERIFY_FAILED`，
> 登录跳转失败，日志已明确输出"OIDC HTTPS 证书校验失败"。

## 1. 三种信任方式与适用性

| 方式 | 做法 | 对本项目是否有效 | 说明 |
|---|---|---|---|
| `SSL_CERT_FILE` | 指向 PEM 证书包（企业根 CA + 公共根） | **有效（首选）** | Python `ssl` 的 OpenSSL 默认校验路径会读取该变量；PyInstaller 打包的 exe 同样继承进程环境变量 |
| `REQUESTS_CA_BUNDLE` | 指向 PEM | **无效** | 只对 `requests`/`urllib3` 生效；本项目用的是 `urllib.request`，且 PyJWT 的 `PyJWKClient` 也走 urllib |
| Windows 证书存储 | `certutil -addstore -f Root xx.cer` | **不一定** | Python/OpenSSL 是否读取 Windows 根存储取决于版本与打包方式，**不能假定生效**；装了也必须用第 3 节脚本实测 |

结论：生产统一用 `SSL_CERT_FILE`，且变量值必须是**合并包**——只放企业根 CA 会替换掉 OpenSSL 默认根证书集合，
导致访问其他 HTTPS 地址失败。合并方式：企业根 CA PEM + Python 自带 `cacert.pem` 拼接。

```powershell
# 1) 企业根 CA 转 PEM（已有 .pem 可跳过）
certutil -encode enterprise-root-ca.cer enterprise-root-ca.pem
# 去掉 BEGIN/END 行的头尾说明后即为 PEM 主体

# 2) 找到当前 Python 的默认 CA 包 (打包环境用打包机同版本 Python)
python -c "import ssl; print(ssl.get_default_verify_paths().cafile)"

# 3) 合并（企业根在前，公共根在后）
Get-Content enterprise-root-ca.pem, <上一步输出的 cafile> | Set-Content C:\sso\conf\ca-bundle.pem -Encoding ascii
```

## 2. 注入位置（按运行方式）

| 运行方式 | 注入位置 |
|---|---|
| NSSM 服务（Keycloak 与本项目服务） | `nssm set <服务名> AppEnvironmentExtra` 追加 `SSL_CERT_FILE=C:\sso\conf\ca-bundle.pem`，随后 `nssm restart <服务名>` |
| 计划任务（同步脚本） | 任务"操作"里设置环境变量，或在包装 ps1 开头 `$env:SSL_CERT_FILE='C:\sso\conf\ca-bundle.pem'` |
| 手工命令行验证 | 当前会话 `$env:SSL_CERT_FILE='C:\sso\conf\ca-bundle.pem'` |
| 打包 exe | 优先由服务/任务注入环境变量；不要写死在 exe 内 |

> 证书文件放在受限目录（仅运行账号可读），不要放仓库或共享盘。

## 3. 验证脚本（不依赖 curl）

保存为 `C:\sso\conf\verify_keycloak_tls.py`，用**与生产相同的运行账号/环境**执行。

```python
"""验证到 Keycloak 的 TLS 信任链与主机名；失败时非 0 退出。"""
import socket
import ssl
import sys
import urllib.request

HOST = "sso.ap.inalfa.local"
PORT = 443
ISSUER_PATH = "/realms/inalfa/.well-known/openid-configuration"

def main() -> int:
    ctx = ssl.create_default_context()  # 默认校验证书链 + 主机名
    try:
        with socket.create_connection((HOST, PORT), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=HOST) as tls:
                cert = tls.getpeercert()
                print("TLS OK")
                print("subject:", dict(x[0] for x in cert["subject"]))
                print("issuer :", dict(x[0] for x in cert["issuer"]))
                print("notAfter:", cert["notAfter"])
        with urllib.request.urlopen(f"https://{HOST}{ISSUER_PATH}", timeout=10) as resp:
            body = resp.read(200).decode("utf-8", "replace")
            print("discovery:", resp.status, body[:120])
    except ssl.SSLCertVerificationError as e:
        print(f"FAIL: 证书校验失败 -> {e}", file=sys.stderr)
        print("检查: SSL_CERT_FILE 是否指向含企业根的 PEM; 证书 SAN 是否含 sso.ap.inalfa.local", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

验证判据：

- 退出码 0，且 `TLS OK` + `discovery: 200`；
- `subject` 的 SAN/CN 必须是 `sso.ap.inalfa.local`（**不是** `localhost`）；
- `issuer` 应为内部 CA；若浏览器能开、脚本不能开，说明运行账号没读到 `SSL_CERT_FILE`（服务未重启或环境变量没生效）。

## 4. 两系统运行检查

```powershell
# 服务进程是否拿到变量
Get-CimInstance Win32_Service -Filter "Name='<MSIA服务名>'" | Select-Object Name, StartMode
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\<MSIA服务名>\Parameters' | Select-Object AppEnvironmentExtra

# 以运行账号执行验证
& C:\sso\conf\verify_keycloak_tls.py  # 或 python C:\sso\conf\verify_keycloak_tls.py
```

## 5. 红线

1. **禁止** `ssl._create_unverified_context()`、`verify=False`、`CERT_NONE`；当前代码没有此类开关，不要新增。
2. **禁止** 为绕过证书问题把 issuer 改成 `http://` 或 `https://127.0.0.1:8443`——会破坏 `iss` 校验与令牌一致性。
3. 证书到期前 30 天更新 PEM 并重启两个应用服务（CA 更换不影响 Keycloak 数据）。
