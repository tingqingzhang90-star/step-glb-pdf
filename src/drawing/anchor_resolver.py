# -*- coding: utf-8 -*-
"""按型号解析语义锚点 — 批量出图的关联标注数据源

drawing_anchors.json 的静态绝对坐标仅对提取时的基准型号有效,换行程/
换电机后即失效。本模块按型号实时解析:

  - 缸体系: 解析计算(安装平移 + D1 = stroke + C 拉伸),不依赖 OCC 几何
  - 电机系: 零件 BRep 实测包络,换电机型号自动跟随
  - 位移规则与 rebuild_assembly.build_assembly 一致:
    主轴坐标大于缸体安装位置的零件,随拉伸量同步平移

调用方式:
    from drawing import anchor_resolver
    profile = anchor_resolver.resolve_anchors("250-E-H2K1-L200-D55")
"""
import copy
import json
import os
import re
from datetime import date

from core import paths
from core import rebuild_assembly as rb

_KEY_RE = re.compile(r"^(.+)-(\d+)$")
_BASE_VIEWS = ["front", "left", "top"]


def _base_name(key):
    m = _KEY_RE.match(key)
    return m.group(1) if m else key


def compute_cylinder_anchors(t_mm, axis_idx, local_min, local_max, radius, scale):
    """缸体锚点解析计算(纯函数)

    局部主轴坐标按 scale 缩放(原点为零件局部原点,与
    stretch_shape_axis 的缩放方式一致),再加安装平移得到世界坐标。

    Args:
        t_mm: 缸体零件安装平移 [x, y, z] mm
        axis_idx: 主轴索引(0=X, 1=Y, 2=Z)
        local_min/local_max: 缸体 BRep 未拉伸时沿主轴的局部坐标范围
        radius: 主缸筒半径 mm
        scale: 拉伸比 D1 / base_D1

    Returns:
        dict: front_end/back_end/axis_point/axis_dir/radius/length
    """
    s0 = local_min * scale
    s1 = local_max * scale
    back = [round(v, 2) for v in t_mm]
    back[axis_idx] = round(t_mm[axis_idx] + s0, 2)
    front = [round(v, 2) for v in t_mm]
    front[axis_idx] = round(t_mm[axis_idx] + s1, 2)
    center = [round(v, 2) for v in t_mm]
    center[axis_idx] = round(t_mm[axis_idx] + (s0 + s1) / 2, 2)
    direction = [0.0, 0.0, 0.0]
    direction[axis_idx] = 1.0
    return {
        "front_end": front,
        "back_end": back,
        "axis_point": center,
        "axis_dir": direction,
        "radius": round(float(radius), 2),
        "length": round(s1 - s0, 2),
    }


def displace_parts(parts_data, axis_idx, cyl_axis_coord_mm, delta_mm):
    """配合零件位移补偿(纯函数,返回深拷贝)

    与 build_assembly 规则一致: 未抑制且主轴安装坐标大于缸体安装坐标
    的零件,沿主轴平移 delta_mm(拉伸引起的缸体延伸量)。

    Args:
        parts_data: parts_transform.json 数据
        axis_idx: 主轴索引
        cyl_axis_coord_mm: 缸体安装平移的主轴分量 mm
        delta_mm: 位移量 mm(正值沿主轴正向)

    Returns:
        dict: 位移后的 parts_data 副本
    """
    data = copy.deepcopy(parts_data)
    if abs(delta_mm) < 1e-6:
        return data
    for info in data.values():
        if info.get("suppressed", False):
            continue
        coord = info["transform_matrix"][9 + axis_idx] * 1000.0
        if coord > cyl_axis_coord_mm:
            info["transform_matrix"][9 + axis_idx] += delta_mm / 1000.0
    return data


# ==================== OCC 读取层 ====================

def _read_part_shape(step_file):
    """读零件 shape(优先 .brep 缓存,回退 .step)"""
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.BRepTools import breptools
    from OCC.Core.TopoDS import TopoDS_Shape

    step_path = rb.resolve_part_file(step_file)
    brep = os.path.splitext(step_path)[0] + ".brep"
    if os.path.exists(brep):
        shape = TopoDS_Shape()
        breptools.Read(shape, brep, BRep_Builder())
        if not shape.IsNull():
            return shape
    return rb.read_step(step_path)


