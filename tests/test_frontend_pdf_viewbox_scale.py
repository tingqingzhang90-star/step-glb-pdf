# -*- coding: utf-8 -*-
"""前端实例模板的 PDF 视图缩放回归测试

根因复盘: 后端 batch_drawing.generate_one_frontend 早期把
placement.scale 硬编码为 1.0,导致 400x300 缩略图里的画布像素
被原样当成 mm 写到 A3 图纸上, 视图整体被放大 ~6 倍,边线会
超出图框(本应在右内框 405mm 之内的耳叉接头跑到 ~450mm)。

修复: 改成 placement.scale = v.scale(前端 UI 缩放比例,无量纲),
与 SVG 节点 <g transform="translate(v.x,v.y) scale(v.scale)"> 一致。
这条用例断言 placement.scale 必须等于模板里存的 view.scale,
以及最右端边线落在 A3 内框 405mm 以内。

运行:
    pytest tests/test_frontend_pdf_viewbox_scale.py -v
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rebuild_placements(template_doc, palette):
    """镜像修复后 src/batch/batch_drawing.py 中 placements 的构造逻辑
    这里不直接 import batch.batch_drawing, 避免在单元测试中触发
    drawing_engine 等重型模块加载。 两条用例都跑同一份逻辑, 验证:
      1. placement.scale == v.scale
      2. 边线最右端 x < A3 内框 405mm
    """
    placements = {}
    for v in template_doc["views"]:
        src = v["source_view"]
        pv = palette["views"].get(src)
        if pv is None:
            raise ValueError(f"palette 缺视图: {src}")
        k_target = pv.get("bbox", {}).get("scale") or 1.0
        view_scale = float(v.get("scale") or 1.0)
        placements[v["id"]] = {
            "x": v["x"], "y": v["y"],
            "scale": view_scale,
            "source_view": src,
            "segs": pv.get("edges", []),
            "hidden": pv.get("hidden_edges", []),
            "k": k_target,
        }
    return placements


def _make_template_doc():
    """最小模板: 一个视图, x/y/scale 与典型 A3 调色板一致"""
    return {
        "model_id": "TEST",
        "template_identity": "TEST",
        "sheet": {"size": "A3", "width": 420, "height": 297},
        "views": [{
            "id": "view_a",
            "source_view": "left",
            "label": "左视",
            "x": 69,
            "y": 14,
            "scale": 0.93,
            "px_per_mm": 0.1545,
        }],
        "annotations": [],
    }


def _make_palette_stub():
    """palette: left 视图归一化到 400x300, 边线 x 范围 60..340"""
    edges = [{
        "type": "line",
        "x1": 60.0, "y1": 150.0, "x2": 340.0, "y2": 150.0,
        "meta": {"orientation": "horizontal"},
    }]
    return {"views": {"left": {
        "edges": edges, "hidden_edges": [],
        "bbox": {"x": 0, "y": 0, "width": 400, "height": 300,
                 "scale": 0.1545, "orig_width": 1812.5, "orig_height": 303.0,
                 "offset_x": 207.96, "offset_y": 183.38},
    }}}


def test_placement_scale_uses_template_view_scale():
    """placement.scale 必须等于模板 v.scale, 不能退化为 1.0"""
    p = _rebuild_placements(_make_template_doc(), _make_palette_stub())["view_a"]
    assert p["scale"] == 0.93, f"placement.scale={p['scale']}, 期望 0.93"
    # 在 420x297 (A3) 图纸里, left 视图最右端
    #   x = 69 + 340 * 0.93 = 385.2 mm, 远在 405 mm 内边距以内
    right_edge = p["x"] + 340 * p["scale"]
    assert right_edge < 405, (
        f"right_edge={right_edge:.2f}mm 超出图框 405mm; "
        "说明 placement.scale 又退化为 1.0 了")


def test_placement_scale_old_code_overflows():
    """回归 guard: 模拟 bug 状态(scale=1.0), 验证它确实会超界"""
    p = {"x": 69, "y": 14, "scale": 1.0}
    right_edge = p["x"] + 340 * p["scale"]
    assert right_edge >= 405, (
        "此断言仅用于文档化: 旧代码(placement.scale=1.0)右端 409mm "
        "已超图框 405mm, 触发图 1 中右下视图耳叉越界")


def test_real_source_has_correct_scale(monkeypatch):
    """直接读源码, 断言修复后的 batch_drawing.py 不再写死 scale=1.0"""
    src_path = os.path.join(_PROJECT_ROOT, "src", "batch", "batch_drawing.py")
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()
    # 1. 不允许再写死 scale=1.0
    assert '"scale": 1.0' not in src, (
        "src/batch/batch_drawing.py 仍写死 placement.scale=1.0, "
        "会再次触发 400x300 缩略图被原样当成 mm 写入 PDF 的 bug")
    # 2. 必须用模板 v.scale
    assert "v.get(\"scale\")" in src or "v.get('scale')" in src, (
        "src/batch/bing_drawing.py 应读取 v['scale'] 作为 placement.scale")
