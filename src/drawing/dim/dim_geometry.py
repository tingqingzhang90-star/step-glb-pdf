# -*- coding: utf-8 -*-
"""标注几何纯函数 — cad-viewer-app dimensions/geometry.js + arrow.js 的 Python 移植

坐标系与前端一致:图纸坐标 y 向下,单位为图纸像素(A0 画布)。
逐函数对齐 JS 实现,保证后端重算的标注几何与编辑器所见即所得。
"""
import math

from .dim_style import dim_arrow_len_px, dim_arrow_half_px, dim_arrow_extension_px

ARROW_LEN = dim_arrow_len_px()
ARROW_HALF = dim_arrow_half_px()
ARROW_EXTENSION = dim_arrow_extension_px()


def to_line_seg(seg):
    """line/近似直线 polyline → 两点线段;真曲线返回 None"""
    if not seg:
        return None
    st = seg.get("type")
    if st == "line":
        return {"x1": seg["x1"], "y1": seg["y1"],
                "x2": seg["x2"], "y2": seg["y2"], "meta": seg.get("meta")}
    if st == "polyline":
        pts = seg.get("points") or []
        if len(pts) < 2:
            return None
        x1, y1 = pts[0][0], pts[0][1]
        x2, y2 = pts[-1][0], pts[-1][1]
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 0.01:
            return None
        max_dev = 0.0
        for p in pts[1:-1]:
            cross = abs((x2 - x1) * (y1 - p[1]) - (x1 - p[0]) * (y2 - y1))
            max_dev = max(max_dev, cross / length)
        if max_dev > 0.015 * length:
            return None
        return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "meta": seg.get("meta")}
    return None


def fit_circle_least_squares(pts):
    """Kasa 最小二乘圆拟合(退化兜底),失败返回 None"""
    if not pts or len(pts) < 4:
        return None
    n = len(pts)
    u = sum(p[0] for p in pts) / n
    v = sum(p[1] for p in pts) / n
    suu = suv = svv = suif = svif = 0.0
    for p in pts:
        ui, vi = p[0] - u, p[1] - v
        fi = ui * ui + vi * vi
        suu += ui * ui
        suv += ui * vi
        svv += vi * vi
        suif += ui * fi
        svif += vi * fi
    denom = suu * svv - suv * suv
    if abs(denom) < 1e-9:
        return None
    cu = (svv * suif - suv * svif) / (2 * denom)
    cv = (suu * svif - suv * suif) / (2 * denom)
    cx, cy = cu + u, cv + v
    r = math.sqrt(sum((p[0] - cx) ** 2 + (p[1] - cy) ** 2 for p in pts) / n)
    if r < 0.01:
        return None
    if max(abs(math.hypot(p[0] - cx, p[1] - cy) - r) for p in pts) > max(r * 0.10, 0.8):
        return None
    return {"cx": cx, "cy": cy, "r": r}


def to_circle(seg):
    """circle/圆弧 polyline → {cx, cy, r, meta}(与前端 toCircle 同语义)"""
    if not seg:
        return None
    st = seg.get("type")
    if st == "circle":
        return {"cx": seg["cx"], "cy": seg["cy"], "r": seg["r"],
                "meta": seg.get("meta")}
    if st == "polyline":
        pts = seg.get("points") or []
        meta = seg.get("meta") or {}
        if meta.get("curve") == "circle" and isinstance(meta.get("center"), list):
            rpx = meta.get("radius_px")
            if isinstance(rpx, (int, float)) and rpx > 0:
                return {"cx": meta["center"][0], "cy": meta["center"][1],
                        "r": rpx, "meta": meta}
        if len(pts) >= 3:
            fit = fit_circle_least_squares(pts)
            if fit:
                return {"cx": fit["cx"], "cy": fit["cy"], "r": fit["r"],
                        "meta": meta}
    return None


def line_basis(p1, p2):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length < 0.5:
        return None
    unit = (dx / length, dy / length)
    return {"unit": unit, "perp": (-unit[1], unit[0]), "len": length}


def offset_point(point, direction, distance):
    return (point[0] + direction[0] * distance,
            point[1] + direction[1] * distance)


def signed_distance_to_line(point, line_point, normal):
    return ((point[0] - line_point[0]) * normal[0]
            + (point[1] - line_point[1]) * normal[1])