def _shape_world_bbox(shape, matrix):
    """应用变换矩阵后的世界包围盒

    Returns:
        (min3, max3) 各分量保留 2 位小数
    """
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform

    tr = BRepBuilderAPI_Transform(rb.matrix_to_trsf(matrix))
    tr.Perform(shape, True)
    bb = Bnd_Box()
    brepbndlib.Add(tr.ModifiedShape(shape), bb)
    vals = bb.Get()
    r = lambda v: round(float(v), 2)
    return [r(v) for v in vals[:3]], [r(v) for v in vals[3:]]


def _part_end_faces(shape, matrix, axis_dir):
    """提取零件中垂直于主轴的所有平面端面(变换后),附带面积信息

    Returns:
        list[{"center":[x,y,z], "proj":float, "area":float}]
    """
    import numpy as np
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.TopoDS import topods
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCC.Core.BRepTools import breptools
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps

    tr = BRepBuilderAPI_Transform(rb.matrix_to_trsf(matrix))
    tr.Perform(shape)
    tr_shape = tr.ModifiedShape(shape)
    axis = np.array(axis_dir, dtype=float)
    norm_axis = axis / (np.linalg.norm(axis) + 1e-12)

    faces = []
    exp = TopExp_Explorer(tr_shape, TopAbs_FACE)
    while exp.More():
        face = topods.Face(exp.Current())
        try:
            adaptor = BRepAdaptor_Surface(face)
            if adaptor.GetType() != 0:  # 只认平面端面
                exp.Next()
                continue
            normal = adaptor.Plane().Axis().Direction()
            nvec = np.array([float(normal.X()), float(normal.Y()), float(normal.Z())])
            nlen = np.linalg.norm(nvec)
            if nlen < 1e-9:
                exp.Next()
                continue
            nvec = nvec / nlen
            # 法向与主轴平行(夹角 < 5°)
            if abs(abs(np.dot(nvec, norm_axis)) - 1.0) > 0.08:
                exp.Next()
                continue
            u1, u2, v1, v2 = breptools.UVBounds(face)
            pnt = adaptor.Value((u1 + u2) / 2.0, (v1 + v2) / 2.0)
            center = [round(float(pnt.X()), 2), round(float(pnt.Y()), 2), round(float(pnt.Z()), 2)]
            proj = float(np.dot(np.array(center, dtype=float), norm_axis))
            props = GProp_GProps()
            brepgprop.SurfaceProperties(face, props)
            area = float(props.Mass())
            faces.append({"center": center, "proj": proj, "area": area})
        except Exception:
            pass
        exp.Next()
    return faces


def _max_cylinder_radius(shape):
    """最大圆柱面半径(主缸筒半径),无圆柱面时返回 None"""
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.TopoDS import topods
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface

    radius = None
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        try:
            adaptor = BRepAdaptor_Surface(topods.Face(exp.Current()))
            if adaptor.GetType() == 1:  # GeomAbs_Cylinder
                r = float(adaptor.Cylinder().Radius())
                radius = r if radius is None else max(radius, r)
        except Exception:
            pass
        exp.Next()
    return radius


# ==================== 型号解析 ====================

def _load_model_parts(model_code):
    """解析型号 → (sel, config, motor, 带显隐的 parts_data)"""
    sel = rb.parse_model_code(model_code)
    suffix = "直连" if sel["type"].upper() == "E" else "折返"
    series_name = f"{sel['series']}{suffix}"
    config = rb.load_config(series_name)
    # 必须切换激活系列:零件查找路径随它变。不切就会去默认系列(250直连)的
    # 目录里找本系列零件,读取 STEP 直接失败。
    rb.set_series(series_name)
    motor = rb.resolve_motor(config, sel.get("motor"))
    visibility = rb.resolve_visibility(config, sel["mount"], sel["load"], motor)
    with open(paths.transform_json(series_name), "r", encoding="utf-8") as f:
        parts_data = json.load(f)
    for key, info in parts_data.items():
        info["suppressed"] = not visibility.get(_base_name(key), True)
    return sel, series_name, config, motor, parts_data


