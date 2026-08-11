# -*- coding: utf-8 -*-
"""从实际 STEP/BRep 模型中提取语义锚点坐标

功能:
  1. 读取零件 BRep 文件 + 变换矩阵,在装配体坐标系中重建各零件位置
  2. 识别缸体零件,提取缸筒端面中心点(front_end / back_end)和主轴方向
  3. 识别电机零件,计算电机包络 bounding box
  4. 识别安装孔(法兰上的圆形面)
  5. 更新 src/drawing_anchors.json,替换占位数据为真实坐标

使用方式:
    conda run -n pdf1 python tools/extract_anchors.py --model-code 250-E-H3K2-L100-D11
    conda run -n pdf1 python tools/extract_anchors.py --model-code 250-E-H2K1-L100-D11 --update

依赖:
    pythonocc-core (conda env: pdf1)
"""
import os
import sys
import json
import math
import argparse

# 添加 src 目录到路径
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_PROJECT_ROOT, "src")
sys.path.insert(0, _SRC)

# OCC 导入
from OCC.Core.BRep import BRep_Builder
from OCC.Core.BRepTools import breptools_Read
from OCC.Core.TopoDS import TopoDS_Shape, topods
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.gp import gp_Trsf, gp_Pnt, gp_Dir, gp_Ax1

# 复用 rebuild_assembly 的函数
import rebuild_assembly as rb


# ==================== 零件加载 ====================

def load_part_brep(part_name, parts_data):
    """读取单个零件的 BRep 文件并应用变换矩阵

    Args:
        part_name: parts_data 中的 key (如 "250缸体-1")
        parts_data: parts_transform.json 的数据

    Returns:
        TopoDS_Shape (已应用变换,在装配体坐标系中) 或 None
    """
    info = parts_data.get(part_name)
    if not info:
        return None

    step_file = info.get("step_file", "")
    if not step_file:
        return None

    # BRep 文件路径(step_file 的扩展名替换为 .brep)
    brep_name = os.path.splitext(step_file)[0] + ".brep"
    brep_path = os.path.join(rb.PARTS_DIR, brep_name)

    if not os.path.exists(brep_path):
        # 回退到 .step
        step_path = os.path.join(rb.PARTS_DIR, step_file)
        if os.path.exists(step_path):
            shape = rb.read_step(step_path)
        else:
            return None
    else:
        shape = TopoDS_Shape()
        builder = BRep_Builder()
        breptools_Read(shape, brep_path, builder)
        if shape.IsNull():
            return None

    # 应用变换矩阵
    matrix = info.get("transform_matrix")
    if matrix:
        trsf = rb.matrix_to_trsf(matrix)
        from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
        transform = BRepBuilderAPI_Transform(trsf)
        transform.Perform(shape, True)
        return transform.ModifiedShape(shape)

    return shape


def get_part_base_name(key):
    """提取零件基础名(去掉 -N 后缀)

    "250缸体-1" → "250缸体"
    "11kw-1" → "11kw"
    """
    import re
    m = re.match(r"^(.+)-(\d+)$", key)
    return m.group(1) if m else key


# ==================== 缸体端面提取 ====================

