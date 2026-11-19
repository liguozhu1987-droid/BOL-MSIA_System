============================================================
  BOL 管理分析平台 - 独立可执行程序部署包
  打包时间: 2026-11-06 16:38:10
============================================================

[部署步骤]
  1. 将本 ZIP 整体复制到目标机器
  2. 右键解压到任意目录（例如 D:\BOLServer\）
  3. 按需创建数据库配置文件（见下方"数据库配置"）
  4. 运行 BOLServer.exe            # 默认监听 0.0.0.0:8090
  5. 浏览器访问 http://127.0.0.1:8090/

  !!! BOLServer.exe 不是单文件程序，必须与 _internal 目录一起部署 !!!
      只复制 exe 会报"启动前置条件未满足：静态文件目录不存在"。

[部署后自检]
  以下任一项缺失，说明解压/复制不完整，或已被杀毒软件删除：
    _internal\staticfiles\index.html          前端入口
    _internal\staticfiles\assets/index-DQ7r91ah.js
                                                前端入口 JS（缺失则页面白屏）
    _internal\staticfiles\admin\              Django 后台静态资源
    _internal\apps\                           业务模块资源（migrations 等）
  本次打包静态文件总数: 214 个
  本次 BOLServer.exe 体积: 10.3 MB

[数据库配置]
  1. 复制 db_config.ini.example 为 db_config.ini（与 exe 同目录）
  2. 确认 driver 与目标机器"已安装"的 ODBC 驱动完全一致，否则接口全部 500：
       PowerShell 执行  Get-OdbcDriver | Select-Object Name
       常见值: ODBC Driver 17 for SQL Server / ODBC Driver 18 for SQL Server
  3. 不创建 db_config.ini 时，程序使用内置默认值（ODBC Driver 18），
     但内置默认不含口令，必须先按第 1 步创建 db_config.ini 才能连接数据库
  4. 报错 IM002 / Data source name not found 即为驱动名不匹配

[端口配置]
  默认端口: 8090
  自定义:   BOLServer.exe --port 9000
  指定网卡: BOLServer.exe --host 127.0.0.1

[冒烟测试]
  服务启动后依次验证（PowerShell）：
    Invoke-WebRequest http://127.0.0.1:8090/ -UseBasicParsing
    Invoke-RestMethod http://127.0.0.1:8090/api/auth/guest-login/ -Method POST
  两者均应返回 200。若登录接口返回 500，优先排查 db_config.ini 的驱动名。

[杀毒软件注意事项]
  本程序为 PyInstaller 打包产物，部分杀软会启发式误报。建议：
  1. 将部署目录加入杀软白名单/排除项（最有效）
  2. 不要对 exe 或 _internal 目录做二次加壳、压缩、加密
  3. 若文件被杀软删除，请勿直接重装，先按《打包防杀软误报方法.md》
     第 6 节的恢复手册找回源码，再重新打包

============================================================
