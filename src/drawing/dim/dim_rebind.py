# -*- coding: utf-8 -*-
"""几何指纹重绑引擎 — 基准型号边线 → 目标型号边线

同系列型号差异 = 缸体沿主轴(Z)拉伸 + 电机零件替换。重绑分三类:
  1. 普通标注: 基准边线经轴向位移补偿后,按几何指纹在目标视图匹配;
  2. bind_motor 标注: 跳过边线匹配,两端直接绑电机包络锚点(换电机自动跟随);
  3. 匹配失败: 计入失配报告,不渲染,不做静默错位。

位移补偿规则(实测验证,见 docs/同系列模板复用规则.md):
  z <  缸体安装位      → 不动(电机侧/后端零件)
  缸体安装位 ≤ z ≤ 基准前端 → z' = 安装位 + (z - 安装位) × scale(缸体自身)
  z >  基准前端        → z' = z + ΔD1(前端配合零件整体平移)
"""
import math

from drawing.view_axes import axial_projection

POS_TOL = 5.0   # 位置匹配容差 mm
LEN_TOL = 2.5   # 长度/半径匹配容差 mm
DIR_COS_TOL = 0.97  # 匹配前后引用点相对方向的最小夹角余弦(约 14°)


def _by_id(profile):
    return {a["id"]: a for a in profile["anchors"]}


def compensation_ctx(base_profile, target_profile):
    """从基准/目标锚点构造位移补偿参数"""
    b = _by_id(base_profile)
    t = _by_id(target_profile)
    back = b["cylinder.back_end"]["point3d"][2]
    front = b["cylinder.front_end"]["point3d"][2]
    d1_base = front - back
    d1_target = (t["cylinder.front_end"]["point3d"][2]
                 - t["cylinder.back_end"]["point3d"][2])
    scale = d1_target / d1_base if d1_base > 1e-9 else 1.0
    return {"back": back, "front": front, "scale": scale,
            "delta": d1_target - d1_base}


def _shift(v, sign, ctx):
    """单个轴向坐标的位移补偿"""
    z = sign * v
    if z <= ctx["back"]:
        return v
    if z <= ctx["front"]:
        zt = ctx["back"] + (z - ctx["back"]) * ctx["scale"]
    else:
        zt = z + ctx["delta"]
    return sign * zt


def _compensate_pair(x, y, axis, sign, ctx):
    """对 mm 坐标点做轴向补偿(x/y 两个分量中只有轴向分量移动)"""
    if axis is None:
        return [x, y]
    if axis == "x":
        return [_shift(x, sign, ctx), y]
    return [x, _shift(y, sign, ctx)]


def _expected_mm(seg, axis, sign, ctx):
    """基准边线在目标型号下的期望 mm 坐标(按类型取值)"""
    meta = seg.get("meta") or {}
    st = seg.get("type")
    if st == "line":
        m = meta.get("mm_coords")
        if not m or len(m) < 4:
            return None
        p1 = _compensate_pair(m[0], m[1], axis, sign, ctx)
        p2 = _compensate_pair(m[2], m[3], axis, sign, ctx)
        return {"kind": "line", "p1": p1, "p2": p2,
                "length": meta.get("length"),
                "orientation": meta.get("orientation")}
    if st == "circle":
        c = meta.get("center_mm")
        if not c:
            return None
        cc = _compensate_pair(c[0], c[1], axis, sign, ctx)
        return {"kind": "circle", "center": cc, "radius": meta.get("radius")}
    if st == "polyline":
        if meta.get("curve") == "circle" and meta.get("center_mm"):
            c = meta["center_mm"]
            cc = _compensate_pair(c[0], c[1], axis, sign, ctx)
            return {"kind": "circle", "center": cc, "radius": meta.get("radius")}
        m = meta.get("mm_coords")
        if not m or len(m) < 4:
            return None
        p1 = _compensate_pair(m[0], m[1], axis, sign, ctx)
        p2 = _compensate_pair(m[2], m[3], axis, sign, ctx)
        return {"kind": "polyline", "p1": p1, "p2": p2,
                "length": meta.get("length")}
    return None


