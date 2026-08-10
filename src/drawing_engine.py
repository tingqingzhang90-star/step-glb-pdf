# -*- coding: utf-8 -*-
"""
工程图 2D 投影引擎

使用 pythonOCC HLRBRep(隐藏线消除)算法,从 3D 装配体生成 2D 工程图视图:
  - 主视图(Front): 沿 Y 轴负方向投影,缸体水平放置
  - 俯视图(Top): 沿 Z 轴负方向投影
  - 侧视图(Left): 沿 X 轴负方向投影
  - 轴测视图(Iso): 等轴测方向投影

输出 JSON 格式的 2D 线框数据(线段、圆弧、圆),供前端 SVG/Canvas 渲染。

依赖:
    conda run -n pdf1 python ...

调用方式:
    from drawing_engine import generate_drawing_views
    views = generate_drawing_views("output/250-E-H2K1-L100/assembly.step")
"""
import os
import json
import time
import math

from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TopoDS import TopoDS_Shape, topods
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCC.Core.BRep import BRep_Tool
from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Trsf, gp_Lin, gp_Pln
from OCC.Core.HLRBRep import (HLRBRep_Algo, HLRBRep_HLRToShape,
                              HLRBRep_PolyAlgo, HLRBRep_PolyHLRToShape)
from OCC.Core.HLRAlgo import HLRAlgo_Projector
from OCC.Core.Geom import Geom_Line, Geom_Plane
from OCC.Core.GeomAPI import GeomAPI_IntCS
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
from OCC.Core.GeomAdaptor import GeomAdaptor_Curve
from OCC.Core.GCPnts import GCPnts_QuasiUniformDeflection
from OCC.Core.TopAbs import TopAbs_VERTEX
from OCC.Core.BRep import BRep_Tool


def read_step_to_shape(step_path):
    """读取 STEP 文件为 TopoDS_Shape"""
    reader = STEPControl_Reader()
    status = reader.ReadFile(step_path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"无法读取 STEP 文件: {step_path}")
    reader.TransferRoots()
    return reader.OneShape()


def read_shape_cached(step_path):
    """读取 shape(带 BRep 缓存,比 STEP 快 14 倍)

    首次读取 STEP 并缓存为 .brep 二进制文件,后续直接读取 .brep。
    BRep 读取 ~0.4s vs STEP 读取 ~5.5s。

    Args:
        step_path: STEP 文件路径

    Returns:
        TopoDS_Shape
    """
    from OCC.Core.BRepTools import breptools
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.TopoDS import TopoDS_Shape

    brep_path = step_path.rsplit('.', 1)[0] + '.brep'
    step_exists = os.path.exists(step_path)

    # 如果 STEP 不存在但 BRep 缓存存在,直接读 BRep(BREP-only 模式)
    if not step_exists and os.path.exists(brep_path):
        shape = TopoDS_Shape()
        builder = BRep_Builder()
        breptools.Read(shape, brep_path, builder)
        if not shape.IsNull():
            return shape
        raise RuntimeError(f"BRep 缓存读取失败: {brep_path}")

    # 如果 BRep 缓存存在且比 STEP 文件新,直接读取
    if os.path.exists(brep_path):
        if os.path.getmtime(brep_path) >= os.path.getmtime(step_path):
            shape = TopoDS_Shape()
            builder = BRep_Builder()
            breptools.Read(shape, brep_path, builder)
            if not shape.IsNull():
                return shape

    # 否则读取 STEP 并缓存为 BRep
    shape = read_step_to_shape(step_path)
    try:
        breptools.Write(shape, brep_path)
    except Exception:
        pass  # 缓存写入失败不影响主流程
    return shape


def _project_shape(shape, view_dir, up_dir=None, show_hidden=False):
    """对 shape 执行 HLR 投影,返回 (visible_edges, hidden_edges)

    使用 HLRBRep_Algo(精确隐藏线消除算法)。
    默认不生成隐藏边(工程图通常只显示可见轮廓),大幅减少输出数据量。

    Args:
        shape: TopoDS_Shape - 3D 形状
        view_dir: gp_Dir - 视图方向(投影方向)
        up_dir: gp_Dir - 上方向(控制视图旋转角度)
        show_hidden: bool - 是否生成隐藏边(虚线)

    Returns:
        (visible_segments, hidden_segments)
        每个元素是 list of dict: {"type": "line"/"arc"/"circle", ...}
    """
    if up_dir is None:
        # 默认上方向:与视图方向垂直,优先 Z 轴
        if abs(view_dir.Z()) < 0.9:
            up_dir = gp_Dir(0, 0, 1)
        else:
            up_dir = gp_Dir(0, 1, 0)

    # 构造投影坐标系
    origin = gp_Pnt(0, 0, 0)
    ax2 = gp_Ax2(origin, view_dir, up_dir)

    # 使用精确 HLR 算法
    hlr = HLRBRep_Algo()
    hlr.Add(shape)
    hlr.Projector(HLRAlgo_Projector(ax2))
    hlr.Update()
    hlr.Hide()

    # 提取可见和隐藏边
    hlr_to_shape = HLRBRep_HLRToShape(hlr)

    # 可见边(实线)
    visible_shape = hlr_to_shape.VCompound()
    visible_segments = _extract_2d_segments(visible_shape)

    # 隐藏边(虚线) - 默认不提取(性能优化)
    hidden_segments = []
    if show_hidden:
        hidden_shape = hlr_to_shape.HCompound()
        hidden_segments = _extract_2d_segments(hidden_shape)

    return visible_segments, hidden_segments


