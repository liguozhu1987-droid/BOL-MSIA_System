"""SQLAlchemy 声明式基类与命名约定

所有 MSIA 业务表使用 CN_AME_MISA_ 前缀。
索引 / 约束统一命名:
- 主键: PK_MISA_<表名>
- 唯一: UX_MISA_<表名>_<列名>
- 索引: IX_MISA_<表名>_<列名>
- 外键: FK_MISA_<表名>_<列名>_<引用表名>
- 检查: CK_MISA_<表名>_<约束名>
"""
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# 统一命名约定, 生成符合规范的约束名
naming_convention = {
    "ix": "IX_MISA_%(table_name)s_%(column_0_name)s",
    "uq": "UX_MISA_%(table_name)s_%(column_0_name)s",
    "ck": "CK_MISA_%(table_name)s_%(constraint_name)s",
    "fk": "FK_MISA_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "PK_MISA_%(table_name)s",
}

metadata = MetaData(naming_convention=naming_convention)


class Base(DeclarativeBase):
    """声明式基类, 所有模型继承此类"""
    metadata = metadata
