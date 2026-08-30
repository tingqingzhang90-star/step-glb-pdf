# -*- coding: utf-8 -*-
"""工程图 PDF 渲染器 — 从 apply_template 结果直接绘制 PDF

不走 SVG→svglib 转换(svglib 无法映射 CID 中文字体,且 px→pt 会缩水),
直接用 reportlab canvas 绘制视图边线/标注/标题栏,中文字体用内置
STSong-Light。

模板坐标系与 SVG 一致(y 向下,原点左上),PDF 坐标系 y 向上,
渲染时统一做 y 翻转: pdf_y = sheet_height - tmpl_y。

调用方式:
    from drawing_pdf import render_drawing_pdf
    render_drawing_pdf(template_result, "out.pdf", params)
"""
import os

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

_CN_FONT = "STSong-Light"
_FONT_READY = False

# 线宽/字号(模板坐标 mm)
_W_VISIBLE = 0.4
_W_HIDDEN = 0.3
_W_DIM = 0.5
_W_EXT = 0.3
_FS_DIM = 3.0
_FS_LABEL = 2.5
_FS_TITLE = 2.5
_FS_VIEW = 3.5
_ARROWS = 1.5  # 箭头大小

_C_EDGE = (0.2, 0.2, 0.2)
_C_HIDDEN = (0.6, 0.6, 0.6)
_C_DIM = (0.08, 0.4, 0.75)
_C_EXT = (0.4, 0.4, 0.4)


def _ensure_font():
    global _FONT_READY
    if not _FONT_READY:
        pdfmetrics.registerFont(UnicodeCIDFont(_CN_FONT))
        _FONT_READY = True


def _draw_segment(c, seg, scale, ox, oy, fy):
    """单条边线: 模型坐标 → 模板屏幕坐标 → PDF(含 y 翻转)"""
    t = lambda v: v * scale + ox
    u = lambda v: fy(v * scale + oy)
    st = seg.get("type", "")
    if st == "line":
        c.line(t(seg["x1"]), u(seg["y1"]), t(seg["x2"]), u(seg["y2"]))
    elif st == "circle":
        c.circle(t(seg["cx"]), u(seg["cy"]), seg["r"] * scale, stroke=1, fill=0)
    elif st == "polyline":
        pts = seg.get("points", [])
        if len(pts) >= 2:
            path = c.beginPath()
            path.moveTo(t(pts[0][0]), u(pts[0][1]))
            for p in pts[1:]:
                path.lineTo(t(p[0]), u(p[1]))
            c.drawPath(path, stroke=1, fill=0)


def _draw_arrow(c, x, y_tmpl, direction, fy):
    """实心三角箭头(direction 为模板坐标系语义: up=y 减小)"""
    s = _ARROWS
    y = fy(y_tmpl)
    if direction == "right":
        pts = [(x, y), (x + s, y - s / 2), (x + s, y + s / 2)]
    elif direction == "left":
        pts = [(x, y), (x - s, y - s / 2), (x - s, y + s / 2)]
    elif direction == "up":  # 模板系向上 = PDF y 减小
        pts = [(x, y), (x - s / 2, y - s), (x + s / 2, y - s)]
    elif direction == "down":
        pts = [(x, y), (x - s / 2, y + s), (x + s / 2, y + s)]
    else:
        return
    p = c.beginPath()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    p.close()
    c.drawPath(p, stroke=0, fill=1)


def _draw_dim_text(c, x, y_tmpl, text, fy, size=_FS_DIM, center=True):
    c.setFont(_CN_FONT, size)
    if center:
        c.drawCentredString(x, fy(y_tmpl), text)
    else:
        c.drawString(x, fy(y_tmpl), text)


def _draw_linear_dim(c, dim, fy):
    """线性/文字型线性标注: 尺寸线 + 延伸线 + 箭头 + 文本(模板坐标系)"""
    p1, p2 = dim.get("p1_screen"), dim.get("p2_screen")
    if not p1 or not p2:
        return
    offset = dim.get("offset", 20)
    orient = dim.get("orientation", "horizontal")
    c.setFillColorRGB(*_C_DIM)

    if orient == "horizontal":
        oy = max(p1[1], p2[1]) + offset
        c.setStrokeColorRGB(*_C_EXT)
        c.setLineWidth(_W_EXT)
        c.setDash(1, 1)
        c.line(p1[0], fy(p1[1]), p1[0], fy(oy))
        c.line(p2[0], fy(p2[1]), p2[0], fy(oy))
        c.setDash()
        c.setStrokeColorRGB(*_C_DIM)
        c.setLineWidth(_W_DIM)
        c.line(p1[0], fy(oy), p2[0], fy(oy))
        d1 = "right" if p2[0] > p1[0] else "left"
        d2 = "left" if p2[0] > p1[0] else "right"
        _draw_arrow(c, p1[0], oy, d1, fy)
        _draw_arrow(c, p2[0], oy, d2, fy)
        _draw_dim_text(c, (p1[0] + p2[0]) / 2, oy - 4.2, dim.get("text", ""), fy)
        if dim.get("label"):
            _draw_dim_text(c, (p1[0] + p2[0]) / 2, max(p1[1], p2[1]) + 5,
                           f"({dim['label']})", fy, size=_FS_LABEL)
    elif orient == "vertical":
        ox = max(p1[0], p2[0]) + offset
        c.setStrokeColorRGB(*_C_EXT)
        c.setLineWidth(_W_EXT)
        c.setDash(1, 1)
        c.line(p1[0], fy(p1[1]), ox, fy(p1[1]))
        c.line(p2[0], fy(p2[1]), ox, fy(p2[1]))
        c.setDash()
        c.setStrokeColorRGB(*_C_DIM)
        c.setLineWidth(_W_DIM)
        c.line(ox, fy(p1[1]), ox, fy(p2[1]))
        _draw_arrow(c, ox, p1[1], "down" if p2[1] < p1[1] else "up", fy)
        _draw_arrow(c, ox, p2[1], "up" if p2[1] < p1[1] else "down", fy)
        _draw_dim_text(c, ox + 2, (p1[1] + p2[1]) / 2, dim.get("text", ""), fy)
        if dim.get("label"):
            _draw_dim_text(c, ox + 2, (p1[1] + p2[1]) / 2 + 4,
                           f"({dim['label']})", fy, size=_FS_LABEL)
    else:
        c.setStrokeColorRGB(*_C_DIM)
        c.setLineWidth(_W_DIM)
        c.line(p1[0], fy(p1[1]), p2[0], fy(p2[1]))
        _draw_dim_text(c, (p1[0] + p2[0]) / 2,
                       (p1[1] + p2[1]) / 2 + 1.2, dim.get("text", ""), fy)


