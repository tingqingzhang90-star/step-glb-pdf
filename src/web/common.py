# -*- coding: utf-8 -*-
"""web 层共享常量与路径

把 src/web 下各蓝图共用的路径、输出目录、模板目录集中到一处,
避免每个文件各自拼路径(旧 server.py 在每个文件里重复计算 _HERE/_SRC_DIR)。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))   # src/web
SRC_DIR = os.path.dirname(_HERE)                       # src
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from core import rebuild_assembly as rb

PROJECT_ROOT = os.path.dirname(SRC_DIR)                # 项目根

# 输出与配置目录(core 在 import 时已初始化)
OUT_DIR = rb.OUT_DIR
CONFIG_DIR = rb.CONFIG_DIR

# web 内部目录
STATIC_DIR = os.path.join(_HERE, "static")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "data", "templates", "engineering")

# 前端页面文件
ASSEMBLY_PANEL_HTML = os.path.join(_HERE, "templates", "assembly_panel.html")
SW_COMPARE_PANEL_HTML = os.path.join(_HERE, "templates", "sw_compare_panel.html")
PART_EXPORT_PANEL_HTML = os.path.join(_HERE, "part_export_panel.html")
VIEWER_HTML = os.path.join(_HERE, "viewer.html")
DRAWING_EDITOR_HTML = os.path.join(_HERE, "drawing_editor.html")
