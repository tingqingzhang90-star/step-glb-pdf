# -*- coding: utf-8 -*-
"""调试脚本:检查缸体零件的面类型,排查端面提取失败原因"""
import os
import sys
import json

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_PROJECT_ROOT, "src")
sys.path.insert(0, _SRC)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "tools"))

from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.TopoDS import topods

import rebuild_assembly as rb
from extract_anchors import load_part_brep, get_part_base_name


def check_face_types(shape, label=""):
    """遍历所有面,打印类型统计"""
    type_counts = {}
    type_names = {
        0: "Plane(平面)",
        1: "Cylinder(圆柱面)",
        2: "Cone(圆锥面)",
        3: "Sphere(球面)",
        4: "Torus(环面)",
        5: "BezierSurface",
        6: "BSplineSurface",
        7: "SurfaceOfRevolution",
        8: "SurfaceOfExtrusion",
        9: "OffsetSurface",
        10: "Other",
    }

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    face_idx = 0
    cylinders = []
    planes = []

    while explorer.More():
        face = topods.Face(explorer.Current())
        try:
            adaptor = BRepAdaptor_Surface(face)
            stype = adaptor.GetType()
            type_counts[stype] = type_counts.get(stype, 0) + 1

            if stype == 1:  # Cylinder
                cyl = adaptor.Cylinder()
                r = float(cyl.Radius())
                axis = cyl.Axis().Direction()
                loc = cyl.Location()
                cylinders.append({
                    "radius": round(r, 2),
                    "axis_dir": [round(float(axis.X()), 4),
                                 round(float(axis.Y()), 4),
                                 round(float(axis.Z()), 4)],
                    "loc": [round(float(loc.X()), 2),
                            round(float(loc.Y()), 2),
                            round(float(loc.Z()), 2)],
                })
            elif stype == 0:  # Plane
                pln = adaptor.Plane()
                normal = pln.Axis().Direction()
                loc = pln.Location()
                planes.append({
                    "normal": [round(float(normal.X()), 4),
                               round(float(normal.Y()), 4),
                               round(float(normal.Z()), 4)],
                    "loc": [round(float(loc.X()), 2),
                            round(float(loc.Y()), 2),
                            round(float(loc.Z()), 2)],
                })
        except Exception as e:
            print(f"  面{face_idx} 异常: {e}")
        face_idx += 1
        explorer.Next()

    print(f"\n=== {label} 面类型统计 ===")
    print(f"总面数: {face_idx}")
    for stype, count in sorted(type_counts.items()):
        name = type_names.get(stype, f"Unknown({stype})")
        print(f"  {name}: {count}")

    if cylinders:
        print(f"\n圆柱面({len(cylinders)}个):")
        for i, c in enumerate(cylinders[:10]):
            print(f"  [{i}] 半径={c['radius']}mm 轴方向={c['axis_dir']} 位置={c['loc']}")

    if planes:
        print(f"\n平面({len(planes)}个,前5个):")
        for i, p in enumerate(planes[:5]):
            print(f"  [{i}] 法线={p['normal']} 位置={p['loc']}")

    return cylinders, planes


if __name__ == "__main__":
    with open(rb.MATRIX_JSON, "r", encoding="utf-8") as f:
        parts_data = json.load(f)

    # 找缸体零件
    cyl_key = None
    for key in parts_data:
        base = get_part_base_name(key)
        if base == "250缸体" and not parts_data[key].get("suppressed", False):
            cyl_key = key
            break

    if not cyl_key:
        print("✗ 未找到缸体零件")
        sys.exit(1)

    print(f"缸体零件: {cyl_key}")
    shape = load_part_brep(cyl_key, parts_data)

    if shape is None or shape.IsNull():
        print("✗ 缸体形状为空")
        sys.exit(1)

    print(f"✓ 缸体形状已加载")

    # 检查面类型
    check_face_types(shape, "缸体(已应用变换)")

    # 也检查未应用变换的原始零件
    print("\n--- 对比:原始零件(未应用变换) ---")
    step_file = parts_data[cyl_key].get("step_file", "")
    brep_name = os.path.splitext(step_file)[0] + ".brep"
    brep_path = os.path.join(rb.PARTS_DIR, brep_name)
    step_path = os.path.join(rb.PARTS_DIR, step_file)

    if os.path.exists(brep_path):
        from OCC.Core.BRep import BRep_Builder
        from OCC.Core.BRepTools import breptools_Read
        from OCC.Core.TopoDS import TopoDS_Shape
        raw_shape = TopoDS_Shape()
        builder = BRep_Builder()
        breptools_Read(raw_shape, brep_path, builder)
        if not raw_shape.IsNull():
            check_face_types(raw_shape, "原始缸体(未变换)")
    elif os.path.exists(step_path):
        raw_shape = rb.read_step(step_path)
        if raw_shape and not raw_shape.IsNull():
            check_face_types(raw_shape, "原始缸体(未变换)")
