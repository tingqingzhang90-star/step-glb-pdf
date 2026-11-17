# -*- coding: utf-8 -*-
"""断裂视图的 PDF 绘制:双段裁剪、右段平移、双波浪线

边线描边由调用方的 stroke(c, placement, mapper, dx, dy) 提供,本模块只做
视图级坐标变换,不复制也不改动 edges/hidden 数组。
"""
from drawing import break_view


def draw_broken(c, placement, mapper, spec, stroke, color, width):
    """分两段裁剪描边,切口处再补两条波浪折断线"""
    canvas = 400.0 if spec.axis == "x" else 300.0
    for lo, hi, shift in break_view.clip_ranges(spec, canvas):
        # 右段绘制时坐标已平移,裁剪框必须跟着平移,否则切口附近会被裁空
        _clip_band(c, placement, mapper, spec, lo + shift, hi + shift)
        dx, dy = (shift, 0.0) if spec.axis == "x" else (0.0, shift)
        stroke(c, placement, mapper, dx, dy)
        c.restoreState()
    _draw_waves(c, placement, mapper, spec, color, width)


def _clip_band(c, placement, mapper, spec, lo, hi):
    """把轴向 [lo, hi] 之外的边线裁掉,另一轴取整个 400x300 画布"""
    s = placement["scale"]
    ox, oy = placement["x"], placement["y"]
    if spec.axis == "x":
        p1 = mapper.pt(lo * s + ox, oy)
        p2 = mapper.pt(hi * s + ox, 300 * s + oy)
    else:
        p1 = mapper.pt(ox, lo * s + oy)
        p2 = mapper.pt(400 * s + ox, hi * s + oy)
    c.saveState()
    path = c.beginPath()
    path.rect(min(p1[0], p2[0]), min(p1[1], p2[1]),
              abs(p2[0] - p1[0]), abs(p2[1] - p1[1]))
    c.clipPath(path, stroke=0, fill=0)


def _draw_waves(c, placement, mapper, spec, color, width):
    """跨轴范围取视图内容包围盒,波浪线不画到空白画布上"""
    cb = placement.get("contentBBox") or {}
    if spec.axis == "x":
        cross_lo = float(cb.get("y") or 0)
        cross_hi = cross_lo + float(cb.get("height") or 300)
    else:
        cross_lo = float(cb.get("x") or 0)
        cross_hi = cross_lo + float(cb.get("width") or 400)
    s = placement["scale"]
    ox, oy = placement["x"], placement["y"]
    c.setStrokeColorRGB(*color)
    c.setLineWidth(width)
    for pts in break_view.wave_points(spec, cross_lo, cross_hi):
        if len(pts) < 2:
            continue
        path = c.beginPath()
        path.moveTo(*mapper.pt(pts[0][0] * s + ox, pts[0][1] * s + oy))
        for p in pts[1:]:
            path.lineTo(*mapper.pt(p[0] * s + ox, p[1] * s + oy))
        c.drawPath(path, stroke=1, fill=0)
