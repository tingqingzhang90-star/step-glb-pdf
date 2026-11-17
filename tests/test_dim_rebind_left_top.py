# -*- coding: utf-8 -*-
"""轴向补偿与源文件落盘防御测试

left_top(左视上视)漏登记轴向映射时,该视图标注不做轴向补偿:行程拉伸
后缸体区孔位偏移超过 POS_TOL,重绑失配;落盘端又把失配标注按模板旧下标
写出,前端按目标边表渲染成斜穿视图的乱线(实测 492 孔距变 672.6)。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/ -q
"""
import json
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from batch import batch_drawing
from drawing.dim import dim_rebind


def _ctx_l100_to_l120():
    """真实行程补偿参数: D1 440 → 460(L100 → L120)"""
    return {"back": 0.0, "front": 440.0, "scale": 460.0 / 440.0, "delta": 20.0}


def _circle(cx, cy, r):
    return {"type": "circle", "cx": 0.0, "cy": 0.0, "r": 0.0,
            "meta": {"radius": r, "center_mm": [cx, cy]}}


def test_axial_projection_covers_left_top():
    """从投影方向推导,而不是靠字典里登记视图名"""
    from drawing.view_axes import axial_projection

    assert axial_projection("left_top") == ("x", 1.0)


def test_match_edge_fails_loud_on_unknown_view():
    """未知视图名不再静默跳过补偿"""
    seg, reason, idx = dim_rebind.match_edge(
        _circle(465.0, -150.0, 11.0), "some_new_view",
        _ctx_l100_to_l120(), [_circle(485.0, -150.0, 11.0)])
    assert seg is None and idx is None
    assert "未定义视图投影方向" in reason


def test_rebind_rejects_diagonal_ref_pair():
    """两条 ref 各自匹配成功但整体方向歪掉时,整条标注判失配"""
    base_refs = [
        {"ref": {"viewId": "view_1", "idx": 0, "type": "edges"},
         "seg": _circle(0.0, 0.0, 11.0)},
        {"ref": {"viewId": "view_1", "idx": 1, "type": "edges"},
         "seg": _circle(8.0, 0.0, 11.0)},
    ]
    target = [_circle(0.0, 0.0, 11.0), _circle(8.0, 4.0, 11.0)]
    placements = {"view_1": _placement(target)}
    result = dim_rebind.rebind_annotation(
        {"id": "a1", "type": "linear", "mode": "center"}, base_refs,
        {"back": 0.0, "front": 440.0, "scale": 1.0, "delta": 0.0},
        {"anchors": []}, placements, {})
    assert result["status"] == "unmatched"
    assert "相对方向" in result["reason"]


def test_match_edge_compensates_left_top_axial_shift():
    """L100→L120 后右法兰孔 465→485,left_top 视图必须补偿后命中"""
    base = _circle(465.0, -150.0, 11.0)
    target_segs = [
        _circle(-27.0, -150.0, 11.0),   # 左法兰孔,拉伸不动区
        _circle(485.0, 150.0, 11.0),    # 同法兰另一排孔,y 不同
        _circle(485.0, -150.0, 11.0),   # 拉伸后的右法兰孔
        _circle(-157.0, -2.0, 8.75),    # 无关圆
    ]
    seg, _score, idx = dim_rebind.match_edge(
        base, "left_top", _ctx_l100_to_l120(), target_segs)
    assert seg is not None
    assert idx == 2


def _line(x1=0.0, y1=0.0, x2=1.0, y2=1.0):
    return {"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2}


def _placement(edges):
    return {"x": 0, "y": 0, "scale": 1.0, "source_view": "left",
            "segs": edges, "hidden": [], "k": 1.0, "bbox": {}}


def _minimal_doc():
    return {
        "sheet": {},
        "model_id": "m",
        "views": [{"id": "view_1", "x": 0, "y": 0, "scale": 1.0,
                   "source_view": "left", "label": None, "group": None}],
        "annotations": [],
    }


def _write_source(model_code, doc, placements, out_dir, anns):
    os.makedirs(os.path.join(out_dir, model_code), exist_ok=True)
    batch_drawing._write_model_source(
        model_code, doc, placements, {"views": {}}, out_dir, annotations=anns)
    return json.load(open(os.path.join(out_dir, model_code,
                                       "drawing_source.json"), encoding="utf-8"))


def test_write_model_source_drops_out_of_range_refs(tmp_path):
    """越界 ref 落盘后前端按目标边表取不到几何,整条静默乱渲染,必须丢弃"""
    edges = [_line(), _line(1, 0, 2, 1), _line(2, 0, 3, 1)]
    anns = [
        {"id": "a1", "type": "linear",
         "refs": [{"viewId": "view_1", "idx": 2, "type": "edges"}]},
        {"id": "a2", "type": "linear",
         "refs": [{"viewId": "view_1", "idx": 99, "type": "edges"}]},
        {"id": "a3", "type": "linear", "mode": "motor-envelope",
         "refs": [{"viewId": "view_1", "idx": -1, "type": "edges"}]},
    ]
    saved = _write_source("m", _minimal_doc(),
                          {"view_1": _placement(edges)}, str(tmp_path), anns)
    assert [a["id"] for a in saved["annotations"]] == ["a1", "a3"]


def test_write_model_source_drops_missing_view_refs(tmp_path):
    edges = [_line()]
    anns = [
        {"id": "ok", "type": "linear",
         "refs": [{"viewId": "view_1", "idx": 0, "type": "edges"}]},
        {"id": "ghost", "type": "linear",
         "refs": [{"viewId": "view_x", "idx": 0, "type": "edges"}]},
    ]
    saved = _write_source("m", _minimal_doc(),
                          {"view_1": _placement(edges)}, str(tmp_path), anns)
    assert [a["id"] for a in saved["annotations"]] == ["ok"]


def test_write_model_source_keeps_refs_and_mm_with_break(tmp_path):
    """断裂只写 view.break:边线数组、refs.idx 与 spanMm 真值都不得被改"""
    spec = {"axis": "x", "cutA": 100.0, "cutB": 160.0, "pxPerMm": 0.2,
            "waveAmp": 3, "waveCycles": 3, "visualGap": 6}
    edges = [_line(50, 120, 220, 120), _line(60, 130, 80, 130)]
    edges[0]["meta"] = {"mm_coords": [-137.0, 10.0, 320.5, 10.0]}
    before = json.loads(json.dumps(edges))
    anns = [{"id": "a1", "type": "linear", "mode": "single", "spanMm": 457.5,
             "refs": [{"viewId": "view_1", "idx": 0, "type": "edges"}]}]
    placement = _placement(edges)
    placement["break"] = spec
    saved = _write_source("m", _minimal_doc(),
                          {"view_1": placement}, str(tmp_path), anns)
    view = saved["views"][0]
    assert view["break"] == spec
    assert view["edges"] == before
    assert len(view["edges"]) == 2
    ann = saved["annotations"][0]
    assert ann["refs"][0]["idx"] == 0
    assert ann["spanMm"] == 457.5
    assert view["edges"][0]["meta"]["mm_coords"] == [-137.0, 10.0, 320.5, 10.0]
