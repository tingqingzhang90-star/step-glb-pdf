# -*- coding: utf-8 -*-
"""断裂后标注几何回归:数值仍是真实 mm,尺寸线连续但跨度变短

坐标出口 _sheet_point 统一走断裂投影;有 mm_coords/spanMm 时数值取真值,
缺元数据时 _fallback_mm 把省略的轴向分量补回去,不会算短。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from drawing.dim import dim_render  # noqa: E402

_SPEC = {"axis": "x", "cutA": 100.0, "cutB": 160.0, "pxPerMm": 0.2,
         "waveAmp": 3, "waveCycles": 3, "visualGap": 6}
_VIEW = {"x": 30, "y": 30, "scale": 0.9, "k": 0.2}


def _seg(with_mm=True):
    meta = {"orientation": "horizontal"}
    if with_mm:
        meta["mm_coords"] = [-137.0, 10.0, 320.5, 10.0]
    return {"type": "line", "x1": 50.0, "y1": 120.0,
            "x2": 220.0, "y2": 120.0, "meta": meta}


def _dim_line_len(prims):
    (p1, p2) = prims["dim_lines"][0]
    return abs(p2[0] - p1[0])


def _render(with_mm=True):
    ann = {"id": "a1", "type": "linear", "mode": "single", "offset": 50}
    plain = dim_render.build_dim_primitives(
        ann, [_seg(with_mm)], [{**_VIEW, "break": None}])
    broken = dim_render.build_dim_primitives(
        ann, [_seg(with_mm)], [{**_VIEW, "break": _SPEC}])
    return plain, broken


def test_true_mm_text_unchanged_after_break():
    plain, broken = _render()
    assert plain["texts"][0]["text"] == "457.5"
    assert broken["texts"][0]["text"] == plain["texts"][0]["text"]


def test_dim_line_is_continuous_but_shorter():
    plain, broken = _render()
    assert len(broken["dim_lines"]) == 1
    assert 0 < _dim_line_len(broken) < _dim_line_len(plain)


def test_fallback_mm_is_restored_when_metadata_missing():
    plain, broken = _render(with_mm=False)
    assert broken["texts"][0]["text"] == plain["texts"][0]["text"]


def test_span_mm_wins_over_projected_geometry():
    ann = {"id": "a1", "type": "linear", "mode": "motor-envelope", "offset": 50,
           "spanMm": 457.5}
    segs = [_seg(), {**_seg(), "x1": 300.0, "x2": 300.0}]
    views = [{**_VIEW, "break": _SPEC}, {**_VIEW, "break": _SPEC}]
    prims = dim_render.build_dim_primitives(ann, segs, views)
    assert prims is not None
    assert prims["texts"][0]["text"] == "457.5"
