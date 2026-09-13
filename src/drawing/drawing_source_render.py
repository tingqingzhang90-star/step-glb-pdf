# -*- coding: utf-8 -*-
"""从 drawing_source.json 直接渲染工程图 PDF

drawing_source.json 由 cad-viewer-app 导出,自带绝对坐标(views.x/y、tables.x/y、
title_block.fields.x/y、bom_table.x/y),因此后端无需重新投影几何,直接按同一坐标
用 reportlab 重绘即可与前端所见一致。中文字体用内置 STSong-Light(CID),规避
svglib 无法映射中文的问题。

坐标约定(与 cad-viewer-app 一致):
  - 视图组 transform = translate(view.x, view.y) scale(view.bbox.scale)
  - 标注/表格/标题栏均使用 sheet mm 坐标(原点左上,y 向下)
  - reportlab 画布 y 向上,渲染时统一做 y 翻转: pdf_y = sheetH - y
"""
import os

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

_CN_FONT = "STSong-Light"
_FONT_READY = False

# 前端导出时把单元格字体(px)按画布缩放换算成 mm;文档未存 sheetZoom,
# 用常见导出缩放 2px/mm 近似还原(后续可从 doc 取精确值再调)。
_PX_PER_MM = 2.0

# 线宽 / 字号
_W_VISIBLE = 0.4
_W_HIDDEN = 0.3
_W_TABLE = 0.3
_W_TITLE = 0.3
_FS_TITLE = 3.0
_W_DIM = 0.5
_W_EXT = 0.3
_FS_DIM = 3.0
_C_EDGE = (0.2, 0.2, 0.2)
_C_HIDDEN = (0.6, 0.6, 0.6)
_C_DIM = (0.08, 0.4, 0.75)
_C_EXT = (0.4, 0.4, 0.4)


def _ensure_font():
    global _FONT_READY
    if not _FONT_READY:
        pdfmetrics.registerFont(UnicodeCIDFont(_CN_FONT))
        _FONT_READY = True


def _hex_rgb(hex_color, default):
    if not hex_color:
        return default
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return default
    try:
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return default


def _view_scale(view):
    return view.get("bbox", {}).get("scale") or view.get("scale") or 1.0


def render_drawing_source_pdf(doc, output_pdf):
    """将 drawing_source.json(dict) 渲染为 PDF 工程图,返回输出文件绝对路径"""
    _ensure_font()
    sheet = doc.get("sheet", {}) or {}
    sw = sheet.get("width", 420)
    sh = sheet.get("height", 297)
    fy = lambda v: sh - v  # 模板 y(向下) → PDF y(向上)

    out_dir = os.path.dirname(os.path.abspath(output_pdf))
    os.makedirs(out_dir, exist_ok=True)

    c = pdf_canvas.Canvas(output_pdf, pagesize=(sw * mm, sh * mm))
    c.setTitle(doc.get("model_id") or "工程图")
    c.scale(mm, mm)  # 之后所有坐标均为 sheet mm

    # 图框
    c.setStrokeColorRGB(*_C_EDGE)
    c.setLineWidth(0.8)
    c.rect(10, fy(10), sw - 20, sh - 20, stroke=1, fill=0)

    _draw_views(c, doc.get("views", []), fy)
    _draw_annotations(c, doc, fy)
    for t in doc.get("tables", []):
        _draw_table(c, t, fy)
    _draw_title_block(c, doc.get("title_block"), fy)
    _draw_bom(c, doc.get("bom_table"), fy)

    c.showPage()
    c.save()
    return os.path.abspath(output_pdf)


# --------------------------------------------------------------------------
# 视图几何
# --------------------------------------------------------------------------
def _draw_views(c, views, fy):
    for view in views:
        s = _view_scale(view)
        ox, oy = view.get("x", 0), view.get("y", 0)
        label = view.get("label") or view.get("id")
        c.setFillColorRGB(*_C_HIDDEN)
        c.setFont(_CN_FONT, 3.5)
        c.drawString(ox + 2, fy(oy - 2), label)

        c.setLineWidth(_W_VISIBLE)
        c.setStrokeColorRGB(*_C_EDGE)
        for seg in view.get("edges", []):
            _draw_seg(c, seg, s, ox, oy, fy)

        c.setLineWidth(_W_HIDDEN)
        c.setStrokeColorRGB(*_C_HIDDEN)
        c.setDash(1, 1)
        for seg in view.get("hidden_edges", []) or []:
            _draw_seg(c, seg, s, ox, oy, fy)
        c.setDash()