def _project_shape_poly(shape, view_dir, up_dir=None, show_hidden=False):
    """对 shape 执行 HLR 投影(多边形离散算法,快速版)

    使用 HLRBRep_PolyAlgo(基于三角化的离散隐藏线消除算法)。
    相比 HLRBRep_Algo 精确算法,速度提升 10-20 倍,结果为多段线而非精确几何,
    对于工程图视图完全够用。

    前置条件:shape 必须已三角化(BRepMesh_IncrementalMesh)

    Args:
        shape: TopoDS_Shape - 3D 形状(必须已三角化)
        view_dir: gp_Dir - 视图方向(投影方向)
        up_dir: gp_Dir - 上方向(控制视图旋转角度)
        show_hidden: bool - 是否生成隐藏边(虚线)

    Returns:
        (visible_segments, hidden_segments)
    """
    if up_dir is None:
        if abs(view_dir.Z()) < 0.9:
            up_dir = gp_Dir(0, 0, 1)
        else:
            up_dir = gp_Dir(0, 1, 0)

    origin = gp_Pnt(0, 0, 0)
    ax2 = gp_Ax2(origin, view_dir, up_dir)

    # 使用多边形离散 HLR 算法(速度快 10-20 倍)
    hlr = HLRBRep_PolyAlgo()
    hlr.Load(shape)
    hlr.Projector(HLRAlgo_Projector(ax2))
    hlr.Update()

    # 提取可见和隐藏边
    # PolyHLRToShape 默认构造函数不接受参数,需先创建再 Update
    hlr_to_shape = HLRBRep_PolyHLRToShape()
    hlr_to_shape.Update(hlr)

    # 可见边(实线)
    visible_shape = hlr_to_shape.VCompound()
    visible_segments = _extract_2d_segments(visible_shape)

    # 隐藏边(虚线)
    hidden_segments = []
    if show_hidden:
        hidden_shape = hlr_to_shape.HCompound()
        hidden_segments = _extract_2d_segments(hidden_shape)

    return visible_segments, hidden_segments


def _project_to_image(shape, view_dir, up_dir=None,
                      image_size=(400, 300), line_thickness=1.0,
                      use_hlr=True):
    """使用 OCC 离屏渲染导出视图 PNG(Base64 编码)

    这是 SolidWorks 等专业软件内部使用的 3D 渲染管线 + HLR 模式。
    相比 HLRBRep_Algo 几何算法,渲染管线方式:
      - 效果可靠(就是 pythonOCC GUI 中看到的效果)
      - 速度极快(OpenGL GPU 加速,毫秒级)
      - 无需处理边线断裂问题(渲染管线天然处理遮挡)

    Args:
        shape: TopoDS_Shape - 3D 形状
        view_dir: gp_Dir - 视图方向(投影方向)
        up_dir: gp_Dir - 上方向(控制视图旋转)
        image_size: (width, height) - 输出图像尺寸
        line_thickness: 线宽
        use_hlr: 是否使用 HLR 模式(隐藏线消除),True=线框+隐藏线消除

    Returns:
        dict: {
            "png_base64": str,        # PNG 图像的 base64 编码
            "width": int, "height": int,
            "view_dir": tuple, "up_dir": tuple
        }
    """
    import base64
    import tempfile
    import os as os_module
    from OCC.Display.OCCViewer import OffscreenRenderer
    from OCC.Core.Quantity import Quantity_Color, Quantity_NOC_BLACK, Quantity_NOC_WHITE
    from OCC.Core.AIS import AIS_Shape
    from OCC.Core.Aspect import Aspect_GFM_NONE

    if up_dir is None:
        if abs(view_dir.Z()) < 0.9:
            up_dir = gp_Dir(0, 0, 1)
        else:
            up_dir = gp_Dir(0, 1, 0)

    # 1. 创建离屏渲染器(无需 GUI)
    renderer = OffscreenRenderer(screen_size=image_size)
    renderer.hide_triedron()  # 隐藏坐标轴

    # 2. 创建 AIS_Shape 并设置属性
    ais_shape = AIS_Shape(shape)

    # 设置白色背景
    white = Quantity_Color(1.0, 1.0, 1.0, 0)
    renderer.set_bg_gradient_color(white, white)

    # 3. 设置显示模式:HLR(隐藏线消除) 或 普通线框
    if use_hlr:
        renderer.SetModeHLR()
    else:
        renderer.SetModeWireFrame()

    # 4. 关闭阴影
    renderer.View.SetShadingModel(0)

    # 5. 设置正交投影
    renderer.View.Camera().SetProjectionType(0)  # 0=正交,1=透视

    # 6. 显示形状
    renderer.Context.Display(ais_shape, True)
    ais_shape.SetColor(Quantity_Color(Quantity_NOC_BLACK))

    # 7. 设置视图方向(OCC V3d_View 的 eye/center/up 三个向量)
    eye = gp_Pnt(0, 0, 0)
    center = gp_Pnt(float(view_dir.X()), float(view_dir.Y()), float(view_dir.Z()))
    up = gp_Pnt(float(up_dir.X()), float(up_dir.Y()), float(up_dir.Z()))
    renderer.View.SetEye(eye)
    renderer.View.SetAt(center)
    renderer.View.SetUp(up)
    # SetProj 必须用 gp_Dir 类型
    renderer.View.SetProj(view_dir, up_dir)

    # 8. 自适应模型到视图
    renderer.FitAll()
    renderer.Context.UpdateCurrentViewer()
    renderer.Repaint()

    # 9. 导出为 PNG 文件,再读为 base64
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        renderer.View.Dump(tmp_path)
        with open(tmp_path, 'rb') as f:
            png_bytes = f.read()
        png_b64 = base64.b64encode(png_bytes).decode('ascii')
    finally:
        if os_module.path.exists(tmp_path):
            os_module.remove(tmp_path)

    # 10. 清理
    renderer.Context.Remove(ais_shape, True)
    renderer.EraseAll()

    return {
        "png_base64": png_b64,
        "width": image_size[0],
        "height": image_size[1],
        "view_dir": (float(view_dir.X()), float(view_dir.Y()), float(view_dir.Z())),
        "up_dir": (float(up_dir.X()), float(up_dir.Y()), float(up_dir.Z()))
    }


def _extract_2d_segments(shape):
    """将 HLR 投影后的 shape 转换为 2D 线段/圆弧数据

    HLR 输出的边是 3D 的(在投影平面上),需要提取为 2D 坐标。
    """
    if shape is None or shape.IsNull():
        return []

    segments = []
    explorer = TopExp_Explorer(shape, TopAbs_EDGE)

    while explorer.More():
        edge = topods.Edge(explorer.Current())
        segments.extend(_edge_to_segments(edge))
        explorer.Next()

    return segments