def _target_key(seg):
    """目标边线的指纹取值(与 _expected_mm 同构)"""
    meta = seg.get("meta") or {}
    st = seg.get("type")
    if st == "line":
        m = meta.get("mm_coords")
        if not m or len(m) < 4:
            return None
        return {"kind": "line", "p1": [m[0], m[1]], "p2": [m[2], m[3]],
                "length": meta.get("length"),
                "orientation": meta.get("orientation")}
    if st == "circle":
        c = meta.get("center_mm")
        if not c:
            return None
        return {"kind": "circle", "center": [c[0], c[1]],
                "radius": meta.get("radius")}
    if st == "polyline":
        if meta.get("curve") == "circle" and meta.get("center_mm"):
            c = meta["center_mm"]
            return {"kind": "circle", "center": [c[0], c[1]],
                    "radius": meta.get("radius")}
        m = meta.get("mm_coords")
        if not m or len(m) < 4:
            return None
        return {"kind": "polyline", "p1": [m[0], m[1]], "p2": [m[2], m[3]],
                "length": meta.get("length")}
    return None


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _direction_close(a, b, tol=DIR_COS_TOL):
    """两向量方向是否一致(端点顺序可相反;退化向量不判)"""
    na = math.hypot(a[0], a[1])
    nb = math.hypot(b[0], b[1])
    if na < 1e-6 or nb < 1e-6:
        return True
    return abs(a[0] * b[0] + a[1] * b[1]) / (na * nb) >= tol


def _ref_point(seg):
    """标注引用边的代表点:圆心或线段中点"""
    key = _target_key(seg)
    if not key:
        return None
    if "center" in key:
        return key["center"]
    return [(key["p1"][0] + key["p2"][0]) / 2,
            (key["p1"][1] + key["p2"][1]) / 2]


def _kind_compatible(k1, k2):
    """line 与 polyline(非圆弧)同为"线段类"指纹，允许互匹配。

    模板按 algo(精确 HLR)输出记录基准边线：直边记为 line、样条/离散边记为
    polyline；poly 离散链路可能把同一条边表示成另一种(长直边被三角化切成
    若干弦后合并为 line，或反之)。二者指纹结构一致(p1/p2/length)，按 kind
    严格相等会失配，故归为同一类。
    """
    if k1 in ("line", "polyline") and k2 in ("line", "polyline"):
        return True
    return k1 == k2


def match_edge(base_seg, view_name, ctx, target_segs):
    """在目标边线列表中寻找基准边线的对应边

    Returns:
        (target_seg, score, target_idx) 匹配成功; (None, 失配原因, None) 失败
    """
    try:
        axis_sign = axial_projection(view_name)
    except ValueError as e:
        return None, str(e), None
    axis, sign = axis_sign if axis_sign else (None, 1.0)
    exp = _expected_mm(base_seg, axis, sign, ctx)
    if exp is None:
        return None, "基准边线缺少 mm 元数据", None

    best, best_score, best_idx = None, None, None
    for i, seg in enumerate(target_segs):
        key = _target_key(seg)
        if key is None or not _kind_compatible(key["kind"], exp["kind"]):
            continue
        if exp["kind"] in ("line", "polyline") or key["kind"] in ("line", "polyline"):
            # 线段/折线:中点位置匹配 + 长度作 score 软约束
            # 缸体沿轴向拉伸时,同名位置线段长度会变(L100→L200 多 100mm),
            # 不能用 LEN_TOL 硬卡;改用 LEN_TOL*10 软罚分,仅 POS_TOL 硬过滤
            mid_e = ((exp["p1"][0] + exp["p2"][0]) / 2,
                     (exp["p1"][1] + exp["p2"][1]) / 2)
            mid_t = ((key["p1"][0] + key["p2"][0]) / 2,
                     (key["p1"][1] + key["p2"][1]) / 2)
            pos = _dist(mid_e, mid_t)
            if pos > POS_TOL:
                continue
            # 中点相近但方向不同的边不可能是同一条边:缸体只沿主轴拉伸,
            # 不会把水平边变成斜边。缺 orientation 的 poly 边保持兼容。
            if (exp.get("orientation") and key.get("orientation")
                    and exp["orientation"] != key["orientation"]):
                continue
            dv_e = (exp["p2"][0] - exp["p1"][0], exp["p2"][1] - exp["p1"][1])
            dv_t = (key["p2"][0] - key["p1"][0], key["p2"][1] - key["p1"][1])
            if not _direction_close(dv_e, dv_t):
                continue
            len_e = exp.get("length") or math.hypot(
                exp["p2"][0] - exp["p1"][0], exp["p2"][1] - exp["p1"][1])
            len_t = key.get("length") or math.hypot(
                key["p2"][0] - key["p1"][0], key["p2"][1] - key["p1"][1])
            dl = abs(len_e - len_t)
            score = pos + 0.01 * dl  # 长度差仅作 tie-breaker
        else:  # circle(含 polyline 圆弧)
            if "center" not in exp or "center" not in key:
                continue
            pos = _dist(exp["center"], key["center"])
            if pos > POS_TOL:
                continue
            if exp.get("radius") is None or key.get("radius") is None:
                continue
            dr = abs(exp["radius"] - key["radius"])
            if dr > LEN_TOL:
                continue
            score = pos + dr
        if best_score is None or score < best_score:
            best, best_score, best_idx = seg, score, i
    if best is None:
        return None, "目标视图中无几何指纹相符的边线", None
    return best, best_score, best_idx


