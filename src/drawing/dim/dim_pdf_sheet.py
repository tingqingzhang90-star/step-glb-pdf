# -*- coding: utf-8 -*-
"""工程图 PDF 渲染层 — 视图边线 + 前端样式标注 + 图框

图纸坐标 = 图纸毫米尺寸(前端选定 A0/A1/A2/A3/A4 后,SVG 坐标即 mm 坐标),
后端 PDF 页面尺寸直接取自模板 sheet.width/height,不再做尺寸映射转换。

样式与前端共享 cad_viewer_style.json:
  前端用 px(屏幕像素,SVG non-scaling-stroke),
  后端按 96dpi 折算成 mm,确保前后端视觉一致(等比缩放)。
"""
import json
import math
import os

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

# 加载共享样式配置(项目根 cad_viewer_style.json,前后端共用)
# 本文件位于 src/drawing/dim/,需上溯四级: dim → drawing → src → 项目根
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
_STYLE_PATH = os.path.join(_PROJECT_ROOT, "cad_viewer_style.json")
with open(_STYLE_PATH, "r", encoding="utf-8") as _f:
    _CFG = json.load(_f)

_PX2MM = _CFG["_px_to_mm_at_96dpi"]   # 0.2645833 mm/px (96dpi)
# 后端常量(从 px 换算成 mm)
_W_VISIBLE = _CFG["edge"]["visible"]["stroke_px"] * _PX2MM   # 0.265
_W_HIDDEN = _CFG["edge"]["hidden"]["stroke_px"] * _PX2MM     # 0.212
_W_DIM = _CFG["dim"]["line"]["stroke_px"] * _PX2MM          # 0.265
_W_EXT = _CFG["dim"]["ext"]["stroke_px"] * _PX2MM            # 0.212
_W_MARK = _CFG["center_mark"]["stroke_px"] * _PX2MM          # 0.212
# 字号 px → mm。注意画布已 c.scale(mm,mm),setFont 的数值单位是 mm
# 而不是 pt:若传 pt 值会被坐标系再放大 2.834 倍(pt→mm 因子),
# 导致 PDF 文字比前端预览大 3.8 倍
_FS_TEXT_MM = _CFG["dim"]["text"]["font_px"] * _PX2MM  # 7px → 1.85mm
# 箭头 px → mm
_ARROW_LEN_MM = _CFG["dim"]["arrow"]["len_px"] * _PX2MM
_ARROW_HALF_MM = _CFG["dim"]["arrow"]["half_px"] * _PX2MM
_C_EDGE = (0.1, 0.1, 0.1)
_C_HIDDEN = (0.45, 0.45, 0.45)


def _hex_rgb(color):
    c = color or "#303133"
    try:
        return (int(c[1:3], 16) / 255, int(c[3:5], 16) / 255,
                int(c[5:7], 16) / 255)
    except (ValueError, IndexError):
        return (0.19, 0.19, 0.19)


class SheetMapper:
    """图纸坐标(y 向下) → PDF mm 坐标(y 向上)

    sheet 坐标即 mm(前端 SVG viewBox 即 mm),k=1.0 不缩放,
    仅做 y 轴反转(SVG y 向下 → PDF y 向上)。
    """

    def __init__(self, sheet_w, sheet_h):
        self.k = 1.0
        self.sheet_h = sheet_h

    def pt(self, x, y):
        return (x * self.k, self.sheet_h - y * self.k)


def _draw_view_edges(c, placement, mapper):
    k = mapper.k
    for seg in placement["segs"]:
        _draw_seg(c, seg, placement, mapper, _C_EDGE, _W_VISIBLE * k, None)
    for seg in placement.get("hidden", []):
        _draw_seg(c, seg, placement, mapper, _C_HIDDEN, _W_HIDDEN * k,
                  (2.5, 1.5))


def _draw_seg(c, seg, placement, mapper, color, width, dash):
    s = placement["scale"]
    ox, oy = placement["x"], placement["y"]

    def px(v):
        return v * s + ox

    def py(v):
        return v * s + oy

    st = seg.get("type")
    c.setStrokeColorRGB(*color)
    c.setLineWidth(width)
    if dash:
        c.setDash(*dash)
    if st == "line":
        c.line(*mapper.pt(px(seg["x1"]), py(seg["y1"])),
               *mapper.pt(px(seg["x2"]), py(seg["y2"])))
    elif st == "circle":
        cx, cy = mapper.pt(px(seg["cx"]), py(seg["cy"]))
        c.circle(cx, cy, seg["r"] * s * mapper.k, stroke=1, fill=0)
    elif st == "polyline":
        pts = seg.get("points") or []
        if len(pts) >= 2:
            path = c.beginPath()
            path.moveTo(*mapper.pt(px(pts[0][0]), py(pts[0][1])))
            for p in pts[1:]:
                path.lineTo(*mapper.pt(px(p[0]), py(p[1])))
            c.drawPath(path, stroke=1, fill=0)
    if dash:
        c.setDash()