def _edge_to_segments(edge):
    """将一条边转换为 2D 线段/圆弧数据(含元数据)

    元数据 meta 用于模板边线匹配:
      - line: orientation(horizontal/vertical/diagonal), length, midpoint
      - circle: radius, center
    """
    segments = []

    try:
        adaptor = BRepAdaptor_Curve(edge)
        curve_type = adaptor.GetType()

        if curve_type == 0:  # GeomAbs_Line
            start = adaptor.Value(adaptor.FirstParameter())
            end = adaptor.Value(adaptor.LastParameter())
            x1, y1 = float(start.X()), float(start.Y())
            x2, y2 = float(end.X()), float(end.Y())
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 0.001:
                return segments
            # 方向判断
            if abs(dy) < 0.1:
                orientation = "horizontal"
            elif abs(dx) < 0.1:
                orientation = "vertical"
            else:
                orientation = "diagonal"
            segments.append({
                "type": "line",
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "meta": {
                    "orientation": orientation,
                    "length": round(length, 2),
                    "midpoint": [round((x1 + x2) / 2, 2), round((y1 + y2) / 2, 2)]
                }
            })
        elif curve_type == 1:  # GeomAbs_Circle
            circ = adaptor.Circle()
            center = circ.Location()
            radius = circ.Radius()
            u1 = adaptor.FirstParameter()
            u2 = adaptor.LastParameter()
            if abs(u2 - u1 - 2 * math.pi) < 0.1:
                segments.append({
                    "type": "circle",
                    "cx": float(center.X()), "cy": float(center.Y()),
                    "r": float(radius),
                    "meta": {
                        "radius": round(float(radius), 2),
                        "center": [round(float(center.X()), 2), round(float(center.Y()), 2)]
                    }
                })
            else:
                pts = _discretize_curve(adaptor)
                if pts:
                    segments.append({"type": "polyline", "points": pts})
        else:
            pts = _discretize_curve(adaptor)
            if pts:
                segments.append({"type": "polyline", "points": pts})
    except Exception:
        pass

    return segments


def _discretize_curve(adaptor, deflection=0.1):
    """将曲线离散为 2D 点列表

    Args:
        adaptor: BRepAdaptor_Curve
        deflection: 离散精度(mm)

    Returns:
        [[x1,y1], [x2,y2], ...] 或 None
    """
    try:
        u1 = adaptor.FirstParameter()
        u2 = adaptor.LastParameter()
        if u2 <= u1:
            return None

        sampler = GCPnts_QuasiUniformDeflection(adaptor, deflection)
        if sampler.NbPoints() < 2:
            # 退化为直线
            p1 = adaptor.Value(u1)
            p2 = adaptor.Value(u2)
            return [[float(p1.X()), float(p1.Y())], [float(p2.X()), float(p2.Y())]]

        pts = []
        for i in range(1, sampler.NbPoints() + 1):
            p = sampler.Value(i)
            pts.append([float(p.X()), float(p.Y())])
        return pts
    except Exception:
        return None


def _compute_bbox(segments_list):
    """计算所有线段的包围盒

    Returns:
        (min_x, min_y, max_x, max_y)
    """
    min_x = min_y = float('inf')
    max_x = max_y = float('-inf')

    for segs in segments_list:
        for seg in segs:
            if seg["type"] == "line":
                for x, y in [(seg["x1"], seg["y1"]), (seg["x2"], seg["y2"])]:
                    min_x = min(min_x, x); max_x = max(max_x, x)
                    min_y = min(min_y, y); max_y = max(max_y, y)
            elif seg["type"] == "circle":
                cx, cy, r = seg["cx"], seg["cy"], seg["r"]
                min_x = min(min_x, cx - r); max_x = max(max_x, cx + r)
                min_y = min(min_y, cy - r); max_y = max(max_y, cy + r)
            elif seg["type"] == "polyline":
                for x, y in seg["points"]:
                    min_x = min(min_x, x); max_x = max(max_x, x)
                    min_y = min(min_y, y); max_y = max(max_y, y)

    if min_x == float('inf'):
        return 0, 0, 0, 0
    return min_x, min_y, max_x, max_y


def _normalize_view(segments, hidden_segments, target_width=400, target_height=300,
                    uniform_scale=None):
    """归一化视图坐标到 [0, target_width] x [0, target_height]

    保持宽高比,居中放置。

    Args:
        segments: 可见边线段列表
        hidden_segments: 隐藏边线段列表
        target_width: 目标宽度
        target_height: 目标高度
        uniform_scale: 统一缩放比例(由外部传入,确保所有视图比例一致)。
                       为 None 时自动计算(旧行为,仅用于独立视图生成)。
    """
    all_segs = segments + hidden_segments
    if not all_segs:
        return segments, hidden_segments, {"x": 0, "y": 0, "width": 0, "height": 0, "scale": 1}

    min_x, min_y, max_x, max_y = _compute_bbox([all_segs])
    width = max_x - min_x
    height = max_y - min_y

    if width < 0.01 or height < 0.01:
        return segments, hidden_segments, {"x": 0, "y": 0, "width": 0, "height": 0, "scale": 1}

    margin = 10
    avail_w = target_width - 2 * margin
    avail_h = target_height - 2 * margin

    # 统一缩放:所有视图使用相同的 scale(基于模型3D包围盒),
    # 确保视图之间大小成比例(如 SolidWorks 工程图)
    if uniform_scale is not None:
        scale = uniform_scale
    else:
        # 独立缩放(旧行为,仅用于 generate_view_by_name 等单视图场景)
        scale = min(avail_w / width, avail_h / height)

    # 居中偏移
    offset_x = margin + (avail_w - width * scale) / 2 - min_x * scale
    offset_y = margin + (avail_h - height * scale) / 2 - min_y * scale

    def transform_seg(seg):
        if seg["type"] == "line":
            return {
                "type": "line",
                "x1": round(seg["x1"] * scale + offset_x, 2),
                "y1": round(seg["y1"] * scale + offset_y, 2),
                "x2": round(seg["x2"] * scale + offset_x, 2),
                "y2": round(seg["y2"] * scale + offset_y, 2),
            }
        elif seg["type"] == "circle":
            return {
                "type": "circle",
                "cx": round(seg["cx"] * scale + offset_x, 2),
                "cy": round(seg["cy"] * scale + offset_y, 2),
                "r": round(seg["r"] * scale, 2),
            }
        elif seg["type"] == "polyline":
            return {
                "type": "polyline",
                "points": [[round(x * scale + offset_x, 2), round(y * scale + offset_y, 2)]
                           for x, y in seg["points"]]
            }
        return seg

    norm_segments = [transform_seg(s) for s in segments]
    norm_hidden = [transform_seg(s) for s in hidden_segments]

    bbox = {
        "x": 0, "y": 0,
        "width": target_width, "height": target_height,
        "scale": round(scale, 4),
        "orig_width": round(width, 2), "orig_height": round(height, 2)
    }

    return norm_segments, norm_hidden, bbox


