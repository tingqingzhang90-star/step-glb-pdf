# -*- coding: utf-8 -*-
"""两套 PDF 渲染器的断裂视图回归:能出图、边线数组不变、标注端点跟随投影

断裂视图靠 clipPath + 右段平移实现,不删除也不重排 edges;标注引用的两个
端点投影后仍连成一条尺寸线,数值另取 mm 真值。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from drawing import break_view as bv  # noqa: E402
from drawing import drawing_source_render as src_render  # noqa: E402
from drawing.dim import dim_pdf_sheet  # noqa: E402

_SPEC = {"axis": "x", "cutA": 100.0, "cutB": 160.0, "pxPerMm": 0.2,
         "waveAmp": 3, "waveCycles": 3, "visualGap": 6}
_SHEET = {"size": "A3", "width": 420, "height": 297}
_CB = {"x": 40, "y": 100, "width": 240, "height": 60}


def _edges():
    return [
        {"type": "line", "x1": 50.0, "y1": 120.0, "x2": 220.0, "y2": 120.0,
         "meta": {"mm_coords": [-137.0, 10.0, 320.5, 10.0]}},
        {"type": "circle", "cx": 80.0, "cy": 130.0, "r": 10.0,
         "meta": {"radius": 24.0}},
    ]


def test_frontend_pdf_renders_broken_view(tmp_path):
    edges = _edges()
    placement = {
        "x": 30, "y": 30, "scale": 0.9, "k": 0.2,
        "segs": edges, "hidden": [], "contentBBox": _CB,
        "break": _SPEC,
    }
    out = tmp_path / "frontend.pdf"
    dim_pdf_sheet.render_frontend_pdf(
        [], {"view_1": placement}, {"sheet": _SHEET, "views": [], "tables": []},
        "TEST", str(out))
    assert out.read_bytes().startswith(b"%PDF")
    assert out.stat().st_size > 1000
    assert len(placement["segs"]) == 2
    assert placement["segs"][0]["meta"]["mm_coords"] == [-137.0, 10.0, 320.5, 10.0]


def test_source_pdf_renders_broken_view(tmp_path):
    doc = {
        "sheet": _SHEET, "model_id": "TEST", "annotations": [],
        "views": [{
            "id": "view_1", "source_view": "left", "x": 30, "y": 30,
            "scale": 0.9, "bbox": {"scale": 0.2},
            "contentBBox": _CB, "edges": _edges(), "hidden_edges": [],
            "break": _SPEC,
        }],
    }
    out = tmp_path / "source.pdf"
    src_render.render_drawing_source_pdf(doc, str(out))
    assert out.read_bytes().startswith(b"%PDF")
    assert out.stat().st_size > 1000
    assert len(doc["views"][0]["edges"]) == 2


def test_source_pdf_edge_endpoints_follow_break():
    spec = bv.from_dict(_SPEC)
    shift = spec.shift
    view = {"x": 30, "y": 30, "scale": 0.9, "edges": _edges(),
            "hidden_edges": [], "break": _SPEC}
    p1, p2 = src_render._edge_endpoints(view, 0)
    plain = {**view, "break": None}
    q1, q2 = src_render._edge_endpoints(plain, 0)
    assert q2[0] - q1[0] == 170.0 * 0.9
    assert p2[0] - p1[0] == (170.0 - shift) * 0.9
    assert p1[0] == q1[0]  # 左段不动
    assert p1[1] == q1[1] and p2[1] == q2[1]


def test_source_pdf_view_scale_uses_sheet_scale():
    assert src_render._view_scale({"scale": 0.9, "bbox": {"scale": 0.2}}) == 0.9
