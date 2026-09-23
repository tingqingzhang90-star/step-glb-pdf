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
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

from drawing.dim.dim_geometry import (to_line_seg, to_circle, line_basis, offset_point,
                          signed_distance_to_line, closest_point_on_line,
                          project_point_to_line, line_intersection,
                          farthest_endpoint_from, build_arc_points,
                          build_linear_arrows, build_arrow_points,
                          extend_linear_line, arc_patch_range,
                          build_circle_patch_arc, estimate_text_width,
                          format_mm, format_deg)
from drawing.dim.dim_style import (dim_ext_overshoot_mm, dim_text_gap_mm, dim_label_gap_mm,
                                   dim_angle_text_gap_px, dim_angle_arc_ext_px,
                                   dim_text_font_mm, dim_diameter_text_gap_px)

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


def _texts_and_final(prims, text, custom_text, label=None):
    if custom_text:
        prims["text"] = custom_text
        for t in prims.get("texts", []):
            t["text"] = custom_text
    # 伴随文字标签(label):在每个数值文字左侧沿基线反方向固定偏移,
    # 与前端 core.js renderDimension 中 labelPos 计算保持一致。
    if label:
        texts = prims.setdefault("texts", [])
        # 注意:遍历快照,不能边遍历边向 texts.append,否则无限循环
        for vt in list(texts):
            vp = vt["pos"]
            va = vt["angle"]
            # 标签与数值共用同一基线 y(保证等高);仅 x 沿反方向偏移间距
            lx = vp[0] - math.cos(va) * LABEL_GAP
            ly = vp[1]
            texts.append({"pos": (lx, ly), "text": label,
                          "angle": va, "anchor": "end"})
    return prims


def _arrow_mode(ann):
    """读取前端标注数据中的箭头方向模式(outward/inward/auto)"""
    return ann.get("arrowMode") or ann.get("arrow_mode") or "auto"


def _line_extension(ann):
    """读取前端标注数据中的尺寸线单侧延长量(px);返回 (start, end) 元组,
    未设置时对应位置为 None 用全局默认。"""
    s = ann.get("extensionStartPx")
    e = ann.get("extensionEndPx")
    return (
        s if isinstance(s, (int, float)) else None,
        e if isinstance(e, (int, float)) else None,
    )


# 标注外观几何量取自前后端共用样式配置(cad_viewer_style.json)
EXT_OVERSHOOT = dim_ext_overshoot_mm()   # 尺寸界线越过尺寸线的长度(mm)
TEXT_GAP = dim_text_gap_mm()             # 文字与尺寸线的间距(mm)
LABEL_GAP = dim_label_gap_mm()           # 伴随文字与数值的间距(mm),=字号*label_gap_factor(配置)

# 中心夹角标注专用量(单位与前端 core.js 同名常量一致,均为图纸 px)
ANGLE_DEFAULT_RADIUS = 200               # 未指定时的默认弧半径
ANGLE_EXT_OVERSHOOT = 30                 # 尺寸界线越过弧的长度
# 直径标注(贯穿直线与折返引线)文字与标注线的间距,由 cad_viewer_style.json
# 的 dim.diameter.text_gap_px 配置(与前端 core.js DIAMETER_TEXT_GAP 共用同一份 json)
DIAMETER_TEXT_GAP = dim_diameter_text_gap_px()
# 文字间距与弧延伸长度改由 cad_viewer_style.json 的 dim.angle 配置:
#   text_gap_px 文字相对弧的内侧间距    arc_ext_px 弧越过箭头尾部的延伸长度
# 取值为图纸 px,与前端 core.js 同名常量共用同一份 json。

# 孔组中心标记:十字臂长 = 孔半径 × 该系数(与前端 core.js BOLT_MARK_SCALE 一致)
BOLT_MARK_SCALE = 1.6
BOLT_MIN_CIRCLES = 3


def _ext_line(p, e):
    """延伸线从被测点 p 画到尺寸线点 e,并越过尺寸线一小段"""
    dx, dy = e[0] - p[0], e[1] - p[1]
    ln = math.hypot(dx, dy)
    if ln < 1e-6:
        return (p, e)
    return (p, (e[0] + dx / ln * EXT_OVERSHOOT,
                e[1] + dy / ln * EXT_OVERSHOOT))


