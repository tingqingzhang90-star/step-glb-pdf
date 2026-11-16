# -*- coding: utf-8 -*-
"""业务蓝图包

各蓝图在 web/app.py 的 create_app() 内延迟导入并注册,不在此处自动 import,
以便 .env 与任务池单例先于蓝图初始化。
"""
