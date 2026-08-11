# -*- coding: utf-8 -*-
"""调试:打印 top 视图中最长 polyline 的前5个和后5个点坐标"""
import sys, os, math
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
import drawing_engine as d

step = os.path.join(_PROJECT_ROOT, "output", "250-E-H3K2-L100-D11", "assembly.step")
shape = d.read_shape_cached(step)

cfg = d.STANDARD_VIEW_CONFIGS["top"]
v, h = d._project_shape(shape, cfg["dir"], cfg["up"], False)

polys = [(d._segment_length(s), s) for s in v if s.get("type") == "polyline"]
polys.sort(key=lambda x: x[0], reverse=True)

for rank, (length, poly) in enumerate(polys[:3]):
    pts = poly.get("points", [])
    print(f"\n=== top polyline #{rank+1} length={length:.1f} pts={len(pts)} ===")
    print(f"  first 5: {pts[:5]}")
    print(f"  last 5:  {pts[-5:]}")
    # 计算 bbox
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    print(f"  x range: {min(xs):.1f} ~ {max(xs):.1f}")
    print(f"  y range: {min(ys):.1f} ~ {max(ys):.1f}")