def _pdf_text_angle(unit):
    """linear 文字的 PDF 旋转角:跟随尺寸线方向,且不倒置

    视觉规范:水平线水平排,竖直线字头朝左(GB)。图纸坐标(y 向下)
    角度取反即 PDF(y 向上)角度。
    """
    a = math.atan2(unit[1], unit[0])
    if math.cos(a) < -1e-9:
        a += math.pi
    if math.isclose(abs(a), math.pi / 2, abs_tol=1e-9):
        a = -math.pi / 2
    return -a


def _linear_text(unit, mid, text, slide=0.0):
    """文字置于尺寸线上,沿线滑动 slide,再沿法向偏移 TEXT_GAP

    水平尺寸线文字在上方,竖直在左侧(GB,且避开旋转字身压线),
    斜线法向统一朝视觉上方,避免文字落到线下。
    """
    nx, ny = -unit[1], unit[0]
    if abs(unit[0]) < 1e-9:      # 竖直尺寸线:文字在左侧
        nx, ny = -1.0, 0.0
    elif ny > 0:                 # 其余:法向统一朝视觉上方(y 向下坐标)
        nx, ny = -nx, -ny
    return {"pos": (mid[0] + unit[0] * slide + nx * TEXT_GAP,
                    mid[1] + unit[1] * slide + ny * TEXT_GAP),
            "text": text, "angle": _pdf_text_angle(unit),
            "anchor": "middle"}


def build_dim_primitives(ann, segs, views):
    """按 core.js 对应 build*Geometry 在图纸坐标系重建标注几何

    Returns:
        dict: {lines, ext_lines, arrows, texts, arcs, center_marks, text}
        或 None(几何构建失败)
    """
    dtype = ann.get("type")
    custom = ann.get("customText") or None
    label = ann.get("label") or None

    if dtype == "linear":
        mode = ann.get("mode") or "single"
        # motor-envelope 重绑后返回左右端面两条边,走专用渲染
        builder = {"single": _linear_single, "parallel": _linear_parallel,
                   "center": _linear_center,
                   "circle-edge": _linear_circle_edge,
                   "motor-envelope": _linear_motor_envelope}.get(mode)
        if builder is None:
            return None
        prims = builder(ann, segs, views)
    elif dtype == "diameter":
        if ann.get("diameterMode") == "leader":
            prims = _diameter_leader(ann, segs[0], views[0])
        else:
            prims = _diameter(ann, segs[0], views[0])
    elif dtype == "angle":
        prims = (_angle_points(ann, segs, views)
                 if ann.get("angleMode") == "points" else _angle(ann, segs, views))
    elif dtype == "center-mark":
        prims = _center_mark(ann, segs, views)
    else:
        return None
    if prims is None:
        return None
    return _texts_and_final(prims, prims.get("text"), custom, label)


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
    slide = ann.get("textSlide") or 0.0
    e1 = offset_point(p1, basis["perp"], offset)
    e2 = offset_point(p2, basis["perp"], offset)
    unit = basis["unit"]
    mm_val = _line_mm_length(line)
    if mm_val is None:
        mm_val = basis["len"] / (view["scale"] * (view["k"] or 1.0))
    text = format_mm(mm_val)
    arrows = build_linear_arrows(e1, e2, unit, text, _arrow_mode(ann))
    dim_start, dim_end = extend_linear_line(e1, e2, arrows["outward"], unit, *_line_extension(ann))
    mid = ((e1[0] + e2[0]) / 2, (e1[1] + e2[1]) / 2)
    return {
        "lines": [_ext_line(p1, e1), _ext_line(p2, e2)],
        "dim_lines": [(dim_start, dim_end)],
        "arrows": [arrows["arrow1"], arrows["arrow2"]],
        "texts": [_linear_text(unit, mid, text, slide)],
        "center_marks": [], "text": text,
    }


