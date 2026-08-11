# -*- coding: utf-8 -*-
"""调试:打印每个视图的 view_dir, up_dir, 计算出的 x_dir"""
import sys, os
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
import drawing_engine as d
from OCC.Core.gp import gp_Dir

for n, cfg in d.STANDARD_VIEW_CONFIGS.items():
    vd = cfg["dir"]
    up = cfg["up"]
    # 和 _project_shape_poly 里一样的 x_dir 计算
    x_dir = gp_Dir(
        vd.Y() * up.Z() - vd.Z() * up.Y(),
        vd.Z() * up.X() - vd.X() * up.Z(),
        vd.X() * up.Y() - vd.Y() * up.X()
    )
    print(f"{n}: view_dir=({vd.X():.1f},{vd.Y():.1f},{vd.Z():.1f})  "
          f"up_dir=({up.X():.1f},{up.Y():.1f},{up.Z():.1f})  "
          f"x_dir=({x_dir.X():.4f},{x_dir.Y():.4f},{x_dir.Z():.4f})")