def _motor_face_lines(target_profile, view_name):
    """电机包络两端面的投影线(mm),供 bind_motor 标注合成边线

    Returns:
        (face_min, face_max, size, span_mm): 两端面线段(各为 (p1, p2))与外露跨度,
        无电机或该视图轴向退化时返回四个 None
    """
    from drawing.dim.dim_envelope import envelope_faces

    faces = envelope_faces(target_profile["anchors"], view_name)
    if not faces:
        return None, None, None, None
    motor = _by_id(target_profile).get("motor.body")
    return faces["face_min"], faces["face_max"], motor["size"], faces["span_mm"]


def _mm_to_canvas_fn(view_segs, k):
    """从视图任一带 mm 元数据的 line 边线反推 mm→画布 px 仿射变换

    仅作兜底:优先用 `_canvas_fn_from_bbox`。反推值受该边线 mm 元数据
    取整影响,与前端使用的 bbox 参数有 ~0.02px 级偏差;而调色板边线里存在
    大量 0.1px 级退化碎片,这点偏差就足以让"最近边"吸到另一条碎片,导致
    尺寸线基线漂移。
    """
    if not k:
        return None
    for seg in view_segs:
        if seg.get("type") != "line":
            continue
        m = (seg.get("meta") or {}).get("mm_coords")
        if m and len(m) >= 4:
            off_x = seg["x1"] - m[0] * k
            off_y = seg["y1"] - m[1] * k
            return lambda p: (p[0] * k + off_x, p[1] * k + off_y)
    return None


def _canvas_fn_from_bbox(bbox):
    """与前端 faceToSheet 完全一致的 mm→画布 px 变换(直接用调色板 bbox 参数)

    前端: 图纸坐标 = getSheetPoint(view, mm*bbox.scale + bbox.offset_*)。
    必须与前端同源,否则包络端面会偏零点几像素,吸到另一条碎片。
    """
    if not bbox:
        return None
    k = bbox.get("scale")
    if not k:
        return None
    ox = bbox.get("offset_x") or 0.0
    oy = bbox.get("offset_y") or 0.0
    return lambda p: (p[0] * k + ox, p[1] * k + oy)


def _synthetic_seg(p1_mm, p2_mm, to_canvas):
    """由 mm 端点合成 line 边线(带 canvas 坐标与 meta)"""
    c1 = to_canvas(p1_mm)
    c2 = to_canvas(p2_mm)
    if c1 is None or c2 is None:
        return None
    dx, dy = p2_mm[0] - p1_mm[0], p2_mm[1] - p1_mm[1]
    orientation = "vertical" if abs(dx) < abs(dy) * 0.01 else (
        "horizontal" if abs(dy) < abs(dx) * 0.01 else "angled")
    return {
        "type": "line",
        "x1": c1[0], "y1": c1[1], "x2": c2[0], "y2": c2[1],
        "meta": {"mm_coords": [p1_mm[0], p1_mm[1], p2_mm[0], p2_mm[1]],
                 "length": round(math.hypot(dx, dy), 4),
                 "orientation": orientation},
    }


