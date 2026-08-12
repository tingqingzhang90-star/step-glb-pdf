# -*- coding: utf-8 -*-
"""检查 front 视图的边线类型分布,排查 dim_bore 未匹配原因"""
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import drawing_engine as d

STEP = os.path.join(os.path.dirname(__file__), "..", "output",
                    "250-E-H3K2-L100-D11", "assembly.step")

raw = d.generate_drawing_views_raw(STEP, views=["front", "left", "top"])

for name, view in raw["views"].items():
    segs = view["visible"]
    types = Counter(s.get("type") for s in segs)
    circles = [s for s in segs if s.get("type") == "circle"]
    print(f"{name}: {len(segs)} segments, types={dict(types)}")
    for c in circles[:5]:
        print(f"  circle: cx={c.get('cx'):.1f} cy={c.get('cy'):.1f} r={c.get('r'):.1f}")
    if not circles:
        # 检查 polyline 里是否有近似圆的
        polys = [s for s in segs if s.get("type") == "polyline"]
        print(f"  (无圆, 有 {len(polys)} 条 polyline)")
        for p in polys[:3]:
            pts = p.get("points", [])
            if pts:
                xs = [pt[0] for pt in pts]
                ys = [pt[1] for pt in pts]
                print(f"    polyline: {len(pts)} pts, "
                      f"x=[{min(xs):.1f},{max(xs):.1f}] y=[{min(ys):.1f},{max(ys):.1f}]")
