# -*- coding: utf-8 -*-
"""前端样式标注的重算与 PDF 渲染 — 对齐 cad-viewer-app dimensions/core.js

把重绑后的标注(目标边线 + 模板外观参数)在图纸坐标系(A0, y 向下)重建
几何,再等比映射到 A3 PDF。构建算法逐条移植 core.js 的 build*Geometry,
箭头/文字/中心十字与编辑器所见即所得。
"""
import math

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

from drawing.dim.dim_geometry import (to_line_seg, to_circle, line_basis, offset_point,
                          signed_distance_to_line, closest_point_on_line,
                          project_point_to_line, line_intersection,
                          farthest_endpoint_from, build_arc_points,
                          build_linear_arrows, build_arrow_points,
                          format_mm, format_deg)

_CN_FONT = "STSong-Light"
_FONT_READY = False
DEFAULT_DIM_COLOR = "#303133"

PDF_W, PDF_H = 420.0, 297.0  # A3 横放 mm


def _ensure_font():
    global _FONT_READY
    if not _FONT_READY:
        pdfmetrics.registerFont(UnicodeCIDFont(_CN_FONT))
        _FONT_READY = True


def _hex_rgb(color):
    c = color or DEFAULT_DIM_COLOR
    try:
        return (int(c[1:3], 16) / 255, int(c[3:5], 16) / 255,
                int(c[5:7], 16) / 255)
    except (ValueError, IndexError):
        return (0.19, 0.19, 0.19)


def _sheet_point(placement, lx, ly):
    return (placement["x"] + lx * placement["scale"],
            placement["y"] + ly * placement["scale"])


def _line_mm_length(line):
    m = (line.get("meta") or {}).get("mm_coords")
    if not m or len(m) < 4:
        return None
    return math.hypot(m[2] - m[0], m[3] - m[1])


def _parallel_mm_distance(line1, line2):
    m1 = (line1.get("meta") or {}).get("mm_coords")
    m2 = (line2.get("meta") or {}).get("mm_coords")
    if not m1 or not m2 or len(m1) < 4 or len(m2) < 4:
        return None
    dx, dy = m2[2] - m2[0], m2[3] - m2[1]
    len2 = dx * dx + dy * dy
    if len2 < 1e-9:
        return None
    nlen = math.sqrt(len2)
    nx, ny = -dy / nlen, dx / nlen
    d1 = abs((m1[0] - m2[0]) * nx + (m1[1] - m2[1]) * ny)
    d2 = abs((m1[2] - m2[0]) * nx + (m1[3] - m2[1]) * ny)
    return min(d1, d2)


def _circle_center_mm(seg):
    circ = to_circle(seg)
    if not circ:
        return None
    meta = circ.get("meta") or {}
    c = meta.get("center_mm")
    return (c[0], c[1]) if isinstance(c, list) and len(c) == 2 else None


def _point_to_line_mm(c, endpoints):
    a, b = endpoints
    dx, dy = b[0] - a[0], b[1] - a[1]
    len2 = dx * dx + dy * dy
    if len2 < 1e-9:
        return None
    nlen = math.sqrt(len2)
    nx, ny = -dy / nlen, dx / nlen
    return abs((c[0] - a[0]) * nx + (c[1] - a[1]) * ny)


def _mark_half_px(seg, placement):
    circ = to_circle(seg)
    if not circ:
        return 0.0
    return circ["r"] * placement["scale"] + 0.2 / (placement["k"] or 1.0)


def _texts_and_final(prims, text, custom_text):
    if custom_text:
        prims["text"] = custom_text
        for t in prims.get("texts", []):
            t["text"] = custom_text
    return prims


