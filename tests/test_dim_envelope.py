# -*- coding: utf-8 -*-
"""电机/减速机包络投影与后端吸附测试

用伪造 anchors 驱动,不依赖 pythonOCC 与真实模型文件。
覆盖:envelope_faces 端面方向判定、gearbox 包络按 body_id 取、
_snap_seg_to_view 把 bbox 长端面线吸到视图真实边线端点。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/test_dim_envelope.py -v
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from drawing.dim import dim_envelope  # noqa: E402
from drawing.dim import dim_rebind  # noqa: E402


def _motor_anchors(prefix="motor", z_min=100.0, z_max=300.0):
    """构造 left 视图下轴向水平的包络锚点(point2d 直接给定投影坐标)"""
    return [
        {"id": f"{prefix}.body",
         "bbox_min": [0.0, 10.0, z_min], "bbox_max": [50.0, 30.0, z_max]},
        {"id": f"{prefix}.axis_min_face", "point2d": [z_min, 10.0]},
        {"id": f"{prefix}.axis_max_face", "point2d": [z_max, 30.0]},
    ]


def test_envelope_faces_horizontal_orientation():
    faces = dim_envelope.envelope_faces(_motor_anchors(), "left")
    assert faces is not None
    assert faces["orientation"] == "horizontal"
    # 端面线是竖直线段: x 固定, y 取包络轮廓范围(投影后 y 取反,符合 SVG 坐标系)
    assert faces["face_min"] == ((100.0, -30.0), (100.0, -10.0))
    assert faces["face_max"] == ((300.0, -30.0), (300.0, -10.0))
    assert faces["span_mm"] == pytest.approx(201.0, abs=0.5)


def test_gearbox_envelope_uses_gearbox_body():
    anchors = _motor_anchors("gearbox", z_min=150.0, z_max=260.0)
    faces = dim_envelope.gearbox_envelope_faces(anchors, "left")
    assert faces is not None
    assert faces["face_min"] == ((150.0, -30.0), (150.0, -10.0))
    assert faces["span_mm"] == pytest.approx(111.8, abs=0.5)


def test_envelope_faces_returns_none_when_body_missing():
    assert dim_envelope.envelope_faces([], "left") is None


def test_snap_seg_to_view_horizontal_uses_real_edge_span():
    """吸附后端面线应取真实边线的完整范围,而不是 bbox 极值"""
    seg = {"type": "line", "x1": 100.0, "y1": 0.0, "x2": 100.0, "y2": 400.0,
           "meta": {"orientation": "vertical"}}
    view_segs = [{"type": "line", "x1": 102.0, "y1": 120.0, "x2": 102.0, "y2": 160.0}]
    snapped = dim_rebind._snap_seg_to_view(seg, view_segs, "horizontal", 50)
    # 端面线 x 定位到候选边线平均 x, y 范围取候选边线真实端点的极值
    assert snapped["x1"] == snapped["x2"] == 102.0
    assert snapped["y1"] == 120.0
    assert snapped["y2"] == 160.0
    assert snapped["meta"]["orientation"] == "vertical"
    assert snapped["meta"]["length"] == 40.0


def test_snap_seg_to_view_horizontal_collects_multiple_edges():
    """端面附近多条边线时,范围取所有边线端点的极值"""
    seg = {"type": "line", "x1": 100.0, "y1": 0.0, "x2": 100.0, "y2": 400.0,
           "meta": {"orientation": "vertical"}}
    view_segs = [
        {"type": "line", "x1": 102.0, "y1": 120.0, "x2": 102.0, "y2": 160.0},
        {"type": "line", "x1": 104.0, "y1": 155.0, "x2": 104.0, "y2": 190.0},
    ]
    snapped = dim_rebind._snap_seg_to_view(seg, view_segs, "horizontal", 50)
    assert snapped["x1"] == snapped["x2"]
    assert snapped["y1"] == 120.0
    assert snapped["y2"] == 190.0
    assert snapped["meta"]["length"] == 70.0


def test_snap_seg_to_view_keeps_original_when_no_edge_in_range():
    seg = {"type": "line", "x1": 100.0, "y1": 0.0, "x2": 100.0, "y2": 400.0,
           "meta": {"orientation": "vertical"}}
    view_segs = [{"type": "line", "x1": 900.0, "y1": 120.0, "x2": 900.0, "y2": 160.0}]
    snapped = dim_rebind._snap_seg_to_view(seg, view_segs, "horizontal", 50)
    assert snapped["x1"] == 100.0  # 超出吸附阈值,保持原样
