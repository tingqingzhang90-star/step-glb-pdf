# -*- coding: utf-8 -*-
"""B-Rep 圆边直接投影 —— 让 poly 链路保留原生圆/弧语义。

背景
----
poly(HLRBRep_PolyAlgo)把圆离散成三角网格弦段,再由 hlr_arcfit 从弦段反推
圆/弧。这条路必然丢语义:
  * 短弧拟合圆是病态的(Ø24 沉孔曾飘到 22.0~24.6);
  * 大圆几何明明在弦段里却识别不成圆 —— 实测 Ø138 有 40 条弦段、角度覆盖
    5.94rad,Ø200 有 122 条、覆盖 6.18rad,但 poly 都没输出圆实体;
  * 反过来还会把碎弦误拟成噪声微圆(Ø1.0~Ø1.6 之类)。

做法
----
绕开"弦段反推":圆心与半径直接取 B-Rep 真值,可见范围用 PolyAlgo 可见弦段
落在圆上的角度覆盖确定,点列按精确圆解析采样。于是 poly 保留离散投影的速度,
圆/弧语义与 algo 一致。
"""
import math

from OCC.Core.gp import gp_Pnt, gp_Ax3, gp_Trsf
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_EDGE
from OCC.Core.TopoDS import topods
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve

from drawing.hlr_arc_geom import (angle_ranges, arc_overlap, dedup_arcs,
                                  make_entity, ranges_cover_full)

_CIRCLE_EDGE_CACHE = {}   # model_path -> 3D 圆边
_VIEW_CIRCLE_CACHE = {}   # (model_path, view) -> 该视图投影为圆的边

# 弦段端点归属到圆的距离容差(mm):须小于同心圆最小间距(实测 0.25mm),否则串圆
_ON_CIRCLE_TOL = 0.15
# 一条圆边至少要有这么多个"真弦"(两端都落在圆上的弦段)才认为它可见。
# 单端点判定会把孔壁等巧合点也算上:螺栓分布圆半径恰好 = 孔心距 ± 孔半径,
# 12 个孔壁的点被误点亮成 Ø228/Ø230 整圈弧(algo 里完全不存在),实测
# 这类圆的真弦数为 0,而真实圆的真弦数 ≥10,判据区分度完全。
_MIN_HITS = 6
# 可见弧段的最小跨度(rad):短于此认为是散点误判,不成弧
_MIN_SPAN = 0.15
# 按边分组生成弧的最小跨度(rad):落点已经过真弦+边范围双重筛选,门槛须低于
# _MIN_SPAN,否则齿槽这类短弧(r=87.5 时槽底弧约 0.12rad)会被整段丢掉
_MIN_SPAN_SEG = 0.03
# 落点归属到边段角度区间的容差(rad),补偿弦端点离散偏差
_SEG_TOL = 0.03


def collect_circle_edges(shape, cache_key):
    """抽取 B-Rep 全部圆边(与视图无关,进程内只遍历一次)。

    每项 (cx,cy,cz, r, ax,ay,az, u1,u2, xx,xy,xz, yx,yy,yz):
    圆心3D、半径、圆轴、参数范围、圆局部 X/Y 轴(用于按参数求圆上点)。
    """
    item = _CIRCLE_EDGE_CACHE.get(cache_key)
    if item is not None:
        return item
    out = []
    explorer = TopExp_Explorer(shape, TopAbs_EDGE)
    while explorer.More():
        try:
            ad = BRepAdaptor_Curve(topods.Edge(explorer.Current()))
            if ad.GetType() == 1:  # GeomAbs_Circle
                circ = ad.Circle()
                loc = circ.Location()
                axd = circ.Axis().Direction()
                xd = circ.XAxis().Direction()
                yd = circ.YAxis().Direction()
                out.append((loc.X(), loc.Y(), loc.Z(), float(circ.Radius()),
                            axd.X(), axd.Y(), axd.Z(),
                            ad.FirstParameter(), ad.LastParameter(),
                            xd.X(), xd.Y(), xd.Z(), yd.X(), yd.Y(), yd.Z()))
        except Exception:
            pass
        explorer.Next()
    _CIRCLE_EDGE_CACHE[cache_key] = out
    return out