def _linear_motor_envelope(ann, segs, views):
    """电机包络尺寸:用左右两条端面线,生成跨度的水平/竖直尺寸线,与前端
    buildMotorEnvelopeGeometry 一致(单条被测线无法表达整个包络跨度)。"""
    if len(segs) < 2 or len(views) < 2:
        return None
    line1 = to_line_seg(segs[0])
    line2 = to_line_seg(segs[1])
    if not line1 or not line2:
        return None
    # 两端面线在画布坐标上的端点
    p1a = _sheet_point(views[0], line1["x1"], line1["y1"])
    p1b = _sheet_point(views[0], line1["x2"], line1["y2"])
    p2a = _sheet_point(views[1], line2["x1"], line2["y1"])
    p2b = _sheet_point(views[1], line2["x2"], line2["y2"])

    # 端面线方向由 meta.orientation 提供(吸附后端面线退化为点,无法从 dx/dy 判断)
    # vertical   端面线 → horizontal 包络(尺寸线水平)
    # horizontal 端面线 → vertical   包络(尺寸线竖直)
    o1 = line1.get("meta", {}).get("orientation", "vertical")
    o2 = line2.get("meta", {}).get("orientation", "vertical")
    if o1 != o2:
        return None

    offset = ann.get("offset") or 50
    slide = ann.get("textSlide") or 0.0
    # 与前端 buildMotorEnvelopeGeometry 严格对齐:
    # - 取每条端面线"朝向尺寸线"的端点(同 pickEnvelopeEndpoint);
    # - 统一取 max y / max x(最下/最右端点),让尺寸线基线依附在包络下方/右方;
    # - normal 固定 (0,1)/(1,0),offset 带符号直接乘,正负自然决定上/下、左/右。
    # 之前按 offset 符号分别取 min/max y 会导致负 offset(尺寸线在上方)时
    # 基线被抬到最高端点,尺寸线紧贴图框甚至超出。
    if o1 == "vertical":  # 包络水平(端面线竖直)
        # 尺寸线水平,延伸线竖直
        unit = (1.0, 0.0)
        normal = (0.0, 1.0)
        if offset >= 0:
            ext1 = p1a if p1a[1] > p1b[1] else p1b  # 下端点
            ext2 = p2a if p2a[1] > p2b[1] else p2b
        else:
            ext1 = p1a if p1a[1] < p1b[1] else p1b  # 上端点
            ext2 = p2a if p2a[1] < p2b[1] else p2b
        # 统一为最下端点(max y),offset 为负时加上负值自然向上
        y = max(ext1[1], ext2[1])
        ext1 = (ext1[0], y)
        ext2 = (ext2[0], y)
    else:  # 包络竖直(端面线水平)
        unit = (0.0, 1.0)
        normal = (1.0, 0.0)
        if offset >= 0:
            ext1 = p1a if p1a[0] > p1b[0] else p1b  # 右端点
            ext2 = p2a if p2a[0] > p2b[0] else p2b
        else:
            ext1 = p1a if p1a[0] < p1b[0] else p1b  # 左端点
            ext2 = p2a if p2a[0] < p2b[0] else p2b
        # 统一为最右端点(max x),offset 为负时加上负值自然向左
        x = max(ext1[0], ext2[0])
        ext1 = (x, ext1[1])
        ext2 = (x, ext2[1])

    # span_mm 优先取模板中保存的
    mm_val = ann.get("spanMm")
    if mm_val is None:
        m1 = (line1.get("meta") or {}).get("mm_coords") or []
        m2 = (line2.get("meta") or {}).get("mm_coords") or []
        if m1 and m2:
            mm_val = math.hypot(m2[0] - m1[0], m2[1] - m1[1])
        else:
            return None
    text = format_mm(mm_val)

    dim_base = offset_point(ext1, normal, offset)
    dim_end = offset_point(ext2, normal, offset)

    arrows = build_linear_arrows(dim_base, dim_end, unit, text, _arrow_mode(ann))
    dim_start, dim_end = extend_linear_line(dim_base, dim_end, arrows["outward"], unit, *_line_extension(ann))
    mid = ((dim_base[0] + dim_end[0]) / 2.0, (dim_base[1] + dim_end[1]) / 2.0)
    return {
        "lines": [_ext_line(ext1, dim_base), _ext_line(ext2, dim_end)],
        "dim_lines": [(dim_start, dim_end)],
        "arrows": [arrows["arrow1"], arrows["arrow2"]],
        "texts": [_linear_text(unit, mid, text, slide)],
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
    slide = ann.get("textSlide") or 0.0
    dim_base = offset_point(start, basis["unit"], offset)
    dim_end = offset_point(dim_base, normal, distance)
    mm_val = _parallel_mm_distance(line1, line2)
    if mm_val is None:
        mm_val = distance / (v1["scale"] * (v1["k"] or 1.0))
    text = format_mm(mm_val)
    arrows = build_linear_arrows(dim_base, dim_end, normal, text, _arrow_mode(ann))
    dim_start, dim_end = extend_linear_line(dim_base, dim_end, arrows["outward"], normal, *_line_extension(ann))
    mid = ((dim_base[0] + dim_end[0]) / 2, (dim_base[1] + dim_end[1]) / 2)
    return {
        "lines": [_ext_line(start, dim_base), _ext_line(end, dim_end)],
        "dim_lines": [(dim_start, dim_end)],
        "arrows": [arrows["arrow1"], arrows["arrow2"]],
        "texts": [_linear_text(normal, mid, text, slide)],
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
    slide = ann.get("textSlide") or 0.0
    e1 = offset_point(c1, basis["perp"], offset)
    e2 = offset_point(c2, basis["perp"], offset)
    m1 = (to_circle(segs[0]).get("meta") or {}).get("center_mm")
    m2 = (to_circle(segs[1]).get("meta") or {}).get("center_mm")
    if m1 and m2:
        mm_val = math.hypot(m1[0] - m2[0], m1[1] - m2[1])
    else:
        mm_val = basis["len"] / (v1["scale"] * (v1["k"] or 1.0))
    text = format_mm(mm_val)
    arrows = build_linear_arrows(e1, e2, basis["unit"], text, _arrow_mode(ann))
    dim_start, dim_end = extend_linear_line(e1, e2, arrows["outward"], basis["unit"], *_line_extension(ann))
    mid = ((e1[0] + e2[0]) / 2, (e1[1] + e2[1]) / 2)
    return {
        "lines": [_ext_line(c1, e1), _ext_line(c2, e2)],
        "dim_lines": [(dim_start, dim_end)],
        "arrows": [arrows["arrow1"], arrows["arrow2"]],
        "texts": [_linear_text(basis["unit"], mid, text, slide)],
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
    slide = ann.get("textSlide") or 0.0
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
    arrows = build_linear_arrows(foot_c, foot_f, basis["perp"], text, _arrow_mode(ann))
    dim_start, dim_end = extend_linear_line(foot_c, foot_f, arrows["outward"], basis["perp"], *_line_extension(ann))
    mid = ((foot_c[0] + foot_f[0]) / 2, (foot_c[1] + foot_f[1]) / 2)
    return {
        "lines": [_ext_line(c, foot_c), _ext_line(f, foot_f)],
        "dim_lines": [(dim_start, dim_end)],
        "arrows": [arrows["arrow1"], arrows["arrow2"]],
        "texts": [_linear_text(basis["perp"], mid, text, slide)],
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
    radius = (circ.get("meta") or {}).get("radius")
    mm_val = radius * 2 if radius else circ["r"] * 2 / (view["k"] or 1.0)
    text = f"ø{format_mm(mm_val)}"
    text_angle = angle + math.pi if abs(angle) > math.pi / 2 else angle
    # 文字默认位于标注线尾部(线尾 = leader_end),与前端 buildDiameterGeometry 同式:
    #   可读方向朝圆外(d[0]>=0)时文字末端贴线尾,朝圆内时文字起点贴线尾;
    #   textSlide 为沿直径线的附加位移(正 = 朝线尾/外侧);
    #   文字与线的间距取 cad_viewer_style.json 的 dim.diameter.text_gap_px。
    # 文字宽度按 PDF 实测(pdfmetrics.stringWidth),与折线模式同一套测量
    font_mm = dim_text_font_mm()
    pt2u = 25.4 / 72.0          # 1pt = 0.3528 图纸单位(坐标 1 单位 = 1mm)
    try:
        _ensure_font()
        text_w = stringWidth(text, _CN_FONT, font_mm) * pt2u
    except Exception:           # 字体未注册等异常时退回估宽
        text_w = estimate_text_width(text)
    slide = ann.get("textSlide") or 0.0
    along = (text_w if d[0] >= 0 else 0.0) - slide
    text_pos = (leader_end[0] - d[0] * along + perp[0] * DIAMETER_TEXT_GAP,
                leader_end[1] - d[1] * along + perp[1] * DIAMETER_TEXT_GAP)
    # 引用圆为部分弧且箭头接触角处缺失时,从弧断点无缝补一段圆弧(与前端一致)
    patch = arc_patch_range(seg, circ, angle)
    arcs = [build_circle_patch_arc(cx, cy, r, patch)] if patch else []
    return {
        "lines": [], "dim_lines": [(leader_start, leader_end)],
        "arcs": arcs,
        "arrows": [build_arrow_points(edge_pt, d, False)],
        "texts": [{"pos": text_pos, "text": text,
                   "angle": text_angle, "anchor": "start"}],
        "center_marks": [], "text": text,
    }


def _diameter_leader(ann, seg, view):
    """引线直径标注:水平文字线 + 折线引线 + 箭头指向圆周"""
    circ = to_circle(seg)
    if not circ or not view:
        return None
    cx = view["x"] + circ["cx"] * view["scale"]
    cy = view["y"] + circ["cy"] * view["scale"]
    r = circ["r"] * view["scale"]

    # 文字左端位置(前端保存的 textPos)
    text_left = ann.get("textLeft") or {"x": 0, "y": 0}
    text_x = text_left.get("x", 0)
    text_y = text_left.get("y", 0)

    # 引线角度
    angle = ann.get("leaderAngle")
    if angle is None:
        angle = -math.pi / 4
    d = (math.cos(angle), math.sin(angle))

    # 直径值与文字:支持自定义全文(如 "12x ø13.5 贯穿"),
    # 水平搁置线(下划线)长度按全文估算,与前端 buildDiameterLeaderGeometry 同式
    radius = (circ.get("meta") or {}).get("radius")
    mm_val = radius * 2 if radius else circ["r"] * 2 / (view["k"] or 1.0)
    text = ann.get("customText") or f"ø{format_mm(mm_val)}"

    # 水平文字线:长度按 PDF 实测文字宽度(pdfmetrics.stringWidth)计算。
    # 图纸坐标 1:1 当 mm 用,而 PDF 字号 = font_px×PX2MM(pt),实际字高只有
    # ~1.7 图纸单位;前端估宽(len×7)按 18 单位字号校准,直接当 mm 会让
    # 下划线比实际文字宽 3~4 倍、间距也大近一倍(文字悬空、线甩出老远)。
    # 间距/余量/肩部按字号等比(与前端 4/8/10 ÷ 字号18 同比例),两端视觉一致。
    font_mm = dim_text_font_mm()
    pt2u = 25.4 / 72.0          # 1pt = 0.3528 图纸单位(坐标 1 单位 = 1mm)
    em = font_mm * pt2u         # 字号换算到图纸单位
    try:
        _ensure_font()
        text_w = stringWidth(text, _CN_FONT, font_mm) * pt2u
    except Exception:           # 字体未注册等异常时退回估宽
        text_w = estimate_text_width(text)
    # 文字与水平搁置线的间距由 cad_viewer_style.json 的 dim.diameter.text_gap_px 配置
    # (与前端 core.js LEADER_TEXT_GAP 共用同一份 json)
    text_gap = DIAMETER_TEXT_GAP
    text_line_start = (text_x, text_y + text_gap)
    text_w += em * (4.0 / 18.0)   # 小余量,搁置线略长于文字(同前端)
    text_line_end = (text_x + text_w, text_y + text_gap)

    # 折点 = 水平线右端
    bend_pt = text_line_end

    # 折点到圆的射线交点
    dx = bend_pt[0] - cx
    dy = bend_pt[1] - cy
    a = d[0] ** 2 + d[1] ** 2  # = 1
    b = 2 * (dx * d[0] + dy * d[1])
    c = dx ** 2 + dy ** 2 - r ** 2
    disc = b ** 2 - 4 * a * c
    if disc < 0:
        return None
    sqrt_disc = math.sqrt(disc)
    t1 = (-b - sqrt_disc) / (2 * a)
    t2 = (-b + sqrt_disc) / (2 * a)
    t = t1 if t1 > 0 else (t2 if t2 > 0 else 1)
    if t < 1:
        t = 1
    edge_pt = (bend_pt[0] + d[0] * t, bend_pt[1] + d[1] * t)
    # 箭头接触角处部分弧缺失时从弧断点补一段圆弧(与前端一致)
    contact = math.atan2(edge_pt[1] - cy, edge_pt[0] - cx)
    patch = arc_patch_range(seg, circ, contact)
    arcs = [build_circle_patch_arc(cx, cy, r, patch)] if patch else []

    return {
        "lines": [],
        "dim_lines": [
            (text_line_start, text_line_end),   # 水平文字线
            (bend_pt, (cx + d[0] * r, cy + d[1] * r)),  # 折线引线(贯穿整条直径到对侧圆周)
        ],
        "arcs": arcs,
        # 箭头:尖端触圆周、沿引线方向(d=折点→圆心)指向圆内,箭身在引线外侧,
        # 与前端 buildArrowPoints(edgePt, dir, true) 一致
        "arrows": [build_arrow_points(edge_pt, d, True)],
        "texts": [{"pos": (text_x, text_y), "text": text,
                   "angle": 0, "anchor": "start"}],
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


def _dim_point(seg, view, point_kind):
    """点引用解析(与 core.js resolveDimPoint 一致):圆取圆心,直线按 pointKind 取端点"""
    if not seg or not view:
        return None
    circ = to_circle(seg)
    if circ:
        return _sheet_point(view, circ["cx"], circ["cy"])
    line = to_line_seg(seg)
    if not line:
        return None
    a = _sheet_point(view, line["x1"], line["y1"])
    b = _sheet_point(view, line["x2"], line["y2"])
    return b if point_kind == "end" else a


def _angle_ext_line(vertex, unit, point_dist, radius, overshoot):
    """角度尺寸界线:被测点 → 弧并越过 overshoot;弧更靠近顶点时从弧起画"""
    near = min(point_dist, radius)
    far = max(point_dist, radius) + overshoot
    return ((vertex[0] + unit[0] * near, vertex[1] + unit[1] * near),
            (vertex[0] + unit[0] * far, vertex[1] + unit[1] * far))


def _angle_points(ann, segs, views):
    """中心夹角标注:顶点(法兰中心) + 两个被测点(孔心/端点)

    与 core.js buildAnglePointsGeometry 同公式,顺序:取小于 180° 的一侧画弧,
    尺寸界线沿径向延伸到弧并越过 overshoot(随半径按比例钳制),
    箭头放弧两端,弧两端再延伸一小段越过箭头尾部,文字贴近弧(小半径放外侧)。
    """
    if len(segs) < 3 or len(views) < 3:
        return None
    refs = ann.get("refs") or []

    def kind(i):
        return refs[i].get("pointKind") if i < len(refs) else None

    vertex = _dim_point(segs[0], views[0], kind(0))
    p1 = _dim_point(segs[1], views[1], kind(1))
    p2 = _dim_point(segs[2], views[2], kind(2))
    if not vertex or not p1 or not p2:
        return None
    d1 = (p1[0] - vertex[0], p1[1] - vertex[1])
    d2 = (p2[0] - vertex[0], p2[1] - vertex[1])
    l1 = math.hypot(d1[0], d1[1])
    l2 = math.hypot(d2[0], d2[1])
    if l1 < 1e-6 or l2 < 1e-6:
        return None
    u1 = (d1[0] / l1, d1[1] / l1)
    u2 = (d2[0] / l2, d2[1] / l2)
    start = math.atan2(u1[1], u1[0])
    end = math.atan2(u2[1], u2[0])
    while end < start:
        end += math.pi * 2
    if end - start > math.pi:
        start, end = end, start + math.pi * 2
    sweep = end - start
    radius = max(float(ann.get("radius") or ANGLE_DEFAULT_RADIUS), 12.0)
    overshoot = ann.get("extOvershoot")
    if not isinstance(overshoot, (int, float)):
        overshoot = ANGLE_EXT_OVERSHOOT
    # 尺寸界线越过弧的长度随弧半径按比例收缩: 固定 30px 在小半径下会比弧本身
    # 还长(延伸线甩出老远); 既有标注存的大 overshoot 在此同样被钳制
    overshoot = max(4.0, min(float(overshoot), radius * 0.15))
    # 箭头放在弧两端(与尺寸界线交点), 弧两端各接一段直线延长线:
    # 延长线沿切线(即箭头轴线)走直线, 从箭头尾部底中心穿出; 长度由
    # dim.angle.arc_ext_px 配置(默认 20px)。不能继续沿圆弧延伸: 圆弧与
    # 箭头轴线在尾部附近因曲率不共线, 放大看会像从尾部底一角冒出来。
    tail_len = dim_angle_arc_ext_px()
    ap1 = (vertex[0] + math.cos(start) * radius, vertex[1] + math.sin(start) * radius)
    ap2 = (vertex[0] + math.cos(end) * radius, vertex[1] + math.sin(end) * radius)
    tan1 = (-math.sin(start), math.cos(start))
    tan2 = (-math.sin(end), math.cos(end))
    tail1 = (ap1[0] - tan1[0] * tail_len, ap1[1] - tan1[1] * tail_len)
    tail2 = (ap2[0] + tan2[0] * tail_len, ap2[1] + tan2[1] * tail_len)
    mid = start + sweep / 2
    # 文字贴近弧: 半径足够时放弧内侧, 太小时放弧外侧(间距由 dim.angle.text_gap_px 配置)
    text_gap = dim_angle_text_gap_px()
    text_dist = radius - text_gap if radius - text_gap >= 14 else radius + 10
    text = format_deg(sweep * 180 / math.pi)
    return {
        "lines": [_angle_ext_line(vertex, u1, l1, radius, overshoot),
                  _angle_ext_line(vertex, u2, l2, radius, overshoot)],
        "dim_lines": [],
        "arcs": [[tail1] + build_arc_points(vertex[0], vertex[1], radius, start, end)
                 + [tail2]],
        "arrows": [build_arrow_points(ap1, tan1, True),
                   build_arrow_points(ap2, (-tan2[0], -tan2[1]), True)],
        "texts": [{"pos": (vertex[0] + math.cos(mid) * text_dist,
                           vertex[1] + math.sin(mid) * text_dist),
                   "text": text, "angle": 0.0, "anchor": "middle"}],
        "center_marks": [], "text": text,
    }


def _center_mark(ann, segs, views):
    """单孔中心标记(水平/竖直十字);孔组与孔组圆心走 _center_mark_group"""
    if ann.get("groupCenter"):
        return _center_mark_group(segs, views, only_center=True)
    if ann.get("group"):
        return _center_mark_group(segs, views)
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


def _center_mark_group(segs, views, only_center=False):
    """孔组中心标记:分度圆(虚线圆) + 各孔沿径向/切向的十字

    分度圆圆心取各孔心均值、半径取平均距离,与前端 buildCenterMarkGroupGeometry
    同公式;每个孔的十字一条线沿"中心→孔心"方向、另一条是其垂线,
    故 center_marks 的 angle 就是该孔的方位角。
    only_center=True 时只画分度圆圆心处一个水平/竖直十字(把分度圆当"一个孔")。
    """
    if len(segs) < BOLT_MIN_CIRCLES:
        return None
    points = []
    for seg, view in zip(segs, views):
        p = _dim_point(seg, view, "center")
        if p is None or not to_circle(seg):
            return None
        points.append(p)
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    radius = sum(math.hypot(p[0] - cx, p[1] - cy) for p in points) / len(points)
    if only_center:
        return {"lines": [], "dim_lines": [], "arrows": [], "arcs": [],
                "center_marks": [{"pos": (cx, cy), "r": radius, "angle": None}],
                "texts": [], "text": ""}
    marks = []
    for seg, view, p in zip(segs, views, points):
        circ = to_circle(seg)
        half = circ["r"] * (view.get("scale") or 1.0) * BOLT_MARK_SCALE
        marks.append({"pos": p, "r": half,
                      "angle": math.atan2(p[1] - cy, p[0] - cx)})
    return {"lines": [], "dim_lines": [], "arrows": [], "arcs": [],
            "dashed_circles": [{"x": cx, "y": cy, "r": radius}] if radius > 1.0 else [],
            "center_marks": marks, "texts": [], "text": ""}
