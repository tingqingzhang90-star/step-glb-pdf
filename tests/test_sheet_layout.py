# -*- coding: utf-8 -*-
"""图纸布局求解回归:不越界、间距下限、对齐保持、阈值与 A0~A4

断裂触发只依赖缩放比与配置阈值;求解过程不写回 views,边线数组与
标注 refs.idx 由 batch_drawing 保持原样,本文件只锁定布局输出。
"""
import copy
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from drawing import break_view as bv  # noqa: E402
from drawing import sheet_layout as sl  # noqa: E402

_SHEETS = {
    "A0": (1189, 841), "A1": (841, 594), "A2": (594, 420),
    "A3": (420, 297), "A4": (297, 210),
}
_NO_BREAK = {"min_readable_scale": 0.01}
_TEST_CFG = {**_NO_BREAK, "margin": 20.0, "min_gap": 12.0,
             "reserved_bottom": 55.0, "break_omit_mm": 400.0,
             "break_visual_gap": 6.0}


def _views(long_width=380.0):
    """模拟真实模板:front 端视图一列,left/left_top 两个轴向长视图一列"""
    def cb(x, width):
        return {"x": x, "y": 120.0, "width": width, "height": 60.0}
    return [
        {"id": "view_1", "source_view": "left", "x": 65, "y": -68,
         "contentBBox": cb(60, long_width), "bbox": {"scale": 0.17}},
        {"id": "view_2", "source_view": "front", "x": -112, "y": -68,
         "contentBBox": cb(170, 60), "bbox": {"scale": 0.17}},
        {"id": "view_3", "source_view": "left_top", "x": 65, "y": -15,
         "contentBBox": cb(60, long_width), "bbox": {"scale": 0.17}},
    ]


def _rects(views, result):
    out = {}
    for v in views:
        p = result[v["id"]]
        cb = v["contentBBox"]
        spec = bv.from_dict(p["break"])
        shift = spec.shift if spec else 0.0
        w = cb["width"] - (shift if spec and spec.axis == "x" else 0)
        h = cb["height"] - (shift if spec and spec.axis == "y" else 0)
        out[v["id"]] = {
            "x": p["x"] + cb["x"] * p["scale"],
            "y": p["y"] + cb["y"] * p["scale"],
            "w": w * p["scale"], "h": h * p["scale"],
        }
    return out


def _assert_inside(views, result, width, height, cfg):
    tol = 0.02  # x/y 落盘取整到 3 位、scale 到 5 位带来的反推误差
    for rid, r in _rects(views, result).items():
        assert r["x"] >= cfg["margin"] - tol, f"{rid} 左边越界"
        assert r["y"] >= cfg["margin"] - tol, f"{rid} 上边越界"
        assert r["x"] + r["w"] <= width - cfg["margin"] + tol, f"{rid} 右边越界"
        assert r["y"] + r["h"] <= height - cfg["margin"] - cfg["reserved_bottom"] + tol, \
            f"{rid} 下边压到标题栏"


@pytest.mark.parametrize("name,dims", list(_SHEETS.items()))
def test_all_sheet_sizes_keep_views_inside_frame(name, dims):
    views = _views(long_width=900.0)
    sheet = {"size": name, "width": dims[0], "height": dims[1]}
    result = sl.solve_layout(sheet, views, _TEST_CFG)
    assert set(result) == {"view_1", "view_2", "view_3"}
    _assert_inside(views, result, dims[0], dims[1], _TEST_CFG)


def test_min_gap_and_alignment_groups_kept():
    views = _views()
    result = sl.solve_layout({"width": 420, "height": 297}, views, _TEST_CFG)
    rects = _rects(views, result)
    # 同列:内容左边界严格对齐
    assert rects["view_1"]["x"] == pytest.approx(rects["view_3"]["x"])
    # 同行:内容上边界严格对齐
    assert rects["view_1"]["y"] == pytest.approx(rects["view_2"]["y"])
    # 同列两行间距不低于下限
    vertical_gap = rects["view_3"]["y"] - rects["view_1"]["y"] - rects["view_1"]["h"]
    assert vertical_gap >= _TEST_CFG["min_gap"] - 0.02
    # 两列间距不低于下限
    horizontal_gap = rects["view_1"]["x"] - rects["view_2"]["x"] - rects["view_2"]["w"]
    assert horizontal_gap >= _TEST_CFG["min_gap"] - 0.02


def test_break_triggers_below_readable_threshold():
    views = _views(long_width=1200.0)
    cfg = {**_TEST_CFG, "min_readable_scale": 0.75}
    sheet = {"width": 420, "height": 297}
    plain = sl.solve_layout(sheet, views, _NO_BREAK)
    broken = sl.solve_layout(sheet, views, cfg)
    assert all(p["break"] is None for p in plain.values())
    assert broken["view_1"]["break"] is not None
    assert broken["view_2"]["break"] is None  # front 端视图保持完整
    assert broken["view_1"]["break"]["axis"] == "x"
    assert broken["view_1"]["scale"] > plain["view_1"]["scale"]
    _assert_inside(views, broken, 420, 297, cfg)


def test_low_threshold_disables_break_as_soft_switch():
    views = _views(long_width=1200.0)
    result = sl.solve_layout({"width": 297, "height": 210}, views, _NO_BREAK)
    assert all(p["break"] is None for p in result.values())


def test_break_band_stays_inside_long_view_content():
    views = _views(long_width=1200.0)
    result = sl.solve_layout({"width": 420, "height": 297}, views,
                             {**_TEST_CFG, "min_readable_scale": 0.75})
    spec = bv.from_dict(result["view_1"]["break"])
    cb = views[0]["contentBBox"]
    assert cb["x"] < spec.cut_a < spec.cut_b < cb["x"] + cb["width"]
    assert spec.px_per_mm == pytest.approx(0.17)
    assert spec.shift > 0


def test_solve_layout_does_not_mutate_views_or_edge_contract():
    views = _views()
    before = copy.deepcopy(views)
    sl.solve_layout({"width": 420, "height": 297}, views, _TEST_CFG)
    assert views == before


def test_load_cfg_reads_env_override(monkeypatch):
    monkeypatch.setenv("DRAWING_VIEW_MIN_GAP_MM", "25")
    cfg = sl.load_cfg()
    assert cfg["min_gap"] == 25.0
    assert cfg["break_wave_cycles"] >= 1


def test_empty_views_returns_empty():
    assert sl.solve_layout({"width": 420, "height": 297}, [], _TEST_CFG) == {}
