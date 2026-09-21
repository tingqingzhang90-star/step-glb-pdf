# -*- coding: utf-8 -*-
"""孔组中心标记(分度圆 + 各孔径向/切向十字)几何测试

与前端 core.js buildCenterMarkGroupGeometry 同公式:分度圆圆心取各孔心均值、
半径取平均距离;每孔十字的一条线沿"中心→孔心"、另一条是其垂线,
故 center_marks 的 angle 即该孔方位角。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/test_dim_center_mark_group.py -v
"""
import math
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from drawing.dim import dim_render  # noqa: E402


def _circle(cx, cy, r=6.0):
    return {"type": "circle", "cx": cx, "cy": cy, "r": r}


def _view(scale=1.0):
    return {"x": 0.0, "y": 0.0, "scale": scale, "k": 1.0}


def _bolt_points(count=12, radius=100.0):
    return [(radius * math.cos(2 * math.pi * i / count),
             radius * math.sin(2 * math.pi * i / count)) for i in range(count)]


def test_pitch_circle_and_radial_marks():
    pts = _bolt_points()
    segs = [_circle(x, y) for x, y in pts]
    prims = dim_render._center_mark_group(segs, [_view()] * len(pts))
    assert prims is not None
    pitch = prims["dashed_circles"][0]
    assert pitch["x"] == pytest.approx(0.0, abs=1e-6)
    assert pitch["y"] == pytest.approx(0.0, abs=1e-6)
    assert pitch["r"] == pytest.approx(100.0, abs=1e-6)
    assert len(prims["center_marks"]) == len(pts)
    for (x, y), mark in zip(pts, prims["center_marks"]):
        assert mark["pos"] == pytest.approx((x, y))
        # 十字方向 = 该孔相对分度圆圆心的方位角(径向),垂线由渲染侧跟着转
        assert mark["angle"] == pytest.approx(math.atan2(y, x))
        assert mark["r"] == pytest.approx(6.0 * dim_render.BOLT_MARK_SCALE)


def test_mark_length_follows_view_scale():
    segs = [_circle(x, y) for x, y in _bolt_points(4)]
    prims = dim_render._center_mark_group(segs, [_view(scale=2.0)] * 4)
    assert prims["center_marks"][0]["r"] == pytest.approx(6.0 * 2.0 * dim_render.BOLT_MARK_SCALE)


def test_fewer_than_three_holes_returns_none():
    segs = [_circle(0.0, 100.0), _circle(0.0, -100.0)]
    assert dim_render._center_mark_group(segs, [_view()] * 2) is None


def test_non_circle_hole_returns_none():
    line = {"type": "line", "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}
    segs = [_circle(0.0, 100.0), line, _circle(0.0, -100.0)]
    assert dim_render._center_mark_group(segs, [_view()] * 3) is None


def test_concentric_holes_have_no_pitch_circle():
    segs = [_circle(0.0, 0.0, 6.0), _circle(0.0, 0.0, 8.0), _circle(0.0, 0.0, 10.0)]
    prims = dim_render._center_mark_group(segs, [_view()] * 3)
    assert prims["dashed_circles"] == []


def test_build_dim_primitives_dispatches_group_mode():
    pts = _bolt_points(6, 80.0)
    prims = dim_render.build_dim_primitives(
        {"type": "center-mark", "group": True},
        [_circle(x, y) for x, y in pts], [_view()] * 6)
    assert prims is not None
    assert prims["dashed_circles"]
    assert len(prims["center_marks"]) == 6


def test_single_center_mark_unchanged():
    prims = dim_render.build_dim_primitives(
        {"type": "center-mark"}, [_circle(10.0, 20.0)], [_view()])
    assert prims["center_marks"][0]["angle"] is None
    assert "dashed_circles" not in prims


def test_group_center_draws_single_cross_at_pitch_center():
    """把分度圆当"一个孔"做单孔中心标记:只在圆心画一个水平/竖直十字"""
    pts = _bolt_points()
    prims = dim_render._center_mark_group(
        [_circle(x, y) for x, y in pts], [_view()] * len(pts), only_center=True)
    assert prims is not None
    assert "dashed_circles" not in prims
    assert len(prims["center_marks"]) == 1
    mark = prims["center_marks"][0]
    assert mark["pos"] == pytest.approx((0.0, 0.0))
    assert mark["r"] == pytest.approx(100.0)      # 臂长 = 分度圆半径
    assert mark["angle"] is None                  # 水平/竖直


def test_build_dim_primitives_dispatches_group_center():
    pts = _bolt_points(6, 80.0)
    prims = dim_render.build_dim_primitives(
        {"type": "center-mark", "groupCenter": True},
        [_circle(x, y) for x, y in pts], [_view()] * 6)
    assert len(prims["center_marks"]) == 1
    assert "dashed_circles" not in prims
