# -*- coding: utf-8 -*-
"""调试:打印每个视图最长的边线,定位离群长线来源"""
import sys, os
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
import drawing_engine as d

step = os.path.join(_PROJECT_ROOT, "output", "250-E-H3K2-L100-D11", "assembly.step")
shape = d.read_shape_cached(step)

for n in ["front", "back", "left", "right", "top", "bottom"]:
    cfg = d.STANDARD_VIEW_CONFIGS[n]
    v, h = d._project_shape(shape, cfg["dir"], cfg["up"], False)

    lines = [(d._segment_length(s), s) for s in v if s.get("type") == "line"]
    lines.sort(key=lambda x: x[0], reverse=True)

    polys = [(d._segment_length(s), s) for s in v if s.get("type") == "polyline"]
    polys.sort(key=lambda x: x[0], reverse=True)

    circles = [(s.get("r", 0), s) for s in v if s.get("type") == "circle"]
    circles.sort(key=lambda x: x[0], reverse=True)

    print(f"\n=== {n} ===")
    print(f"  lines(top3): {[(round(l,1), s) for l,s in lines[:3]]}")
    print(f"  polylines(top3): {[(round(l,1), len(s.get('points',[]))) for l,s in polys[:3]]}")
    print(f"  circles(top3): {[(round(r,1), s.get('cx'), s.get('cy')) for r,s in circles[:3]]}")

    # 找最大 2D 范围
    all_segs = v + h
    if all_segs:
        min_x, min_y, max_x, max_y = d._compute_bbox([all_segs])
        print(f"  bbox: ({min_x:.1f},{min_y:.1f}) - ({max_x:.1f},{max_y:.1f})  extent=({max_x-min_x:.1f},{max_y-min_y:.1f})")
