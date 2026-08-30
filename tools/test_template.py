# -*- coding: utf-8 -*-
"""快速测试 drawing_template 引擎(无需 STEP 文件,使用 mock 数据)"""
import sys
import os
import json

# 添加 src 目录到路径
_src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, _src)

from drawing.rule_template import drawing_template as dt

# 加载模板和锚点
t = dt.load_default_template()
a = dt.load_default_anchors()
print("template_id:", t.get("template_id"))
print("anchors count:", len(a.get("anchors", [])))

# 构造 mock 视图数据
mock_views = {
    "views": {
        "front": {
            "label": "Front",
            "visible": [
                {"type": "line", "x1": 0, "y1": 0, "x2": 100, "y2": 0,
                 "meta": {"orientation": "horizontal", "length": 100}},
                {"type": "line", "x1": 0, "y1": 0, "x2": 0, "y2": 50,
                 "meta": {"orientation": "vertical", "length": 50}},
                {"type": "line", "x1": 100, "y1": 0, "x2": 100, "y2": 50,
                 "meta": {"orientation": "vertical", "length": 50}},
                {"type": "line", "x1": 0, "y1": 50, "x2": 100, "y2": 50,
                 "meta": {"orientation": "horizontal", "length": 100}},
                {"type": "circle", "cx": 50, "cy": 25, "r": 20}
            ],
            "hidden": [],
            "bbox": {"min_x": 0, "min_y": 0, "max_x": 100, "max_y": 50,
                     "width": 100, "height": 50},
            "seg_count": 5
        },
        "top": {
            "label": "Top",
            "visible": [
                {"type": "line", "x1": 0, "y1": 0, "x2": 100, "y2": 0,
                 "meta": {"orientation": "horizontal", "length": 100}}
            ],
            "hidden": [],
            "bbox": {"min_x": 0, "min_y": 0, "max_x": 100, "max_y": 30,
                     "width": 100, "height": 30},
            "seg_count": 1
        },
        "left": {
            "label": "Left",
            "visible": [
                {"type": "line", "x1": 0, "y1": 0, "x2": 200, "y2": 0,
                 "meta": {"orientation": "horizontal", "length": 200}}
            ],
            "hidden": [],
            "bbox": {"min_x": 0, "min_y": 0, "max_x": 200, "max_y": 50,
                     "width": 200, "height": 50},
            "seg_count": 1
        }
    },
    "model_bbox": {"width": 100, "height": 50, "depth": 200},
    "elapsed": 0.1
}
mock_views["anchors"] = a

params = {
    "model_code": "250-E-H3K2-L100-D11",
    "series": "250",
    "date": "2026-08-11",
    "scale": "2",
    "motor_code": "D11",
    "has_motor": True
}

r = dt.apply_template(mock_views, t, params)
print(json.dumps(r, ensure_ascii=False, indent=2))
