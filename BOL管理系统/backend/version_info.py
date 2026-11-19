# BOLServer.exe 版本信息资源（PyInstaller eval 表达式格式：文件体必须为单个 VSVersionInfo(...) 表达式，不能有 docstring/语句）
# 嵌入公司/产品元数据，降低杀毒软件对无版本信息 PyInstaller 产物的启发式误报
VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(2, 3, 0, 0),
        prodvers=(2, 3, 0, 0),
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    '080404b0',
                    [
                        StringStruct('CompanyName', 'Inalfa BOL Management'),
                        StringStruct('FileDescription', 'BOL Management and Analysis Platform Server'),
                        StringStruct('FileVersion', '2.3.0.0'),
                        StringStruct('InternalName', 'BOLServer'),
                        StringStruct('LegalCopyright', 'Copyright (C) 2026 Inalfa. Internal use only.'),
                        StringStruct('OriginalFilename', 'BOLServer.exe'),
                        StringStruct('ProductName', 'BOL Management and Analysis Platform'),
                        StringStruct('ProductVersion', '2.3.0.0'),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct('Translation', [2052, 1200])]),
    ],
)
