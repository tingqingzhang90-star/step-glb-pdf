# -*- coding: utf-8 -*-
"""零件导出面板(兼容壳,见 web/blueprints/part_export.py)

保留模块级 app / paths / pe / bc,使现有测试 test_part_export_panel.py 无需改动。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_HERE)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from web.app import app, main

# 兼容测试:暴露原模块级引用(test_part_export_panel.py 用到)
from core import paths
from core import part_exporter as pe
from core import build_config as bc

__all__ = ["app", "paths", "pe", "bc", "main"]

if __name__ == "__main__":
    main()