def _draw_leader_dim(c, dim, fy):
    """直径/半径类: 圆心 → 引线 → 文本"""
    center = dim.get("center_screen")
    if not center:
        return
    leader = dim.get("leader_end")
    c.setStrokeColorRGB(*_C_DIM)
    c.setFillColorRGB(*_C_DIM)
    if leader:
        c.setLineWidth(_W_DIM)
        c.line(center[0], fy(center[1]), leader[0], fy(leader[1]))
        _draw_dim_text(c, leader[0] + 1, leader[1], dim.get("text", ""), fy,
                       center=False)
    else:
        _draw_dim_text(c, center[0], center[1] - 2, dim.get("text", ""), fy)


def _draw_text_dim(c, dim, fy):
    pos = dim.get("position") or {"x": 0, "y": 0}
    c.setFillColorRGB(*_C_EDGE)
    _draw_dim_text(c, pos.get("x", 0), pos.get("y", 0), dim.get("text", ""), fy,
                   center=False)


def render_drawing_pdf(template_result, output_pdf, params=None):
    """将 apply_template() 的结果渲染为 PDF 工程图

    Args:
        template_result: apply_template() 返回值(含 sheet/views/dimensions/title_block)
        output_pdf: 输出 PDF 路径
        params: 参数 dict(仅用于 PDF 元数据标题)

    Returns:
        str: 输出文件绝对路径
    """
    _ensure_font()
    sheet = template_result.get("sheet", {"width": 420, "height": 297})
    sw, sh = sheet.get("width", 420), sheet.get("height", 297)
    fy = lambda v: sh - v  # 模板 y(向下) → PDF y(向上)

    out_dir = os.path.dirname(os.path.abspath(output_pdf))
    os.makedirs(out_dir, exist_ok=True)

    c = pdf_canvas.Canvas(output_pdf, pagesize=(sw * mm, sh * mm))
    title = (params or {}).get("model_code", "工程图")
    c.setTitle(title)
    c.scale(mm, mm)  # 之后所有坐标均为模板 mm 坐标

    # 图框
    c.setStrokeColorRGB(*_C_EDGE)
    c.setLineWidth(0.8)
    c.rect(10, fy(10), sw - 20, sh - 20, stroke=1, fill=0)

    # 视图边线
    for view_id, vdata in template_result.get("views", {}).items():
        scale = vdata.get("scale", 1.0)
        ox, oy = vdata.get("offset", [0, 0])
        c.setFillColorRGB(*_C_HIDDEN)
        c.setFont(_CN_FONT, _FS_VIEW)
        c.drawString(ox + 5, fy(oy - 5), vdata.get("label", view_id))

        c.setLineWidth(_W_VISIBLE)
        c.setStrokeColorRGB(*_C_EDGE)
        for seg in vdata.get("visible", []):
            _draw_segment(c, seg, scale, ox, oy, fy)
        c.setLineWidth(_W_HIDDEN)
        c.setStrokeColorRGB(*_C_HIDDEN)
        c.setDash(1, 1)
        for seg in vdata.get("hidden", []):
            _draw_segment(c, seg, scale, ox, oy, fy)
        c.setDash()

    # 标注
    for dim in template_result.get("dimensions", []):
        dt = dim.get("type", "")
        if dt in ("linear", "linear_text"):
            _draw_linear_dim(c, dim, fy)
        elif dt in ("hole", "diameter", "radius"):
            _draw_leader_dim(c, dim, fy)
        elif dt == "text":
            _draw_text_dim(c, dim, fy)

    # 标题栏(SVG 版位于右下角)
    fields = template_result.get("title_block", {}).get("fields", [])
    if fields:
        c.setStrokeColorRGB(*_C_EDGE)
        c.setLineWidth(0.5)
        c.rect(sw - 110, fy(sh - 10), 100, 35, stroke=1, fill=0)
        c.setFillColorRGB(*_C_EDGE)
        for field in fields:
            c.setFont(_CN_FONT, _FS_TITLE)
            c.drawString(field.get("x", 0), fy(field.get("y", 0)),
                         f"{field.get('name', '')}: {field.get('value', '')}")

    c.showPage()
    c.save()
    return os.path.abspath(output_pdf)
