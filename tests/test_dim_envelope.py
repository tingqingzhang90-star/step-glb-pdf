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
from drawing.dim import dim_render  # noqa: E402


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


def test_snap_seg_to_view_horizontal_picks_bottom_on_positive_offset():
    seg = {"type": "line", "x1": 100.0, "y1": 0.0, "x2": 100.0, "y2": 400.0,
           "meta": {"orientation": "vertical"}}
    view_segs = [{"type": "line", "x1": 102.0, "y1": 120.0, "x2": 102.0, "y2": 160.0}]
    snapped = dim_rebind._snap_seg_to_view(seg, view_segs, "horizontal", 50)
    # 吸附到 x 最接近的真实边线,并取该边线下端点
    assert snapped["x1"] == snapped["x2"] == 102.0
    assert snapped["y1"] == snapped["y2"] == 160.0


def test_snap_seg_to_view_horizontal_picks_top_on_negative_offset():
    seg = {"type": "line", "x1": 100.0, "y1": 0.0, "x2": 100.0, "y2": 400.0,
           "meta": {"orientation": "vertical"}}
    view_segs = [{"type": "line", "x1": 102.0, "y1": 120.0, "x2": 102.0, "y2": 160.0}]
    snapped = dim_rebind._snap_seg_to_view(seg, view_segs, "horizontal", -50)
    assert snapped["y1"] == snapped["y2"] == 120.0


def test_snap_seg_to_view_keeps_original_when_no_edge_in_range():
    seg = {"type": "line", "x1": 100.0, "y1": 0.0, "x2": 100.0, "y2": 400.0,
           "meta": {"orientation": "vertical"}}
    view_segs = [{"type": "line", "x1": 900.0, "y1": 120.0, "x2": 900.0, "y2": 160.0}]
    snapped = dim_rebind._snap_seg_to_view(seg, view_segs, "horizontal", 50)
    assert snapped["x1"] == 100.0  # 超出吸附阈值,保持原样


def test_snap_threshold_is_measured_in_sheet_coords():
    """阈值 30 是图纸 px:画布距离要乘 view.scale 才能与前端 snapEndpointToViewEdge
    比较。视图缩小(scale<1)时画布阈值放宽,否则会漏吸导致尺寸线位置漂移。"""
    seg = {"type": "line", "x1": 100.0, "y1": 0.0, "x2": 100.0, "y2": 400.0,
           "meta": {"orientation": "vertical"}}
    far = [{"type": "line", "x1": 131.0, "y1": 120.0, "x2": 131.0, "y2": 160.0}]
    # scale=1.0: 31 画布 px = 31 图纸 px > 30 → 不吸
    assert dim_rebind._snap_seg_to_view(
        seg, far, "horizontal", 50, 1.0)["x1"] == 100.0
    # scale=0.93: 31 画布 px = 28.8 图纸 px < 30 → 吸上
    snapped = dim_rebind._snap_seg_to_view(seg, far, "horizontal", 50, 0.93)
    assert snapped["x1"] == snapped["x2"] == 131.0
    assert snapped["y1"] == snapped["y2"] == 160.0


def test_snap_stays_on_joint_face_not_inner_gearbox_edge():
    """接壤面 -137 的贯穿长边被长度判据排除后,减速机内部 -122 的短边
    不得因"更近"被当成端面吸附目标,端线必须留在接壤面。"""
    seg = {"type": "line", "x1": 118.53, "y1": 57.60,
           "x2": 118.53, "y2": 128.44,
           "meta": {"orientation": "vertical",
                    "mm_coords": [-137.0, -435.0, -137.0, -205.0]}}
    view_segs = [
        {"type": "line", "x1": 118.53, "y1": 20.0, "x2": 118.53, "y2": 200.0,
         "meta": {"mm_coords": [-137.0, -558.0, -137.0, 27.0]}},
        {"type": "line", "x1": 123.15, "y1": 72.4, "x2": 123.15, "y2": 127.8,
         "meta": {"mm_coords": [-122.0, -387.0, -122.0, -207.0]}},
    ]
    snapped = dim_rebind._snap_seg_to_view(seg, view_segs, "horizontal", -28.0)
    assert snapped["x1"] == snapped["x2"] == 118.53

    # 同一端面内的毫米级微调仍允许
    view_segs[1]["meta"]["mm_coords"] = [-135.5, -387.0, -135.5, -207.0]
    snapped = dim_rebind._snap_seg_to_view(seg, view_segs, "horizontal", -28.0)
    assert snapped["x1"] == 123.15