def view_circles(shape, ax2, cache_key, view_key):
    """当前视图投影为圆的 B-Rep 圆边。

    返回 [(cx2d, cy2d, r, _u1, _u2, full, ranges)]:ranges 记录该圆下各弧边
    投影后的 2D 角度区间 [(起始角, 角跨度), ...]。齿圈一类的模型里齿槽圆弧
    是同圆心同半径的多条独立短弧边, 生成实体时必须按边分组取落点, 否则落点
    会被聚类成一整圈幽灵圆(algo 按边输出, 不会连弧)。
    """
    item = _VIEW_CIRCLE_CACHE.get(view_key)
    if item is not None:
        return item
    trsf = gp_Trsf()
    trsf.SetTransformation(gp_Ax3(ax2))
    vd = ax2.Direction()
    # 同一(圆心,半径)会对应多条 B-Rep 边:圆柱面两条边界圆、整圆被切成多段
    # 弧,投影后完全重合。不去重会为每个都生成实体(实测实体数 127→2736)。
    agg = {}
    for (x, y, z, r, dx, dy, dz, u1, u2,
         xx, xy, xz, yx, yy, yz) in collect_circle_edges(shape, cache_key):
        if abs(dx * vd.X() + dy * vd.Y() + dz * vd.Z()) <= 0.99:
            continue
        p = gp_Pnt(x, y, z)
        p.Transform(trsf)
        # 同一物理圆的弧边圆心 3D 坐标完全一致; 深度不同的是不同层的边
        # (圆柱两边界圆、齿圈前后两侧), 投影重合但可见范围独立, 必须分层
        # 聚合 —— 否则多层弧边的区间并集会覆盖整圈, 把齿槽误判成物理整圆
        key = (round(p.X(), 2), round(p.Y(), 2), round(r, 3),
               round(p.Z(), 1))
        it = agg.get(key)
        if it is None:
            agg[key] = it = [p.X(), p.Y(), r, False, []]

        def _ang(u):
            q = gp_Pnt(x + r * (math.cos(u) * xx + math.sin(u) * yx),
                       y + r * (math.cos(u) * xy + math.sin(u) * yy),
                       z + r * (math.cos(u) * xz + math.sin(u) * yz))
            q.Transform(trsf)
            return math.atan2(q.Y() - p.Y(), q.X() - p.X())

        if abs(u2 - u1) >= 2 * math.pi - 0.05:
            it[3] = True
        else:
            # 投影变换可能镜像手性: 2D 角方向与圆参数方向相反时, 端点角差
            # 的补角才是真实跨度(实测 13° 弧被算成 347°)。与 3D 参数跨度
            # 比较取一致的方向, 镜像时换算为正向区间 [a2, a1]
            a1 = _ang(u1)
            a2 = _ang(u2)
            d = (a2 - a1) % (2 * math.pi)
            if abs(d - (u2 - u1)) <= abs((2 * math.pi - d) - (u2 - u1)):
                s0, sp = a1, d
            else:
                s0, sp = a2, 2 * math.pi - d
            it[4].append((s0, sp if sp > 1e-9 else 2 * math.pi))
    out = [(v[0], v[1], v[2], 0.0, 0.0, v[3], v[4]) for v in agg.values()]
    _VIEW_CIRCLE_CACHE[view_key] = out
    return out


# 按 (view_key, deflection) 缓存 build_view_circles 的结果:同一视图的弦段集合
# 在给定网格精度下是确定的, 重复请求(Web 同视图再生成)直接命中, 不再重跑
# O(圆数 × 弦段数) 的扫描。视图间不共享, 故不影响正确性。
_BUILDCACHE = {}


