# -*- coding: utf-8 -*-
"""断裂视图几何 — 视图级坐标变换的唯一来源

断裂不改动 edges/hidden_edges 数组:渲染时用双段裁剪(clip)+右段平移,
标注端点、调色板端面点统一走 project_point,几何自动跟随;尺寸数值仍取
模型 mm 真值(span_mm / meta.mm_coords),不受断裂影响。

cut_a/cut_b 是视图局部画布 px 坐标,跨端 JSON 用 camelCase,Python 与
前端 breakView.js 用同一组用例对拍,避免前后端投影漂移。
"""
import math
from dataclasses import dataclass

DEFAULT_VISUAL_GAP = 6.0
DEFAULT_WAVE_AMP = 3.0
DEFAULT_WAVE_CYCLES = 3


@dataclass(frozen=True)
class BreakSpec:
    axis: str                 # 画布局部轴向 "x" / "y"
    cut_a: float              # 断裂带起点(画布 px)
    cut_b: float              # 断裂带终点(画布 px)
    px_per_mm: float          # bbox.scale,模型 mm → 画布 px
    wave_amp: float = DEFAULT_WAVE_AMP
    wave_cycles: int = DEFAULT_WAVE_CYCLES
    visual_gap: float = DEFAULT_VISUAL_GAP

    @property
    def band_width(self) -> float:
        return self.cut_b - self.cut_a

    @property
    def shift(self) -> float:
        """右段左移量:省略长度减去断裂处保留的视觉间隙"""
        return self.band_width - self.visual_gap

    @property
    def right_cut(self) -> float:
        """右切口投影后的坐标,两条波浪线就画在这里与 cut_a 处"""
        return self.cut_a + self.visual_gap


def to_dict(spec):
    """BreakSpec → 可落盘 dict(camelCase,与前端 breakView.js 同源)"""
    if spec is None:
        return None
    return {
        "axis": spec.axis,
        "cutA": round(spec.cut_a, 4),
        "cutB": round(spec.cut_b, 4),
        "pxPerMm": round(spec.px_per_mm, 6),
        "waveAmp": spec.wave_amp,
        "waveCycles": spec.wave_cycles,
        "visualGap": spec.visual_gap,
    }


def from_dict(raw):
    """落盘 dict → BreakSpec;字段不全或几何无效时返回 None(按无断裂处理)"""
    if not isinstance(raw, dict) or raw.get("axis") not in ("x", "y"):
        return None
    try:
        spec = BreakSpec(
            axis=raw["axis"],
            cut_a=float(raw["cutA"]),
            cut_b=float(raw["cutB"]),
            px_per_mm=float(raw["pxPerMm"]),
            wave_amp=float(raw.get("waveAmp") or DEFAULT_WAVE_AMP),
            wave_cycles=int(raw.get("waveCycles") or DEFAULT_WAVE_CYCLES),
            visual_gap=float(raw.get("visualGap") or DEFAULT_VISUAL_GAP),
        )
    except (KeyError, TypeError, ValueError):
        return None
    # 省略量小于一个视觉间隙时断裂带看不出来,按无断裂处理
    if (spec.shift < spec.visual_gap or spec.px_per_mm <= 0
            or spec.wave_cycles < 1):
        return None
    return spec


def project_coord(value_px, spec):
    """画布 px 轴向坐标投影;落在断裂带内返回 None(该点被裁掉)"""
    if spec is None:
        return value_px
    if value_px <= spec.cut_a:
        return value_px
    if value_px >= spec.cut_b:
        return value_px - spec.shift
    return None


def clamp_coord(value_px, spec):
    """落在断裂带内的点钳到最近切口,供标注端点使用(永不返回 None)"""
    v = project_coord(value_px, spec)
    if v is not None:
        return v
    mid = (spec.cut_a + spec.cut_b) / 2.0
    return spec.cut_a if value_px < mid else spec.right_cut


def project_point(x, y, spec):
    """投影局部画布点;标注端点落在断裂带内时贴到切口,尺寸线仍连续"""
    if spec is None:
        return (x, y)
    axis_value = x if spec.axis == "x" else y
    projected = clamp_coord(axis_value, spec)
    return (projected, y) if spec.axis == "x" else (x, projected)


def choose_break_band(lo_px, hi_px, omit_mm, px_per_mm, visual_gap):
    """在内容轴向中部取断裂带,返回 (cut_a, cut_b) 画布 px 或 None"""
    width = hi_px - lo_px
    max_omit = width - 2 * visual_gap - 1.0
    if max_omit <= 0 or omit_mm <= 0 or px_per_mm <= 0:
        return None
    omit = min(omit_mm * px_per_mm, max_omit)
    mid = (lo_px + hi_px) / 2.0
    return (round(mid - omit / 2.0, 4), round(mid + omit / 2.0, 4))


def build_spec(axis, lo_px, hi_px, omit_mm, px_per_mm,
               wave_amp=DEFAULT_WAVE_AMP, wave_cycles=DEFAULT_WAVE_CYCLES,
               visual_gap=DEFAULT_VISUAL_GAP):
    """由内容范围构造 BreakSpec;断裂带放不下时返回 None"""
    band = choose_break_band(lo_px, hi_px, omit_mm, px_per_mm, visual_gap)
    if band is None:
        return None
    return from_dict(to_dict(BreakSpec(
        axis=axis, cut_a=band[0], cut_b=band[1], px_per_mm=px_per_mm,
        wave_amp=wave_amp, wave_cycles=wave_cycles, visual_gap=visual_gap)))


def clip_ranges(spec, canvas_size):
    """双段裁剪范围 [(clip_lo, clip_hi, shift)],坐标为裁剪前的画布 px"""
    if spec is None:
        return [(0.0, float(canvas_size), 0.0)]
    return [
        (0.0, spec.cut_a, 0.0),
        (spec.cut_b, float(canvas_size), -spec.shift),
    ]


def wave_points(spec, cross_lo, cross_hi):
    """两条折断波浪线点列(画布 px):左切口与右切口各一条"""
    if spec is None or cross_hi <= cross_lo:
        return ([], [])
    n = max(12, spec.wave_cycles * 12)
    span = cross_hi - cross_lo
    left, right = [], []
    for i in range(n + 1):
        t = i / n
        c = cross_lo + span * t
        d = spec.wave_amp * math.sin(2 * math.pi * spec.wave_cycles * t)
        a = spec.cut_a + d
        b = spec.right_cut + d
        left.append((a, c) if spec.axis == "x" else (c, a))
        right.append((b, c) if spec.axis == "x" else (c, b))
    return left, right
