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

from drawing.dim import dim_render, dim_style  # noqa: E402


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


def test_leader_custom_text_and_underline_width():
    """引线直径:自定义全文(如 "12x ø13.5 贯穿")生效,
    水平搁置线长度按 PDF 实测字宽(pdfmetrics)+ 字号等比余量,
    间距也按字号等比(固定 4 图纸单位在 PDF 里会大近一倍,文字悬空)"""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    dim_render._ensure_font()
    font_mm = dim_style.dim_text_font_mm()
    pt2u = 25.4 / 72.0
    em = font_mm * pt2u

    def underline_w(s):
        return (stringWidth(s, dim_render._CN_FONT, font_mm) * pt2u
                + em * (4.0 / 18.0))

    seg, view = _circle_seg(), _view()
    # 弯折点 = 文字线右端,引线角度取弯折点指向圆心,保证与圆相交
    full = "12x ø13.5 贯穿"
    bend_x = 200.0 + underline_w(full)
    angle = math.atan2(50.0 - 304.0, 100.0 - bend_x)
    ann = {"diameterMode": "leader", "leaderAngle": angle,
           "textLeft": {"x": 200.0, "y": 300.0},
           "customText": full}
    prims = dim_render._diameter_leader(ann, seg, view)
    assert prims["text"] == full
    line_start, line_end = prims["dim_lines"][0]
    assert line_end[0] - line_start[0] == pytest.approx(underline_w(full), abs=0.01)
    # 搁置线水平,且与文字基线的间距 = 字号等比(4/18 em,贴线)
    assert line_end[1] == pytest.approx(line_start[1], abs=1e-9)
    assert line_start[1] == pytest.approx(300.0 + em * (4.0 / 18.0), abs=1e-6)
    assert prims["texts"][0]["anchor"] == "start"
    # 箭头:尖端触圆周指向圆心,箭身在引线外侧(距圆心比尖端远)
    apex, a1, a2 = prims["arrows"][0]

    def _dc(p):
        return (p[0] - 100.0) ** 2 + (p[1] - 50.0) ** 2

    assert _dc(apex) < _dc(a1) and _dc(apex) < _dc(a2)
    assert math.isqrt(round(_dc(apex))) ** 2 == pytest.approx(_dc(apex), abs=1.0)
    # 无自定义文字时退回 ø 测量值(弯折点/角度与实现同式推导,保证引线命中圆)
    dia_text = f"ø{dim_render.format_mm(22.0)}"
    base = dim_render._diameter_leader(
        {"diameterMode": "leader",
         "leaderAngle": math.atan2(50.0 - 304.0,
                                   100.0 - (200.0 + underline_w(dia_text))),
         "textLeft": {"x": 200.0, "y": 300.0}}, seg, view)
    assert base["text"].startswith("ø")