def _draw_seg(c, seg, s, ox, oy, fy):
    t = seg.get("type")
    tx = lambda x: ox + s * x
    ty = lambda y: oy + s * y

    def P(p):
        return (tx(p[0]), fy(ty(p[1])))

    if t == "line":
        c.line(tx(seg["x1"]), fy(ty(seg["y1"])), tx(seg["x2"]), fy(ty(seg["y2"])))
    elif t == "polyline":
        pts = seg.get("points", [])
        if len(pts) >= 2:
            path = c.beginPath()
            path.moveTo(*P(pts[0]))
            for p in pts[1:]:
                path.lineTo(*P(p))
            c.drawPath(path, stroke=1, fill=0)
    elif t == "circle":
        cx, cy = tx(seg["cx"]), fy(ty(seg["cy"]))
        c.circle(cx, cy, s * seg["r"], stroke=1, fill=0)


# --------------------------------------------------------------------------
# 标注(线性标注为主,直径/半径/指引线尽力还原)
# --------------------------------------------------------------------------
def _edge_endpoints(view, idx, hidden=False):
    segs = view.get("hidden_edges", []) if hidden else view.get("edges", [])
    if idx is None or idx < 0 or idx >= len(segs):
        return None
    seg = segs[idx]
    s = _view_scale(view)
    ox, oy = view.get("x", 0), view.get("y", 0)

    def P(p):
        return (ox + s * p[0], oy + s * p[1])

    if seg.get("type") == "line":
        return P((seg["x1"], seg["y1"])), P((seg["x2"], seg["y2"]))
    if seg.get("type") == "polyline":
        pts = seg.get("points", [])
        if len(pts) >= 2:
            return P(pts[0]), P(pts[-1])
    return None


def _draw_annotations(c, doc, fy):
    views = {v["id"]: v for v in doc.get("views", [])}
    for ann in doc.get("annotations", []):
        color = _hex_rgb(ann.get("color"), _C_DIM)
        c.setStrokeColorRGB(*color)
        c.setFillColorRGB(*color)
        at = ann.get("type")
        refs = ann.get("refs", [])
        if at in ("linear", "linear_text") and refs:
            ref = refs[0]
            view = views.get(ref.get("viewId"))
            if not view:
                continue
            ends = _edge_endpoints(view, ref.get("idx"),
                                   hidden=(ref.get("type") == "hiddenEdges"))
            if not ends:
                continue
            p1m, p2m = ends  # sheet mm, y 向下
            offset = (ann.get("offset") or 8) * _view_scale(view)
            _draw_linear_dim(c, p1m, p2m, ann.get("text", ""), offset, fy)
        elif at in ("diameter", "radius", "hole"):
            # 指引线类:尽力在引用边中点附近标出文字
            if refs:
                ref = refs[0]
                view = views.get(ref.get("viewId"))
                if view:
                    ends = _edge_endpoints(view, ref.get("idx"),
                                           hidden=(ref.get("type") == "hiddenEdges"))
                    if ends:
                        mid = ((ends[0][0] + ends[1][0]) / 2,
                               (ends[0][1] + ends[1][1]) / 2)
                        c.setFont(_CN_FONT, _FS_DIM)
                        c.drawCentredString(mid[0], fy(mid[1] - 4),
                                            ann.get("text", ""))


def _draw_linear_dim(c, p1, p2, text, offset, fy):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    horizontal = abs(dx) >= abs(dy)
    c.setStrokeColorRGB(*_C_EXT)
    c.setLineWidth(_W_EXT)
    c.setDash(1, 1)
    if horizontal:
        oy_line = min(p1[1], p2[1]) - offset  # 向外(屏幕上方)
        c.line(p1[0], fy(p1[1]), p1[0], fy(oy_line))
        c.line(p2[0], fy(p2[1]), p2[0], fy(oy_line))
        c.setDash()
        c.setStrokeColorRGB(*_C_DIM)
        c.setLineWidth(_W_DIM)
        c.line(p1[0], fy(oy_line), p2[0], fy(oy_line))
        c.setFont(_CN_FONT, _FS_DIM)
        c.drawCentredString((p1[0] + p2[0]) / 2, fy(oy_line - 4), text)
    else:
        ox_line = max(p1[0], p2[0]) + offset
        c.line(p1[0], fy(p1[1]), ox_line, fy(p1[1]))
        c.line(p2[0], fy(p2[1]), ox_line, fy(p2[1]))
        c.setDash()
        c.setStrokeColorRGB(*_C_DIM)
        c.setLineWidth(_W_DIM)
        c.line(ox_line, fy(p1[1]), ox_line, fy(p2[1]))
        c.setFont(_CN_FONT, _FS_DIM)
        c.drawCentredString(ox_line + 2, fy((p1[1] + p2[1]) / 2), text)


