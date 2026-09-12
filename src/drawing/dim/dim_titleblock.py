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
        # 与 anchor_resolver.build_model_params 保持一致,供标题栏 {{scale}} 使用
        "scale": "2",
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
    """字段最终文本:手动覆盖 value 优先,否则解析 source;两者均会解析 {{变量}}"""
    value = field.get("value")
    if value not in (None, ""):
        return resolve_source(value, params)
    return resolve_source(field.get("source"), params)


def _gaps(values):
    """相邻坐标的间距列表,用于由字段 x/y 反推列宽/行高。"""
    return [values[i + 1] - values[i] for i in range(len(values) - 1)]


def _truncate_to_width(c, text, font, fs_mm, max_w):
    """按可用宽度截断文本,过长时保留 ... 后缀"""
    if c.stringWidth(text, font, fs_mm) <= max_w:
        return text
    suffix = "..."
    suffix_w = c.stringWidth(suffix, font, fs_mm)
    if max_w <= suffix_w:
        return text[:1]
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if c.stringWidth(text[:mid], font, fs_mm) + suffix_w <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + suffix


def draw_title_block(c, title_block, params, mapper, font, fs_mm, *, bottom_y=None):
    """标题栏:按字段 x/y 建成网格,画上外框与分隔线。

    默认锚定在右下角内框线内;传入 bottom_y 时以其为下边界。
    字段 name(模板)或 label(前端保存)作为标签,文字按格裁剪,
    防止溢出到相邻格或图框外。返回标题栏上边界(SVG y 向下)。
    """
    fields = [
        f for f in (title_block or {}).get("fields", [])
        if f.get("x") is not None and f.get("y") is not None
    ]
    if not fields:
        return None

    margin = 20
    pad = 1.5
    sheet_w = getattr(mapper, "sheet_w", 420)
    sheet_h = getattr(mapper, "sheet_h", 297)

    col_xs = sorted({round(f["x"]) for f in fields})
    row_ys = sorted({round(f["y"]) for f in fields})
    col_w = _gaps(col_xs)
    row_h = _gaps(row_ys)
    if not col_w:
        col_w.append(42)
    if len(col_w) < len(col_xs):
        col_w.append(40)
    if not row_h:
        row_h.append(8)
    if len(row_h) < len(row_ys):
        row_h.append(8)

    total_w = sum(col_w)
    total_h = sum(row_h)
    right_inner = sheet_w - margin
    # 默认贴内框线,留 1mm 间隙
    if bottom_y is None:
        bottom_y = sheet_h - margin - 1
    box_right = right_inner - 1
    box_left = max(margin, box_right - total_w)
    box_bottom = bottom_y
    box_top = box_bottom - total_h

    c.setFont(font, fs_mm)
    c.setStrokeColorRGB(0.1, 0.1, 0.1)
    c.setLineWidth(0.4)
    c.setFillColorRGB(0.1, 0.1, 0.1)

    # 外框:PDF 坐标 y 向上
    pdf_bottom = sheet_h - box_bottom
    c.rect(box_left, pdf_bottom, total_w, total_h, stroke=1, fill=0)

    # 列分隔线
    x = box_left
    for w in col_w[:-1]:
        x += w
        c.line(x, pdf_bottom, x, pdf_bottom + total_h)

    # 行分隔线(SVG y 向下,PDF y 向上)
    y = box_top
    for h in row_h[:-1]:
        y += h
        pdf_y = sheet_h - y
        c.line(box_left, pdf_y, box_right, pdf_y)

    for f in fields:
        label = str(f.get("name") or f.get("label", ""))
        value = field_text(f, params)
        text = f"{label}: {value}" if label else str(value)
        ci = col_xs.index(round(f["x"]))
        ri = row_ys.index(round(f["y"]))
        cell_l = box_left + sum(col_w[:ci])
        cell_w = col_w[ci]
        cell_t = box_top + sum(row_h[:ri])
        cell_b = cell_t + row_h[ri]
        cell_cy = (cell_t + cell_b) / 2
        cell_h = cell_b - cell_t
        max_w = max(cell_w - 2 * pad, 10)
        truncated = _truncate_to_width(c, text, font, fs_mm, max_w)
        tx = cell_l + pad
        ty = sheet_h - cell_cy - 0.35 * fs_mm

        # 按单元格裁剪,确保无论如何不会画到邻格
        # reportlab 5.x 的 rect() 已移除 clip 参数,统一用 clipPath 裁剪
        c.saveState()
        clip = c.beginPath()
        clip.rect(cell_l, sheet_h - cell_b, cell_w, cell_h)
        c.clipPath(clip, stroke=0, fill=0)
        c.drawString(tx, ty, truncated)
        c.restoreState()

    return box_top


def draw_bom_table(c, bom_table, mapper, font, fs_mm, *, top_limit=None, bottom_y=None):
    """BOM:按 columns 画表头 + 逐行单元格(序号/名称/数量/备注)。

    默认使用 bom_table 中的 x/y;传入 bottom_y 时表格下边界对齐它。
    传入 top_limit 时保证表格底部不超过该边界(用于避让标题栏)。
    返回表格上边界(SVG y 向下)。
    """
    rows = (bom_table or {}).get("rows") or []
    if not rows:
        return None
    cols = (bom_table or {}).get("columns") or []
    widths = _BOM_COL_W[:max(len(cols), 1)]
    x0 = (bom_table or {}).get("x", _BOM_X)
    y0 = (bom_table or {}).get("y", _BOM_Y)

    # 保证表格不超出右内框线(margin=20);若放不下则整体左移
    total_w = sum(widths)
    margin = 20
    right_limit = getattr(mapper, "sheet_w", 420) - margin
    if x0 + total_w > right_limit:
        x0 = max(margin, right_limit - total_w)

    total_h = len(rows) * _BOM_ROW_H
    if bottom_y is not None:
        y0 = bottom_y - total_h
    elif top_limit is not None and y0 + total_h > top_limit - 2:
        y0 = max(margin, top_limit - 2 - total_h)

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

    return y0
