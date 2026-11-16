# -*- coding: utf-8 -*-
"""视图方向换算测试

轴向补偿不再靠视图名枚举:所有标准视图从投影方向自动推导,新增视图
天然覆盖;未知视图与轴测视图必须显式失败,不能静默跳过补偿。
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from drawing.view_axes import (VIEW_DIRECTIONS, axial_projection,  # noqa: E402
                               view_screen_axes)


@pytest.mark.parametrize("name,expected", [
    ("left", ("x", 1.0)),
    ("right", ("x", -1.0)),
    ("top", ("y", 1.0)),
    ("bottom", ("y", -1.0)),
    ("left_top", ("x", 1.0)),
])
def test_axial_projection(name, expected):
    assert axial_projection(name) == expected


@pytest.mark.parametrize("name", ["front", "back"])
def test_axial_perpendicular_to_view(name):
    """Z 垂直投影面时拉伸不改变 2D 位置,合法地无需补偿"""
    assert axial_projection(name) is None


def test_unknown_view_fails_loud():
    with pytest.raises(ValueError, match="未定义视图投影方向"):
        axial_projection("some_new_view")


@pytest.mark.parametrize("name", ["isometric", "dimetric_left", "dimetric_right"])
def test_oblique_view_fails_loud(name):
    """轴测视图的 Z 是斜投影,单轴补偿无法表达,必须报失配而不是静默跳过"""
    with pytest.raises(ValueError, match="斜投影"):
        axial_projection(name)


def test_screen_axes_match_occ_ax2():
    """纯 Python 推导必须与 HLR 实际用的 gp_Ax2 完全一致"""
    from OCC.Core.gp import gp_Ax2, gp_Dir, gp_Pnt

    for name, cfg in VIEW_DIRECTIONS.items():
        d = gp_Dir(*cfg["dir"])
        u = gp_Dir(*cfg["up"])
        x_dir = gp_Dir(
            d.Y() * u.Z() - d.Z() * u.Y(),
            d.Z() * u.X() - d.X() * u.Z(),
            d.X() * u.Y() - d.Y() * u.X())
        ax2 = gp_Ax2(gp_Pnt(0, 0, 0), d, x_dir)
        px, py = view_screen_axes(name)
        X, Y = ax2.XDirection(), ax2.YDirection()
        for got, exp in zip(px, (X.X(), X.Y(), X.Z())):
            assert abs(got - exp) < 1e-6, name
        for got, exp in zip(py, (Y.X(), Y.Y(), Y.Z())):
            assert abs(got - exp) < 1e-6, name


def test_standard_view_configs_use_single_source():
    """投影引擎的方向不得再维护第二份"""
    from core.drawing_engine import STANDARD_VIEW_CONFIGS

    assert set(STANDARD_VIEW_CONFIGS) == set(VIEW_DIRECTIONS)
    for name, cfg in STANDARD_VIEW_CONFIGS.items():
        d = cfg["dir"]
        u = cfg["up"]
        for got, exp in zip((d.X(), d.Y(), d.Z()),
                            VIEW_DIRECTIONS[name]["dir"]):
            assert abs(got - exp / (sum(c * c for c in VIEW_DIRECTIONS[name]["dir"]) ** 0.5)) < 1e-6
        for got, exp in zip((u.X(), u.Y(), u.Z()),
                            VIEW_DIRECTIONS[name]["up"]):
            assert abs(got - exp / (sum(c * c for c in VIEW_DIRECTIONS[name]["up"]) ** 0.5)) < 1e-6


def test_anchor_projection_covers_left_top():
    """left_top 的锚点必须按 +Z 投影,不能退化为 X-Y 平面"""
    from drawing.rule_template.drawing_template import _anchor_to_2d_point

    p = _anchor_to_2d_point({"point3d": [10.0, 20.0, 300.0]}, "left_top")
    assert p == [300.0, 10.0]
