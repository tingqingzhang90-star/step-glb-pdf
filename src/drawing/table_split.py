# -*- coding: utf-8 -*-
"""单元格"格内子分割"的几何与分隔线绘制,供多套 PDF 渲染路径复用。

拆分语义与前端 TableSplitParts.vue 保持一致:
  split_dir='h' 左右等分为 N 列(内部竖线);'v' 上下等分为 N 行(内部横线)。
  cell.parts[i].text 为各子格文字;整格 cell.text 在拆分后为空。
坐标以 SVG mm 表示(原点左上、y 向下),由调用方通过 pt 映射到 PDF 坐标。
"""
from typing import Callable, List, Tuple

# (x1, y1, x2, y2, text),单位 SVG mm
CellTextRect = Tuple[float, float, float, float, str]
Pt = Callable[[float, float], Tuple[float, float]]

# 多行文字行距(相对字号倍数),前后端一致
LINE_SPACING = 1.25


def parse_align(align: str) -> Tuple[str, str]:
    """把 'h-center v-bottom' 解析成 ('h-center', 'v-bottom'),缺省左对齐/垂直居中。"""
    ha, va = "h-left", "v-center"
    for p in (align or "").split():
        if p.startswith("h-"):
            ha = p
        elif p.startswith("v-"):
            va = p
    return ha, va


def line_baselines(fs: float, n: int, lh: float,
                   y_top: float, y_bottom: float, va: str):
    """返回 n 行文字各自的 baseline y(坐标系 y 向上,y_top > y_bottom)。

    单行保持旧的居中/贴边公式,保证既有出图零回归;
    多行时按行距把整块文字按 va 摆进 [y_bottom, y_top]。
    """
    if n <= 1:
        if va == "v-top":
            return [y_top - 0.8 * fs]
        if va == "v-bottom":
            return [y_bottom + 0.2 * fs]
        return [(y_top + y_bottom) / 2 - 0.35 * fs]
    if va == "v-top":
        return [y_top - 0.8 * fs - i * lh for i in range(n)]
    if va == "v-bottom":
        return [y_bottom + 0.2 * fs + (n - 1 - i) * lh for i in range(n)]
    mid = (y_top + y_bottom) / 2 - 0.35 * fs
    return [mid + ((n - 1) / 2 - i) * lh for i in range(n)]


def cell_text_rects(sx1: float, sy1: float, sx2: float, sy2: float,
                    cell: dict) -> List[CellTextRect]:
    """拆分格 → 各子格矩形 + 对应文字;未拆分 → 整格 + cell.text。"""
    n = cell.get("split_count", 0) if cell.get("split_dir") else 0
    if n >= 2 and cell.get("parts"):
        dir_h = cell["split_dir"] == "h"
        parts = cell["parts"]
        out = []
        for i in range(n):
            text = (parts[i] or {}).get("text") or ""
            if dir_h:
                x0 = sx1 + (sx2 - sx1) * i / n
                x1 = sx1 + (sx2 - sx1) * (i + 1)
                out.append((x0, sy1, x1, sy2, text))
            else:
                y0 = sy1 + (sy2 - sy1) * i / n
                y1 = sy1 + (sy2 - sy1) * (i + 1)
                out.append((sx1, y0, sx2, y1, text))
        return out
    return [(sx1, sy1, sx2, sy2, cell.get("text") or "")]


def draw_split_dividers(c, cell: dict, pt: Pt,
                        sx1: float, sy1: float, sx2: float, sy2: float,
                        bc, bw) -> None:
    """在拆分单元格内画等分线(调用方已确保 cell 确实被拆分)。"""
    n = cell.get("split_count", 0) if cell.get("split_dir") else 0
    if n < 2 or not cell.get("parts"):
        return
    dir_h = cell["split_dir"] == "h"
    c.setStrokeColorRGB(*bc)
    c.setLineWidth(bw)
    for i in range(1, n):
        if dir_h:
            x = sx1 + (sx2 - sx1) * i / n
            p1 = pt(x, sy1)
            p2 = pt(x, sy2)
        else:
            y = sy1 + (sy2 - sy1) * i / n
            p1 = pt(sx1, y)
            p2 = pt(sx2, y)
        c.line(p1[0], p1[1], p2[0], p2[1])