def _snap_seg_to_view(seg, view_segs, orientation, offset, view_scale=1.0):
    """把合成的端面线吸附到视图中最接近的真实边线端点

    电机包络端点来自 bbox 8 角点投影,端面线 y/x 跨度=轮廓全范围,
    远超电机在视图中的真实边线,导致尺寸线悬空。
    这里在视图边线中找同方向、位置最接近的边线,把端面线端点替换为
    该真实边线的端点(与前端 snapEndpointToViewEdge 行为一致)。

    前端在**图纸坐标**里度量:候选边 sheet x = x1*scale + view.x,
    阈值 30 图纸 px。本函数工作在画布 px,故阈值/线宽判据都要除以
    view_scale 换算,否则视图缩放 ≠ 1 时吸到的是另一条边(尺寸线漂移)。

    连接端面附近既有贯穿多个视图的长轮廓边,也有落在下方视图的碎片边,
    吸附到它们的远端会把尺寸界线拉到视图下方。故候选边长度、以及吸附
    端点相对包络轮廓端点的偏移,都不得超过端面线本身(取 1.5 倍余量)。
    """
    if not view_segs:
        return seg
    s = max(float(view_scale or 1.0), 1e-6)
    SNAP = 30.0 / s          # 30 图纸 px → 画布 px
    FLAT = 2.0 / s           # 前端"近似竖直/水平"判据同样在图纸坐标
    best = None
    best_dist = float('inf')
    if orientation == "horizontal":
        limit = abs(seg["y2"] - seg["y1"]) * 1.5
        pt_y = max(seg["y1"], seg["y2"]) if offset >= 0 else min(seg["y1"], seg["y2"])
        # 端面线竖直,找同 x 附近的竖直边线
        # 距离/落点都用候选边线的首个端点(与前端 Math.abs(x1 - pt.x) 一致):
        # 调色板里有大量 0.1px 级退化碎片,用中点度量会吸到另一条碎片
        for e in view_segs:
            if e.get("type") != "line":
                continue
            if abs(e["x1"] - e["x2"]) > FLAT:
                continue
            if abs(e["y2"] - e["y1"]) > limit:
                continue
            target_y = max(e["y1"], e["y2"]) if offset >= 0 else min(e["y1"], e["y2"])
            if abs(target_y - pt_y) > limit:
                continue
            dist = abs(e["x1"] - seg["x1"])
            if dist < best_dist and dist < SNAP:
                best_dist = dist
                best = e
        if best is None:
            return seg
        # 取真实边线的上端或下端(按 offset 方向)
        if offset >= 0:
            y = max(best["y1"], best["y2"])
        else:
            y = min(best["y1"], best["y2"])
        seg_snap = dict(seg)
        seg_snap["x1"] = seg_snap["x2"] = best["x1"]
        seg_snap["y1"] = seg_snap["y2"] = y
        return seg_snap
    else:
        limit = abs(seg["x2"] - seg["x1"]) * 1.5
        pt_x = max(seg["x1"], seg["x2"]) if offset >= 0 else min(seg["x1"], seg["x2"])
        # 端面线水平,找同 y 附近的水平边线
        for e in view_segs:
            if e.get("type") != "line":
                continue
            if abs(e["y1"] - e["y2"]) > FLAT:
                continue
            if abs(e["x2"] - e["x1"]) > limit:
                continue
            target_x = max(e["x1"], e["x2"]) if offset >= 0 else min(e["x1"], e["x2"])
            if abs(target_x - pt_x) > limit:
                continue
            dist = abs(e["y1"] - seg["y1"])
            if dist < best_dist and dist < SNAP:
                best_dist = dist
                best = e
        if best is None:
            return seg
        if offset >= 0:
            x = max(best["x1"], best["x2"])
        else:
            x = min(best["x1"], best["x2"])
        seg_snap = dict(seg)
        seg_snap["x1"] = seg_snap["x2"] = x
        seg_snap["y1"] = seg_snap["y2"] = best["y1"]
        return seg_snap


def _seg_endpoints(seg):
    """边线首/末端点(line 用 x1y1/x2y2,polyline 用首尾采样点)"""
    if seg.get("type") == "line":
        return (seg["x1"], seg["y1"]), (seg["x2"], seg["y2"])
    if seg.get("type") == "polyline":
        pts = seg.get("points") or []
        if len(pts) >= 2:
            return pts[0], pts[-1]
    return None, None


def _reversed_seg(seg):
    """端点首尾互换的浅拷贝(line 连 meta.mm_coords 一起换)"""
    out = dict(seg)
    if seg.get("type") == "line":
        out["x1"], out["y1"], out["x2"], out["y2"] = \
            seg["x2"], seg["y2"], seg["x1"], seg["y1"]
        meta = dict(out.get("meta") or {})
        mm = meta.get("mm_coords")
        if mm and len(mm) >= 4:
            meta["mm_coords"] = [mm[2], mm[3], mm[0], mm[1]]
        out["meta"] = meta
    elif seg.get("type") == "polyline":
        out["points"] = list(reversed(seg.get("points") or []))
    return out