def build_dim_primitives(ann, segs, views):
    """按 core.js 对应 build*Geometry 在图纸坐标系重建标注几何

    Returns:
        dict: {lines, ext_lines, arrows, texts, arcs, center_marks, text}
        或 None(几何构建失败)
    """
    dtype = ann.get("type")
    custom = ann.get("customText") or None

    if dtype == "linear":
        mode = ann.get("mode") or "single"
        builder = {"single": _linear_single, "parallel": _linear_parallel,
                   "center": _linear_center,
                   "circle-edge": _linear_circle_edge}.get(mode)
        if builder is None:
            return None
        prims = builder(ann, segs, views)
    elif dtype == "diameter":
        prims = _diameter(ann, segs[0], views[0])
    elif dtype == "angle":
        prims = _angle(ann, segs, views)
    elif dtype == "center-mark":
        prims = _center_mark(segs, views)
    else:
        return None
    if prims is None:
        return None
    return _texts_and_final(prims, prims.get("text"), custom)


def _linear_single(ann, segs, views):
    line = to_line_seg(segs[0])
    view = views[0]
    if not line or not view:
        return None
    p1 = _sheet_point(view, line["x1"], line["y1"])
    p2 = _sheet_point(view, line["x2"], line["y2"])
    basis = line_basis(p1, p2)
    if not basis:
        return None
    offset = ann.get("offset") or 50
    e1 = offset_point(p1, basis["perp"], offset)
    e2 = offset_point(p2, basis["perp"], offset)
    mm_val = _line_mm_length(line)
    if mm_val is None:
        mm_val = basis["len"] / (view["scale"] * (view["k"] or 1.0))
    text = format_mm(mm_val)
    arrows = build_linear_arrows(e1, e2, basis["unit"], text)
    return {
        "lines": [(p1, e1), (p2, e2)],
        "dim_lines": [(e1, e2)],
        "arrows": [arrows["arrow1"], arrows["arrow2"]],
        "texts": [{"pos": ((e1[0] + e2[0]) / 2, (e1[1] + e2[1]) / 2 - 3),
                   "text": text, "angle": 0.0, "anchor": "middle"}],
        "center_marks": [], "text": text,
    }


def _linear_parallel(ann, segs, views):
    line1, line2 = to_line_seg(segs[0]), to_line_seg(segs[1])
    v1, v2 = views[0], views[1]
    if not line1 or not line2:
        return None
    p1 = _sheet_point(v1, line1["x1"], line1["y1"])
    p2 = _sheet_point(v1, line1["x2"], line1["y2"])
    q1 = _sheet_point(v2, line2["x1"], line2["y1"])
    q2 = _sheet_point(v2, line2["x2"], line2["y2"])
    basis = line_basis(p1, p2)
    if not basis:
        return None
    normal = basis["perp"]
    distance = signed_distance_to_line(q1, p1, normal)
    if distance < 0:
        normal = (-normal[0], -normal[1])
        distance = -distance
    if distance < 0.5:
        return None
    start = closest_point_on_line(q1[0], q1[1], p1[0], p1[1], p2[0], p2[1])
    end = offset_point(start, normal, distance)
    offset = ann.get("offset") or 50
    dim_base = offset_point(start, basis["unit"], offset)
    dim_end = offset_point(dim_base, normal, distance)
    mm_val = _parallel_mm_distance(line1, line2)
    if mm_val is None:
        mm_val = distance / (v1["scale"] * (v1["k"] or 1.0))
    text = format_mm(mm_val)
    arrows = build_linear_arrows(dim_base, dim_end, normal, text)
    shift = 10 if arrows["outward"] else 14
    mid = ((dim_base[0] + dim_end[0]) / 2, (dim_base[1] + dim_end[1]) / 2)
    return {
        "lines": [(start, dim_base), (end, dim_end)],
        "dim_lines": [(dim_base, dim_end)],
        "arrows": [arrows["arrow1"], arrows["arrow2"]],
        "texts": [{"pos": (mid[0] + basis["unit"][0] * shift,
                           mid[1] + basis["unit"][1] * shift),
                   "text": text, "angle": 0.0, "anchor": "middle"}],
        "center_marks": [], "text": text,
    }


