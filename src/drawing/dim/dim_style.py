# -*- coding: utf-8 -*-
"""前后端共用样式配置加载(cad_viewer_style.json)

与前端 cad-viewer-app/src/composables/useStyleConfig.js 读同一份 json:
  - stroke_px / font_px:屏幕 px,后端按 96dpi 折成 mm
  - *_mm:图纸几何量(SVG viewBox 单位即 mm),两端都不折算
 """

import json
import os

# 本文件位于 src/drawing/dim/,需上溯四级: dim → drawing → src → 项目根
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
_STYLE_PATH = os.path.join(_PROJECT_ROOT, "cad_viewer_style.json")

with open(_STYLE_PATH, "r", encoding="utf-8") as _f:
    CFG = json.load(_f)

PX2MM = CFG["_px_to_mm_at_96dpi"]

# json 缺字段时的兜底值,避免旧配置文件直接崩
_FALLBACK = {"ext_overshoot_mm": 2.5, "text_gap_mm": 4.0,
             "arrow_len_px": 14.0, "arrow_half_px": 1.6, "arrow_ext_px": 16.0,
             "angle_text_gap_px": 4.0, "angle_arc_ext_px": 20.0}


def _dim(section, key, fallback_key):
    try:
        return float(CFG["dim"][section][key])
    except (KeyError, TypeError, ValueError):
        return _FALLBACK[fallback_key]


def dim_ext_overshoot_mm():
    """尺寸界线越过尺寸线的长度(mm,图纸坐标)"""
    return _dim("ext", "overshoot_mm", "ext_overshoot_mm")


def dim_text_gap_mm():
    """文字与尺寸线的间距(mm,图纸坐标)"""
    return _dim("text", "gap_mm", "text_gap_mm")


def dim_label_gap_mm():
    """伴随文字标签与数值的间距(mm,图纸坐标)= 字号 * 系数(默认 0.55em),
    视觉等同字间距,与前端 core.js 共用同一份 json"""
    try:
        factor = float(CFG["dim"]["text"]["label_gap_factor"])
    except (KeyError, TypeError, ValueError):
        factor = 0.55
    try:
        font_px = float(CFG["dim"]["text"]["font_px"])
    except (KeyError, TypeError, ValueError):
        font_px = 18
    return font_px * PX2MM * factor


def dim_text_font_mm():
    """标注文字的 PDF 字号(pt):font_px 按 96dpi 折算(mm)。
    reportlab setFont 的 size 以 pt 计,画布 scale(mm,mm) 后实际字高
    = size × 25.4/72 图纸单位。引线直径下划线按该字号实测文字宽度用。"""
    try:
        return float(CFG["dim"]["text"]["font_px"]) * PX2MM
    except (KeyError, TypeError, ValueError):
        return 18.0 * PX2MM


def dim_arrow_len_px():
    """箭头长度(图纸单位,与前端 arrow.js 共用同一份 json)"""
    return _dim("arrow", "len_px", "arrow_len_px")


def dim_arrow_half_px():
    """箭头底部半宽(图纸单位,越小越尖锐)"""
    return _dim("arrow", "half_px", "arrow_half_px")


def dim_arrow_extension_px():
    """箭头向内(尖端相对)时尺寸线穿过箭头的延长量(px,与前端 arrow.js 共用同一份 json)"""
    return _dim("arrow", "extension_px", "arrow_ext_px")


def dim_angle_text_gap_px():
    """角度标注文字与弧线的间距(图纸 px, 与前端 core.js ANGLE_TEXT_GAP 共用同一份 json)"""
    return _dim("angle", "text_gap_px", "angle_text_gap_px")


def dim_angle_arc_ext_px():
    """角度标注弧两端越过箭头尾部的延伸长度(图纸 px, 与前端 core.js ANGLE_ARC_EXT_PX 共用)"""
    return _dim("angle", "arc_ext_px", "angle_arc_ext_px")