def build_view_circles(shape, ax2, segs, cache_key, view_key, deflection=0.5):
    """从 B-Rep 圆边直接生成原生圆/弧实体(不经弦段拟合)。

    Args:
        segs: PolyAlgo 可见/隐藏弦段(type=line),用于确定每个圆的可见角度范围。
        deflection: 网格精度(mm), 影响 segs 筛选, 纳入缓存键避免串味。

    Returns:
        (entities, circles):entities 为生成的圆/弧实体;circles 为该视图全部
        B-Rep 投影圆(含各弧边的 2D 角度区间),供调用方去重与剔除伪圆。
    """
    ckey = (view_key, round(deflection, 3))
    hit = _BUILDCACHE.get(ckey)
    if hit is not None:
        return hit
    circles = view_circles(shape, ax2, cache_key, view_key)
    chords = [s for s in (segs or []) if s.get("type") == "line"]
    if not chords or not circles:
        res = ([], circles)
        _BUILDCACHE[ckey] = res
        return res

    # 弦按中点分桶到均匀网格: 每个圆只扫描中点落在自身 (r+tol) 邻域格子内的弦段,
    # 把 O(圆数 × 弦段数) 降到 ~O(弦段数)(大量小圆/孔的情形收益最大)。
    # 正确性: 若某弦两端都落在圆 (r±tol) 内, 其中点(凸组合)也必在 (r+tol) 内,
    # 故不会漏判; 精确的平方距离判定仍对每个候选弦执行, 不会误判。
    GRID = 10.0        # 网格边长(mm)
    GRID_CAP = 80.0    # 圆过大(少量大圆)时退化为全扫描, 避免扫过多格子
    grid = {}
    for i, s in enumerate(chords):
        mx = (s["x1"] + s["x2"]) * 0.5
        my = (s["y1"] + s["y2"]) * 0.5
        grid.setdefault((int(math.floor(mx / GRID)),
                         int(math.floor(my / GRID))), []).append(i)

    entities = []
    raw = []
    for (cx, cy, r, _u1, _u2, full, ranges) in circles:
        tol = max(_ON_CIRCLE_TOL, 0.005 * r)
        # 用平方距离做快速剔除, 避免对每条弦两端都调用耗时的 math.hypot(sqrt);
        # |d - r| <= tol  ⟺  (r-tol)^2 <= d^2 <= (r+tol)^2, 与原始判定等价
        lo = (r - tol) * (r - tol)
        hi = (r + tol) * (r + tol)
        reach = r + tol
        # 仅取中点落在圆 (r+tol) 邻域格子内的候选弦; 超大圆直接全扫
        if reach > GRID_CAP:
            cand = range(len(chords))
        else:
            cand = []
            h = int(math.ceil(reach / GRID))
            cgx = int(math.floor(cx / GRID))
            cgy = int(math.floor(cy / GRID))
            for gx in range(cgx - h, cgx + h + 1):
                for gy in range(cgy - h, cgy + h + 1):
                    col = grid.get((gx, gy))
                    if col:
                        cand.extend(col)
        angs = []
        n_chord = 0
        for i in cand:
            s = chords[i]
            dx1 = s["x1"] - cx
            dy1 = s["y1"] - cy
            dx2 = s["x2"] - cx
            dy2 = s["y2"] - cy
            # 只认"真弦":两端都落在圆上的弦段。单端点判定会把孔壁等巧合点
            # 算进来(螺栓分布圆半径=孔心距±孔半径),点亮不存在的圆
            if (lo <= dx1 * dx1 + dy1 * dy1 <= hi) and \
               (lo <= dx2 * dx2 + dy2 * dy2 <= hi):
                n_chord += 1
                angs.append(math.atan2(dy1, dx1))
                angs.append(math.atan2(dy2, dx2))
        if n_chord < _MIN_HITS:
            continue
        # 整圆边(或物理整圆被切成多段首尾相接的弧边)才允许整圈判定;齿槽
        # 这类分离短弧必须按边分组取落点, 否则各齿的落点绕圈分布会被聚类
        # 成一整圈幽灵圆(250-F-H2K1 齿圈实测连成 330° 长弧)
        whole = full or ranges_cover_full(ranges)
        if whole:
            groups = [angs]
            min_span = _MIN_SPAN
        else:
            groups = []
            for (s0, sp) in ranges:
                seg = [a for a in angs
                       if (a - s0) % (2 * math.pi) <= sp + _SEG_TOL
                       or (a - s0) % (2 * math.pi) >= 2 * math.pi - _SEG_TOL]
                if seg:
                    groups.append(seg)
            min_span = _MIN_SPAN_SEG
        for seg in groups:
            for a0, a1 in angle_ranges(seg):
                if a1 - a0 < min_span:
                    continue
                ent = make_entity(cx, cy, r, a0, a1)
                if ent:
                    raw.append((cx, cy, r, a0 % (2 * math.pi),
                                a1 - a0, ent))
    entities = dedup_arcs(raw)
    res = (entities, circles)
    _BUILDCACHE[ckey] = res
    return res


def _matches(seg, circles, center_tol):
    m = seg.get("meta") or {}
    r = m.get("radius")
    c = m.get("center_mm") or m.get("center")
    if not r or not c:
        return False
    for item in circles:
        ex, ey, er = item[0], item[1], item[2]
        if (math.hypot(ex - c[0], ey - c[1]) <= center_tol
                and abs(er - r) <= max(0.5, 0.02 * r)):
            return True
    return False


def drop_duplicate_fitted(fitted, circles, center_tol=1.0):
    """移除拟合结果里已被 B-Rep 原生圆覆盖的圆/弧,避免同一圆重复出现两次。"""
    if not circles:
        return fitted
    return [s for s in fitted if not _matches(s, circles, center_tol)]


def strip_bogus_circle_meta(fitted, circles, center_tol=1.0):
    """把 B-Rep 里找不到对应圆边的"伪圆"降级为普通折线,不再带错误半径。

    碎弦会被拟合误判成微圆(实测 Ø1.0~Ø1.6 一类),这些没有 B-Rep 圆边支撑,
    留着圆语义会让前端把它当孔标注。去掉 radius/curve/center 元数据即可,
    几何点列保留,不影响渲染(假圆的几何删除交给 drop_fake_resampled)。
    """
    if not circles:
        return fitted
    for seg in fitted:
        m = seg.get("meta") or {}
        if m.get("radius") and not _matches(seg, circles, center_tol):
            for k in ("radius", "curve", "center_mm", "center",
                      "arc_span", "radius_px", "fit_rms"):
                m.pop(k, None)
    return fitted

