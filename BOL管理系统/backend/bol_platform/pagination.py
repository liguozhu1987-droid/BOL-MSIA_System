# -*- coding: utf-8 -*-
"""自定义分页：允许客户端通过 page_size 参数控制每页条数"""
from rest_framework.pagination import PageNumberPagination


class CustomPageNumberPagination(PageNumberPagination):
    page_size_query_param = 'page_size'
    max_page_size = 200