def _resolve_group_bbox(data, part_names):
    """给定零件名集合,返回它们装配后的世界包络 (bmin, bmax)"""
    keys = [k for k in data
            if _base_name(k) in part_names and not data[k].get("suppressed")]
    if not keys:
        return None
    bmin = [float("inf")] * 3
    bmax = [float("-inf")] * 3
    for k in keys:
        shape = _read_part_shape(data[k]["step_file"])
        pmin, pmax = _shape_world_bbox(shape, data[k]["transform_matrix"])
        bmin = [min(a, b) for a, b in zip(bmin, pmin)]
        bmax = [max(a, b) for a, b in zip(bmax, pmax)]
    return bmin, bmax


def _resolve_motor_bbox(data, config, motor):
    """电机+减速机零件组的世界包络 (bmin, bmax),无电机零件时返回 None"""
    on_parts = set(config.get("motor", {}).get(motor, {}).get("on", []))
    return _resolve_group_bbox(data, on_parts)


def _resolve_gearbox_bbox(data, config, motor):
    """仅减速机零件的世界包络 (bmin, bmax),无减速机时返回 None"""
    motor_cfg = config.get("motor", {}).get(motor, {})
    on_parts = set(motor_cfg.get("on", []))
    # 简单启发:零件名不含 'kw'/'电机' 的视为减速机(如 AB180)
    gearbox_parts = {p for p in on_parts
                     if 'kw' not in p.lower() and '电机' not in p}
    if not gearbox_parts:
        return None
    return _resolve_group_bbox(data, gearbox_parts)


def _resolve_motor_real_faces(data, config, motor, axis_dir):
    """从电机相关零件中提取主轴方向最外侧的两个真实端面中心

    电机+减速机装配中,每个零件通常有两个面积最大的"本体端面"(左右两侧),
    安装法兰台阶端面面积较小。对每个零件取面积最大的两个端面,再用其中
    的最左/最右作为该零件的代表;跨零件合并后得到全局最左/最右端面,
    从而避开法兰凸缘,同时保留电机最左端面。
    """
    on_parts = set(config.get("motor", {}).get(motor, {}).get("on", []))

    all_mins = []
    all_maxs = []
    for k in data:
        if _base_name(k) not in on_parts or data[k].get("suppressed"):
            continue
        shape = _read_part_shape(data[k]["step_file"])
        faces = _part_end_faces(shape, data[k]["transform_matrix"], axis_dir)
        if not faces:
            continue
        # 按面积排序取前两名(本体端面),防止小法兰台阶干扰
        top = sorted(faces, key=lambda f: f["area"], reverse=True)[:2]
        all_mins.append(min(top, key=lambda f: f["proj"]))
        all_maxs.append(max(top, key=lambda f: f["proj"]))

    if not all_mins or not all_maxs:
        return None
    rmin = min(all_mins, key=lambda f: f["proj"])
    rmax = max(all_maxs, key=lambda f: f["proj"])
    return rmin["center"], rmax["center"]


def _anchor_entry(anchor_id, atype, label, **extra):
    entry = {"id": anchor_id, "type": atype, "label": label,
             "views": list(_BASE_VIEWS)}
    entry.update(extra)
    return entry


