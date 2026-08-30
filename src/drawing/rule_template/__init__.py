# -*- coding: utf-8 -*-
"""规则式模板引擎

标注以 bbox_x_min 等规则描述,与前端实例模板(几何指纹重绑)并列为两种模板形态。

注意: drawing_template.json 与 drawing_anchors.json 由 drawing_template.py
按 os.path.dirname(__file__) 同目录查找,必须与本模块放在一起,不可移出。
"""
from . import drawing_template  # noqa: F401  便于 from drawing.rule_template import drawing_template