def _align_seg_direction(base_seg, target_seg):
    """把匹配到的目标边线端点顺序对齐基准边线方向

    线性标注的 offset/textSlide 语义沿"被测边自身"定义:
    single 的 offset 沿边法向(dim_geometry.line_basis 的 perp 由端点
    顺序决定), parallel/circle-edge 的 offset 沿边方向滑动。
    HLR 输出边线的端点顺序是任意的,同一条边在目标型号图纸里可能首尾
    颠倒:直接用会让 perp/unit 翻转,尺寸线从零件一侧跳到另一侧
    (编辑器里在零件上方,导出图跑到零件内部)。
    这里以基准边线方向为准,必要时翻转目标边线端点。两边是同一标准视图,
    画布坐标取向一致,方向向量可直接比较。
    """
    if target_seg.get("type") not in ("line", "polyline"):
        return target_seg
    b1, b2 = _seg_endpoints(base_seg)
    t1, t2 = _seg_endpoints(target_seg)
    if not b1 or not t1:
        return target_seg
    if (b2[0] - b1[0]) * (t2[0] - t1[0]) + \
       (b2[1] - b1[1]) * (t2[1] - t1[1]) < 0:
        return _reversed_seg(target_seg)
    return target_seg


def rebind_annotation(ann, base_refs, ctx, target_profile,
                      view_placements, match_cache, group_refs=None):
    """重绑单条标注

    Args:
        ann: 模板标注 dict
        base_refs: frontend_template.resolve_base_refs 的一项 refs
        ctx: compensation_ctx 输出
        target_profile: 目标型号锚点
        view_placements: view_id → 目标视图放置 {x, y, scale, source_view, segs}
        match_cache: (source_view, list_type, idx) → 匹配结果缓存

    Returns:
        {"status": "matched"|"motor"|"unmatched", "reason", "segs", "views"}
        matched 时附带 "ref_map"(重映射后的 refs,下标换成目标型号边线)与
        "ref_map_target"(写回 refs 还是 groupRefs),供源文件落盘使用
    """
    # bind_motor 线性标注:两端绑电机包络面(换电机型号自动跟随)
    if ann.get("bind_motor"):
        if ann.get("type") != "linear" or ann.get("mode") not in (None, "single", "parallel", "motor-envelope"):
            return {"status": "unmatched",
                    "reason": "bind_motor 仅支持线性标注(单边/平行间距/电机包络)",
                    "segs": [], "views": []}
        view_id = ann["refs"][0]["viewId"] if ann.get("refs") else None
        placement = view_placements.get(view_id)
        if not placement:
            return {"status": "unmatched", "reason": "视图不存在",
                    "segs": [], "views": []}
        faces = _motor_face_lines(target_profile, placement["source_view"])
        if not faces or faces[0] is None:
            return {"status": "unmatched",
                    "reason": f"视图 {placement['source_view']} 下电机轴向与投影方向垂直,"
                              "两端面重合,无法标注包络尺寸",
                    "segs": [], "views": []}
        fmin, fmax, _size, span_mm = faces
        # 与前端 faceToSheet 同源: 优先用调色板 bbox 参数(mm→画布 px),
        # 缺失时才退回从边线 mm 元数据反推
        to_canvas = (_canvas_fn_from_bbox(placement.get("bbox"))
                     or _mm_to_canvas_fn(placement["segs"], placement["k"]))
        if to_canvas is None:
            return {"status": "unmatched", "reason": "视图缺少 mm 元数据,无法换算",
                    "segs": [], "views": []}
        seg_min = _synthetic_seg(fmin[0], fmin[1], to_canvas)
        seg_max = _synthetic_seg(fmax[0], fmax[1], to_canvas)
        if not seg_min or not seg_max:
            return {"status": "unmatched", "reason": "电机包络线合成失败",
                    "segs": [], "views": []}
        # 吸附会把端面线退化成点;渲染端仍需减速机轮廓原始范围定位界线终点
        for seg in (seg_min, seg_max):
            axis = "y" if seg["meta"]["orientation"] == "vertical" else "x"
            seg["meta"]["face_extent"] = sorted((seg[axis + "1"], seg[axis + "2"]))
        # 电机包络端面线 y/x 范围来自 bbox 8 角点投影,会远超电机实际边线,
        # 需吸附到视图真实边线端点,让延伸线起点落在视图电机实际边缘。
        # 候选集与前端 snapEndpointToViewEdge 一致:可见边 + 隐藏边。
        segs_view = (placement.get("segs") or []) + (placement.get("hidden") or [])
        if ann.get("mode") != "single" and segs_view:
            # 端面线方向:vertical 端面线对应 horizontal 包络,horizontal 端面线对应 vertical 包络
            dim_orientation = "horizontal" if seg_min.get("meta", {}).get("orientation") == "vertical" else "vertical"
            # offset 前后端取值规则统一(前端存 null 时后端不能用 None 比较符号)
            snap_offset = ann.get("offset") or 50
            view_scale = float(placement.get("scale") or 1.0)
            seg_min = _snap_seg_to_view(seg_min, segs_view, dim_orientation,
                                        snap_offset, view_scale)
            seg_max = _snap_seg_to_view(seg_max, segs_view, dim_orientation,
                                        snap_offset, view_scale)
        if ann.get("mode") == "single":
            return {"status": "motor", "reason": "",
                    "segs": [seg_max], "views": [placement]}
        result = {"status": "motor", "reason": "",
                  "segs": [seg_min, seg_max], "views": [placement, placement]}
        # 模板里的 spanMm 是放置时的旧包络长度,换型号/裁切后必须由目标包络重算
        if ann.get("mode") == "motor-envelope":
            result["span_mm"] = span_mm
        return result

    # 孔组引用(分度圆直径标注):按各孔边线匹配,渲染端再合成 Bolt 圆
    ref_entries = group_refs if ann.get("groupRefs") and group_refs else base_refs
    if not ref_entries:
        return {"status": "unmatched", "reason": "标注无引用边线(refs 为空)",
                "segs": [], "views": []}
    segs, views, ref_map = [], [], []
    for entry in ref_entries:
        if "error" in entry:
            return {"status": "unmatched", "reason": entry["error"],
                    "segs": [], "views": []}
        ref = entry["ref"]
        placement = view_placements.get(ref["viewId"])
        if not placement:
            return {"status": "unmatched", "reason": f"视图不存在: {ref['viewId']}",
                    "segs": [], "views": []}
        cache_key = (placement["source_view"], ref.get("type"), ref.get("idx"))
        if cache_key in match_cache:
            target_seg, target_idx = match_cache[cache_key]
        else:
            target_seg, _, target_idx = match_edge(
                entry["seg"], placement["source_view"], ctx, placement["segs"])
            match_cache[cache_key] = (target_seg, target_idx)
        if target_seg is None:
            return {"status": "unmatched",
                    "reason": f"边线未匹配(视图 {placement['source_view']} idx={ref.get('idx')})",
                    "segs": [], "views": []}
        segs.append(_align_seg_direction(entry["seg"], target_seg))
        views.append(placement)
        ref_map.append({"viewId": ref["viewId"], "idx": target_idx,
                        "type": ref.get("type")})
    used_group = bool(ann.get("groupRefs") and group_refs)
    # 两条引用各自都"匹配成功"仍可能整体错绑:吸到附近同半径杂圆/相邻孔时,
    # 相对方向会歪掉,前端就渲染成斜穿视图的乱线。基准与目标的引用点
    # 方向必须一致(缸体沿主轴拉伸只改变距离,不会转成斜向)。
    if len(ref_entries) == 2 and not used_group:
        b0, b1 = _ref_point(ref_entries[0]["seg"]), _ref_point(ref_entries[1]["seg"])
        t0, t1 = _ref_point(segs[0]), _ref_point(segs[1])
        if b0 and b1 and t0 and t1:
            bv = (b1[0] - b0[0], b1[1] - b0[1])
            tv = (t1[0] - t0[0], t1[1] - t0[1])
            if not _direction_close(bv, tv):
                return {"status": "unmatched",
                        "reason": "重绑后引用点相对方向改变(疑似吸到错误边)",
                        "segs": [], "views": []}
    return {"status": "matched", "reason": "", "segs": segs, "views": views,
            "ref_map": ref_map,
            "ref_map_target": "groupRefs" if used_group else "refs"}
