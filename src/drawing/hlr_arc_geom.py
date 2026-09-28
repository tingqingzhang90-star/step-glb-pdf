# -*- coding: utf-8 -*-
"""圆/弧实体的几何构造 —— 供 hlr_brep_circles 组装原生圆/弧使用。

拆出来的原因是 hlr_brep_circles 已接近单文件行数上限, 而本模块的内容全是
纯几何运算(角度聚类、区间交叠、圆/弧点列采样), 不依赖 B-Rep 拓扑, 单独放
可被两处的算子复用。
"""
import math

# 相邻落点角度差超过它就认为弧在此断开(rad)
_GAP_TOL = 0.35
# 弧点列采样角步长(rad)
_SAMPLE_STEP = 0.12


def angle_ranges(angs, gap=_GAP_TOL):
    """把落点角度聚类成连续区间 [(a0, a1), ...],处理 ±π 环绕。

    以最大间隙处切开:间隙不超过 gap 说明落点绕满一圈,视为整圆。
    """
    a = sorted(angs)
    n = len(a)
    if n < 2:
        return [(a[0], a[0])] if n else []
    gaps = [(a[(i + 1) % n] - a[i]) % (2 * math.pi) for i in range(n)]
    cut = max(range(n), key=lambda i: gaps[i])
    if gaps[cut] <= gap:
        return [(a[0], a[0] + 2 * math.pi)]
    start = (cut + 1) % n
    ordered = [a[(start + i) % n] for i in range(n)]
    unwrapped = [ordered[0]]
    for v in ordered[1:]:
        while v < unwrapped[-1]:
            v += 2 * math.pi
        unwrapped.append(v)
    ranges = []
    seg_start = prev = unwrapped[0]
    for v in unwrapped[1:]:
        if v - prev > gap:
            ranges.append((seg_start, prev))
            seg_start = v
        prev = v
    ranges.append((seg_start, prev))
    return [(s, e) for s, e in ranges if e - s > 1e-6]


def ranges_cover_full(ranges):
    """各弧边的 2D 角度区间是否并成整圈(物理整圆被切成多段弧边的情形)。"""
    n = 72
    hit = sum(any((2 * math.pi * i / n - s) % (2 * math.pi) <= sp
                  for (s, sp) in ranges) for i in range(n))
    return hit >= n - 2


def arc_overlap(s1, sp1, s2, sp2):
    """两个 2D 角度区间(处理 ±2π 环绕)的交叠长度。"""
    def unfold(s, sp):
        s %= 2 * math.pi
        if s + sp <= 2 * math.pi + 1e-9:
            return [(s, s + sp)]
        return [(s, 2 * math.pi), (0.0, s + sp - 2 * math.pi)]
    return sum(max(0.0, min(a1, b1) - max(a0, b0))
               for (a0, a1) in unfold(s1, sp1)
               for (b0, b1) in unfold(s2, sp2))


def dedup_arcs(raw):
    """跨深度层去重: 不同层的边投影重合时(圆柱两边界圆、齿圈两侧), 同一
    2D 弧段只保留一份, 避免分层聚合后实体数成倍膨胀。"""
    kept = []
    for (cx, cy, r, a0, span, ent) in raw:
        rtol = max(0.05, 0.002 * r)
        if not any(abs(kx - cx) <= 0.1 and abs(ky - cy) <= 0.1
                   and abs(kr - r) <= rtol
                   and arc_overlap(ka, ks, a0, span) > 0.6 * min(ks, span)
                   for (kx, ky, kr, ka, ks, _e) in kept):
            kept.append((cx, cy, r, a0, span, ent))
    return [ent for (_, _, _, _, _, ent) in kept]