# --------------------------------------------------------------------------
# 表格(含标题栏表格、技术参数表等)
# --------------------------------------------------------------------------
def _cell_rect(table, r, c, cs, rs):
    colw = table.get("col_widths", [])
    rowh = table.get("row_heights", [])
    x0 = table.get("x", 0)
    y0 = table.get("y", 0)
    xc = x0 + sum(colw[:c])
    yc_top = y0 + sum(rowh[:r])
    w = sum(colw[c:c + cs])
    h = sum(rowh[r:r + rs])
    return xc, yc_top, w, h


def _draw_table(c, table, fy):
    colw = table.get("col_widths", [])
    rowh = table.get("row_heights", [])
    if not colw or not rowh:
        return
    x0 = table.get("x", 0)
    y0 = table.get("y", 0)
    w_total = sum(colw)
    h_total = sum(rowh)

    # 外框 + 网格(逐格画,合并单元格自然只画其自身边框)
    c.setStrokeColorRGB(*_C_EDGE)
    c.setLineWidth(_W_TABLE)
    for cell in table.get("cells", []):
        r, c_ = cell.get("r"), cell.get("c")
        cs = cell.get("colspan", 1)
        rs = cell.get("rowspan", 1)
        xc, yc_top, w, h = _cell_rect(table, r, c_, cs, rs)
        c.rect(xc, fy(yc_top + h), w, h, stroke=1, fill=0)

    # 文本
    for cell in table.get("cells", []):
        text = cell.get("text")
        if not text:
            continue
        r, c_ = cell.get("r"), cell.get("c")
        cs = cell.get("colspan", 1)
        rs = cell.get("rowspan", 1)
        xc, yc_top, w, h = _cell_rect(table, r, c_, cs, rs)
        fs = (cell.get("font_size") or 20) / _PX_PER_MM
        fs = max(1.5, min(fs, h * 0.7))
        c.setFillColorRGB(*_C_EDGE)
        c.setFont(_CN_FONT, fs)
        align = cell.get("align", "") or ""
        # 基线:单元底部(屏幕 y 向下)对应 PDF 顶 - h + 文字偏置
        ty = fy(yc_top + h) + (h - fs) / 2.0
        if "h-center" in align:
            c.drawCentredString(xc + w / 2.0, ty, text)
        elif "h-right" in align:
            c.drawRightString(xc + w - 1.5, ty, text)
        else:
            c.drawString(xc + 1.5, ty, text)


# --------------------------------------------------------------------------
# 标题栏字段(带绝对 x/y)
# --------------------------------------------------------------------------
def _draw_title_block(c, title_block, fy):
    fields = (title_block or {}).get("fields", []) or []
    if not fields:
        return
    c.setFillColorRGB(*_C_EDGE)
    c.setFont(_CN_FONT, _FS_TITLE)
    for f in fields:
        x = f.get("x")
        y = f.get("y")
        if x is None or y is None:
            continue
        value = f.get("value")
        if value is None:
            value = f.get("source") or ""
        if not value:
            continue
        # 只画 value(模板 label 已在图纸固定位置印出)
        c.drawString(x, fy(y), str(value))


# --------------------------------------------------------------------------
# BOM 表
# --------------------------------------------------------------------------
def _draw_bom(c, bom, fy):
    if not bom or not bom.get("columns"):
        return
    x0 = bom.get("x", 0)
    y0 = bom.get("y", 0)
    cols = bom["columns"]
    rows = bom.get("rows", [])
    # 列宽按比例分配(文档未存,用页数均分近似)
    n = len(cols)
    colw = [40.0] * n if n else [40]
    rowh = 8.0
    c.setStrokeColorRGB(*_C_EDGE)
    c.setLineWidth(_W_TABLE)
    c.setFillColorRGB(*_C_EDGE)
    c.setFont(_CN_FONT, 2.6)
    # 表头
    for i, col in enumerate(cols):
        c.rect(x0 + i * colw[i], fy(y0 + rowh), colw[i], rowh, stroke=1, fill=0)
        c.drawCentredString(x0 + i * colw[i] + colw[i] / 2.0,
                            fy(y0 + rowh) + (rowh - 2.6) / 2.0, str(col))
    # 数据行
    for ri, row in enumerate(rows):
        yy = y0 + (ri + 1) * rowh
        vals = [str(row.get("name", "")), str(row.get("qty", "")),
                str(row.get("code") or ""), str(row.get("material") or "")]
        for i in range(n):
            c.rect(x0 + i * colw[i], fy(yy + rowh), colw[i], rowh, stroke=1, fill=0)
            c.drawString(x0 + i * colw[i] + 1.0,
                         fy(yy + rowh) + (rowh - 2.6) / 2.0,
                         vals[i] if i < len(vals) else "")
