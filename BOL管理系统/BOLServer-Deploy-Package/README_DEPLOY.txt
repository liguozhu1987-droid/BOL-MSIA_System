BOL 管理分析平台 - 独立可执行程序部署包
打包时间: 2026-09-30 09:31:22

[部署方式 - 重要]
  1. 将 BOLServer-Deploy-Package.zip 整体复制到目标机器
  2. 右键解压到任意目录（如 D:\BOLServer\）
  3. 运行 BOLServer.exe --port 8090
  4. 浏览器访问 http://127.0.0.1:8090/

  !!! 注意：BOLServer.exe 不是单文件程序，必须与 _internal 目录一起部署 !!!
  !!! 切勿只复制 BOLServer.exe 一个文件，否则启动时报错：
      [错误] 启动前置条件未满足：
        - 静态文件目录和前端 dist 均不存在（已检查内部和外部路径）

[部署后自检]
  确认以下内容存在（任一缺失说明解压/复制不完整）：
    _internal\staticfiles\index.html         前端入口
    _internal\staticfiles\assets\            前端 JS/CSS 资源（100 个文件）
    _internal\staticfiles\admin\             Django 后台静态资源
    _internal\apps\                          业务模块
  本次打包静态文件总数：265 个（前端 101 + admin 127 + rest_framework 27 + 其他）

[端口配置]
  默认端口: 8090
  自定义端口: BOLServer.exe --port 9000
  监听所有地址: BOLServer.exe --host 0.0.0.0 --port 8090

[系统要求]
  - Windows Server 2016+ 或 Windows 10/11
  - ODBC Driver 17 for SQL Server（需预装）
  - 无需安装 Python 或任何依赖
  - 能够访问 SQL Server（HRDB 和 CMC 数据库）

[目录结构]
  BOLServer\
    BOLServer.exe              可执行程序（约 10 MB）
    _internal\                 内部依赖和资源文件（必须与 exe 同目录）
      staticfiles\             Django 静态文件（含前端构建产物，265 个）
      apps\                    业务模块
    db_config.ini.example      数据库配置示例
    README_DEPLOY.txt          本说明文件

[注意事项]
  1. 首次运行可能较慢（初始化资源）
  2. 防火墙需放行对应端口
  3. 如需后台服务，可使用 NSSM 注册为 Windows 服务
  4. 数据库连接配置参考 db_config.ini.example
  5. 若服务器杀毒软件隔离了 _internal 下的文件（PyInstaller 程序偶被误报），
     请将 BOLServer 目录加入杀毒软件白名单后重新解压部署包

[本次更新内容]
  1. 综合看板「改善目标对比」数据源统一为 HRDB 两张表：
     CN_AME_IE_BOL_improveTarget（主表）+ CN_AME_IE_BOL_improveTarget_volume（产量表），
     两表以 nr 关联，三工时口径完全一致：
       - Budget 工时    = bol_budget × Volume / 60
       - 改善目标工时   = bol_budget × (1 - target_bol) × Volume / 60
                          （target_bol 为空时按 0% 改善处理，即等于 Budget 工时）
       - Achievable 工时 = Achievable BOL × Volume / 60
           Achievable BOL 取值规则：
             a) (process_01_ct×process_01_hc + ... + process_04_ct×process_04_hc)
                × (1 + 1/15) / 0.85 / 60 结果非空且非 0 时，采用该实测值；
             b) 无有效实测数据（字段为空或计算结果为 0）时，回退取 bol_budget。
  2. 预算 BOL 模块 Excel 导入弹窗新增「导入履历」：
     记录每次导入的时间、文件名、BOL 类型、财年、导入用户、行数统计与成功/失败状态。