def _circle_from_3(pts):
    """用首/中/末三点定圆, 返回 (cx, cy, r);三点共线时返回 None。"""
    (x1, y1), (x2, y2), (x3, y3) = pts[0], pts[len(pts) // 2], pts[-1]
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-9:
        return None
    s1 = x1 * x1 + y1 * y1
    s2 = x2 * x2 + y2 * y2
    s3 = x3 * x3 + y3 * y3
    ux = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / d
    uy = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d
    return (ux, uy, math.hypot(ux - x1, uy - y1))


def resampled_circle(points, dev_tol=0.01, min_span=math.pi):
    """点列严密落在同一圆上且跨度达半圈以上时返回 (cx, cy, r),否则 None。

    拟合器输出圆时按拟合结果重采样点列, 共圆残差近乎为 0;普通多段线保留原始
    轮廓点列, 残差不会这么小。据此识别"补出来的假圆" —— 注意它可能是 arcfit
    按普通 polyline 输出的, meta 里连 radius 都没有。
    """
    if not points or len(points) < 5:
        return None
    c = _circle_from_3(points)
    if c is None:
        return None
    ux, uy, r = c
    if not 0 < r < 1e4:
        return None
    for (px, py) in points:
        if abs(math.hypot(px - ux, py - uy) - r) > dev_tol:
            return None
    angs = [math.atan2(py - uy, px - ux) for (px, py) in points]
    unw = [angs[0]]
    for a in angs[1:]:
        v = a
        while v - unw[-1] > math.pi:
            v -= 2 * math.pi
        while unw[-1] - v > math.pi:
            v += 2 * math.pi
        unw.append(v)
    return c if abs(unw[-1] - unw[0]) >= min_span else None


def drop_fake_resampled(fitted, entities):
    """删除拟合层重采样补出的、原生层并未生成的大跨度圆。

    arcfit 会把一串连续弦识别成圆并按圆重采样, 有时甚至按普通 polyline 输出
    (meta 里没有 radius, strip_bogus_circle_meta 查不到), 前端照样画出一圈不
    存在的弧 —— 实测 250-F-H2K1 齿圈外被补出 Ø90/301° 一圈, algo 基准里没有。

    保留条件是该圆在原生层已生成过实体:那说明它有足够"真弦"证据支撑。半圈
    以上的真实圆弦段充足, 不会被原生层漏掉, 故按此判据删除不会缺线。
    """
    if not entities:
        return fitted
    native = set()
    for e in entities:
        if e.get("type") == "circle":
            native.add((round(e["cx"], 1), round(e["cy"], 1), round(e["r"], 1)))
            continue
        m = e.get("meta") or {}
        if m.get("radius") and m.get("center_mm"):
            native.add((round(m["center_mm"][0], 1), round(m["center_mm"][1], 1),
                        round(m["radius"], 1)))
    out = []
    for seg in fitted:
        pts = seg.get("points") or seg.get("pts")
        if not pts:
            out.append(seg)
            continue
        # 圆语义已被 strip 剥掉 == B-Rep 里没有对应圆边, 说明它就是拟合噪声;
        # 这类噪声未必严密共圆(实测齿圈外一批 Ø2.6~Ø3.6 残差 0.08~0.47mm),
        # 故残差与跨度门槛放宽一档
        supported = bool((seg.get("meta") or {}).get("radius"))
        dev_tol = 0.01 if supported else 0.75
        min_span = math.pi if supported else math.radians(150.0)
        c = resampled_circle(pts, dev_tol=dev_tol, min_span=min_span)
        if c is None:
            out.append(seg)
            continue
        key = (round(c[0], 1), round(c[1], 1), round(c[2], 1))
        if key not in native:
            continue
        out.append(seg)
    return out


def make_entity(cx, cy, r, a0, a1):
    """按精确圆解析采样出圆/弧实体(整圆出 circle, 否则出带圆语义的多段线)。"""
    span = a1 - a0
    # 可见落点绕满一圈就出原生整圆(不必要求 B-Rep 边是整圆边:整圆被 HLR
    # 切成多段弧后,合并回来的可见范围同样是一整圈)
    if span >= 2 * math.pi - 0.15:
        return {"type": "circle", "cx": cx, "cy": cy, "r": r,
                "meta": {"radius": round(r, 2),
                         "center_mm": [round(cx, 2), round(cy, 2)],
                         "center": [round(cx, 2), round(cy, 2)],
                         "fit_rms": 0.0}}
    if span < 0.02:
        return None
    n = max(3, int(span / _SAMPLE_STEP) + 2)
    pts = [(cx + r * math.cos(a0 + span * i / (n - 1)),
            cy + r * math.sin(a0 + span * i / (n - 1))) for i in range(n)]
    return {"type": "polyline", "points": pts,
            "meta": {"curve": "circle", "radius": round(r, 4),
                     "center_mm": [round(cx, 4), round(cy, 4)],
                     "center": [round(cx, 4), round(cy, 4)],
                     "arc_span": round(span, 4),
                     "length": round(r * span, 2),
                     "fit_rms": 0.0}}
