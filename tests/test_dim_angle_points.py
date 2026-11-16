# -*- coding: utf-8 -*-
"""中心夹角标注(顶点 + 两个被测点)几何测试

与前端 core.js buildAnglePointsGeometry 同公式:取小于 180° 的一侧画弧,
尺寸界线沿径向延伸到弧并越过 ANGLE_EXT_OVERSHOOT,文字放弧内侧。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/test_dim_angle_points.py -v
"""
import math
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from drawing.dim import dim_render, dim_style  # noqa: E402


def _circle(cx, cy, r=5.0):
    return {"type": "circle", "cx": cx, "cy": cy, "r": r}


def _line(x1, y1, x2, y2):
    return {"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2}


def _view():
    return {"x": 0.0, "y": 0.0, "scale": 1.0, "k": 1.0}


def _ann(radius=300.0, kinds=None):
    kinds = kinds or ["center", "center", "center"]
    return {
        "type": "angle", "angleMode": "points",
        "refs": [{"viewId": "v1", "idx": i, "type": "edges", "pointKind": k}
                 for i, k in enumerate(kinds)],
        "radius": radius,
    }


def _quarter_segs():
    """顶点在原点、两个被测点在 +x 与 +y 上(夹角 90°)"""
    return [_circle(0.0, 0.0), _circle(100.0, 0.0), _circle(0.0, 100.0)]


def test_quarter_angle_arc_and_text():
    view = _view()
    prims = dim_render._angle_points(_ann(300.0), _quarter_segs(), [view] * 3)
    assert prims["text"] == "90°"
    arc = prims["arcs"][0]
    # 弧两端各接一段直线延长线(长度 = 配置 arc_ext_px):
    # 起点(300,0)沿切线 +y 向外 → (300,-tail);终点(0,300)沿切线 -x 向外 → (-tail,300)
    tail = dim_style.dim_angle_arc_ext_px()
    assert arc[0] == pytest.approx((300.0, -tail), abs=1e-6)
    assert arc[1] == pytest.approx((300.0, 0.0), abs=1e-6)
    assert arc[-2] == pytest.approx((0.0, 300.0), abs=1e-6)
    assert arc[-1] == pytest.approx((-tail, 300.0), abs=1e-6)
    # 文字落在弧内侧的角平分线上(间距由 dim.angle.text_gap_px 配置)
    tx, ty = prims["texts"][0]["pos"]
    assert math.hypot(tx, ty) == pytest.approx(
        300.0 - dim_style.dim_angle_text_gap_px(), abs=0.01)
    assert tx == pytest.approx(ty, abs=0.01)


def test_angle_config_values_are_applied():
    """dim.angle 配置确实生效:text_gap_px 决定文字半径, arc_ext_px 决定延长线长度"""
    view = _view()
    prims = dim_render._angle_points(_ann(300.0), _quarter_segs(), [view] * 3)
    arc = prims["arcs"][0]
    tail = dim_style.dim_angle_arc_ext_px()
    assert arc[0] == pytest.approx((300.0, -tail), abs=1e-6)
    assert arc[-1] == pytest.approx((-tail, 300.0), abs=1e-6)
    tx, ty = prims["texts"][0]["pos"]
    assert math.hypot(tx, ty) == pytest.approx(
        300.0 - dim_style.dim_angle_text_gap_px(), abs=0.01)


def test_arc_tail_is_collinear_with_arrow_axis():
    """延长线与箭头轴线共线:箭头尾部底中心(两底角中点)落在延长线上,
    保证延长线从尾部底中心穿出(而非从底的一角冒出)"""
    view = _view()
    prims = dim_render._angle_points(_ann(300.0), _quarter_segs(), [view] * 3)
    arc = prims["arcs"][0]
    pairs = ((arc[1], arc[0], prims["arrows"][0]),      # 起点侧:尖端→外延端点
             (arc[-2], arc[-1], prims["arrows"][1]))    # 终点侧
    for tip, tail_pt, arrow in pairs:
        base = ((arrow[1][0] + arrow[2][0]) / 2.0,
                (arrow[1][1] + arrow[2][1]) / 2.0)      # 尾部底中心
        ax, ay = base[0] - tip[0], base[1] - tip[1]
        bx, by = tail_pt[0] - tip[0], tail_pt[1] - tip[1]
        assert abs(ax * by - ay * bx) < 1e-6, (tip, base, tail_pt)


def test_extension_lines_reach_past_arc():
    view = _view()
    prims = dim_render._angle_points(_ann(300.0), _quarter_segs(), [view] * 3)
    line1, line2 = prims["lines"]
    assert line1[0] == pytest.approx((100.0, 0.0))
    assert line1[1] == pytest.approx((330.0, 0.0))
    assert line2[0] == pytest.approx((0.0, 100.0))
    assert line2[1] == pytest.approx((0.0, 330.0))


def test_extension_lines_start_from_arc_when_radius_is_inner():
    view = _view()
    prims = dim_render._angle_points(_ann(50.0), _quarter_segs(), [view] * 3)
    line1 = prims["lines"][0]
    # overshoot 随半径钳制: max(4, min(30, 50*0.15)) = 7.5
    assert line1[0] == pytest.approx((50.0, 0.0))
    assert line1[1] == pytest.approx((107.5, 0.0))


def test_line_point_kind_picks_endpoint():
    view = _view()
    # 斜线 (100,0)→(0,90):start 端点在 +x 上(与 +y 夹角 90°),end 端点在 +y 上(夹角 0°)
    segs = [_circle(0.0, 0.0), _line(100.0, 0.0, 0.0, 90.0), _circle(0.0, 100.0)]
    start_prims = dim_render._angle_points(_ann(300.0, ["center", "start", "center"]), segs, [view] * 3)
    end_prims = dim_render._angle_points(_ann(300.0, ["center", "end", "center"]), segs, [view] * 3)
    assert start_prims["text"] == "90°"
    assert end_prims["text"] == "0°"


def test_straight_angle_is_one_eighty():
    view = _view()
    segs = [_circle(0.0, 0.0), _circle(100.0, 0.0), _circle(-100.0, 0.0)]
    prims = dim_render._angle_points(_ann(300.0), segs, [view] * 3)
    assert prims["text"] == "180°"


def test_missing_point_returns_none():
    view = _view()
    # 既不是圆也不是直线的对象取不到点(如普通折线),几何构建失败
    polyline = {"type": "polyline", "points": [[0.0, 0.0], [10.0, 10.0], [20.0, 5.0]]}
    segs = [_circle(0.0, 0.0), polyline, _circle(0.0, 100.0)]
    assert dim_render._angle_points(_ann(300.0), segs, [view] * 3) is None


def test_build_dim_primitives_dispatches_points_mode():
    view = _view()
    prims = dim_render.build_dim_primitives(_ann(300.0), _quarter_segs(), [view] * 3)
    assert prims is not None
    assert prims["text"] == "90°"
    assert len(prims["lines"]) == 2
    assert prims["arcs"]
