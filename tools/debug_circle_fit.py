# -*- coding: utf-8 -*-
"""检查 front 视图所有 polyline 的点数和形状,找出可能的圆"""
import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import drawing_engine as d
from drawing_template import _fit_circles_from_polylines

STEP = os.path.join(os.path.dirname(__file__), "..", "output",
                    "250-E-H3K2-L100-D11", "assembly.step")

raw = d.generate_drawing_views_raw(STEP, views=["front"])
segs = raw["views"]["front"]["visible"]

polys = [s for s in segs if s.get("type") == "polyline"]
print(f"front 视图: {len(polys)} 条 polyline")

for i, p in enumerate(polys):
    pts = p.get("points", [])
    if len(pts) < 6:
        continue
    xs = [pt[0] for pt in pts]
    ys = [pt[1] for pt in pts]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    dists = [math.hypot(pt[0]-cx, pt[1]-cy) for pt in pts]
    avg_r = sum(dists) / len(dists)
    if avg_r < 1.0:
        continue
    variance = sum((dd - avg_r)**2 for dd in dists) / len(dists)
    cv = (variance ** 0.5) / avg_r
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    # 圆形特征: cv 小, 宽高比接近 1
    aspect = min(w, h) / max(w, h) if max(w, h) > 0 else 0
    if cv < 0.15 and aspect > 0.7:
        print(f"  poly#{i}: {len(pts)} pts, cx={cx:.1f} cy={cy:.1f} "
              f"r={avg_r:.1f} cv={cv:.3f} aspect={aspect:.2f} "
              f"bbox=({min(xs):.1f},{min(ys):.1f})-({max(xs):.1f},{max(ys):.1f})")

# 测试拟合
fitted = _fit_circles_from_polylines(segs)
print(f"\n拟合出 {len(fitted)} 个圆:")
for c in fitted:
    print(f"  cx={c['cx']} cy={c['cy']} r={c['r']}")
