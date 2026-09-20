# -*- coding: utf-8 -*-
"""路线 D B1 — 离散 line 段圆弧拟合，恢复 circle/arc 语义。

project_discrete_view（PolyAlgo）把圆/弧离散成直线段，丢失几何语义。
本模块把共端点的 line 连成链，最小二乘拟合圆，判定整圆/弧，恢复
type="circle"/"arc" 与 meta.center_mm/radius，使 SVG 圆平滑、下游标注
关联所需的元数据完整。纯 Python 实现，不依赖 numpy。

集成到 step__glb_pdf 后由 drawing.hlr_poly 调用，也可独立使用：

    from drawing.hlr_arcfit import fit_circular_features
    vis2 = fit_circular_features(vis_final, max_radius=shape_max_extent(shape) * 2)
"""
import math


def _quant(p, tol):
    return (round(p[0] / tol), round(p[1] / tol))


def _solve3x3(A, b):
    """高斯消元解 3x3 线性系统，奇异返回 None。"""
    M = [A[i][:] + [b[i]] for i in range(3)]
    for i in range(3):
        piv = max(range(i, 3), key=lambda r: abs(M[r][i]))
        if abs(M[piv][i]) < 1e-12:
            return None
        M[i], M[piv] = M[piv], M[i]
        pv = M[i][i]
        for j in range(i, 4):
            M[i][j] /= pv
        for r in range(3):
            if r != i:
                f = M[r][i]
                for j in range(i, 4):
                    M[r][j] -= f * M[i][j]
    return [M[i][3] for i in range(3)]


def _fit_circle_kasa(pts):
    """Kasa 代数圆拟合（中心化抗病态），返回 (cx, cy, r, rms) 或 None。"""
    n = len(pts)
    if n < 3:
        return None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    U = [p[0] - mx for p in pts]
    V = [p[1] - my for p in pts]
    su2 = sum(u * u for u in U)
    sv2 = sum(v * v for v in V)
    suv = sum(u * v for u, v in zip(U, V))
    su = sum(U)
    sv = sum(V)
    sR = sum(u * u + v * v for u, v in zip(U, V))
    suR = sum((u * u + v * v) * u for u, v in zip(U, V))
    svR = sum((u * u + v * v) * v for u, v in zip(U, V))
    A = [[su2, suv, su], [suv, sv2, sv], [su, sv, n]]
    sol = _solve3x3(A, [-suR, -svR, -sR])
    if sol is None:
        return None
    a, b, c = sol
    r2 = (a * a + b * b) / 4 - c
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    cx = mx - a / 2
    cy = my - b / 2
    err2 = sum((math.hypot(x - cx, y - cy) - r) ** 2 for x, y in pts)
    return (cx, cy, r, math.sqrt(err2 / n))


def _angle_span(pts, cx, cy):
    """按有序点累计角度跨度（弧度），整圆≈2π。"""
    angs = [math.atan2(y - cy, x - cx) for x, y in pts]
    span = 0.0
    for i in range(1, len(angs)):
        d = angs[i] - angs[i - 1]
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        span += d
    return abs(span)


def _chain_lines(lines, tol):
    """把共端点的 line 连成有序 line 链（保留原始 line dict 与 meta）。"""
    adj = {}
    for i, ln in enumerate(lines):
        a = _quant((ln["x1"], ln["y1"]), tol)
        b = _quant((ln["x2"], ln["y2"]), tol)
        adj.setdefault(a, []).append((b, i))
        adj.setdefault(b, []).append((a, i))

    used = [False] * len(lines)

    def swap(ln):
        return {"type": "line", "x1": ln["x2"], "y1": ln["y2"],
                "x2": ln["x1"], "y2": ln["y1"], "meta": ln.get("meta")}

    def grow(chain, at_end):
        while True:
            if at_end:
                tip = (chain[-1]["x2"], chain[-1]["y2"])
            else:
                tip = (chain[0]["x1"], chain[0]["y1"])
            key = _quant(tip, tol)
            nxt = next((idx for _, idx in adj.get(key, []) if not used[idx]), None)
            if nxt is None:
                break
            used[nxt] = True
            ln = lines[nxt]
            lk1 = _quant((ln["x1"], ln["y1"]), tol)
            if lk1 == key:
                ln2 = ln if at_end else swap(ln)
            else:
                ln2 = swap(ln) if at_end else ln
            chain.append(ln2) if at_end else chain.insert(0, ln2)

    chains = []
    for i in range(len(lines)):
        if used[i]:
            continue
        chain = [lines[i]]
        used[i] = True
        grow(chain, True)
        grow(chain, False)
        chains.append(chain)
    return chains


def _make_circle(cx, cy, r, rms):
    return {
        "type": "circle",
        "cx": cx, "cy": cy, "r": r,
        "meta": {
            "radius": round(r, 2),
            "center_mm": [round(cx, 2), round(cy, 2)],
            "center": [round(cx, 2), round(cy, 2)],
            "fit_rms": round(rms, 3),
        },
    }


def _make_arc(cx, cy, r, chain, span, rms):
    pts = [(ln["x1"], ln["y1"]) for ln in chain]
    pts.append((chain[-1]["x2"], chain[-1]["y2"]))
    return {
        "type": "polyline",
        "points": pts,
        "meta": {
            "curve": "circle",
            "radius": round(r, 4),
            "center_mm": [round(cx, 4), round(cy, 4)],
            "center": [round(cx, 4), round(cy, 4)],
            "arc_span": round(span, 4),
            "length": round(r * span, 2),
            "fit_rms": round(rms, 3),
        },
    }


def fit_circular_features(segments, point_tol=0.5, chord_tol=1.0,
                          min_points=6, close_tol=1.5, max_radius=1e4):
    """对离散投影段做圆弧拟合，恢复 circle/arc 语义。

    segments 为 project_discrete_view 的 vis/hid 列表（含 type=line 的离散段）。
    返回新 segments：拟合成功的圆/弧替换原 line，其余 line 原样保留。
    """
    lines = [s for s in segments if s.get("type") == "line"]
    others = [s for s in segments if s.get("type") != "line"]
    if not lines:
        return list(segments)

    chains = _chain_lines(lines, point_tol)
    out = list(others)
    for ch in chains:
        if len(ch) < min_points:
            out.extend(ch)
            continue
        pts = [(ln["x1"], ln["y1"]) for ln in ch]
        pts.append((ch[-1]["x2"], ch[-1]["y2"]))
        res = _fit_circle_kasa(pts)
        if res is None:
            out.extend(ch)
            continue
        cx, cy, r, rms = res
        if r < 0.5 or r > max_radius or rms > chord_tol:
            out.extend(ch)
            continue
        span = _angle_span(pts, cx, cy)
        closed = math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= close_tol
        if span >= 2 * math.pi - 0.35 and closed:
            out.append(_make_circle(cx, cy, r, rms))
        else:
            out.append(_make_arc(cx, cy, r, ch, span, rms))
    return out
