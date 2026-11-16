# -*- coding: utf-8 -*-
"""SW 选型对比(兼容壳,见 web/blueprints/sw_compare.py)

保持旧启动命令可用:
    conda run -n pdf1 python src/sw_compare_server.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_HERE)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from web.app import app, main

if __name__ == "__main__":
    main()