def find_cylinder_end_faces(shape):
    """从缸体形状中提取端面中心点和主轴方向

    策略:
      1. 遍历所有面,找出圆柱面,取半径最大者为主圆柱面
      2. 从主圆柱面获取轴线和半径
      3. 遍历所有平面,找出法线与主轴平行的平面(端面)
      4. 按主轴方向坐标排序,最两端的平面中心即为端面中心

    Args:
        shape: TopoDS_Shape (缸体,已应用变换)

    Returns:
        {
            "front_end": [x, y, z],     # 前端面中心
            "back_end": [x, y, z],      # 后端面中心
            "axis_dir": [dx, dy, dz],   # 主轴方向
            "axis_point": [x, y, z],    # 轴线上一点
            "radius": float,            # 缸筒半径
            "length": float             # 缸筒长度
        } 或 None
    """
    cylindrical_faces = []  # [(radius, axis, location)]
    planar_faces = []       # [(normal, location, center)]

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = topods.Face(explorer.Current())
        try:
            adaptor = BRepAdaptor_Surface(face)
            surf_type = adaptor.GetType()

            # GeomAbs_SurfaceType 枚举: Plane=0, Cylinder=1, Cone=2, Sphere=3, Torus=4
            if surf_type == 1:  # GeomAbs_Cylinder
                cyl = adaptor.Cylinder()
                radius = float(cyl.Radius())
                axis = cyl.Axis()
                loc = cyl.Location()
                cylindrical_faces.append({
                    "radius": radius,
                    "axis_dir": [float(axis.Direction().X()),
                                 float(axis.Direction().Y()),
                                 float(axis.Direction().Z())],
                    "axis_loc": [float(loc.X()), float(loc.Y()), float(loc.Z())]
                })

            # GeomAbs_Plane = 0
            elif surf_type == 0:
                pln = adaptor.Plane()
                normal = pln.Axis().Direction()
                loc = pln.Location()
                # 计算面的中心点(近似:用面的包围盒中心)
                face_bbox = Bnd_Box()
                brepbndlib.Add(face, face_bbox)
                xmin, ymin, zmin, xmax, ymax, zmax = face_bbox.Get()
                center = [(xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2]
                planar_faces.append({
                    "normal": [float(normal.X()), float(normal.Y()), float(normal.Z())],
                    "location": [float(loc.X()), float(loc.Y()), float(loc.Z())],
                    "center": center
                })
        except Exception:
            pass
        explorer.Next()

    if not cylindrical_faces:
        return None

    # 取半径最大的圆柱面作为主缸筒
    main_cyl = max(cylindrical_faces, key=lambda c: c["radius"])
    axis_dir = main_cyl["axis_dir"]
    axis_loc = main_cyl["axis_loc"]
    radius = main_cyl["radius"]

    # 归一化轴方向
    dir_len = math.sqrt(sum(d * d for d in axis_dir))
    if dir_len < 1e-6:
        return None
    axis_dir_norm = [d / dir_len for d in axis_dir]

    # 在平面中找法线与主轴平行的端面
    end_faces = []
    for pf in planar_faces:
        # 计算法线与轴方向的点积(绝对值接近1表示平行)
        dot = abs(pf["normal"][0] * axis_dir_norm[0] +
                  pf["normal"][1] * axis_dir_norm[1] +
                  pf["normal"][2] * axis_dir_norm[2])
        if dot > 0.95:
            # 计算端面中心在轴方向上的投影坐标
            proj = (pf["center"][0] * axis_dir_norm[0] +
                    pf["center"][1] * axis_dir_norm[1] +
                    pf["center"][2] * axis_dir_norm[2])
            end_faces.append({"center": pf["center"], "proj": proj})

    if len(end_faces) < 2:
        # 回退:用包围盒在轴方向的两端
        bbox = Bnd_Box()
        brepbndlib.Add(shape, bbox)
        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
        # 找最长轴
        lens = [xmax - xmin, ymax - ymin, zmax - zmin]
        axis_idx = lens.index(max(lens))
        center = [(xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2]
        if axis_idx == 0:
            front = [xmin, center[1], center[2]]
            back = [xmax, center[1], center[2]]
        elif axis_idx == 1:
            front = [center[0], ymin, center[2]]
            back = [center[0], ymax, center[2]]
        else:
            front = [center[0], center[1], zmin]
            back = [center[0], center[1], zmax]
        length = lens[axis_idx]
        # 用包围盒最长轴作为轴方向
        axis_vec = [0, 0, 0]
        axis_vec[axis_idx] = 1
        return {
            "front_end": [round(v, 2) for v in front],
            "back_end": [round(v, 2) for v in back],
            "axis_dir": [round(v, 4) for v in axis_vec],
            "axis_point": [round(v, 2) for v in center],
            "radius": round(radius, 2),
            "length": round(length, 2)
        }

    # 按轴方向投影排序
    end_faces.sort(key=lambda f: f["proj"])
    front = end_faces[0]["center"]
    back = end_faces[-1]["center"]
    length = abs(end_faces[-1]["proj"] - end_faces[0]["proj"])

    return {
        "front_end": [round(v, 2) for v in front],
        "back_end": [round(v, 2) for v in back],
        "axis_dir": [round(v, 4) for v in axis_dir_norm],
        "axis_point": [round(v, 2) for v in axis_loc],
        "radius": round(radius, 2),
        "length": round(length, 2)
    }


# ==================== 电机识别 ====================

def find_motor_parts(parts_data, config, motor_name):
    """根据配置识别电机相关零件

    Args:
        parts_data: parts_transform.json 数据
        config: 系列配置 JSON
        motor_name: 电机名称(如 "11kw电机")

    Returns:
        list of part keys (如 ["11kw-1", "AB180-1"])
    """
    motor_config = config.get("motor", {}).get(motor_name, {})
    on_parts = motor_config.get("on", [])  # 如 ["AB180", "11kw"]

    motor_keys = []
    for key in parts_data:
        info = parts_data[key]
        if info.get("suppressed", False):
            continue
        base_name = get_part_base_name(key)
        if base_name in on_parts:
            motor_keys.append(key)

    return motor_keys


def compute_motor_bbox(motor_shapes):
    """计算电机零件的合并包围盒

    Args:
        motor_shapes: list of TopoDS_Shape

    Returns:
        {
            "center": [x, y, z],
            "min": [xmin, ymin, zmin],
            "max": [xmax, ymax, zmax],
            "size": [dx, dy, dz]
        } 或 None
    """
    if not motor_shapes:
        return None

    combined = Bnd_Box()
    for shape in motor_shapes:
        brepbndlib.Add(shape, combined)

    xmin, ymin, zmin, xmax, ymax, zmax = combined.Get()
    return {
        "center": [round((xmin + xmax) / 2, 2),
                   round((ymin + ymax) / 2, 2),
                   round((zmin + zmax) / 2, 2)],
        "min": [round(xmin, 2), round(ymin, 2), round(zmin, 2)],
        "max": [round(xmax, 2), round(ymax, 2), round(zmax, 2)],
        "size": [round(xmax - xmin, 2),
                 round(ymax - ymin, 2),
                 round(zmax - zmin, 2)]
    }


# ==================== 安装孔识别 ====================

def find_mounting_holes(shape, axis_dir, radius_min=3.0, radius_max=30.0):
    """在缸体上找安装孔(圆形面)

    Args:
        shape: TopoDS_Shape (缸体)
        axis_dir: 缸体主轴方向 [dx, dy, dz]
        radius_min: 最小孔半径
        radius_max: 最大孔半径

    Returns:
        list of {"center": [x,y,z], "radius": float, "normal": [dx,dy,dz]}
    """
    holes = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = topods.Face(explorer.Current())
        try:
            adaptor = BRepAdaptor_Surface(face)
            if adaptor.GetType() == 1:  # GeomAbs_Cylinder
                cyl = adaptor.Cylinder()
                r = float(cyl.Radius())
                if radius_min < r < radius_max:
                    loc = cyl.Location()
                    axis = cyl.Axis().Direction()
                    holes.append({
                        "center": [round(float(loc.X()), 2),
                                   round(float(loc.Y()), 2),
                                   round(float(loc.Z()), 2)],
                        "radius": round(r, 2),
                        "normal": [round(float(axis.X()), 4),
                                   round(float(axis.Y()), 4),
                                   round(float(axis.Z()), 4)]
                    })
        except Exception:
            pass
        explorer.Next()

    return holes


# ==================== 主流程 ====================

def extract_anchors(model_code, update_json=False):
    """从实际模型中提取锚点坐标

    Args:
        model_code: 型号编码 (如 "250-E-H3K2-L100-D11")
        update_json: 是否更新 drawing_anchors.json

    Returns:
        dict: 提取的锚点数据
    """
    # 1. 解析型号
    sel = rb.parse_model_code(model_code)
    series_name = sel["series"]
    motor_name = sel.get("motor") or rb.DEFAULT_MOTOR
    print(f"型号: {model_code}")
    print(f"系列: {series_name}, 电机: {motor_name}")

    # 2. 加载配置
    config = rb.load_config(f"{series_name}直连" if series_name == "250" else series_name)
    cylinder_part_name = config.get("cylinder_part", "250缸体")

    # 3. 加载零件变换数据
    with open(rb.MATRIX_JSON, "r", encoding="utf-8") as f:
        parts_data = json.load(f)

    # 4. 找到缸体零件并提取端面
    print(f"\n--- 缸体提取 ---")
    print(f"缸体零件名: {cylinder_part_name}")
    cyl_shape = None
    for key in parts_data:
        base = get_part_base_name(key)
        if base == cylinder_part_name and not parts_data[key].get("suppressed", False):
            cyl_shape = load_part_brep(key, parts_data)
            print(f"  读取: {key}")
            break

    anchors_data = {"model_code": model_code}
    if cyl_shape and not cyl_shape.IsNull():
        cyl_info = find_cylinder_end_faces(cyl_shape)
        if cyl_info:
            print(f"  前端面: {cyl_info['front_end']}")
            print(f"  后端面: {cyl_info['back_end']}")
            print(f"  主轴方向: {cyl_info['axis_dir']}")
            print(f"  半径: {cyl_info['radius']}mm, 长度: {cyl_info['length']}mm")
            anchors_data["cylinder.front_end"] = cyl_info["front_end"]
            anchors_data["cylinder.back_end"] = cyl_info["back_end"]
            anchors_data["cylinder.axis_dir"] = cyl_info["axis_dir"]
            anchors_data["cylinder.radius"] = cyl_info["radius"]
            anchors_data["cylinder.length"] = cyl_info["length"]

            # 5. 找安装孔(在缸体上)
            holes = find_mounting_holes(cyl_shape, cyl_info["axis_dir"])
            if holes:
                print(f"  安装孔: 找到 {len(holes)} 个")
                for i, h in enumerate(holes[:4]):  # 最多取前4个
                    print(f"    孔{i+1}: 中心={h['center']} 半径={h['radius']}")
                    anchors_data[f"mounting.hole_{i+1}"] = h["center"]
        else:
            print("  ✗ 未能提取缸体端面")
    else:
        print("  ✗ 未找到缸体零件")

    # 6. 识别电机
    print(f"\n--- 电机识别 ---")
    motor_keys = find_motor_parts(parts_data, config, motor_name)
    print(f"电机零件: {motor_keys}")
    motor_shapes = []
    for key in motor_keys:
        shape = load_part_brep(key, parts_data)
        if shape and not shape.IsNull():
            motor_shapes.append(shape)
            print(f"  读取: {key}")

    if motor_shapes:
        motor_bbox = compute_motor_bbox(motor_shapes)
        if motor_bbox:
            print(f"  电机包络中心: {motor_bbox['center']}")
            print(f"  电机包络尺寸: {motor_bbox['size']}")
            anchors_data["motor.body"] = motor_bbox["center"]
            anchors_data["motor.bbox_min"] = motor_bbox["min"]
            anchors_data["motor.bbox_max"] = motor_bbox["max"]
            anchors_data["motor.size"] = motor_bbox["size"]

    # 7. 更新 drawing_anchors.json
    if update_json:
        update_anchors_json(anchors_data)
    else:
        print(f"\n--- 提取结果(未写入文件) ---")
        print(json.dumps(anchors_data, ensure_ascii=False, indent=2))

    return anchors_data


def update_anchors_json(extracted):
    """更新 src/drawing_anchors.json 中的锚点坐标

    Args:
        extracted: 提取的锚点数据 dict
    """
    anchors_path = os.path.join(_SRC, "drawing_anchors.json")
    with open(anchors_path, "r", encoding="utf-8") as f:
        anchors = json.load(f)

    for anchor in anchors.get("anchors", []):
        aid = anchor.get("id", "")
        if aid == "cylinder.front_end" and "cylinder.front_end" in extracted:
            anchor["point3d"] = extracted["cylinder.front_end"]
        elif aid == "cylinder.back_end" and "cylinder.back_end" in extracted:
            anchor["point3d"] = extracted["cylinder.back_end"]
        elif aid == "cylinder.axis":
            if "cylinder.axis_dir" in extracted:
                anchor["direction3d"] = extracted["cylinder.axis_dir"]
            if "cylinder.radius" in extracted:
                anchor["radius"] = extracted["cylinder.radius"]
            if "cylinder.length" in extracted:
                anchor["length"] = extracted["cylinder.length"]
        elif aid == "motor.body" and "motor.body" in extracted:
            anchor["point3d"] = extracted["motor.body"]
            anchor["bbox_min"] = extracted.get("motor.bbox_min")
            anchor["bbox_max"] = extracted.get("motor.bbox_max")
            anchor["size"] = extracted.get("motor.size")
        elif aid.startswith("mounting.hole_"):
            if aid in extracted:
                anchor["point3d"] = extracted[aid]

    # 更新 profile 信息
    anchors["last_updated"] = {
        "model_code": extracted.get("model_code", "unknown"),
        "source": "auto_extracted"
    }

    with open(anchors_path, "w", encoding="utf-8") as f:
        json.dump(anchors, f, ensure_ascii=False, indent=2)

    print(f"\n✓ 已更新: {anchors_path}")


# ==================== CLI ====================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从 STEP/BRep 模型提取语义锚点")
    parser.add_argument("--model-code", required=True,
                        help="型号编码,如 250-E-H3K2-L100-D11")
    parser.add_argument("--update", action="store_true",
                        help="更新 drawing_anchors.json (默认只打印)")
    args = parser.parse_args()

    extract_anchors(args.model_code, update_json=args.update)
