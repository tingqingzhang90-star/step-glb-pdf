"""hlr_arcfit 单元测试 — 离散弦 → 圆/弧/直线实体的还原规则。

背景(路线 D B1): PolyAlgo 把圆/弧/样条全部离散成短弦，视图会因此"残缺"
(小圆漏检、一条边被打散成几十条短弦)。本测试锁住三条判据:
  1. 小圆(只有 4-5 条弦)也要拟合出来 —— min_points 不能取 6;
  2. 六角/方形轮廓不能被误判成圆 —— 需要 sagitta 守卫;
  3. 未成圆的链合并成单个 line/polyline 并补齐 mm_coords，供尺寸重绑匹配，
     但"折返路径"(薄片/重叠边)不能塌成一条直线。
纯 Python，无需 OCC。
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from drawing.hlr_arcfit import fit_circular_features  # noqa: E402


def poly_chain(pts):
    """把点列转成共端点的 line 段列表(模拟离散弦)。"""
    return [{"type": "line", "x1": a[0], "y1": a[1], "x2": b[0], "y2": b[1]}
            for a, b in zip(pts, pts[1:])]


def arc_pts(cx, cy, r, n, a0=0.0, a1=2 * math.pi):
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n),
             cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def fit(segs, deflection=0.5):
    return fit_circular_features(segs, min_points=4, max_radius=1e4,
                                 sagitta_tol=1.5 * deflection,
                                 straight_tol=max(0.2, deflection))


def test_small_circle_with_few_chords_is_recovered():
    # r=5mm 的螺栓孔在 deflection=0.5 网格下约 6 条弦，旧参数(min_points=6 +
    # 2.0mm 短边过滤)会把它整圈删掉，故 min_points 需放宽且不能按弦长过滤
    segs = poly_chain(arc_pts(100, 50, 5, 6))
    out = fit(segs)
    circles = [s for s in out if s["type"] == "circle"]
    assert len(circles) == 1, out
    assert abs(circles[0]["r"] - 5) < 0.05
    assert abs(circles[0]["cx"] - 100) < 0.05 and abs(circles[0]["cy"] - 50) < 0.05


def test_four_chord_loop_stays_polygon():
    # 4 条弦的闭环几何上就是正方形(矢高 0.293r 远超三角化容差), 不应报成圆;
    # 这是精度与召回的必要取舍: 只按残差判定会把所有棱柱面都变成圆
    out = fit(poly_chain(arc_pts(100, 50, 5, 4)))
    assert not [s for s in out if s["type"] == "circle"], out
    assert sum(1 for s in out if s["type"] in ("line", "polyline")) == 1


def test_hexagon_is_not_fitted_as_circle():
    # 六角轮廓: 顶点在圆上, Kasa 残差≈0, 必须靠矢高判据挡掉
    pts = [(20 * math.cos(2 * math.pi * i / 6), 20 * math.sin(2 * math.pi * i / 6))
           for i in range(7)]
    out = fit(poly_chain(pts))
    assert not [s for s in out if s["type"] == "circle"], out
    # 仍应作为独立实体保留, 几何不丢
    assert sum(1 for s in out if s["type"] in ("line", "polyline")) >= 1


def test_long_edge_chords_merge_into_single_line_with_mm_meta():
    # 一条 410mm 直边被切成若干弦: 必须合并成一条带 mm_coords 的 line,
    # 否则下游按边线指纹匹配尺寸标注会失配
    pts = [(0.0 + 410.0 * i / 5, 12.0) for i in range(6)]
    out = fit(poly_chain(pts))
    assert len(out) == 1, out
    seg = out[0]
    assert seg["type"] == "line"
    assert seg["meta"]["orientation"] == "horizontal"
    assert seg["meta"]["mm_coords"] == [0.0, 12.0, 410.0, 12.0]
    assert abs(seg["meta"]["length"] - 410.0) < 1e-6


def test_doubling_back_chain_keeps_full_geometry():
    # 薄片/重叠边会走出"去而复返"的路径: 垂距很小但弧长远大于弦长,
    # 若塌成一条首尾直线会整段丢线, 故应保留为 polyline
    pts = [(0.0, 0.0), (0.0, 30.0), (0.0, 0.0), (5.0, 0.0)]
    out = fit(poly_chain(pts))
    assert len(out) == 1, out
    assert out[0]["type"] == "polyline"
    assert len(out[0]["points"]) == len(pts)


def test_spline_arc_keeps_curve_metadata():
    # 非整圆的弧仍输出 polyline + curve=circle, 供前端与标注取半径
    out = fit(poly_chain(arc_pts(0, 0, 40, 12, 0.0, math.radians(120))))
    assert len(out) == 1
    seg = out[0]
    assert seg["type"] == "polyline"
    assert seg["meta"]["curve"] == "circle"
    assert abs(seg["meta"]["radius"] - 40) < 0.05
    assert abs(seg["meta"]["arc_span"] - math.radians(120)) < 0.01