def _linear_center(ann, segs, views):
    c1_c = to_circle(segs[0])
    c2_c = to_circle(segs[1])
    v1, v2 = views[0], views[1]
    if not c1_c or not c2_c:
        return None
    c1 = _sheet_point(v1, c1_c["cx"], c1_c["cy"])
    c2 = _sheet_point(v2, c2_c["cx"], c2_c["cy"])
    basis = line_basis(c1, c2)
    if not basis:
        return None
    offset = ann.get("offset") or 50
    e1 = offset_point(c1, basis["perp"], offset)
    e2 = offset_point(c2, basis["perp"], offset)
    m1 = (to_circle(segs[0]).get("meta") or {}).get("center_mm")
    m2 = (to_circle(segs[1]).get("meta") or {}).get("center_mm")
    if m1 and m2:
        mm_val = math.hypot(m1[0] - m2[0], m1[1] - m2[1])
    else:
        mm_val = basis["len"] / (v1["scale"] * (v1["k"] or 1.0))
    text = format_mm(mm_val)
    arrows = build_linear_arrows(e1, e2, basis["unit"], text)
    return {
        "lines": [(c1, e1), (c2, e2)],
        "dim_lines": [(e1, e2)],
        "arrows": [arrows["arrow1"], arrows["arrow2"]],
        "texts": [{"pos": ((e1[0] + e2[0]) / 2, (e1[1] + e2[1]) / 2 - 3),
                   "text": text, "angle": 0.0, "anchor": "middle"}],
        "center_marks": [
            {"pos": c1, "r": _mark_half_px(segs[0], v1), "angle": None},
            {"pos": c2, "r": _mark_half_px(segs[1], v2), "angle": None},
        ],
        "text": text,
    }


def _linear_circle_edge(ann, segs, views):
    circ = to_circle(segs[0])
    line = to_line_seg(segs[1])
    vc, vl = views[0], views[1]
    if not circ or not line:
        return None
    c = _sheet_point(vc, circ["cx"], circ["cy"])
    q1 = _sheet_point(vl, line["x1"], line["y1"])
    q2 = _sheet_point(vl, line["x2"], line["y2"])
    basis = line_basis(q1, q2)
    if not basis:
        return None
    u = basis["unit"]
    offset = ann.get("offset") or 50
    f = project_point_to_line(c, q1, u)
    foot_c = offset_point(c, u, offset)
    foot_f = offset_point(f, u, offset)
    meta = circ.get("meta") or {}
    mm_c = meta.get("center_mm")
    mm_line = (line.get("meta") or {}).get("mm_coords")
    if mm_c and mm_line:
        mm_val = _point_to_line_mm(mm_c, [mm_line[0:2], mm_line[2:4]])
    else:
        d = abs(signed_distance_to_line(c, q1, basis["perp"]))
        mm_val = d / (vc["scale"] * (vc["k"] or 1.0))
    text = format_mm(mm_val)
    arrows = build_linear_arrows(foot_c, foot_f, basis["perp"], text)
    return {
        "lines": [(c, foot_c), (f, foot_f)],
        "dim_lines": [(foot_c, foot_f)],
        "arrows": [arrows["arrow1"], arrows["arrow2"]],
        "texts": [{"pos": ((foot_c[0] + foot_f[0]) / 2,
                           (foot_c[1] + foot_f[1]) / 2 - 3),
                   "text": text, "angle": 0.0, "anchor": "middle"}],
        "center_marks": [{"pos": c, "r": _mark_half_px(segs[0], vc),
                          "angle": math.atan2(u[1], u[0])}],
        "text": text,
    }