def _draw_table_placement(c, table, mapper):
    """画一个表格:网格 + 合并单元格 + 文字

    坐标约定与视图放置一致:table.x/y 是 SVG 左上角(mm,SVG y 向下),
    mapper.pt 把 SVG-y 翻成 PDF-y(y 向上)。colspan/rowspan 只在左上角
    格子声明,被覆盖的格子不出现在 cells 数组里,自然不重复画。

    cell 字段: r, c, colspan(默认1), rowspan(默认1), text, align
    (如 "h-left v-center"), font_size(px), bold
    """
    ox, oy = table["x"], table["y"]
    col_w = table["col_widths"]
    row_h = table["row_heights"]
    # 列左边 x / 行顶部 y:前缀和
    col_left = [ox]
    for w in col_w:
        col_left.append(col_left[-1] + w)
    row_top = [oy]
    for h in row_h:
        row_top.append(row_top[-1] + h)

    border = table.get("border", {})
    bw = border.get("width", 0.3)
    bc = _hex_rgb(border.get("color"))
    tc = _hex_rgb(table.get("text_color", "#303133"))

    try:
        from drawing.dim.dim_render import _CN_FONT
    except Exception:                       # 测试/无 OCC 环境回退
        _CN_FONT = "Helvetica"

    for cell in table.get("cells", []):
        r, col = cell["r"], cell["c"]
        cs = cell.get("colspan", 1)
        rs = cell.get("rowspan", 1)
        # SVG 坐标矩形(左上、右下)
        sx1, sy1 = col_left[col], row_top[r]
        sx2, sy2 = col_left[col + cs], row_top[r + rs]
        # PDF 坐标:y 翻转后,矩形左下/右上
        px1, py_top = mapper.pt(sx1, sy1)
        px2, py_bot = mapper.pt(sx2, sy2)
        rx, ry = min(px1, px2), min(py_top, py_bot)
        rw, rh = abs(px2 - px1), abs(py_top - py_bot)
        c.setStrokeColorRGB(*bc)
        c.setLineWidth(bw)
        c.rect(rx, ry, rw, rh, stroke=1, fill=0)

        text = cell.get("text") or ""
        if not text:
            continue
        fs_mm = cell.get("font_size", 13) * _PX2MM
        c.setFont(_CN_FONT, fs_mm)
        c.setFillColorRGB(*tc)
        # 水平对齐:left/center/right;padding 1mm
        align = cell.get("align", "h-left v-center")
        ha = "h-left"
        for part in align.split():
            if part.startswith("h-"):
                ha = part
        if ha == "h-center":
            tx = (px1 + px2) / 2
            draw = c.drawCentredString
        elif ha == "h-right":
            tx = max(px1, px2) - 1
            draw = c.drawRightString
        else:
            tx = min(px1, px2) + 1
            draw = c.drawString
        # 垂直:baseline 偏移近似(ascent≈0.8em,中心-0.35em)
        cy = (py_top + py_bot) / 2 - 0.35 * fs_mm
        draw(tx, cy, text)


