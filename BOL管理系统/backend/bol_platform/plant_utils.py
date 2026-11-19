# -*- coding: utf-8 -*-
"""工厂名称标准化工具

系统中工厂地点在不同模块使用不同字段名和格式：
- BolOverView.location: 全称（Beijing, Changchun）
- BottleNeckCt/RealCtExtract.company: 短代码（BJ, CC）
- BudgetBol.plant: 全称+后缀（Beijing, Beijing_IHE）
- OPE 视图: company 短代码（BJ）

统一标准化为短代码：CJ/BJ/SH/CQ/GZ/WH/CMC/YT
"""

# 标准工厂代码 → 所有可能的原始值（小写匹配）
PLANT_ALIASES = {
    'CJ': ['cj', 'cj inalfa', 'cc', 'changchun'],
    'BJ': ['bj', 'bj inalfa', 'beijing'],
    'SH': ['sh', 'sh inalfa', 'shanghai'],
    'CQ': ['cq', 'cq inalfa', 'chongqing'],
    'GZ': ['gz', 'gz inalfa', 'guangzhou'],
    'WH': ['wh', 'wh inalfa', 'wuhan'],
    'CMC': ['cmc', 'cmc inalfa'],
    'YT': ['yt', 'yt inalfa'],
}

# 反向映射：原始值（小写） → 标准代码
_ALIAS_TO_STANDARD = {}
for _std, _aliases in PLANT_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_TO_STANDARD[_alias] = _std


def normalize_plant(raw):
    """将各种工厂名称变体标准化为短代码（CJ/BJ/SH/CQ/GZ/WH）

    Args:
        raw: 原始值（如 'Beijing', 'BJ Inalfa', 'Beijing_IHE', 'CC', 'changchun'）

    Returns:
        标准短代码（如 'BJ', 'CJ'），无法识别时返回原值去后缀
    """
    if not raw:
        return ''
    raw = str(raw).strip()
    # 去除 _后缀（如 Beijing_IHE → Beijing）
    base = raw.split('_')[0].strip()
    return _ALIAS_TO_STANDARD.get(base.lower(), base)


def normalize_project_code(raw):
    """标准化项目代码

    BolOverView.program_code 可能带 Ext1- 前缀（如 Ext1-T5550），
    BottleNeckCt.project_code 无此前缀（如 T5550）。
    去除 Ext1- 等扩展前缀，保留核心项目代码以便跨表匹配。

    Args:
        raw: 原始项目代码（如 'Ext1-T5550', 'T5550', 'O6848'）

    Returns:
        标准化后的项目代码（如 'T5550', 'O6848'）
    """
    if not raw:
        return ''
    raw = str(raw).strip()
    # 去除 Ext1- / Ext2- 等扩展前缀
    for prefix in ('Ext1-', 'Ext2-', 'Ext3-', 'ext1-', 'ext2-', 'ext3-'):
        if raw.startswith(prefix):
            return raw[len(prefix):].strip()
    return raw


def get_plant_raw_values(standard_code):
    """获取标准代码对应的所有原始值（用于数据库查询过滤）

    同时返回大写和原始大小写变体，兼容大小写敏感的数据库 collation。
    例如 CJ → ['CJ', 'cj', 'CJ INALFA', 'cj inalfa', 'CC', 'cc', 'CHANGCHUN', 'changchun']

    Args:
        standard_code: 标准短代码（如 'BJ'）

    Returns:
        所有可能的原始值列表（含大写和小写变体）
    """
    aliases = PLANT_ALIASES.get(standard_code, [])
    result = []
    seen = set()
    # 标准代码本身
    for val in [standard_code] + aliases:
        if val not in seen:
            result.append(val)
            seen.add(val)
        upper_val = val.upper()
        if upper_val not in seen:
            result.append(upper_val)
            seen.add(upper_val)
    return result


def build_plant_q(field_name, standard_code, qs_class):
    """构建 Q 对象，用于按标准代码查询数据库中的各种变体

    Args:
        field_name: 数据库字段名（如 'location', 'company', 'plant'）
        standard_code: 标准短代码（如 'BJ'）
        qs_class: Django Q 类（传入 Q 即可）

    Returns:
        Q 对象
    """
    raw_values = get_plant_raw_values(standard_code)
    q = qs_class()
    for val in raw_values:
        q |= qs_class(**{field_name: val})
        # 对于 plant 字段，还要匹配带后缀的（如 Beijing_IHE）
        if field_name == 'plant':
            q |= qs_class(**{f'{field_name}__startswith': f'{val}_'})
    return q
