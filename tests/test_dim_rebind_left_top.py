# -*- coding: utf-8 -*-
"""left_top 视图轴向补偿与源文件落盘防御测试

left_top(左视上视)漏登记 AXIAL_MAP 时,该视图标注不做轴向补偿:行程拉伸
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


def test_axial_map_covers_left_top():
    assert dim_rebind.AXIAL_MAP.get("left_top") == ("x", 1.0)


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
