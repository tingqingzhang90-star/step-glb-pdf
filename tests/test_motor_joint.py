# -*- coding: utf-8 -*-
"""电机包络连接端面:候选筛选、轴向裁切与实测包络

减速机输出段会伸进直连盒/连接板,整体 bbox 比外露长度多出这一段。这里锁住
"包络只到连接端面"的判据,避免改回按整个电机零件 bbox 标注。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/test_motor_joint.py -v
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from drawing import anchor_resolver as ar  # noqa: E402
from drawing.dim import dim_envelope  # noqa: E402


def test_pick_joint_face_trims_embedded_side():
    # 直连 D11: 电机 [-898.24, -236.24],直连盒左端面 -341.24 是连接面
    assert ar.pick_joint_face([(-341.24, 50579)], -898.24, -236.24) == (-341.24, "max")


def test_pick_joint_face_handles_reversed_embed_side():
    # 折返: 内嵌段在轴向最小侧,连接板/轴承座都在 -137
    assert ar.pick_joint_face([(-137.0, 108765)], -242.0, 320.5) == (-137.0, "min")


def test_pick_joint_face_prefers_largest_shared_end_face():
    candidates = [(-137.0, 108765), (230.0, 5187)]
    assert ar.pick_joint_face(candidates, -242.0, 320.5) == (-137.0, "min")


def test_pick_joint_face_rejects_middle_small_and_boundary_faces():
    assert ar.pick_joint_face([(200.0, 90000)], 0.0, 400.0) is None
    assert ar.pick_joint_face([(380.0, 100)], 0.0, 400.0) is None
    assert ar.pick_joint_face([(400.0, 90000)], 0.0, 400.0) is None
    assert ar.pick_joint_face([], 0.0, 400.0) is None


def test_trim_bbox_to_joint_only_moves_embedded_axis():
    bbox = ([82.85, 117.97, -898.24], [329.05, 412.67, -236.24])
    bmin, bmax = ar.trim_bbox_to_joint(bbox, 2, (-341.24, "max"))
    assert bmin == bbox[0]
    assert bmax == [329.05, 412.67, -341.24]
    assert ar.trim_bbox_to_joint(bbox, 2, None) == bbox
    assert ar.trim_bbox_to_joint(bbox, 2, (-137.0, "min"))[0][2] == -137.0


def test_resolved_motor_bbox_ends_at_joint_face():
    profile = ar.resolve_anchors("250-E-H2K1-L100-D11")
    by_id = {a["id"]: a for a in profile["anchors"]}
    body = by_id["motor.body"]
    assert body["bbox_max"][2] == pytest.approx(-341.24, abs=0.01)
    assert body["size"][2] == pytest.approx(557.0, abs=0.01)
    assert by_id["motor.axis_max_face"]["point3d"][2] == pytest.approx(-341.24, abs=0.01)


def test_resolved_motor_bbox_trims_min_side_on_foldback():
    # 连接板两端面 -177/-137 都在电机包络内,但只有 -137 与减速机法兰、
    # 轴承座端面共面,才是减速机与安装件的接壤面。-177 只接盒盖,取它会
    # 把整块板厚多算进电机减速机尺寸。
    profile = ar.resolve_anchors("250-F-H2K1-L100-5.5KW电机")
    by_id = {a["id"]: a for a in profile["anchors"]}
    body = by_id["motor.body"]
    assert body["bbox_min"][2] == pytest.approx(-137.0, abs=0.01)
    assert body["size"][2] == pytest.approx(457.5, abs=0.01)
    assert by_id["motor.axis_min_face"]["point3d"][2] == pytest.approx(-137.0, abs=0.01)


def test_envelope_faces_span_matches_exposed_length():
    anchors = ar.resolve_anchors("250-E-H2K1-L100-D11")["anchors"]
    left = dim_envelope.envelope_faces(anchors, "left")
    assert left["orientation"] == "horizontal"
    assert left["face_max"][0][0] == pytest.approx(-341.24, abs=0.01)
    assert left["span_mm"] == pytest.approx(557.0, abs=0.01)

    top = dim_envelope.envelope_faces(anchors, "top")
    assert top["orientation"] == "vertical"
    assert top["face_max"][0][1] == pytest.approx(-341.24, abs=0.01)
    assert top["span_mm"] == pytest.approx(557.0, abs=0.01)


@pytest.mark.parametrize("code,joint_z,span,side", [
    ("250-E-H2K1-L100-D11", -341.24, 557.0, "max"),
    ("250-E-H2K1-L100-D55", -341.24, 457.5, "max"),
    ("250-F-H2K1-L100-5.5KW电机", -137.0, 457.5, "min"),
])
def test_left_envelope_ends_at_joint_for_each_mount(code, joint_z, span, side):
    anchors = ar.resolve_anchors(code)["anchors"]
    faces = dim_envelope.envelope_faces(anchors, "left")
    face = faces["face_max"] if side == "max" else faces["face_min"]
    assert face[0][0] == pytest.approx(joint_z, abs=0.01)
    assert faces["span_mm"] == pytest.approx(span, abs=0.01)


def test_rule_template_envelope_value_matches_exposed_length():
    from drawing.rule_template import drawing_template as dt

    profile = ar.resolve_anchors("250-E-H2K1-L100-D11")
    anchor_map = {a["id"]: a for a in profile["anchors"]}
    dim_def = {"id": "dim_motor_length_top", "type": "linear_envelope",
               "view": "top", "text": "电机减速机尺寸", "show_value": True,
               "offset": 25}
    r = dt._envelope_dimension(dim_def, anchor_map, {"has_motor": True},
                               lambda x, y: [x, y])
    assert r["value"] == pytest.approx(557.0, abs=0.01)
    assert r["text"] == "557 (电机减速机尺寸)"


def _motor_ann(mode="motor-envelope"):
    return {"type": "linear", "mode": mode, "bind_motor": True,
            "refs": [{"viewId": "view_1", "idx": -1, "type": "edges"}],
            "offset": 50, "spanMm": 662}


def _placement():
    return {"source_view": "left", "segs": [], "hidden": [], "k": 1.0,
            "scale": 1.0, "bbox": {"scale": 1.0, "offset_x": 0.0, "offset_y": 0.0}}


def test_rebind_motor_envelope_returns_exposed_span():
    from drawing.dim import dim_rebind

    profile = ar.resolve_anchors("250-E-H2K1-L100-D11")
    r = dim_rebind.rebind_annotation(
        _motor_ann(), [], {}, profile, {"view_1": _placement()}, {})
    assert r["status"] == "motor"
    assert r["span_mm"] == pytest.approx(557.0, abs=0.01)
    assert r["segs"][1]["meta"]["mm_coords"][0] == pytest.approx(-341.24, abs=0.01)


def test_rebind_single_mode_keeps_its_own_value():
    from drawing.dim import dim_rebind

    profile = ar.resolve_anchors("250-E-H2K1-L100-D11")
    r = dim_rebind.rebind_annotation(
        _motor_ann("single"), [], {}, profile, {"view_1": _placement()}, {})
    assert r["status"] == "motor"
    assert "span_mm" not in r