def _diameter(ann, seg, view):
    circ = to_circle(seg)
    if not circ or not view:
        return None
    cx = view["x"] + circ["cx"] * view["scale"]
    cy = view["y"] + circ["cy"] * view["scale"]
    r = circ["r"] * view["scale"]
    angle = ann.get("leaderAngle")
    if angle is None:
        angle = -math.pi / 4
    leader_length = ann.get("leaderLength") or 30
    d = (math.cos(angle), math.sin(angle))
    leader_start = (cx - d[0] * r, cy - d[1] * r)
    edge_pt = (cx + d[0] * r, cy + d[1] * r)
    leader_end = (cx + d[0] * (r + leader_length),
                  cy + d[1] * (r + leader_length))
    perp1 = (-d[1], d[0])
    perp2 = (d[1], -d[0])
    perp = perp1 if perp1[1] <= perp2[1] else perp2
    text_pos = (leader_end[0] - d[0] * 20 + perp[0] * 4,
                leader_end[1] - d[1] * 20 + perp[1] * 4)
    radius = (circ.get("meta") or {}).get("radius")
    mm_val = radius * 2 if radius else circ["r"] * 2 / (view["k"] or 1.0)
    text_angle = angle + math.pi if abs(angle) > math.pi / 2 else angle
    text = f"ø{format_mm(mm_val)}"
    return {
        "lines": [], "dim_lines": [(leader_start, leader_end)],
        "arrows": [build_arrow_points(edge_pt, d, False)],
        "texts": [{"pos": text_pos, "text": text,
                   "angle": text_angle, "anchor": "start"}],
        "center_marks": [], "text": text,
    }


def _angle(ann, segs, views):
    line1, line2 = to_line_seg(segs[0]), to_line_seg(segs[1])
    v1, v2 = views[0], views[1]
    if not line1 or not line2:
        return None
    p1 = _sheet_point(v1, line1["x1"], line1["y1"])
    p2 = _sheet_point(v1, line1["x2"], line1["y2"])
    q1 = _sheet_point(v2, line2["x1"], line2["y1"])
    q2 = _sheet_point(v2, line2["x2"], line2["y2"])
    inter = line_intersection(p1, p2, q1, q2)
    if not inter:
        return None
    dir1 = line_basis(inter, farthest_endpoint_from(inter, p1, p2))
    dir2 = line_basis(inter, farthest_endpoint_from(inter, q1, q2))
    if not dir1 or not dir2:
        return None
    start = math.atan2(dir1["unit"][1], dir1["unit"][0])
    end = math.atan2(dir2["unit"][1], dir2["unit"][0])
    while end < start:
        end += math.pi * 2
    if end - start > math.pi:
        start, end = end, start + math.pi * 2
    sweep = end - start
    radius = ann.get("radius") or 40
    a1 = start + sweep * 0.05
    a2 = end - sweep * 0.05
    ap1 = (inter[0] + math.cos(a1) * radius, inter[1] + math.sin(a1) * radius)
    ap2 = (inter[0] + math.cos(a2) * radius, inter[1] + math.sin(a2) * radius)
    tan1 = (-math.sin(a1), math.cos(a1))
    tan2 = (-math.sin(a2), math.cos(a2))
    mid_angle = start + sweep / 2
    angle_val = min(sweep, math.pi * 2 - sweep)
    text = format_deg(angle_val * 180 / math.pi)
    return {
        "lines": [], "dim_lines": [],
        "arcs": [build_arc_points(inter[0], inter[1], radius, start, end)],
        "arrows": [build_arrow_points(ap1, tan1, True),
                   build_arrow_points(ap2, (-tan2[0], -tan2[1]), True)],
        "texts": [{"pos": (inter[0] + math.cos(mid_angle) * (radius + 18),
                           inter[1] + math.sin(mid_angle) * (radius + 18)),
                   "text": text, "angle": 0.0, "anchor": "middle"}],
        "center_marks": [], "text": text,
    }


def _center_mark(segs, views):
    marks = []
    for seg, view in zip(segs, views):
        circ = to_circle(seg)
        if circ:
            c = _sheet_point(view, circ["cx"], circ["cy"])
            marks.append({"pos": c, "r": _mark_half_px(seg, view),
                          "angle": None})
    if not marks:
        return None
    return {"lines": [], "dim_lines": [], "arrows": [], "texts": [],
            "center_marks": marks, "text": ""}
