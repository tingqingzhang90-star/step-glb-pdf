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

# 各视图投影面坐标轴与模型主轴(Z)的映射(ax2 坐标系,单位 mm)
AXIAL_MAP = {"left": ("x", 1.0), "right": ("x", -1.0),
             "top": ("y", 1.0), "bottom": ("y", -1.0)}

POS_TOL = 5.0   # 位置匹配容差 mm
LEN_TOL = 2.5   # 长度/半径匹配容差 mm


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
        (target_seg, score) 匹配成功; (None, 失配原因) 失败
    """
    axis_sign = AXIAL_MAP.get(view_name)
    axis, sign = axis_sign if axis_sign else (None, 1.0)
    exp = _expected_mm(base_seg, axis, sign, ctx)
    if exp is None:
        return None, "基准边线缺少 mm 元数据"

    best, best_score = None, None
    for seg in target_segs:
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
            best, best_score = seg, score
    if best is None:
        return None, "目标视图中无几何指纹相符的边线"
    return best, best_score


def _motor_face_lines(target_profile, view_name):
    """电机包络两端面的投影线(mm),供 bind_motor 标注合成边线

    Returns:
        (face_min, face_max, size): 两端面线段(各为 (p1, p2)),无电机或
        该视图轴向退化时返回 (None, None, None)
    """
    from drawing.dim.dim_envelope import envelope_faces

    faces = envelope_faces(target_profile["anchors"], view_name)
    if not faces:
        return None, None, None
    motor = _by_id(target_profile).get("motor.body")
    return faces["face_min"], faces["face_max"], motor["size"]


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
    """
    if not view_segs:
        return seg
    s = max(float(view_scale or 1.0), 1e-6)
    SNAP = 30.0 / s          # 30 图纸 px → 画布 px
    FLAT = 2.0 / s           # 前端"近似竖直/水平"判据同样在图纸坐标
    best = None
    best_dist = float('inf')
    if orientation == "horizontal":
        # 端面线竖直,找同 x 附近的竖直边线
        # 距离/落点都用候选边线的首个端点(与前端 Math.abs(x1 - pt.x) 一致):
        # 调色板里有大量 0.1px 级退化碎片,用中点度量会吸到另一条碎片
        for e in view_segs:
            if e.get("type") != "line":
                continue
            if abs(e["x1"] - e["x2"]) > FLAT:
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
        # 端面线水平,找同 y 附近的水平边线
        for e in view_segs:
            if e.get("type") != "line":
                continue
            if abs(e["y1"] - e["y2"]) > FLAT:
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
        fmin, fmax, _size = faces
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
        return {"status": "motor", "reason": "",
                "segs": [seg_min, seg_max], "views": [placement, placement]}

    # 孔组引用(分度圆直径标注):按各孔边线匹配,渲染端再合成 Bolt 圆
    ref_entries = group_refs if ann.get("groupRefs") and group_refs else base_refs
    if not ref_entries:
        return {"status": "unmatched", "reason": "标注无引用边线(refs 为空)",
                "segs": [], "views": []}
    segs, views = [], []
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
            target_seg = match_cache[cache_key]
        else:
            target_seg, _ = match_edge(entry["seg"], placement["source_view"],
                                       ctx, placement["segs"])
            match_cache[cache_key] = target_seg
        if target_seg is None:
            return {"status": "unmatched",
                    "reason": f"边线未匹配(视图 {placement['source_view']} idx={ref.get('idx')})",
                    "segs": [], "views": []}
        segs.append(_align_seg_direction(entry["seg"], target_seg))
        views.append(placement)
    return {"status": "matched", "reason": "", "segs": segs, "views": views}