def closest_point_on_line(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    len_sq = dx * dx + dy * dy
    if len_sq < 0.01:
        return (x1, y1)
    t = ((px - x1) * dx + (py - y1) * dy) / len_sq
    t = max(0.0, min(1.0, t))
    return (x1 + t * dx, y1 + t * dy)


def project_point_to_line(point, line_point, direction):
    t = ((point[0] - line_point[0]) * direction[0]
         + (point[1] - line_point[1]) * direction[1])
    return (line_point[0] + direction[0] * t,
            line_point[1] + direction[1] * t)


def line_intersection(p1, p2, q1, q2):
    d1x, d1y = p2[0] - p1[0], p2[1] - p1[1]
    d2x, d2y = q2[0] - q1[0], q2[1] - q1[1]
    cross = d1x * d2y - d1y * d2x
    if abs(cross) < 0.001:
        return None
    t = ((q1[0] - p1[0]) * d2y - (q1[1] - p1[1]) * d2x) / cross
    return (p1[0] + t * d1x, p1[1] + t * d1y)


def farthest_endpoint_from(point, a, b):
    da = math.hypot(a[0] - point[0], a[1] - point[1])
    db = math.hypot(b[0] - point[0], b[1] - point[1])
    return a if da >= db else b


def build_arc_points(cx, cy, r, start_angle, end_angle, steps=20):
    """角度标注圆弧的折线近似点列(对应 JS buildArcPath)"""
    pts = []
    for i in range(steps + 1):
        t = start_angle + (end_angle - start_angle) * (i / steps)
        pts.append((cx + math.cos(t) * r, cy + math.sin(t) * r))
    return pts


def estimate_text_width(text):
    return len(str(text or "")) * 7 + 8


def build_arrow_points(end, direction, outward=True):
    """长尖实心箭头三顶点(图纸坐标),与 JS ARROW_LEN/ARROW_HALF 一致"""
    tip = direction if outward else (-direction[0], -direction[1])
    back = (-tip[0], -tip[1])
    perp = (-tip[1], tip[0])
    base_x = end[0] + back[0] * ARROW_LEN
    base_y = end[1] + back[1] * ARROW_LEN
    w = ARROW_HALF
    return [
        (end[0], end[1]),
        (base_x + perp[0] * w, base_y + perp[1] * w),
        (base_x - perp[0] * w, base_y - perp[1] * w),
    ]


def linear_arrow_dirs(start, end, text):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy) or 1.0
    unit = (dx / length, dy / length)
    span = ARROW_LEN * 2 + estimate_text_width(text) + 12
    return {"outward": length >= span, "unit": unit}


def build_linear_arrows(start, end, unit, text, mode="auto"):
    if mode == "outward":
        outward = True
    elif mode == "inward":
        outward = False
    else:
        dirs = linear_arrow_dirs(start, end, text)
        outward = dirs["outward"]
    dir1 = (-unit[0], -unit[1]) if outward else unit
    dir2 = unit if outward else (-unit[0], -unit[1])
    return {
        "outward": outward,
        "arrow1": build_arrow_points(start, dir1, True),
        "arrow2": build_arrow_points(end, dir2, True),
    }


def extend_linear_line(start, end, outward, unit, ext_start_px=None, ext_end_px=None):
    """尺寸线两端实际起止:outward 时等于箭头尖端;inward 时穿过箭头向外延伸。
    ext_start_px / ext_end_px 可选,分别覆盖全局 ARROW_EXTENSION(单侧独立延长)。
    对应 JS extendLinearLine。"""
    ext_s = ARROW_EXTENSION if ext_start_px is None else ext_start_px
    ext_e = ARROW_EXTENSION if ext_end_px is None else ext_end_px
    if outward:
        return start, end
    return (
        (start[0] - unit[0] * ext_s, start[1] - unit[1] * ext_s),
        (end[0] + unit[0] * ext_e, end[1] + unit[1] * ext_e),
    )


def format_mm(value):
    """对应 JS formatMm: 440 → '440', 440.5 → '440.5'(不带单位)"""
    s = f"{float(value or 0):.1f}".rstrip("0").rstrip(".")
    return s or '0'


def format_deg(value):
    s = f"{float(value or 0):.1f}".rstrip("0").rstrip(".")
    return f"{s or '0'}°"
