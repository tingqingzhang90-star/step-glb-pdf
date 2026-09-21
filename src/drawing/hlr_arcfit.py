# -*- coding: utf-8 -*-
"""路线 D B1 — 离散 line 段圆弧拟合，恢复 circle/arc 语义。

project_discrete_view（PolyAlgo）把圆/弧离散成直线段，丢失几何语义。
本模块把共端点的 line 连成链，最小二乘拟合圆，判定整圆/弧，恢复
type="circle"/"arc" 与 meta.center_mm/radius，使 SVG 圆平滑、下游标注
关联所需的元数据完整。

未拟合为圆的链同样要合并：一条模型边在三角化后是几十条短弦，若原样下发，
下游按边线指纹(mm_coords/length)匹配尺寸标注会全部失配，数据量也会膨胀。
合并规则为——近似直线 → line(补 orientation/midpoint/mm_coords)，其余 → polyline。

纯 Python 实现，不依赖 numpy。集成到 step__glb_pdf 后由 drawing.hlr_poly 调用，
也可独立使用：

    from drawing.hlr_arcfit import fit_circular_features
    vis2 = fit_circular_features(vis_final, min_points=4, max_radius=extent * 2,
                                 sagitta_tol=1.5 * deflection,
                                 straight_tol=deflection)

sagitta_tol 是"圆柱面 vs 多边形"的必要判据：三角化弦中点到拟合圆的偏差不超过
三角化容差，而六角/方形轮廓在同样半径下偏差约 0.134r，据此可避免把棱柱面误判成圆。
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


def _median(values):
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _fit_circle_robust(pts, trim_thresh=0.3, max_iter=2):
    """鲁棒圆拟合:Kasa 初值 + 按残差剔除外点后重拟合。

    PolyAlgo 把圆离散成弦,链首尾常混入 1~2 个偏离真实圆 ~2mm 的杂点
    (圆在倒角/键槽等特征处被打断),普通最小二乘(Kasa)会被这些外点把半径
    拉偏 ~1.6mm(实测 Ø310 被拟成 308.4),而内点残差只有网格容差级 ~0.05mm。
    用中位数 + MAD 分离内外点后重拟合,恢复真实半径。
    剔除只影响半径/圆心;返回的 rms 按全链点计算(对最终圆),保证
    "是否够圆"的判定不因剔除而放宽。返回 (cx, cy, r, rms, inlier_pts)。
    """
    res = _fit_circle_kasa(pts)
    if res is None:
        return None
    cx, cy, r, _ = res
    kept = list(pts)
    if len(kept) >= 6:
        for _ in range(max_iter):
            resid = [abs(math.hypot(x - cx, y - cy) - r) for x, y in kept]
            med = _median(resid)
            mad = _median([abs(d - med) for d in resid])
            thresh = max(med + 4.0 * mad, trim_thresh)
            nxt = [p for p, d in zip(kept, resid) if d <= thresh]
            if len(nxt) < 3 or len(nxt) == len(kept):
                break
            new = _fit_circle_kasa(nxt)
            if new is None:
                break
            cx, cy, r, _ = new
            kept = nxt
    err2 = sum((math.hypot(x - cx, y - cy) - r) ** 2 for x, y in pts)
    return (cx, cy, r, math.sqrt(err2 / len(pts)), kept)


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


def _points_sagitta(pts, cx, cy, r):
    """连续点对(弦)中点到拟合圆的最大偏差(mm)。

    三角化弦的中点相对拟合圆最多偏离三角化容差(deflection);而多边形
    (六角/方形轮廓)的中点在同样半径下偏离 0.134r 量级,据此可把"多边形
    被误判成圆"挡掉 —— 前提是三角化足够细(deflection 远小于 0.134r)。
    直接吃点列,配合鲁棒拟合只用内点计算,避免链首尾杂点抬高矢高判据
    导致真圆被误拒。
    """
    worst = 0.0
    for a, b in zip(pts, pts[1:]):
        mx = (a[0] + b[0]) / 2.0
        my = (a[1] + b[1]) / 2.0
        d = abs(math.hypot(mx - cx, my - cy) - r)
        if d > worst:
            worst = d
    return worst


def _chain_points(chain):
    pts = [(ln["x1"], ln["y1"]) for ln in chain]
    pts.append((chain[-1]["x2"], chain[-1]["y2"]))
    return pts


def _deviation(pts, p1, p2):
    """点到首尾连线的最大垂距(mm)，用于判断链是否近似直线。"""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    seg = math.hypot(dx, dy)
    if seg < 1e-9:
        return max(math.hypot(p[0] - p1[0], p[1] - p1[1]) for p in pts)
    worst = 0.0
    for x, y in pts:
        d = abs(dy * (x - p1[0]) - dx * (y - p1[1])) / seg
        if d > worst:
            worst = d
    return worst


def _merge_chain(chain, straight_tol):
    """把未拟合为圆的链合并成一个实体，保留几何与匹配所需的 mm 元数据。

    近似直线 → type=line（补 orientation/midpoint/mm_coords，供包围盒角色与
    尺寸重绑识别）；弯曲链(样条等) → type=polyline。离散弦本身没有这些
    元数据，若不合并，下游按边线指纹匹配尺寸标注会全部失配。
    """
    pts = _chain_points(chain)
    p1, p2 = pts[0], pts[-1]
    chord = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
    # 垂距小 + 弧长约等于弦长才算直线:薄片/重叠边会走出"折返路径",垂距同样
    # 很小但弧长远大于弦长,若直接合并成首尾直线会整段丢掉折返部分。
    if _deviation(pts, p1, p2) <= straight_tol and total <= chord * 1.05 + straight_tol:
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        if abs(dy) < 0.1:
            orientation = "horizontal"
        elif abs(dx) < 0.1:
            orientation = "vertical"
        else:
            orientation = "diagonal"
        return {
            "type": "line",
            "x1": p1[0], "y1": p1[1], "x2": p2[0], "y2": p2[1],
            "meta": {
                "orientation": orientation,
                "length": round(total, 4),
                "midpoint": [round((p1[0] + p2[0]) / 2, 2),
                             round((p1[1] + p2[1]) / 2, 2)],
                "mm_coords": [round(p1[0], 6), round(p1[1], 6),
                              round(p2[0], 6), round(p2[1], 6)],
            },
        }
    return {
        "type": "polyline",
        "points": pts,
        "meta": {"length": round(total, 2),
                 "mm_coords": [round(p1[0], 6), round(p1[1], 6),
                               round(p2[0], 6), round(p2[1], 6)]},
    }


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


def _make_arc(cx, cy, r, pts, span, rms):
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


def _merge_cocircular(segments, center_tol=1.5, merge_rms_tol=0.15,
                      max_radius=1e4):
    """同圆碎片共享合并拟合的半径(不替换几何,渲染不缺线)。

    离散 HLR 把圆柱面(如沉孔壁)的剪影离散成 r 波动 ±0.1mm 的弦段,同一圆在
    链接时被拆成多段,短弧单独拟合圆是病态的(实测 Ø24 沉孔飘到 22.0~24.6)。
    这里按圆心聚类,组内合点拟合出更准的圆心/半径,再回写到组内每个碎片的
    meta —— 碎片的点列与数量原样保留,只修正标注用的半径。
    合并判定用普通 Kasa 残差:真同圆残差小(网格波动 ~0.1mm),同心不同半径
    (如 r=12 与 r=7.75)残差大,保持独立。
    """
    groups = []  # [cx, cy, points, segs]
    rest = []
    for seg in segments:
        m = seg.get("meta") or {}
        if not m.get("radius") or seg.get("type") == "circle":
            rest.append(seg)
            continue
        if m.get("curve") == "circle" and m.get("center_mm") and seg.get("points"):
            cx, cy = m["center_mm"]
            placed = False
            for g in groups:
                if math.hypot(g[0] - cx, g[1] - cy) <= center_tol:
                    g[2].extend(seg["points"])
                    g[3].append(seg)
                    placed = True
                    break
            if not placed:
                groups.append([cx, cy, list(seg["points"]), [seg]])
            continue
        rest.append(seg)

    if not groups:
        return segments

    out = list(rest)
    for gx, gy, pts, segs in groups:
        if len(segs) < 2:
            out.extend(segs)
            continue
        kasa = _fit_circle_kasa(pts)
        if kasa is None or kasa[3] > merge_rms_tol:
            out.extend(segs)
            continue
        res = _fit_circle_robust(pts)
        if res is None:
            out.extend(segs)
            continue
        cx, cy, r, rms, _inl = res
        if r < 0.5 or r > max_radius:
            out.extend(segs)
            continue
        for seg in segs:
            m = seg["meta"]
            m["radius"] = round(r, 4)
            m["center_mm"] = [round(cx, 4), round(cy, 4)]
            m["center"] = [round(cx, 4), round(cy, 4)]
            if "length" in m:
                m["length"] = round(r * m.get("arc_span", 0), 2)
            m["fit_rms"] = round(rms, 3)
        out.extend(segs)
    return out


def fit_circular_features(segments, point_tol=0.5, chord_tol=1.0,
                          min_points=6, close_tol=1.5, max_radius=1e4,
                          sagitta_tol=0.75, straight_tol=0.2):
    """对离散投影段做圆弧拟合，恢复 circle/arc 语义。

    segments 为 project_discrete_view 的 vis/hid 列表（含 type=line 的离散段）。
    返回新 segments：拟合成功的圆/弧替换该链；未拟合的链合并为 line/polyline
    （补 mm_coords/length 等元数据），单条 line 原样保留。

    Args:
        point_tol: 端点量化容差(mm)，用于把共端点的 line 连成链
        chord_tol: 拟合残差上限(mm)，弦端点到拟合圆的 RMS
        min_points: 最少弦数；三角化弦的小圆可能只有 4-5 条弦，粗网格下
            取 6 会让小圆全部漏检
        sagitta_tol: 弦中点到拟合圆的最大偏差上限(mm)，用于挡掉把多边形
            (六角/方形)误判成圆；调用方按三角化容差给值(约 1.5×deflection)。
            None 表示不做该判定(仅当输入已是精确圆弧时可用)
        max_radius: 半径上限(mm)，超过视为拟合退化
        straight_tol: 合并链时判定"近似直线"的最大垂距(mm)，给三角化容差量级
    """
    lines = [s for s in segments if s.get("type") == "line"]
    others = [s for s in segments if s.get("type") != "line"]
    if not lines:
        return list(segments)

    chains = _chain_lines(lines, point_tol)
    out = list(others)
    for ch in chains:
        if len(ch) < min_points:
            out.append(_merge_chain(ch, straight_tol) if len(ch) > 1 else ch[0])
            continue
        pts = _chain_points(ch)
        res = _fit_circle_robust(pts)
        if res is None:
            out.append(_merge_chain(ch, straight_tol))
            continue
        cx, cy, r, rms, inl = res
        if r < 0.5 or r > max_radius or rms > chord_tol:
            out.append(_merge_chain(ch, straight_tol))
            continue
        if sagitta_tol is not None and _points_sagitta(pts, cx, cy, r) > sagitta_tol:
            out.append(_merge_chain(ch, straight_tol))
            continue
        span = _angle_span(pts, cx, cy)
        closed = math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= close_tol
        if span >= 2 * math.pi - 0.35 and closed:
            out.append(_make_circle(cx, cy, r, rms))
        else:
            out.append(_make_arc(cx, cy, r, pts, span, rms))
    if sagitta_tol is not None:
        out = _merge_cocircular(out, max_radius=max_radius)
    return out
