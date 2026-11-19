# -*- coding: utf-8 -*-
"""
BOL 平台数据库路由：
  - projects / dynamic_bol 应用 → hrdb 库（HRDB，只读，不建表不迁移）
  - budget_bol / sensor_bol / tracking / analytics 应用 → default 库（CMC，可读写）
"""


class BolDbRouter:
    # projects/dynamic_bol/actual_ct 都映射 HRDB 只读库
    hrdb_apps = {'projects', 'dynamic_bol', 'actual_ct'}

    def db_for_read(self, model, **hints):
        if model._meta.app_label in self.hrdb_apps:
            return 'hrdb'
        return 'default'

    def db_for_write(self, model, **hints):
        if model._meta.app_label in self.hrdb_apps:
            return None  # HRDB 只读，禁止写
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        # 允许跨库关联查询（仅外键逻辑关联，不强约束）
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # HRDB 的表已存在且只读，禁止迁移
        if app_label in self.hrdb_apps:
            return False
        # 其他应用只在 default(CMC) 库迁移
        return db == 'default'
