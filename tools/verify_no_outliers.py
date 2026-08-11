# -*- coding: utf-8 -*-
"""验证 bbox 投影裁剪修复后, 各视图是否还有越界/离群边"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import drawing_engine as d

STEP = os.path.join(os.path.dirname(__file__), "..", "output",
                    "250-E-H3K2-L100-D11", "assembly.step")


def seg_bbox(segments):
    xs, ys = [], []
    for s in segments:
        if s["type"] == "line":
            xs += [s["x1"], s["x2"]]
            ys += [s["y1"], s["y2"]]
        elif s["type"] == "circle":
            xs += [s["cx"] - s["r"], s["cx"] + s["r"]]
            ys += [s["cy"] - s["r"], s["cy"] + s["r"]]
        elif s["type"] == "polyline":
            for p in s["points"]:
                xs.append(p[0])
                ys.append(p[1])
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def main():
    result = d.generate_all_standard_views(STEP)
    print(f"max_2d_extent_mm={result.get('max_2d_extent_mm')} "
          f"uniform_scale={result.get('uniform_scale')}")
    for name, view in result["views"].items():
        segs = view["edges"]
        bb = seg_bbox(segs)
        if bb:
            w, h = bb[2] - bb[0], bb[3] - bb[1]
            print(f"  {name:16s} edges={len(segs):4d} extent=({w:.1f},{h:.1f})")
        else:
            print(f"  {name:16s} edges=0")


if __name__ == "__main__":
    main()