def test_snap_distance_and_target_use_first_endpoint():
    """距离与落点都取候选边首个端点(前端 Math.abs(x1 - pt.x)):
    调色板里大量 0.1px 级退化碎片,用中点度量会吸到另一条碎片,基线随之漂移。"""
    seg = {"type": "line", "x1": 100.0, "y1": 0.0, "x2": 100.0, "y2": 400.0,
           "meta": {"orientation": "vertical"}}
    view_segs = [
        # 首端点 x1 更近,但中点更远 → 必须按 x1 判定
        {"type": "line", "x1": 101.0, "y1": 150.0, "x2": 103.0, "y2": 150.0},
        {"type": "line", "x1": 102.0, "y1": 120.0, "x2": 102.0, "y2": 130.0},
    ]
    snapped = dim_rebind._snap_seg_to_view(seg, view_segs, "horizontal", 50)
    assert snapped["x1"] == snapped["x2"] == 101.0   # 落点为候选边 x1
    assert snapped["y1"] == snapped["y2"] == 150.0   # 下端点(max y)


def test_canvas_fn_from_bbox_matches_frontend_face_to_sheet():
    """bbox 变换 = 前端 faceToSheet 的 mm*scale+offset,缺失时返回 None 走兜底"""
    fn = dim_rebind._canvas_fn_from_bbox(
        {"scale": 0.1754, "offset_x": 217.5861, "offset_y": 192.7406})
    assert fn((-898.24, -412.67)) == pytest.approx((60.0348, 120.3583), abs=1e-3)
    assert dim_rebind._canvas_fn_from_bbox(None) is None
    assert dim_rebind._canvas_fn_from_bbox({"offset_x": 1.0}) is None


def test_align_seg_direction_flips_reversed_target():
    """HLR 输出边线端点顺序任意:目标边与基准边反向时必须翻转,
    否则 single 模式的 perp 反号,尺寸线从零件一侧跳到另一侧"""
    base = {"type": "line", "x1": 220.74, "y1": 132.46,
            "x2": 291.89, "y2": 132.46,
            "meta": {"mm_coords": [100.0, 5.0, 200.0, 5.0]}}
    target = {"type": "line", "x1": 288.96, "y1": 128.98,
              "x2": 213.47, "y2": 128.98,
              "meta": {"mm_coords": [200.0, 4.0, 100.0, 4.0]}}
    aligned = dim_rebind._align_seg_direction(base, target)
    assert (aligned["x1"], aligned["y1"]) == (213.47, 128.98)
    assert (aligned["x2"], aligned["y2"]) == (288.96, 128.98)
    assert aligned["meta"]["mm_coords"] == [100.0, 4.0, 200.0, 4.0]


def test_align_seg_direction_keeps_same_direction_target():
    base = {"type": "line", "x1": 0.0, "y1": 0.0, "x2": 10.0, "y2": 0.0}
    target = {"type": "line", "x1": 5.0, "y1": 3.0, "x2": 20.0, "y2": 3.0}
    assert dim_rebind._align_seg_direction(base, target) is target


def test_align_seg_direction_reverses_polyline_points():
    base = {"type": "polyline",
            "points": [[0.0, 0.0], [5.0, 1.0], [10.0, 0.0]]}
    target = {"type": "polyline",
              "points": [[10.0, 3.0], [6.0, 2.0], [1.0, 3.0]]}
    aligned = dim_rebind._align_seg_direction(base, target)
    assert aligned["points"][0] == [1.0, 3.0]
    assert aligned["points"][-1] == [10.0, 3.0]


