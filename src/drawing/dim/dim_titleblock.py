# -*- coding: utf-8 -*-
"""标题栏与 BOM 渲染 — 把源文件里的 title_block / bom_table 画到 PDF。

源文件只存绑定关系(source)与手动覆盖(value),不存死值;
出图时按型号实时解析 {{变量}},这样选型配置变化后标题栏/BOM 会跟着变。
"""
import os
import re
from datetime import datetime

_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")

# BOM 默认位置(与 rule_template 的 bom_table.position 一致)与单元格尺寸
_BOM_X = 300
_BOM_Y = 200
_BOM_ROW_H = 6.0
_BOM_COL_W = [12, 50, 16, 30]


def model_params(model_code):
    """型号 → 标题栏/BOM 可用变量;系列配置缺失时返回仅含型号的最小集"""
    from core import paths
    from core.rebuild_assembly import (
        parse_model_code, load_config, compute_cylinder_scale)

    parsed = parse_model_code(model_code)
    series = parsed["series"]
    config = None
    for name in (f"{series}直连", f"{series}折返"):
        if os.path.isfile(os.path.join(paths.CONFIG_DIR, f"{name}.json")):
            config = load_config(name)
            break

    d1 = None
    if config:
        cyl = compute_cylinder_scale(config, parsed["stroke"])
        if cyl:
            d1 = cyl[1]
    return {
        "series": config.get("series") if config else series,
        "model_code": model_code,
        "stroke": parsed["stroke"].lstrip("L"),
        "d1": d1,
        "motor": parsed.get("motor"),
        "mount": parsed.get("mount"),
        "load": parsed.get("load"),
        "date": datetime.now().strftime("%Y-%m-%d"),
    }


def resolve_source(source, params):
    """解析 {{变量}};变量缺失时保留原占位,便于发现未绑定来源"""
    if not source:
        return ""
    return _VAR_RE.sub(
        lambda m: str(params[m.group(1)])
        if params.get(m.group(1)) is not None else m.group(0),
        str(source))


def field_text(field, params):
    """字段最终文本:手动覆盖 value 优先,否则解析 source"""
    value = field.get("value")
    if value not in (None, ""):
        return str(value)
    return resolve_source(field.get("source"), params)


def draw_title_block(c, title_block, params, mapper, font, fs_mm):
    """标题栏:按字段自带的 x/y(图纸 mm, y 向下)定位画 标签: 值"""
    for field in (title_block or {}).get("fields", []):
        x_svg, y_svg = field.get("x"), field.get("y")
        if x_svg is None or y_svg is None:
            continue
        x, y = mapper.pt(x_svg, y_svg)
        c.setFont(font, fs_mm)
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.drawString(x, y, f"{field.get('label', '')}: {field_text(field, params)}")


def draw_bom_table(c, bom_table, mapper, font, fs_mm):
    """BOM:按 columns 画表头 + 逐行单元格(序号/名称/数量/备注)"""
    rows = (bom_table or {}).get("rows") or []
    if not rows:
        return
    cols = (bom_table or {}).get("columns") or []
    widths = _BOM_COL_W[:max(len(cols), 1)]
    x0 = (bom_table or {}).get("x", _BOM_X)
    y0 = (bom_table or {}).get("y", _BOM_Y)

    def cell_text(col_idx, row, row_idx):
        if col_idx == 0:
            return str(row_idx + 1)
        if col_idx == 1:
            return str(row.get("name", ""))
        if col_idx == 2:
            return str(row.get("qty", 1))
        return ""

    c.setFont(font, fs_mm)
    c.setStrokeColorRGB(0.1, 0.1, 0.1)
    c.setLineWidth(0.3)
    for r, row in enumerate(rows):
        top_svg = y0 + r * _BOM_ROW_H
        x = x0
        for ci, w in enumerate(widths):
            px = x
            # PDF rect 以左下角定位:行顶换算后需减去行高
            _, py = mapper.pt(0, top_svg)
            py -= _BOM_ROW_H
            c.rect(px, py, w, _BOM_ROW_H, stroke=1, fill=0)
            c.setFillColorRGB(0.1, 0.1, 0.1)
            c.drawString(px + 1.2, py + 1.5, cell_text(ci, row, r))
            x += w
