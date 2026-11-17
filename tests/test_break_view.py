# -*- coding: utf-8 -*-
"""断裂几何纯函数回归:投影、波浪线、边线数组契约与前后端对拍数据

断裂带内的边线由 clip_ranges 双段裁剪处理,标注端点则钳到切口;
两者共用同一个 BreakSpec,不改变 edges 数组与 meta.mm_coords。
"""
import copy
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from drawing import break_view as bv  # noqa: E402

with open(os.path.join(_ROOT, "tests", "fixtures",
                       "break_view_cases.json"), encoding="utf-8") as _f:
    _CASES = json.load(_f)


def _spec(index):
    return bv.from_dict(_CASES["specs"][index])


def test_from_dict_roundtrip():
    spec = _spec(0)
    assert bv.from_dict(bv.to_dict(spec)) == spec
    assert spec.shift == 54.0
    assert spec.right_cut == 106.0


def test_from_dict_rejects_invalid():
    assert bv.from_dict(None) is None
    assert bv.from_dict({"axis": "z", "cutA": 1, "cutB": 2, "pxPerMm": 1}) is None
    assert bv.from_dict({"axis": "x", "cutA": 100, "cutB": 104,
                         "pxPerMm": 1, "visualGap": 6}) is None
    assert bv.from_dict({"axis": "x", "cutA": "x", "cutB": 2,
                         "pxPerMm": 1}) is None


def test_parity_project_and_clip():
    for case in _CASES["project"]:
        spec = _spec(case["spec"])
        got = bv.project_coord(case["value"], spec)
        if case["projected"] is None:
            assert got is None
        else:
            assert got == pytest.approx(case["projected"])
        assert bv.clamp_coord(case["value"], spec) == pytest.approx(case["clamped"])
    for case in _CASES["points"]:
        got = bv.project_point(*case["point"], _spec(case["spec"]))
        assert list(got) == pytest.approx(case["expected"])
    for case in _CASES["clip"]:
        got = bv.clip_ranges(_spec(case["spec"]), case["canvas"])
        for row, expected in zip(got, case["expected"]):
            assert list(row) == pytest.approx(expected)
    assert bv.clip_ranges(None, 400) == [(0.0, 400.0, 0.0)]


def test_parity_waves():
    for case in _CASES["waves"]:
        left, right = bv.wave_points(_spec(case["spec"]),
                                     case["crossLo"], case["crossHi"])
        for n, i in enumerate(case["sample"]):
            assert list(left[i]) == pytest.approx(case["left"][n], abs=1e-3)
            assert list(right[i]) == pytest.approx(case["right"][n], abs=1e-3)
    assert bv.wave_points(None, 0, 10) == ([], [])
    assert bv.wave_points(_spec(0), 10, 10) == ([], [])


def test_parity_build_spec():
    for case in _CASES["build"]:
        spec = bv.build_spec(case["axis"], case["lo"], case["hi"],
                             case["omitMm"], case["k"], case["waveAmp"],
                             case["waveCycles"], case["visualGap"])
        assert spec.cut_a == pytest.approx(case["cutA"])
        assert spec.cut_b == pytest.approx(case["cutB"])
        assert bv.from_dict(bv.to_dict(spec)) == spec


def test_choose_break_band_clamps_to_content():
    assert bv.choose_break_band(0, 10, 300, 1.0, 6.0) is None
    band = bv.choose_break_band(0, 100, 300, 1.0, 6.0)
    assert 0 <= band[0] < band[1] <= 100
    assert bv.choose_break_band(0, 100, 0, 1.0, 6.0) is None
    # 省略量小于视觉间隙时 build_spec 直接拒绝,避免画出看不出的断裂
    assert bv.build_spec("x", 0, 20, 1.0, 1.0, visual_gap=6.0) is None


def test_projection_never_touches_edges_or_mm_truth():
    edges = [
        {"type": "line", "x1": 50.0, "y1": 10.0, "x2": 220.0, "y2": 10.0,
         "meta": {"mm_coords": [-137.0, 10.0, 320.5, 10.0]}},
        {"type": "circle", "cx": 120.0, "cy": 20.0, "r": 12.0,
         "meta": {"radius": 24.0, "center_mm": [0.0, 0.0]}},
    ]
    before = copy.deepcopy(edges)
    spec = _spec(0)
    for seg in edges:
        for key in ("x1", "x2", "cx"):
            if key in seg:
                bv.clamp_coord(seg[key], spec)
    assert edges == before
    assert edges[0]["meta"]["mm_coords"] == [-137.0, 10.0, 320.5, 10.0]
    assert len(edges) == 2
