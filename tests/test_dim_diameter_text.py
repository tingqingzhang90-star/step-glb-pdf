# -*- coding: utf-8 -*-
"""直径标注文字沿直径线滑动(textSlide)的几何测试

编辑器 core.buildDiameterGeometry 与导出 _diameter 必须同公式:
text_pos = leader_end - dir * (20 - textSlide) + perp * 4,
否则拖过文字的标注导出后位置会跳回原位。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/test_dim_diameter_text.py -v
"""
import math
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from drawing.dim import dim_render  # noqa: E402


def _circle_seg(r=20.0, cx=0.0, cy=0.0):
    return {"type": "circle", "cx": cx, "cy": cy, "r": r, "meta": {"radius": 11.0}}


def _view(scale=0.6):
    return {"x": 100.0, "y": 50.0, "scale": scale, "k": 1.0}


def _text_pos(ann, seg=None, view=None):
    prims = dim_render._diameter(ann, seg or _circle_seg(), view or _view())
    return prims["texts"][0]["pos"]


def test_text_sits_20_inward_of_leader_end():
    ann = {"leaderAngle": 0.0, "leaderLength": 30}
    prims = dim_render._diameter(ann, _circle_seg(), _view())
    leader_end_x = 100.0 + 20.0 * 0.6 + 30
    assert prims["texts"][0]["pos"][0] == pytest.approx(leader_end_x - 20, abs=0.01)


def test_slide_moves_text_towards_arrow():
    seg, view = _circle_seg(), _view()
    base = _text_pos({"leaderAngle": 0.0}, seg, view)
    slid = _text_pos({"leaderAngle": 0.0, "textSlide": 12.0}, seg, view)
    assert slid[0] - base[0] == pytest.approx(12.0, abs=0.01)
    assert slid[1] == pytest.approx(base[1], abs=0.01)   # 法向偏移不随 slide 变


def test_slide_follows_leader_angle():
    seg, view = _circle_seg(), _view()
    angle = -math.pi / 4
    base = _text_pos({"leaderAngle": angle}, seg, view)
    slid = _text_pos({"leaderAngle": angle, "textSlide": 10.0}, seg, view)
    dx, dy = slid[0] - base[0], slid[1] - base[1]
    assert math.hypot(dx, dy) == pytest.approx(10.0, abs=0.01)
    assert dx == pytest.approx(10.0 * math.cos(angle), abs=0.01)
    assert dy == pytest.approx(10.0 * math.sin(angle), abs=0.01)


def test_slide_accepts_negative_and_missing():
    seg, view = _circle_seg(), _view()
    base = _text_pos({"leaderAngle": 0.0}, seg, view)
    assert _text_pos({"leaderAngle": 0.0, "textSlide": 0}, seg, view) == pytest.approx(base)
    back = _text_pos({"leaderAngle": 0.0, "textSlide": -15.0}, seg, view)
    assert back[0] - base[0] == pytest.approx(-15.0, abs=0.01)