def _build_profile(model_code, series_name, cyl, motor_bbox, gearbox_bbox, motor_real_faces, axis_idx):
    """组装与 drawing_anchors.json 同构的锚点 profile"""
    anchors = [
        _anchor_entry("cylinder.front_end", "plane", "缸筒前端面",
                      point3d=cyl["front_end"]),
        _anchor_entry("cylinder.back_end", "plane", "缸筒后端面",
                      point3d=cyl["back_end"]),
        _anchor_entry("cylinder.axis", "axis", "缸体中心轴",
                      point3d=cyl["axis_point"], direction3d=cyl["axis_dir"],
                      radius=cyl["radius"], length=cyl["length"]),
    ]
    def _add_body_anchors(anchor_id_prefix, bbox, label_body, label_min, label_max):
        if not bbox:
            return
        bmin, bmax = bbox
        size = [round(bmax[i] - bmin[i], 2) for i in range(3)]
        center = [round((bmin[i] + bmax[i]) / 2, 2) for i in range(3)]
        face_min = list(center)
        face_min[axis_idx] = bmin[axis_idx]
        face_max = list(center)
        face_max[axis_idx] = bmax[axis_idx]
        anchors.extend([
            _anchor_entry(f"{anchor_id_prefix}.body", "box", label_body,
                          point3d=center, bbox_min=bmin, bbox_max=bmax,
                          size=size),
            _anchor_entry(f"{anchor_id_prefix}.axis_min_face", "plane", label_min,
                          point3d=[round(v, 2) for v in face_min]),
            _anchor_entry(f"{anchor_id_prefix}.axis_max_face", "plane", label_max,
                          point3d=[round(v, 2) for v in face_max]),
        ])

    _add_body_anchors("motor", motor_bbox, "电机/减速机包络", "电机尾端面", "电机接入端面")
    _add_body_anchors("gearbox", gearbox_bbox, "减速机包络", "减速机尾端面", "减速机接入端面")

    # 真实端面中心:从平面端面提取,比 bbox 极值更贴合实际端面(避免法兰凸缘影响)
    if motor_real_faces:
        rmin, rmax = motor_real_faces
        anchors.extend([
            _anchor_entry("motor.real_axis_min_face", "plane", "电机尾端面(真实端面)",
                          point3d=[round(v, 2) for v in rmin]),
            _anchor_entry("motor.real_axis_max_face", "plane", "减速机接入端面(真实端面)",
                          point3d=[round(v, 2) for v in rmax]),
        ])

    return {
        "profile_id": f"{series_name}-resolved",
        "version": 2,
        "anchors": anchors,
        "last_updated": {"model_code": model_code, "source": "resolved"},
    }


def resolve_anchors(model_code):
    """按型号解析语义锚点

    Args:
        model_code: 型号编码,如 "250-E-H2K1-L200-D55"

    Returns:
        dict: 与 drawing_anchors.json 同构的 profile
    """
    sel, series_name, config, motor, parts_data = _load_model_parts(model_code)

    cyl_part = config.get("cylinder_part", "250缸体")
    cyl_key = next((k for k in parts_data
                    if _base_name(k) == cyl_part
                    and not parts_data[k].get("suppressed")), None)
    if not cyl_key:
        raise ValueError(f"未找到可见缸体零件: {model_code}")

    scale_info = rb.compute_cylinder_scale(config, sel["stroke"])
    _, d1, scale = scale_info if scale_info else (None, None, 1.0)

    cyl_shape = _read_part_shape(parts_data[cyl_key]["step_file"])
    bbox = rb.shape_bbox(cyl_shape)
    axis_idx = rb.find_cylinder_axis(cyl_shape)
    local_min = bbox[axis_idx]
    local_max = bbox[axis_idx + 3]
    radius = _max_cylinder_radius(cyl_shape)
    if radius is None:
        raise ValueError(f"缸体无圆柱面,无法取主缸筒半径: {cyl_key}")

    t_mm = [v * 1000.0 for v in parts_data[cyl_key]["transform_matrix"][9:12]]
    cyl = compute_cylinder_anchors(t_mm, axis_idx, local_min, local_max,
                                   radius, scale)
    delta_mm = (local_max - local_min) * (scale - 1.0)
    data = displace_parts(parts_data, axis_idx, t_mm[axis_idx], delta_mm)

    motor_bbox = _resolve_motor_bbox(data, config, motor)
    gearbox_bbox = _resolve_gearbox_bbox(data, config, motor)
    motor_real_faces = _resolve_motor_real_faces(data, config, motor, cyl["axis_dir"])
    profile = _build_profile(model_code, series_name, cyl, motor_bbox, gearbox_bbox, motor_real_faces, axis_idx)
    profile["d1"] = d1
    return profile


def build_model_params(model_code):
    """构造模板字符串参数(标题栏/条件标注/占位符)"""
    sel, series_name, config, motor, _ = _load_model_parts(model_code)
    stroke_num = int(re.match(r"^L?(\d+)$", sel["stroke"]).group(1))
    cyl = rb.compute_cylinder_scale(config, sel["stroke"])
    return {
        "model_code": model_code,
        "series": sel["series"],
        "series_name": series_name,
        "stroke": stroke_num,
        "d1": cyl[1] if cyl else None,
        "motor": motor,
        "has_motor": True,
        "date": date.today().isoformat(),
        "scale": "2",
    }