def _draw_primitives(c, prims, color, mapper):
    rgb = _hex_rgb(color)
    k = mapper.k
    c.setLineWidth(_W_DIM * k)
    c.setStrokeColorRGB(*rgb)
    c.setFillColorRGB(*rgb)
    for p1, p2 in prims.get("dim_lines", []):
        c.line(*mapper.pt(*p1), *mapper.pt(*p2))
    c.setLineWidth(_W_EXT * k)
    for p1, p2 in prims.get("lines", []):
        c.line(*mapper.pt(*p1), *mapper.pt(*p2))
    # 箭头:前端箭头坐标是 sheet 像素(arrow.js 14px);后端直接当 mm 用
    # 因为前后端 1px=0.2646mm(96dpi),箭头自然就是 ~3.7mm,
    # 不再二次缩放,与前端屏幕视觉一致
    for pts in prims.get("arrows", []):
        if len(pts) < 3:
            continue
        path = c.beginPath()
        path.moveTo(*mapper.pt(*pts[0]))
        for p in pts[1:]:
            path.lineTo(*mapper.pt(*p))
        path.close()
        c.drawPath(path, stroke=0, fill=1)
    for arc in prims.get("arcs", []):
        path = c.beginPath()
        path.moveTo(*mapper.pt(*arc[0]))
        for p in arc[1:]:
            path.lineTo(*mapper.pt(*p))
        c.drawPath(path, stroke=1, fill=0)
    c.setLineWidth(_W_MARK * k)
    for mark in prims.get("center_marks", []):
        x, y = mark["pos"]
        r = mark["r"]
        ang = mark.get("angle")
        if ang is None:
            c.line(*mapper.pt(x - r, y), *mapper.pt(x + r, y))
            c.line(*mapper.pt(x, y - r), *mapper.pt(x, y + r))
        else:
            ca, sa = math.cos(ang), math.sin(ang)
            c.line(*mapper.pt(x - r * ca, y - r * sa),
                   *mapper.pt(x + r * ca, y + r * sa))
            c.line(*mapper.pt(x + r * sa, y - r * ca),
                   *mapper.pt(x - r * sa, y + r * ca))
    from drawing.dim.dim_render import _CN_FONT
    # 字号 10.5pt ≈ GB 5号字(3.7mm),不随图纸缩放
    c.setFont(_CN_FONT, _FS_TEXT_MM)
    for t in prims.get("texts", []):
        x, y = mapper.pt(*t["pos"])
        angle_deg = math.degrees(t.get("angle") or 0.0)
        if abs(angle_deg) < 0.5:
            if t.get("anchor") == "start":
                c.drawString(x, y, t["text"])
            else:
                c.drawCentredString(x, y, t["text"])
        else:
            c.saveState()
            c.translate(x, y)
            c.rotate(angle_deg)
            if t.get("anchor") == "start":
                c.drawString(0, 0, t["text"])
            else:
                c.drawCentredString(0, 0, t["text"])
            c.restoreState()


def render_frontend_pdf(rebound, placements, template_doc, model_code, out_pdf):
    """渲染前端实例模板工程图到 A3 PDF

    Args:
        rebound: 重绑结果列表(含 segs/views/annotation)
        placements: view_id → 放置 {x, y, scale, segs, hidden}
        template_doc: 前端模板 JSON(取 sheet 尺寸)
        model_code: 目标型号(角标)
        out_pdf: 输出路径

    Returns:
        str: 输出文件绝对路径
    """
    import os
    from drawing.dim.dim_render import _ensure_font, build_dim_primitives

    _ensure_font()
    sheet = template_doc.get("sheet", {})
    sheet_w = sheet.get("width", 420)   # 默认 A3 横放
    sheet_h = sheet.get("height", 297)
    sheet_size = sheet.get("size", "A3")
    mapper = SheetMapper(sheet_w, sheet_h)

    out_dir = os.path.dirname(os.path.abspath(out_pdf))
    os.makedirs(out_dir, exist_ok=True)
    # PDF 页面尺寸直接取自模板 sheet,前后端图纸格式一致(无映射转换)
    c = pdf_canvas.Canvas(out_pdf, pagesize=(sheet_w * mm, sheet_h * mm))
    c.setTitle(f"{model_code} ({sheet_size})")
    c.scale(mm, mm)

    # 图框:内缩 20mm,与前端 SVG 图框(App.vue x=20)一致,
    # 否则同一坐标的表格在 PDF 里会显得离图框有缝
    m = 20
    c.setStrokeColorRGB(*_C_EDGE)
    c.setLineWidth(0.8)
    c.rect(m, m, sheet_w - 2 * m, sheet_h - 2 * m, stroke=1, fill=0)

    for placement in placements.values():
        _draw_view_edges(c, placement, mapper)

    # 表格:整批只读 template_doc["tables"],逐个画
    for table in template_doc.get("tables", []):
        _draw_table_placement(c, table, mapper)

    unmatched = 0
    for item in rebound:
        if item.get("status") == "unmatched":
            unmatched += 1
            continue
        ann = item["annotation"]
        prims = build_dim_primitives(ann, item["segs"], item["views"])
        if prims:
            _draw_primitives(c, prims, ann.get("color"), mapper)

    # 角标:型号 + 失配提示
    from drawing.dim.dim_render import _CN_FONT
    c.setFont(_CN_FONT, _FS_TEXT_MM)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.drawRightString(sheet_w - m, m + 3, model_code)
    if unmatched:
        c.setFillColorRGB(0.9, 0.2, 0.2)
        c.drawString(m, m + 3,
                     f"注意: {unmatched} 条标注未匹配,详见批次报告")

    c.showPage()
    c.save()
    return os.path.abspath(out_pdf)