def test_snap_seg_skips_long_view_outline_edge():
    """连接端面处的贯穿长边不是端面边:吸附它会把尺寸界线拉到视图下方"""
    seg = {"type": "line", "x1": 100.0, "y1": 0.0, "x2": 100.0, "y2": 40.0,
           "meta": {"orientation": "vertical"}}
    view_segs = [
        {"type": "line", "x1": 100.0, "y1": 0.0, "x2": 100.0, "y2": 300.0},
        # 落在下方视图的碎片更近(x=100.5),但端点离包络太远,不能被选中
        {"type": "line", "x1": 100.5, "y1": 200.0, "x2": 100.5, "y2": 210.0},
        {"type": "line", "x1": 101.0, "y1": 12.0, "x2": 101.0, "y2": 30.0},
    ]
    snapped = dim_rebind._snap_seg_to_view(seg, view_segs, "horizontal", 50)
    assert snapped["x1"] == snapped["x2"] == 101.0


def test_snap_seg_vertical_skips_long_view_outline_edge():
    seg = {"type": "line", "x1": 0.0, "y1": 100.0, "x2": 40.0, "y2": 100.0,
           "meta": {"orientation": "horizontal"}}
    view_segs = [
        {"type": "line", "x1": 0.0, "y1": 100.0, "x2": 300.0, "y2": 100.0},
        {"type": "line", "x1": 200.0, "y1": 100.5, "x2": 210.0, "y2": 100.5},
        {"type": "line", "x1": 12.0, "y1": 101.0, "x2": 30.0, "y2": 101.0},
    ]
    snapped = dim_rebind._snap_seg_to_view(seg, view_segs, "vertical", 50)
    assert snapped["y1"] == snapped["y2"] == 101.0


def test_rebind_motor_segs_keep_face_extent():
    """吸附把端面线退化成点后,减速机轮廓范围仍要随 meta 传给渲染端"""
    ann = {"type": "linear", "mode": "motor-envelope", "bind_motor": True,
           "refs": [{"viewId": "view_1", "idx": -1, "type": "edges"}],
           "offset": -20, "spanMm": 200}
    placement = {"source_view": "left", "segs": [], "hidden": [],
                 "bbox": {"scale": 1.0, "offset_x": 0.0, "offset_y": 0.0},
                 "scale": 1.0, "x": 0.0, "y": 0.0, "k": 1.0}
    anchors = _motor_anchors()
    anchors[0]["size"] = [50.0, 20.0, 200.0]
    r = dim_rebind.rebind_annotation(
        ann, [], {}, {"anchors": anchors}, {"view_1": placement}, {})
    assert r["status"] == "motor"
    for seg in r["segs"]:
        extent = seg["meta"]["face_extent"]
        assert extent == sorted((seg["y1"], seg["y2"]))


def test_pdf_motor_envelope_ext_lines_are_symmetric():
    """PDF 两条界线都竖直等长,且止于减速机轮廓远侧边缘"""
    ann = {"type": "linear", "mode": "motor-envelope", "offset": -36.0,
           "spanMm": 457.5}
    meta = {"orientation": "vertical", "face_extent": [67.2, 130.68],
            "mm_coords": [-137.0, -435.0, -137.0, -205.0]}
    segs = [
        dict(type="line", x1=100.0, y1=70.54, x2=100.0, y2=70.54, meta=dict(meta)),
        dict(type="line", x1=200.0, y1=70.54, x2=200.0, y2=70.54, meta=dict(meta)),
    ]
    views = [{"x": 0.0, "y": 0.0, "scale": 1.0}] * 2
    out = dim_render._linear_motor_envelope(ann, segs, views)
    assert out is not None
    lines = out["lines"]
    assert len(lines) == 2
    assert lines[0][0][1] == pytest.approx(130.68)
    assert lines[1][0][1] == pytest.approx(130.68)
    for p1, p2 in lines:
        assert p1[0] == pytest.approx(p2[0])
    assert abs(lines[0][0][1] - lines[0][1][1]) == pytest.approx(
        abs(lines[1][0][1] - lines[1][1][1]), abs=0.01)
