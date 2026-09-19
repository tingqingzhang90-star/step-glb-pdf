# -*- coding: utf-8 -*-
"""表格渲染测试

用 FakeCanvas 捕获原语调用,不依赖 OCC 也不写真实 PDF——验证:
  * colspan/rowspan 合并:只画左上角那个矩形,被覆盖格不重复画
  * 水平对齐走对应的 draw 方法(left/center/right)
  * 列宽行高累加正确,矩形位置与尺寸符合预期

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/ -v
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from drawing.dim.dim_pdf_sheet import _draw_table_placement, SheetMapper


class FakeCanvas:
    """捕获 rect / drawString 等调用,断言用"""

    def __init__(self):
        self.calls = []

    def setStrokeColorRGB(self, *a):
        self.calls.append(("stroke", a))

    def setLineWidth(self, w):
        self.calls.append(("lineWidth", round(w, 2)))

    def setFillColorRGB(self, *a):
        self.calls.append(("fill", a))

    def setFont(self, name, size):
        self.calls.append(("font", (name, round(size, 2))))

    def rect(self, x, y, w, h, **k):
        self.calls.append(("rect",
                           (round(x, 1), round(y, 1), round(w, 1), round(h, 1))))

    def drawString(self, x, y, text):
        self.calls.append(("string", (round(x, 1), round(y, 1), text)))

    def drawCentredString(self, x, y, text):
        self.calls.append(("center", (round(x, 1), round(y, 1), text)))

    def drawRightString(self, x, y, text):
        self.calls.append(("right", (round(x, 1), round(y, 1), text)))

    def line(self, x1, y1, x2, y2):
        self.calls.append(("line",
                           (round(x1, 1), round(y1, 1),
                            round(x2, 1), round(y2, 1))))


def _table():
    """2 列 × 3 行,首行合并为标题"""
    return {
        "x": 100, "y": 50,
        "col_widths": [40, 30],
        "row_heights": [14, 8, 8],
        "cells": [
            {"r": 0, "c": 0, "colspan": 2, "text": "技术参数",
             "align": "h-center v-center", "font_size": 12},
            {"r": 1, "c": 0, "text": "产品型号", "align": "h-left"},
            {"r": 1, "c": 1, "text": "YRJ250", "align": "h-left"},
            {"r": 2, "c": 0, "text": "缸径", "align": "h-left"},
            {"r": 2, "c": 1, "text": "20", "align": "h-right"},
        ],
    }


def test_merged_title_drawn_as_one_rect():
    c, m = FakeCanvas(), SheetMapper(420, 297)
    _draw_table_placement(c, _table(), m)
    rects = [a for k, a in c.calls if k == "rect"]
    # 5 个 cell → 5 个矩形(被覆盖格本就不在 cells 里)
    assert len(rects) == 5
    # 标题格:colspan=2 → 宽 = 40+30 = 70
    title = rects[0]
    assert title[2] == 70.0
    # 单元格:宽 = 40
    assert rects[1][2] == 40.0


def test_horizontal_alignment_routes_to_correct_draw():
    c, m = FakeCanvas(), SheetMapper(420, 297)
    _draw_table_placement(c, _table(), m)
    kinds = [k for k, _ in c.calls]
    assert "center" in kinds          # 标题 h-center
    assert "string" in kinds          # h-left
    assert "right" in kinds           # h-right


def test_y_axis_flipped_by_mapper():
    """表格 y 是 SVG(向下),PDF 应翻转:首行在上方(PDF y 更大)"""
    c, m = FakeCanvas(), SheetMapper(420, 297)
    _draw_table_placement(c, _table(), m)
    rects = [a for k, a in c.calls if k == "rect"]
    # sheet_h=297, table.y=50,首行高 14 → 标题格底部 PDF-y = 297-64=233
    assert rects[0][1] == 233.0


def test_empty_cells_skip_text_but_keep_border():
    """空文本格子只画边框,不调 drawString"""
    t = _table()
    t["cells"][0]["text"] = ""
    c, m = FakeCanvas(), SheetMapper(420, 297)
    _draw_table_placement(c, t, m)
    assert len([k for k, _ in c.calls if k == "rect"]) == 5
    assert len([k for k, _ in c.calls
                if k in ("string", "center", "right")]) == 4


def test_vertical_alignment_routes_to_correct_y():
    """v-top/v-center/v-bottom 对应不同 baseline y"""
    t = {
        "x": 0, "y": 0,
        "col_widths": [10, 10, 10],
        "row_heights": [10],
        "cells": [
            {"r": 0, "c": 0, "text": "top", "align": "h-left v-top"},
            {"r": 0, "c": 1, "text": "mid", "align": "h-center v-center"},
            {"r": 0, "c": 2, "text": "bot", "align": "h-right v-bottom"},
        ],
    }
    c, m = FakeCanvas(), SheetMapper(100, 100)
    _draw_table_placement(c, t, m)
    texts = [a for k, a in c.calls
             if k in ("string", "center", "right")]
    # 行高 10, font_size 默认 _TBL_FONT_PX;y 已翻转
    # top: 100 - 0.8*fs; mid: 100 - 5 - 0.35*fs; bot: 100 - 10 + 0.2*fs
    from drawing.dim import dim_pdf_sheet as mod
    fs = mod._TBL_FONT_PX * mod._PX2MM
    top_y, mid_y, bot_y = texts[0][1], texts[1][1], texts[2][1]
    assert top_y == round(100 - 0.8 * fs, 1)
    assert mid_y == round(100 - 5 - 0.35 * fs, 1)
    assert bot_y == round(100 - 10 + 0.2 * fs, 1)


def test_default_colspan_rowspan_is_one():
    """省略 colspan/rowspan 时按单格画"""
    t = {
        "x": 0, "y": 0,
        "col_widths": [10, 10],
        "row_heights": [8],
        "cells": [{"r": 0, "c": 0, "text": "a"},
                  {"r": 0, "c": 1, "text": "b"}],
    }
    c, m = FakeCanvas(), SheetMapper(100, 100)
    _draw_table_placement(c, t, m)
    rects = [a for k, a in c.calls if k == "rect"]
    assert [r[2] for r in rects] == [10.0, 10.0]


def test_render_frontend_pdf_passes_tables_through(tmp_path, monkeypatch):
    """端到端:render_frontend_pdf 能把 tables 字段渲染进 PDF"""
    from drawing.dim import dim_pdf_sheet as mod
    # 出图管线顶层依赖 OCC,打桩掉 view/标注,只留表格
    monkeypatch.setattr(mod, "_draw_view_edges",
                        lambda c, p, m: None)
    monkeypatch.setattr(mod, "_draw_primitives",
                        lambda c, p, color, m: None)
    # dim_render._ensure_font 会注册中文字体,打桩掉避免 OCC 依赖
    monkeypatch.setattr(mod, "_ensure_font", lambda: None,
                        raising=False)

    doc = {"sheet": {"width": 100, "height": 60, "size": "A3"},
           "tables": [_table()]}
    out = tmp_path / "t.pdf"
    mod.render_frontend_pdf([], {}, doc, "M1", str(out))
    assert out.exists() and out.stat().st_size > 0


def _bare_table():
    """单格表,不指定 font_size / border / text_color,走默认值分支"""
    return {"x": 0, "y": 0, "col_widths": [10], "row_heights": [8],
            "cells": [{"r": 0, "c": 0, "text": "a"}]}


def test_default_font_size_uses_shared_config():
    """cell 未指定 font_size 时,字号取 cad_viewer_style.json 的 table.text.font_px"""
    from drawing.dim import dim_pdf_sheet as mod
    c, m = FakeCanvas(), SheetMapper(100, 100)
    _draw_table_placement(c, _bare_table(), m)
    fonts = [a[1] for k, a in c.calls if k == "font"]
    assert fonts == [round(mod._TBL_FONT_PX * mod._PX2MM, 2)]


def test_default_border_uses_shared_config():
    """table 未指定 border 时,线宽取 cad_viewer_style.json 的 table.border.stroke_mm"""
    from drawing.dim import dim_pdf_sheet as mod
    c, m = FakeCanvas(), SheetMapper(100, 100)
    _draw_table_placement(c, _bare_table(), m)
    widths = [a for k, a in c.calls if k == "lineWidth"]
    assert widths == [round(mod._TBL_BORDER_W, 2)]


def test_table_style_constants_match_shared_config():
    """后端常量必须等于 cad_viewer_style.json 的 table 段——前端读同一份,
    两者一旦不同源就会出现预览与 PDF 字号/线宽不一致"""
    import json
    from drawing.dim import dim_pdf_sheet as mod
    with open(os.path.join(_PROJECT_ROOT, "cad_viewer_style.json"),
              encoding="utf-8") as f:
        tbl = json.load(f)["table"]
    assert mod._TBL_FONT_PX == tbl["text"]["font_px"]
    assert mod._TBL_TEXT_COLOR == tbl["text"]["color"]
    assert mod._TBL_BORDER_W == tbl["border"]["stroke_mm"]
    assert mod._TBL_BORDER_COLOR == tbl["border"]["color"]


def _split_table(dir_char, count, parts):
    """单格表,该格被拆分成 count 份,parts 为各子格文字"""
    return {
        "x": 0, "y": 0,
        "col_widths": [20], "row_heights": [30],
        "cells": [{
            "r": 0, "c": 0, "split_dir": dir_char, "split_count": count,
            "text": "", "parts": [{"text": t} for t in parts],
            "align": "h-center v-center", "font_size": 12,
        }],
    }


def test_split_h_draws_one_vertical_divider_and_part_texts():
    """'h' 左右分 2 列 → 1 条竖线,且文字取 parts 而非已清空的 cell.text"""
    c, m = FakeCanvas(), SheetMapper(100, 100)
    _draw_table_placement(c, _split_table("h", 2, ["左", "右"]), m)
    lines = [a for k, a in c.calls if k == "line"]
    assert len(lines) == 1
    x1, y1, x2, y2 = lines[0]
    assert x1 == x2 and y1 != y2        # 竖线跨整格高
    texts = [a[2] for k, a in c.calls if k in ("string", "center", "right")]
    assert texts == ["左", "右"]


def test_split_v_draws_horizontal_dividers_per_gap():
    """'v' 上下分 3 行 → 2 条横线,文字逐块绘制"""
    c, m = FakeCanvas(), SheetMapper(100, 100)
    _draw_table_placement(c, _split_table("v", 3, ["A", "B", "C"]), m)
    lines = [a for k, a in c.calls if k == "line"]
    assert len(lines) == 2
    for x1, y1, x2, y2 in lines:
        assert y1 == y2 and x1 != x2      # 横线跨整格宽
    texts = [a[2] for k, a in c.calls if k in ("string", "center", "right")]
    assert texts == ["A", "B", "C"]


def test_split_empty_cell_text_still_renders_parts():
    """整格 text 清空后,拆分格必须靠 parts 出字,否则 PDF 空白(回归)"""
    c, m = FakeCanvas(), SheetMapper(100, 100)
    _draw_table_placement(c, _split_table("h", 2, ["甲", "乙"]), m)
    texts = [a[2] for k, a in c.calls if k in ("string", "center", "right")]
    assert texts == ["甲", "乙"]


def test_source_render_split_h_draws_divider_and_parts():
    """drawing_source 路径同样要支持拆分:'h' → 竖线 + 子格文字"""
    from drawing.drawing_source_render import _draw_table
    c, fy = FakeCanvas(), (lambda v: 100 - v)
    _draw_table(c, _split_table("h", 2, ["左", "右"]), fy)
    lines = [a for k, a in c.calls if k == "line"]
    assert len(lines) == 1
    x1, y1, x2, y2 = lines[0]
    assert x1 == x2 and y1 != y2
    texts = [a[2] for k, a in c.calls if k in ("string", "center", "right")]
    assert texts == ["左", "右"]


def _ml_table(text, align="h-center v-center"):
    """单格表,用于验证 \\n 多行排版"""
    return {"x": 0, "y": 0, "col_widths": [30], "row_heights": [30],
            "cells": [{"r": 0, "c": 0, "text": text, "align": align,
                       "font_size": 12}]}


def test_multiline_text_draws_each_line_top_to_bottom():
    """单元格 \\n 换行 → 逐行绘制,且第一行在上(PDF y 更大)"""
    c, m = FakeCanvas(), SheetMapper(100, 100)
    _draw_table_placement(c, _ml_table("A\nB\nC"), m)
    drawn = [a for k, a in c.calls if k == "center"]
    assert [d[2] for d in drawn] == ["A", "B", "C"]
    assert drawn[0][1] > drawn[1][1] > drawn[2][1]


def test_multiline_single_line_keeps_old_baseline():
    """单行不走多行布局(零回归):仍是原来的居中 baseline"""
    from drawing.dim import dim_pdf_sheet as mod
    c, m = FakeCanvas(), SheetMapper(100, 100)
    _draw_table_placement(c, _ml_table("单行"), m)
    y = [a[1] for k, a in c.calls if k == "center"][0]
    fs = 12 * mod._PX2MM
    assert y == round(100 - 15 - 0.35 * fs, 1)


def test_split_part_multiline_text_drawn_per_line():
    """拆分子格内的换行同样逐行绘制"""
    c, m = FakeCanvas(), SheetMapper(100, 100)
    _draw_table_placement(c, _split_table("v", 2, ["X\nY", "Z"]), m)
    texts = [a[2] for k, a in c.calls if k in ("string", "center", "right")]
    assert texts == ["X", "Y", "Z"]


def test_source_render_multiline_cell():
    """drawing_source 路径同样支持 \\n 多行"""
    from drawing.drawing_source_render import _draw_table
    t = {"x": 0, "y": 0, "col_widths": [30], "row_heights": [30],
         "cells": [{"r": 0, "c": 0, "text": "A\nB", "align": "h-left",
                    "font_size": 12}]}
    c, fy = FakeCanvas(), (lambda v: 100 - v)
    _draw_table(c, t, fy)
    drawn = [a for k, a in c.calls if k == "string"]
    assert [d[2] for d in drawn] == ["A", "B"]
    assert drawn[0][1] > drawn[1][1]