def generate_drawing_views(step_path, views=None, target_width=400, target_height=300):
    """从 STEP 文件生成工程图视图

    Args:
        step_path: STEP 文件路径
        views: 要生成的视图列表,默认 ["front", "top", "left", "iso"]
        target_width: 每个视图的目标宽度(px)
        target_height: 每个视图的目标高度(px)

    Returns:
        {
            "views": {
                "front": {"visible": [...], "hidden": [...], "bbox": {...}},
                "top": {...},
                "left": {...},
                "iso": {...}
            },
            "model_bbox": {"width": ..., "height": ..., "depth": ...},
            "elapsed": float
        }
    """
    t0 = time.time()

    if views is None:
        views = ["front", "top", "left", "iso"]

    # 读取 STEP
    shape = read_step_to_shape(step_path)

    # 预三角化(PolyAlgo 要求 shape 已有三角化数据)
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    BRepMesh_IncrementalMesh(shape, 0.5, False, 0.5, True)

    # 计算模型包围盒(用于确定投影方向和视图比例)
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    bbox = Bnd_Box()
    brepbndlib.Add(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    model_bbox = {
        "width": round(float(xmax - xmin), 2),
        "height": round(float(ymax - ymin), 2),
        "depth": round(float(zmax - zmin), 2)
    }

    # 定义投影方向
    # 液压缸通常沿 X 轴水平放置
    # 主视图:沿 Y 轴负方向看(看到 X-Z 平面)
    # 俯视图:沿 Z 轴负方向看(看到 X-Y 平面)
    # 侧视图:沿 X 轴负方向看(看到 Y-Z 平面)
    # 轴测视图:等轴测方向
    view_configs = {
        "front": {
            "dir": gp_Dir(0, -1, 0),  # 沿 -Y 方向投影
            "up": gp_Dir(0, 0, 1),    # Z 轴向上
            "label": "主视图"
        },
        "top": {
            "dir": gp_Dir(0, 0, -1),  # 沿 -Z 方向投影
            "up": gp_Dir(0, 1, 0),    # Y 轴向上(俯视图的"上"是模型的 Y 方向)
            "label": "俯视图"
        },
        "left": {
            "dir": gp_Dir(-1, 0, 0),  # 沿 -X 方向投影
            "up": gp_Dir(0, 0, 1),    # Z 轴向上
            "label": "侧视图"
        },
        "iso": {
            "dir": gp_Dir(1, -1, 1),  # 等轴测方向
            "up": gp_Dir(0, 0, 1),    # Z 轴向上
            "label": "轴测视图"
        }
    }

    result_views = {}
    for view_name in views:
        if view_name not in view_configs:
            continue

        cfg = view_configs[view_name]
        t1 = time.time()
        visible, hidden = _project_shape(shape, cfg["dir"], cfg["up"])
        t2 = time.time()

        # 归一化坐标
        norm_visible, norm_hidden, view_bbox = _normalize_view(
            visible, hidden, target_width, target_height
        )

        result_views[view_name] = {
            "label": cfg["label"],
            "visible": norm_visible,
            "hidden": norm_hidden,
            "bbox": view_bbox,
            "seg_count": len(norm_visible),
            "hidden_count": len(norm_hidden),
            "project_time": round(t2 - t1, 3)
        }

    elapsed = time.time() - t0
    return {
        "views": result_views,
        "model_bbox": model_bbox,
        "elapsed": round(elapsed, 3)
    }


def generate_drawing_json(step_path, output_path, views=None,
                          target_width=400, target_height=300):
    """生成工程图视图 JSON 文件

    Args:
        step_path: STEP 文件路径
        output_path: 输出 JSON 路径
        views: 视图列表
        target_width: 视图宽度
        target_height: 视图高度

    Returns:
        (output_path, elapsed_time)
    """
    result = generate_drawing_views(step_path, views, target_width, target_height)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return output_path, result["elapsed"]


def generate_drawing_views_fast(step_path, views=None, target_width=400, target_height=300):
    """快速生成工程图视图(优化版)

    优化点:
        1. 三角化参数 2.0mm(原 0.5mm) → 三角化和 HLR 都更快
        2. 离散精度 0.5mm(原 0.1mm) → 输出数据量更少
        3. 默认只生成 2 个视图(front+top),按需添加
        4. STEP 读取跳过几何校验(忽略文件头格式问题)

    Args:
        step_path: STEP 文件路径
        views: 视图列表,默认 ["front", "top"]
        target_width: 视图宽度(px)
        target_height: 视图高度(px)

    Returns:
        同 generate_drawing_views
    """
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib

    t0 = time.time()

    if views is None:
        views = ["front", "top"]

    # 读取 shape(使用 BRep 缓存,比 STEP 快 14 倍)
    shape = read_shape_cached(step_path)
    t_read = time.time() - t0

    # 预三角化(2.0mm 精度,足够工程图使用)
    t1 = time.time()
    BRepMesh_IncrementalMesh(shape, 2.0, False, 2.0, True)
    t_mesh = time.time() - t1

    # 包围盒
    bbox = Bnd_Box()
    brepbndlib.Add(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    model_bbox = {
        "width": round(float(xmax - xmin), 2),
        "height": round(float(ymax - ymin), 2),
        "depth": round(float(zmax - zmin), 2)
    }

    view_configs = {
        "front": {"dir": gp_Dir(0, -1, 0), "up": gp_Dir(0, 0, 1), "label": "主视图"},
        "top":   {"dir": gp_Dir(0, 0, -1), "up": gp_Dir(0, 1, 0), "label": "俯视图"},
        "left":  {"dir": gp_Dir(-1, 0, 0), "up": gp_Dir(0, 0, 1), "label": "侧视图"},
        "iso":   {"dir": gp_Dir(1, -1, 1), "up": gp_Dir(0, 0, 1), "label": "轴测视图"},
    }

    result_views = {}
    for view_name in views:
        if view_name not in view_configs:
            continue
        cfg = view_configs[view_name]
        t2 = time.time()
        visible, hidden = _project_shape(shape, cfg["dir"], cfg["up"])
        t_proj = time.time() - t2

        norm_visible, norm_hidden, view_bbox = _normalize_view(
            visible, hidden, target_width, target_height
        )
        result_views[view_name] = {
            "label": cfg["label"],
            "visible": norm_visible,
            "hidden": norm_hidden,
            "bbox": view_bbox,
            "seg_count": len(norm_visible),
            "hidden_count": len(norm_hidden),
            "project_time": round(t_proj, 3)
        }

    elapsed = time.time() - t0
    return {
        "views": result_views,
        "model_bbox": model_bbox,
        "elapsed": round(elapsed, 3),
        "timing": {
            "read": round(t_read, 3),
            "mesh": round(t_mesh, 3),
            "total": round(elapsed, 3)
        }
    }


def _assign_bbox_roles(segments):
    """为边线分配包围盒角色(bbox_role)

    找出包围盒四条边界上的边线,标记为:
      bbox_x_min / bbox_x_max / bbox_y_min / bbox_y_max

    用于模板边线匹配(如"最左侧的竖直边"= bbox_x_min)。
    """
    if not segments:
        return segments

    min_x = min_y = float('inf')
    max_x = max_y = float('-inf')

    for seg in segments:
        if seg["type"] == "line":
            min_x = min(min_x, seg["x1"], seg["x2"])
            max_x = max(max_x, seg["x1"], seg["x2"])
            min_y = min(min_y, seg["y1"], seg["y2"])
            max_y = max(max_y, seg["y1"], seg["y2"])
        elif seg["type"] == "circle":
            min_x = min(min_x, seg["cx"] - seg["r"])
            max_x = max(max_x, seg["cx"] + seg["r"])
            min_y = min(min_y, seg["cy"] - seg["r"])
            max_y = max(max_y, seg["cy"] + seg["r"])

    if min_x == float('inf'):
        return segments

    tol = 0.5  # 0.5mm 容差
    for seg in segments:
        if "meta" not in seg:
            seg["meta"] = {}
        roles = []
        if seg["type"] == "line":
            if seg["meta"].get("orientation") == "vertical":
                if abs(min(seg["x1"], seg["x2"]) - min_x) < tol:
                    roles.append("bbox_x_min")
                if abs(max(seg["x1"], seg["x2"]) - max_x) < tol:
                    roles.append("bbox_x_max")
            elif seg["meta"].get("orientation") == "horizontal":
                if abs(min(seg["y1"], seg["y2"]) - min_y) < tol:
                    roles.append("bbox_y_min")
                if abs(max(seg["y1"], seg["y2"]) - max_y) < tol:
                    roles.append("bbox_y_max")
        if roles:
            seg["meta"]["bbox_roles"] = roles

    return segments


def generate_drawing_views_raw(step_path, views=None):
    """生成工程图视图(模型坐标空间,含元数据,用于 DXF 导出)

    与 generate_drawing_views_fast 的区别:
      - 不做归一化,保留模型实际坐标(mm)
      - 边线含完整元数据(方向/长度/中点/包围盒角色)
      - 圆保留圆心+半径(不离散)
      - 返回每个视图的包围盒(用于布局)

    Args:
        step_path: STEP 文件路径
        views: 视图列表,默认 ["front", "top"]

    Returns:
        {
            "views": {
                "front": {"label": ..., "visible": [...], "hidden": [...],
                          "bbox": {"min_x", "min_y", "max_x", "max_y", "width", "height"}},
                ...
            },
            "model_bbox": {"width", "height", "depth"},
            "elapsed": float
        }
    """
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib

    t0 = time.time()

    if views is None:
        views = ["front", "top"]

    shape = read_shape_cached(step_path)
    t_read = time.time() - t0

    BRepMesh_IncrementalMesh(shape, 2.0, False, 2.0, True)
    t_mesh = time.time() - t0 - t_read

    bbox = Bnd_Box()
    brepbndlib.Add(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    model_bbox = {
        "width": round(float(xmax - xmin), 2),
        "height": round(float(ymax - ymin), 2),
        "depth": round(float(zmax - zmin), 2)
    }

    view_configs = {
        "front": {"dir": gp_Dir(0, -1, 0), "up": gp_Dir(0, 0, 1), "label": "主视图"},
        "top":   {"dir": gp_Dir(0, 0, -1), "up": gp_Dir(0, 1, 0), "label": "俯视图"},
        "left":  {"dir": gp_Dir(-1, 0, 0), "up": gp_Dir(0, 0, 1), "label": "侧视图"},
        "iso":   {"dir": gp_Dir(1, -1, 1), "up": gp_Dir(0, 0, 1), "label": "轴测视图"},
    }

    result_views = {}
    for view_name in views:
        if view_name not in view_configs:
            continue
        cfg = view_configs[view_name]
        visible, hidden = _project_shape(shape, cfg["dir"], cfg["up"])

        # 分配包围盒角色
        visible = _assign_bbox_roles(visible)
        hidden = _assign_bbox_roles(hidden)

        # 计算视图包围盒(模型坐标)
        min_x, min_y, max_x, max_y = _compute_bbox([visible, hidden])
        view_bbox = {
            "min_x": round(min_x, 2), "min_y": round(min_y, 2),
            "max_x": round(max_x, 2), "max_y": round(max_y, 2),
            "width": round(max_x - min_x, 2),
            "height": round(max_y - min_y, 2)
        }

        result_views[view_name] = {
            "label": cfg["label"],
            "visible": visible,
            "hidden": hidden,
            "bbox": view_bbox,
            "seg_count": len(visible)
        }

    elapsed = time.time() - t0
    return {
        "views": result_views,
        "model_bbox": model_bbox,
        "elapsed": round(elapsed, 3)
    }


# ===================== SolidWorks 风格视图面板 =====================

# 9 个标准视图配置(对应 SolidWorks 视图调色板)
# dir: 投影方向(从该方向看模型)
# up:  视图上方向(控制视图旋转)
STANDARD_VIEW_CONFIGS = {
    # 6 个基本视图
    "front":    {"dir": gp_Dir(0, -1, 0),  "up": gp_Dir(0, 0, 1),  "label": "前视",  "group": "standard"},
    "back":     {"dir": gp_Dir(0, 1, 0),   "up": gp_Dir(0, 0, 1),  "label": "后视",  "group": "standard"},
    "left":     {"dir": gp_Dir(-1, 0, 0),  "up": gp_Dir(0, 0, 1),  "label": "左视",  "group": "standard"},
    "right":    {"dir": gp_Dir(1, 0, 0),   "up": gp_Dir(0, 0, 1),  "label": "右视",  "group": "standard"},
    "top":      {"dir": gp_Dir(0, 0, -1),  "up": gp_Dir(0, 1, 0),  "label": "上视",  "group": "standard"},
    "bottom":   {"dir": gp_Dir(0, 0, 1),   "up": gp_Dir(0, -1, 0), "label": "下视",  "group": "standard"},
    # 3 个轴测视图
    "isometric":      {"dir": gp_Dir(1, -1, 1),    "up": gp_Dir(0, 0, 1), "label": "等轴测",       "group": "isometric"},
    "dimetric_left":  {"dir": gp_Dir(-1, -1, 0.5), "up": gp_Dir(0, 0, 1), "label": "左右二等角",   "group": "isometric"},
    "dimetric_right": {"dir": gp_Dir(1, -1, 0.5),  "up": gp_Dir(0, 0, 1), "label": "上下二等角",   "group": "isometric"},
}


def _segments_to_svg(segments, hidden_segments=None, width=120, height=90,
                     stroke_color="#333333", hidden_color="#999999",
                     stroke_width=0.8, bg_color="#ffffff"):
    """将 2D 线段数据转换为 SVG 字符串(用于视图缩略图)

    自动归一化到指定宽高,保持宽高比居中。

    Args:
        segments: 可见边线段列表
        hidden_segments: 隐藏边线段列表(可选,虚线渲染)
        width/height: SVG 画布尺寸
        stroke_color: 可见边颜色
        hidden_color: 隐藏边颜色
        stroke_width: 线宽
        bg_color: 背景色

    Returns:
        SVG 字符串
    """
    hidden_segments = hidden_segments or []
    all_segs = segments + hidden_segments
    if not all_segs:
        return f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">' \
               f'<rect width="{width}" height="{height}" fill="{bg_color}"/>' \
               f'<text x="{width//2}" y="{height//2}" text-anchor="middle" fill="#ccc" font-size="10">空</text>' \
               f'</svg>'

    # 归一化
    norm_visible, norm_hidden, _ = _normalize_view(
        segments, hidden_segments, width, height
    )

    parts = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" '
             f'viewBox="0 0 {width} {height}">']
    parts.append(f'<rect width="{width}" height="{height}" fill="{bg_color}"/>')

    # 隐藏边(虚线)
    for seg in norm_hidden:
        if seg["type"] == "line":
            parts.append(f'<line x1="{seg["x1"]}" y1="{seg["y1"]}" x2="{seg["x2"]}" y2="{seg["y2"]}" '
                        f'stroke="{hidden_color}" stroke-width="{stroke_width}" '
                        f'stroke-dasharray="2,2"/>')
        elif seg["type"] == "circle":
            parts.append(f'<circle cx="{seg["cx"]}" cy="{seg["cy"]}" r="{seg["r"]}" '
                        f'stroke="{hidden_color}" stroke-width="{stroke_width}" fill="none" '
                        f'stroke-dasharray="2,2"/>')
        elif seg["type"] == "polyline":
            pts = " ".join(f"{x},{y}" for x, y in seg["points"])
            parts.append(f'<polyline points="{pts}" stroke="{hidden_color}" '
                        f'stroke-width="{stroke_width}" fill="none" stroke-dasharray="2,2"/>')

    # 可见边(实线)
    for seg in norm_visible:
        if seg["type"] == "line":
            parts.append(f'<line x1="{seg["x1"]}" y1="{seg["y1"]}" x2="{seg["x2"]}" y2="{seg["y2"]}" '
                        f'stroke="{stroke_color}" stroke-width="{stroke_width}"/>')
        elif seg["type"] == "circle":
            parts.append(f'<circle cx="{seg["cx"]}" cy="{seg["cy"]}" r="{seg["r"]}" '
                        f'stroke="{stroke_color}" stroke-width="{stroke_width}" fill="none"/>')
        elif seg["type"] == "polyline":
            pts = " ".join(f"{x},{y}" for x, y in seg["points"])
            parts.append(f'<polyline points="{pts}" stroke="{stroke_color}" '
                        f'stroke-width="{stroke_width}" fill="none"/>')

    parts.append('</svg>')
    return "".join(parts)


def generate_all_standard_views(step_path, include_hidden=False,
                                thumb_size=(200, 150),
                                canvas_size=(400, 300)):
    """生成所有 9 个标准视图(PNG 图像,基于 OCC 离屏渲染)

    使用 OCC OffscreenRenderer + HLR 模式,从 3D 模型生成 2D 工程图视图。
    这是 SolidWorks 等专业软件内部使用的方法,效果可靠、速度极快。

    Args:
        step_path: STEP 文件路径
        include_hidden: 已通过 HLR 模式自动处理,此参数保留向后兼容
        thumb_size: 缩略图尺寸 (width, height)
        canvas_size: 画布大图尺寸 (width, height)

    Returns:
        {
            "views": {
                "front": {
                    "label": "前视",
                    "group": "standard",
                    "thumbnail": "data:image/png;base64,...",
                    "image": "data:image/png;base64,...",
                    "thumbnail_size": [w, h],
                    "image_size": [w, h],
                    "project_time": float
                },
                ...
            },
            "model_bbox": {"width", "height", "depth"},
            "elapsed": float,
            "timing": {"read": float, "render": float, "total": float}
        }
    """
    t0 = time.time()

    # 读取 shape(使用 BRep 缓存)
    shape = read_shape_cached(step_path)
    t_read = time.time() - t0

    # 模型包围盒
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    bbox = Bnd_Box()
    brepbndlib.Add(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    model_bbox = {
        "width": round(float(xmax - xmin), 2),
        "height": round(float(ymax - ymin), 2),
        "depth": round(float(zmax - zmin), 2)
    }

    # 共享渲染器(9 视图复用 1 个)
    t1 = time.time()
    renderer = _create_shared_renderer(shape)
    result_views = {}
    for view_name, cfg in STANDARD_VIEW_CONFIGS.items():
        t2 = time.time()
        # 设置视图方向
        _set_view_orientation(renderer, cfg["dir"], cfg["up"])
        renderer.FitAll()
        renderer.Context.UpdateCurrentViewer()
        renderer.Repaint()

        # 缩略图
        thumb_png = _render_to_base64(renderer, thumb_size)
        # 大图(用于画布放置)
        canvas_png = _render_to_base64(renderer, canvas_size)
        t_proj = time.time() - t2

        result_views[view_name] = {
            "label": cfg["label"],
            "group": cfg["group"],
            "thumbnail": f"data:image/png;base64,{thumb_png}",
            "image": f"data:image/png;base64,{canvas_png}",
            "thumbnail_size": list(thumb_size),
            "image_size": list(canvas_size),
            "project_time": round(t_proj, 3)
        }
    _destroy_renderer(renderer)
    t_render = time.time() - t1

    elapsed = time.time() - t0
    return {
        "views": result_views,
        "model_bbox": model_bbox,
        "elapsed": round(elapsed, 3),
        "timing": {
            "read": round(t_read, 3),
            "render": round(t_render, 3),
            "total": round(elapsed, 3)
        }
    }


def _create_shared_renderer(shape):
    """创建共享渲染器(供 generate_all_standard_views 一次性创建复用)

    9 视图渲染只创建 1 个渲染器,显著降低初始化开销。
    """
    from OCC.Display.OCCViewer import OffscreenRenderer
    from OCC.Core.Quantity import Quantity_Color, Quantity_NOC_BLACK
    from OCC.Core.AIS import AIS_Shape

    renderer = OffscreenRenderer(screen_size=(400, 300))
    renderer.hide_triedron()

    # 白色背景
    white = Quantity_Color(1.0, 1.0, 1.0, 0)
    renderer.set_bg_gradient_color(white, white)

    # HLR 模式(隐藏线消除)
    renderer.SetModeHLR()
    # 关闭阴影
    renderer.View.SetShadingModel(0)
    # 正交投影
    renderer.View.Camera().SetProjectionType(0)

    # 显示形状(黑色线框)
    ais_shape = AIS_Shape(shape)
    ais_shape.SetColor(Quantity_Color(Quantity_NOC_BLACK))
    renderer.Context.Display(ais_shape, True)
    renderer._shared_ais = ais_shape  # 保存引用供清理

    return renderer


def _set_view_orientation(renderer, view_dir, up_dir):
    """设置渲染器视图方向

    pythonOCC V3d_View API 参数规范(参考 OCC 官方文档):
      - SetAt(X, Y, Z): 3 个 double,设置视图中心点
      - SetUp(X, Y, Z): 3 个 double,设置上方向
      - SetProj(Vx, Vy, Vz): 3 个 double,设置投影方向
      - SetEye(X, Y, Z): 3 个 double,设置眼睛位置

    注意: 这些方法不接受 gp_Pnt/gp_Dir 对象,而是接受 3 个 double。
    pythonOCC 的 SWIG 绑定要求严格匹配参数个数。

    简化方案: 仅使用 SetProj(Vx, Vy, Vz),OCC 会自动计算 eye 和 up。
    """
    # 仅设置投影方向(OCC 自动计算 eye/up)
    renderer.View.SetProj(
        float(view_dir.X()),
        float(view_dir.Y()),
        float(view_dir.Z())
    )


def _render_to_base64(renderer, size):
    """将当前渲染器视图渲染为指定尺寸的 PNG,返回 base64 字符串"""
    import base64
    import tempfile
    import os as os_module

    renderer.View.SetSize(size[0], size[1])
    renderer.View.MustBeResized()
    renderer.Context.UpdateCurrentViewer()
    renderer.Repaint()

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        renderer.View.Dump(tmp_path)
        with open(tmp_path, 'rb') as f:
            png_bytes = f.read()
        return base64.b64encode(png_bytes).decode('ascii')
    finally:
        if os_module.path.exists(tmp_path):
            os_module.remove(tmp_path)


def _destroy_renderer(renderer):
    """清理渲染器资源"""
    try:
        if hasattr(renderer, '_shared_ais'):
            renderer.Context.Remove(renderer._shared_ais, True)
        renderer.EraseAll()
    except Exception:
        pass


def _generate_all_standard_views_legacy(step_path, include_hidden=False,
                                        thumb_width=120, thumb_height=90,
                                        canvas_width=400, canvas_height=300):
    """[已弃用] 旧版基于 HLRBRep_PolyAlgo 边线数据的视图生成函数

    保留此函数以向后兼容(供旧接口或单元测试使用)。
    新代码应使用 generate_all_standard_views()(基于离屏渲染)。
    """
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib

    t0 = time.time()

    # 读取 shape(使用 BRep 缓存)
    shape = read_shape_cached(step_path)
    t_read = time.time() - t0

    # 预三角化
    t1 = time.time()
    BRepMesh_IncrementalMesh(shape, 2.0, False, 2.0, True)
    t_mesh = time.time() - t1

    # 模型包围盒
    bbox = Bnd_Box()
    brepbndlib.Add(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    model_bbox = {
        "width": round(float(xmax - xmin), 2),
        "height": round(float(ymax - ymin), 2),
        "depth": round(float(zmax - zmin), 2)
    }

    result_views = {}
    # ===== 第一遍: 投影所有视图,收集原始2D坐标 =====
    raw_views = {}
    for view_name, cfg in STANDARD_VIEW_CONFIGS.items():
        t2 = time.time()
        # 使用多边形离散算法(速度快 10-20 倍),shape 已预三角化
        visible, hidden = _project_shape_poly(
            shape, cfg["dir"], cfg["up"], show_hidden=include_hidden
        )
        t_proj = time.time() - t2
        raw_views[view_name] = {
            "visible": visible,
            "hidden": hidden,
            "label": cfg["label"],
            "group": cfg["group"],
            "project_time": round(t_proj, 3)
        }

    # ===== 计算统一缩放比例 =====
    # 基于所有视图的2D包围盒,取最大尺寸,确保所有视图比例一致
    all_raw = []
    for rv in raw_views.values():
        all_raw.extend(rv["visible"])
        all_raw.extend(rv["hidden"])

    if all_raw:
        min_x, min_y, max_x, max_y = _compute_bbox([all_raw])
        max_2d_extent = max(max_x - min_x, max_y - min_y)
    else:
        max_2d_extent = 1.0

    # 统一缩放:基于最大2D尺寸,缩放到画布可用区域
    margin = 10
    avail = min(canvas_width - 2 * margin, canvas_height - 2 * margin)
    uniform_scale = avail / max_2d_extent if max_2d_extent > 0.01 else 1.0

    # ===== 第二遍: 用统一缩放比例归一化所有视图 =====
    for view_name, rv in raw_views.items():
        # 缩略图(独立缩放,填满小画布)
        thumb_visible, thumb_hidden, _ = _normalize_view(
            rv["visible"], rv["hidden"], thumb_width, thumb_height
        )
        thumbnail = _segments_to_svg(
            thumb_visible, thumb_hidden, thumb_width, thumb_height
        )

        # 画布边线(统一缩放,所有视图比例一致)
        canvas_visible, canvas_hidden, canvas_bbox = _normalize_view(
            rv["visible"], rv["hidden"], canvas_width, canvas_height,
            uniform_scale=uniform_scale
        )

        result_views[view_name] = {
            "label": rv["label"],
            "group": rv["group"],
            "thumbnail": thumbnail,
            "edges": canvas_visible,
            "hidden_edges": canvas_hidden,
            "bbox": canvas_bbox,
            "seg_count": len(canvas_visible),
            "hidden_count": len(canvas_hidden),
            "project_time": rv["project_time"]
        }

    elapsed = time.time() - t0
    return {
        "views": result_views,
        "model_bbox": model_bbox,
        "elapsed": round(elapsed, 3),
        "timing": {
            "read": round(t_read, 3),
            "mesh": round(t_mesh, 3),
            "total": round(elapsed, 3)
        }
    }


def generate_view_by_name(step_path, view_name, target_width=400, target_height=300,
                          include_hidden=False):
    """按视图名生成单个视图的投影数据(用于按需生成)

    Args:
        step_path: STEP 文件路径
        view_name: 视图名(front/back/left/right/top/bottom/isometric/dimetric_left/dimetric_right)
        target_width: 视图宽度
        target_height: 视图高度
        include_hidden: 是否生成隐藏边

    Returns:
        {
            "view_name": ...,
            "label": ...,
            "visible": [...],
            "hidden": [...],
            "bbox": {...},
            "seg_count": int
        }
        或 None(视图名无效)
    """
    if view_name not in STANDARD_VIEW_CONFIGS:
        return None

    cfg = STANDARD_VIEW_CONFIGS[view_name]
    shape = read_shape_cached(step_path)

    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    BRepMesh_IncrementalMesh(shape, 2.0, False, 2.0, True)

    visible, hidden = _project_shape(
        shape, cfg["dir"], cfg["up"], show_hidden=include_hidden
    )

    norm_visible, norm_hidden, view_bbox = _normalize_view(
        visible, hidden, target_width, target_height
    )

    return {
        "view_name": view_name,
        "label": cfg["label"],
        "visible": norm_visible,
        "hidden": norm_hidden,
        "bbox": view_bbox,
        "seg_count": len(norm_visible),
        "hidden_count": len(norm_hidden)
    }


# ---------- 测试入口 ----------
if __name__ == "__main__":
    import sys

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        step = r"e:\分享代码\step__glb_pdf\output\250-E-H2K1-L100-D11\assembly.step"
    else:
        step = args[0]

    if not os.path.exists(step):
        print(f"STEP 文件不存在: {step}")
        sys.exit(1)

    print(f"输入: {step}")
    out = os.path.join(os.path.dirname(step), "views.json")

    # 快速模式(2视图, 2.0mm精度)
    use_fast = "--fast" in sys.argv
    if use_fast:
        print("=== 快速模式 ===")
        result = generate_drawing_views_fast(step)
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"输出: {out}")
        print(f"耗时: {result['elapsed']:.3f}s")
        if "timing" in result:
            print(f"  读取: {result['timing']['read']}s, 三角化: {result['timing']['mesh']}s")
        for name, view in result["views"].items():
            print(f"  {view['label']}: {view['seg_count']} 可见边, "
                  f"{view['hidden_count']} 隐藏边, {view['project_time']}s")
    else:
        path, elapsed = generate_drawing_json(step, out)
        print(f"输出: {path}")
        print(f"耗时: {elapsed:.3f}s")

    # 打印统计
    import json as _json
    with open(out, 'r', encoding='utf-8') as f:
        data = _json.load(f)
    print(f"模型包围盒: {data['model_bbox']}")
    for name, view in data["views"].items():
        print(f"  {view['label']}: {view['seg_count']} 可见边, "
              f"{view['hidden_count']} 隐藏边, {view['project_time']}s")
