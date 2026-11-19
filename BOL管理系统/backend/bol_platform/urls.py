# -*- coding: utf-8 -*-
"""BOL管理分析平台 主路由"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve
from django.http import HttpResponse, Http404
from pathlib import Path


def serve_spa(request):
    """SPA 路由回退：非 /api/ 和非 /admin/ 的请求都返回前端 index.html

    Vue Router 使用 history 模式时，刷新子路由需要服务端回退到 index.html。
    """
    index_file = getattr(settings, 'FRONTEND_INDEX', None)
    if not index_file or not Path(index_file).exists():
        raise Http404('前端未构建，请先执行 npm run build')
    return HttpResponse(Path(index_file).read_text(encoding='utf-8'))


urlpatterns = [
    path('admin/', admin.site.urls),
    # 项目主数据（HRDB 只读）
    path('api/projects/', include('apps.projects.urls')),
    # 动态BOL（HRDB 只读）
    path('api/dynamic-bol/', include('apps.dynamic_bol.urls')),
    # 年度预算BOL（CMC 读写）
    path('api/budget-bol/', include('apps.budget_bol.urls')),
    # 实测CT（HRDB 只读，仅CT非BOL）
    path('api/actual-ct/', include('apps.actual_ct.urls')),
    # 高BOL跟踪（CMC 读写）
    path('api/tracking/', include('apps.tracking.urls')),
    # 分析（跨库计算）
    path('api/analytics/', include('apps.analytics.urls')),
    # 人员管理（CMC 读写）
    path('api/users/', include('apps.users.urls')),
    # 用户认证
    path('api/auth/', include('apps.users.auth_urls')),
    # 报告生成（CMC 读写，季度/年度分析报告）
    path('api/', include('apps.reports.urls')),
]

# 生产环境：提供前端静态文件 + SPA 路由回退
if not settings.DEBUG:
    frontend_dist = getattr(settings, 'FRONTEND_DIST', None)
    static_root = getattr(settings, 'STATIC_ROOT', None)

    # 瘦身后前端构建产物已包含在 staticfiles 中（collectstatic 收集）
    # 静态文件根目录：优先 frontend/dist，其次 staticfiles
    frontend_root = None
    if frontend_dist and Path(frontend_dist).exists():
        frontend_root = Path(frontend_dist)
    elif static_root and Path(static_root).exists():
        frontend_root = Path(static_root)

    if frontend_root:
        # 前端构建产物（assets/ 下的 JS/CSS/图片等）
        urlpatterns += [
            re_path(r'^assets/(?P<path>.*)$', serve, {
                'document_root': str(frontend_root / 'assets'),
                'show_indexes': False,
            }),
        ]
        # collectstatic 收集的静态文件（admin 等）
        if static_root and Path(static_root).exists():
            urlpatterns += [
                re_path(r'^static/(?P<path>.*)$', serve, {
                    'document_root': str(static_root),
                    'show_indexes': False,
                }),
            ]
        # 前端根目录的静态文件（favicon.svg, logo.png, icons.svg, skyline.jpg,
        # login-bg.png, login-logo.png 等；未列出的根级请求会落入 SPA 回退返回
        # index.html，导致图片 404 显示为 alt 文本）
        urlpatterns += [
            re_path(r'^(favicon\.svg|logo\.png|icons\.svg|skyline\.jpg|login-bg\.png|login-logo\.png)$', serve, {
                'document_root': str(frontend_root),
                'show_indexes': False,
            }),
        ]
    # SPA 路由回退（放在最后，捕获所有未匹配的非 API/admin/static 路由）
    # 使用 re_path 负向先行断言，确保不会捕获 /api/ /admin/ /assets/ /static/ 路径
    # 同时避免向 serve_spa 传递 catch_all 关键字参数
    urlpatterns += [
        re_path(r'^(?!api/|admin/|assets/|static/|favicon\.svg|logo\.png|icons\.svg|skyline\.jpg).*$', serve_spa),
        path('', serve_spa),
    ]
