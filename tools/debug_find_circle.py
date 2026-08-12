# -*- coding: utf-8 -*-
"""详细检查 front 视图所有 polyline,找半径接近 122.5 的"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import drawing_engine as d

STEP = os.path.join(os.path.dirname(__file__), "..", "output",
                    "250-E-H3K2-L100-D11", "assembly.step")
raw = d.generate_drawing_views_raw(STEP, views=["front"])
segs = raw["views"]["front"]["visible"]

# 缸体圆心在 front 视图的屏幕坐标: x=-205.95, y=229.57, r=122.5
target_cx, target_cy, target_r = -205.95, 229.57, 122.5

polys = [s for s in segs if s.get("type") == "polyline"]
print(f"共 {len(polys)} 条 polyline, 查找接近圆心({target_cx},{target_cy}) r={target_r} 的")

for i, p in enumerate(polys):
    pts = p.get("points", [])
    if len(pts) < 4:
        continue
    xs = [pt[0] for pt in pts]
    ys = [pt[1] for pt in pts]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    # 检查是否接近目标圆心
    dist_to_target = math.hypot(cx - target_cx, cy - target_cy)
    if dist_to_target > 200:
        continue
    print(f"\n  poly#{i}: {len(pts)} pts")
    print(f"    centroid=({cx:.1f}, {cy:.1f}) dist_to_target={dist_to_target:.1f}")
    print(f"    bbox=({min(xs):.1f},{min(ys):.1f})-({max(xs):.1f},{max(ys):.1f})")
    dists = [math.hypot(pt[0]-cx, pt[1]-cy) for pt in pts]
    avg_r = sum(dists)/len(dists)
    print(f"    avg_r={avg_r:.1f} (target={target_r})")
    if avg_r > 1:
        var = sum((dd-avg_r)**2 for dd in dists)/len(dists)
        cv = (var**0.5)/avg_r
        print(f"    cv={cv:.3f}")
    # 打印前5个点
    for j, pt in enumerate(pts[:5]):
        d_to_target = math.hypot(pt[0]-target_cx, pt[1]-target_cy)
        print(f"    pt[{j}]=({pt[0]:.1f},{pt[1]:.1f}) dist_to_circle_center={d_to_target:.1f}")
