# -*- coding: utf-8 -*-
"""
工程图模板引擎 — 关联式标注系统

核心功能:
  1. 加载工程图模板 JSON(定义视图布局 + 标注引用规则)
  2. 边线匹配: 将模板中的引用规则匹配到实际投影边线
  3. 尺寸自动计算: 根据匹配到的边线计算实际尺寸值(线性/孔/角度)

模板中的标注不是写死坐标,而是"引用规则"(如 bbox_x_min = 最左侧竖直边)。
当模型变化时,重新投影→重新匹配→重新计算尺寸值,实现关联标注。

匹配方法:
  - bbox_x_min / bbox_x_max: 包围盒最左/右侧的竖直边
  - bbox_y_min / bbox_y_max: 包围盒最底/顶部的水平边
  - largest_circle: 半径最大的圆
  - longest_edge: 指定方向上最长的边
  - smallest_circle: 半径最小的圆(用于孔标注)

调用方式:
    from drawing_template import apply_template
    result = apply_template(views_data, template, params)
"""
import json
import math
import os


# ==================== 模板加载 ====================

def load_template(template_path):
    """加载工程图模板 JSON

    Args:
        template_path: 模板文件路径

    Returns:
        dict: 模板数据
    """
    with open(template_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_default_template():
    """加载默认液压缸工程图模板"""
    template_path = os.path.join(os.path.dirname(__file__), "drawing_template.json")
    if os.path.exists(template_path):
        return load_template(template_path)
    return _get_builtin_template()


def load_anchors(anchors_path):
    """加载工程图语义锚点 JSON"""
    with open(anchors_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_default_anchors():
    """加载默认液压缸语义锚点"""
    anchors_path = os.path.join(os.path.dirname(__file__), "drawing_anchors.json")
    if os.path.exists(anchors_path):
        return load_anchors(anchors_path)
    return _get_builtin_anchors()


def _get_builtin_template():
    """内置默认模板(液压缸)"""
    return {
        "name": "液压缸工程图模板",
        "template_id": "250-E-H3K2",
        "version": 1,
        "sheet": {"size": "A3", "width": 420, "height": 297},
        "anchor_profile": "250-series-default",
        "views": [
            {"id": "front", "type": "front", "x": 80, "y": 180, "scale": "auto", "target_width": 180, "target_height": 120},
            {"id": "top",   "type": "top",   "x": 80, "y": 40,  "scale": "auto", "target_width": 180, "target_height": 100},
            {"id": "left",  "type": "left",  "x": 230, "y": 180, "scale": "auto", "target_width": 150, "target_height": 120}
        ],
        "dimensions": [
            {
                "id": "dim_total_length",
                "type": "linear",
                "view": "front",
                "orientation": "horizontal",
                "edge1_ref": {"method": "bbox_x_min"},
                "edge2_ref": {"method": "bbox_x_max"},
                "offset": 30,
                "label": "总长"
            },
            {
                "id": "dim_total_height",
                "type": "linear",
                "view": "front",
                "orientation": "vertical",
                "edge1_ref": {"method": "bbox_y_min"},
                "edge2_ref": {"method": "bbox_y_max"},
                "offset": 30,
                "label": "总高"
            },
            {
                "id": "dim_bore",
                "type": "diameter",
                "view": "left",
                "from_anchor": "cylinder.axis",
                "offset": 25,
                "label": "缸径"
            },
            {
                "id": "dim_stroke",
                "type": "linear",
                "view": "left",
                "orientation": "horizontal",
                "from_anchor": "cylinder.front_end",
                "to_anchor": "cylinder.back_end",
                "offset": 24,
                "label": "行程"
            }
        ],
        "title_block": {
            "fields": [
                {"name": "图样名称", "value": "{{series}}液压缸", "x": 280, "y": 20},
                {"name": "型号", "value": "{{model_code}}", "x": 280, "y": 35},
                {"name": "比例", "value": "1:{{scale}}", "x": 350, "y": 20},
                {"name": "日期", "value": "{{date}}", "x": 350, "y": 35}
            ]
        },
        "bom_table": {
            "position": {"x": 300, "y": 200},
            "columns": ["序号", "名称", "数量", "备注"]
        }
    }


def _get_builtin_anchors():
    """内置默认语义锚点(液压缸系列)"""
    return {
        "profile_id": "250-series-default",
        "version": 1,
        "anchors": [
            {
                "id": "cylinder.front_end",
                "type": "plane",
                "label": "缸筒前端面",
                "source": {"kind": "parameter", "name": "stroke_start"},
                "views": ["front", "left", "top"]
            },
            {
                "id": "cylinder.back_end",
                "type": "plane",
                "label": "缸筒后端面",
                "source": {"kind": "parameter", "name": "stroke_end"},
                "views": ["front", "left", "top"]
            },
            {
                "id": "cylinder.axis",
                "type": "axis",
                "label": "缸体中心轴",
                "source": {"kind": "geometry", "name": "main_axis"},
                "views": ["front", "left", "top"]
            },
            {
                "id": "motor.body",
                "type": "box",
                "label": "电机包络",
                "source": {"kind": "part", "name": "motor"},
                "views": ["right", "front"]
            },
            {
                "id": "mounting.hole_1",
                "type": "point",
                "label": "安装孔1",
                "source": {"kind": "geometry", "name": "mount_hole_1"},
                "views": ["front", "top"]
            },
            {
                "id": "mounting.hole_2",
                "type": "point",
                "label": "安装孔2",
                "source": {"kind": "geometry", "name": "mount_hole_2"},
                "views": ["front", "top"]
            }
        ]
    }


# ==================== 边线匹配引擎 ====================

def _fit_circles_from_polylines(segments, tolerance=0.05):
    """从 polyline 段中检测近似圆,返回拟合出的 circle 段列表

    HLR 会把圆弧输出为离散 polyline,导致 largest_circle 等匹配失效。
    此函数对每条 polyline 做圆拟合检测:
      1. 计算点集质心作为候选圆心
      2. 检查所有点到质心距离的变异系数 < tolerance
      3. 检查点数 >= 8(圆弧至少需要多点才可靠拟合)
      4. 检查点集角度跨度 >= 270°(接近完整圆)

    Args:
        segments: 边线列表
        tolerance: 距离变异系数阈值(默认 5%)

    Returns:
        list: 拟合出的 circle 段 [{"type":"circle","cx","cy","r"}, ...]
    """
    circles = []
    for seg in segments:
        if seg.get("type") != "polyline":
            continue
        pts = seg.get("points", [])
        if len(pts) < 8:
            continue

        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)

        # 计算各点到质心距离
        dists = [math.hypot(p[0] - cx, p[1] - cy) for p in pts]
        avg_r = sum(dists) / len(dists)
        if avg_r < 1.0:
            continue

        # 变异系数 = 标准差 / 均值
        variance = sum((d - avg_r) ** 2 for d in dists) / len(dists)
        cv = (variance ** 0.5) / avg_r
        if cv > tolerance:
            continue

        # 检查角度跨度(接近完整圆)
        import math as m
        angles = sorted(m.atan2(p[1] - cy, p[0] - cx) for p in pts)
        max_gap = 0
        for i in range(len(angles)):
            gap = angles[(i + 1) % len(angles)] - angles[i]
            if gap < 0:
                gap += 2 * m.pi
            max_gap = max(max_gap, gap)
        angle_span = 2 * m.pi - max_gap  # 总跨度

        if angle_span < m.radians(270):
            continue

        circles.append({
            "type": "circle",
            "cx": round(cx, 2),
            "cy": round(cy, 2),
            "r": round(avg_r, 2)
        })

    return circles


def _segments_with_fitted_circles(segments):
    """在 segments 中补充拟合出的圆(不修改原列表)"""
    fitted = _fit_circles_from_polylines(segments)
    if fitted:
        return segments + fitted
    return segments


def _find_edge_by_method(segments, method, **kwargs):
    """根据匹配方法找到对应的边线

    Args:
        segments: 视图的可见边线列表
        method: 匹配方法
        **kwargs: 额外参数(direction, tolerance 等)

    Returns:
        匹配到的边线 dict, 或 None
    """
    if not segments:
        return None

    direction = kwargs.get("direction", None)

    if method in ("bbox_x_min", "bbox_x_max"):
        # 找包围盒左/右侧的竖直边
        vertical_edges = [s for s in segments
                          if s["type"] == "line" and s.get("meta", {}).get("orientation") == "vertical"]
        if not vertical_edges:
            return None
        if method == "bbox_x_min":
            # x 值最小的竖直边
            return min(vertical_edges, key=lambda s: min(s["x1"], s["x2"]))
        else:
            return max(vertical_edges, key=lambda s: max(s["x1"], s["x2"]))

    elif method in ("bbox_y_min", "bbox_y_max"):
        # 找包围盒底/顶部的水平边
        horizontal_edges = [s for s in segments
                            if s["type"] == "line" and s.get("meta", {}).get("orientation") == "horizontal"]
        if not horizontal_edges:
            return None
        if method == "bbox_y_min":
            return min(horizontal_edges, key=lambda s: min(s["y1"], s["y2"]))
        else:
            return max(horizontal_edges, key=lambda s: max(s["y1"], s["y2"]))

    elif method == "largest_circle":
        # 半径最大的圆
        circles = [s for s in segments if s["type"] == "circle"]
        if not circles:
            return None
        return max(circles, key=lambda s: s["r"])

    elif method == "smallest_circle":
        # 半径最小的圆(排除极小圆)
        circles = [s for s in segments if s["type"] == "circle" and s["r"] > 1.0]
        if not circles:
            return None
        return min(circles, key=lambda s: s["r"])

    elif method == "longest_edge":
        # 指定方向上最长的边
        candidates = [s for s in segments if s["type"] == "line"]
        if direction:
            candidates = [s for s in candidates
                          if s.get("meta", {}).get("orientation") == direction]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.get("meta", {}).get("length", 0))

    elif method == "shortest_edge":
        candidates = [s for s in segments if s["type"] == "line"]
        if direction:
            candidates = [s for s in candidates
                          if s.get("meta", {}).get("orientation") == direction]
        if not candidates:
            return None
        return min(candidates, key=lambda s: s.get("meta", {}).get("length", 0))

    return None


def _match_edge(segments, ref):
    """匹配单条边线引用

    Args:
        segments: 视图边线列表
        ref: 引用规则 {"method": "bbox_x_min", "direction": "vertical"(可选)}

    Returns:
        匹配到的边线 dict, 或 None
    """
    if not ref or not isinstance(ref, dict):
        return None
    method = ref.get("method", "")
    direction = ref.get("direction")
    return _find_edge_by_method(segments, method, direction=direction)


# ==================== 尺寸计算 ====================

def _calc_linear_dimension(edge1, edge2, orientation):
    """计算线性标注值

    Args:
        edge1: 第一条边
        edge2: 第二条边
        orientation: horizontal / vertical / aligned

    Returns:
        {"value": float, "p1": [x,y], "p2": [x,y], "text": "xxx"}
    """
    if not edge1 or not edge2:
        return None

    # 取两条边的代表点(用于计算距离)
    if orientation == "horizontal":
        # 水平标注: 取两条边的 x 坐标范围
        x1_vals = [edge1.get("x1", 0), edge1.get("x2", 0)]
        x2_vals = [edge2.get("x1", 0), edge2.get("x2", 0)]
        # 取最外侧的点
        x1 = (min(x1_vals) + max(x1_vals)) / 2
        x2 = (min(x2_vals) + max(x2_vals)) / 2
        y = (edge1.get("y1", 0) + edge1.get("y2", 0)) / 2
        dist = abs(x2 - x1)
        return {
            "value": round(dist, 1),
            "p1": [round(x1, 2), round(y, 2)],
            "p2": [round(x2, 2), round(y, 2)],
            "text": f"{dist:.0f}"
        }

    elif orientation == "vertical":
        y1_vals = [edge1.get("y1", 0), edge1.get("y2", 0)]
        y2_vals = [edge2.get("y1", 0), edge2.get("y2", 0)]
        y1 = (min(y1_vals) + max(y1_vals)) / 2
        y2 = (min(y2_vals) + max(y2_vals)) / 2
        x = (edge1.get("x1", 0) + edge1.get("x2", 0)) / 2
        dist = abs(y2 - y1)
        return {
            "value": round(dist, 1),
            "p1": [round(x, 2), round(y1, 2)],
            "p2": [round(x, 2), round(y2, 2)],
            "text": f"{dist:.0f}"
        }

    else:  # aligned
        # 取两条边的中点
        if edge1["type"] == "line":
            p1 = [(edge1["x1"] + edge1["x2"]) / 2, (edge1["y1"] + edge1["y2"]) / 2]
        else:
            p1 = [edge1.get("cx", 0), edge1.get("cy", 0)]
        if edge2["type"] == "line":
            p2 = [(edge2["x1"] + edge2["x2"]) / 2, (edge2["y1"] + edge2["y2"]) / 2]
        else:
            p2 = [edge2.get("cx", 0), edge2.get("cy", 0)]
        dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        return {
            "value": round(dist, 1),
            "p1": [round(p1[0], 2), round(p1[1], 2)],
            "p2": [round(p2[0], 2), round(p2[1], 2)],
            "text": f"{dist:.0f}"
        }


def _calc_hole_dimension(circle_seg):
    """计算孔标注值

    Args:
        circle_seg: 圆边线 {"type": "circle", "cx", "cy", "r", "meta"}

    Returns:
        {"value": diameter, "center": [cx, cy], "text": "Øxxx"}
    """
    if not circle_seg or circle_seg["type"] != "circle":
        return None

    diameter = circle_seg["r"] * 2
    return {
        "value": round(diameter, 1),
        "center": [round(circle_seg["cx"], 2), round(circle_seg["cy"], 2)],
        "radius": round(circle_seg["r"], 2),
        "text": f"Ø{diameter:.0f}"
    }


def _calc_angle_dimension(edge1, edge2):
    """计算角度标注值

    Args:
        edge1: 第一条直线
        edge2: 第二条直线

    Returns:
        {"value": angle_deg, "vertex": [x,y], "text": "xx°"}
    """
    if not edge1 or not edge2:
        return None
    if edge1["type"] != "line" or edge2["type"] != "line":
        return None

    # 计算两条线的方向向量
    dx1 = edge1["x2"] - edge1["x1"]
    dy1 = edge1["y2"] - edge1["y1"]
    dx2 = edge2["x2"] - edge2["x1"]
    dy2 = edge2["y2"] - edge2["y1"]

    len1 = math.hypot(dx1, dy1)
    len2 = math.hypot(dx2, dy2)
    if len1 < 0.001 or len2 < 0.001:
        return None

    # 点积求夹角
    dot = dx1 * dx2 + dy1 * dy2
    cos_angle = max(-1.0, min(1.0, dot / (len1 * len2)))
    angle = math.degrees(math.acos(cos_angle))

    # 找交点(近似:取两条线段端点中最近的)
    vertex = _find_intersection(edge1, edge2)

    return {
        "value": round(angle, 1),
        "vertex": vertex,
        "text": f"{angle:.0f}°"
    }


def _find_intersection(edge1, edge2):
    """求两条线段的交点(近似)"""
    x1, y1, x2, y2 = edge1["x1"], edge1["y1"], edge1["x2"], edge1["y2"]
    x3, y3, x4, y4 = edge2["x1"], edge2["y1"], edge2["x2"], edge2["y2"]

    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 0.001:
        # 平行线,取中点
        return [round((x1 + x3) / 2, 2), round((y1 + y3) / 2, 2)]

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    ix = x1 + t * (x2 - x1)
    iy = y1 + t * (y2 - y1)
    return [round(ix, 2), round(iy, 2)]


# ==================== 模板应用 ====================

def apply_template(views_data, template, params=None):
    """将模板应用到投影视图数据,生成含标注的工程图数据

    Args:
        views_data: generate_drawing_views_raw() 的返回值
        template: 模板 dict
        params: 参数 dict (model_code, series, date, scale 等,用于标题栏)

    Returns:
        {
            "sheet": {...},
            "views": {  # 布局后的视图(含偏移坐标)
                "front": {"label", "visible", "hidden", "bbox", "offset", "scale", "segments_with_meta"},
                ...
            },
            "dimensions": [  # 计算后的标注
                {"id", "type", "view", "value", "text", "p1", "p2", "offset", ...},
                ...
            ],
            "title_block": {...},
            "bom_table": {...},
            "unmatched": [...]  # 未匹配到的标注 id 列表
        }
    """
    if params is None:
        params = {}

    result = {
        "sheet": template.get("sheet", {"width": 420, "height": 297}),
        "template_id": template.get("template_id"),
        "anchor_profile": template.get("anchor_profile"),
        "views": {},
        "dimensions": [],
        "title_block": {},
        "bom_table": {},
        "unmatched": []
    }

    raw_views = views_data.get("views", {})
    anchors = views_data.get("anchors", {}).get("anchors", [])
    anchor_map = {a.get("id"): a for a in anchors if a.get("id")}

    # 1. 布局视图: 计算每个视图的偏移和缩放
    #
    # 注意:
    #   当多个视图都配置为 scale=auto 时,不能让每个视图单独按自己的 bbox 放大,
    #   否则细长视图会被放得过大,导致线条杂糅; 这里改为整张图共用一个自动比例。
    auto_scale_values = []
    for view_def in template.get("views", []):
        view_type = view_def["type"]
        if view_type not in raw_views or view_def.get("scale") != "auto":
            continue
        bbox = raw_views[view_type]["bbox"]
        target_w = view_def.get("target_width", 200)
        target_h = view_def.get("target_height", 150)
        if bbox["width"] > 0 and bbox["height"] > 0:
            auto_scale_values.append(min(target_w / bbox["width"], target_h / bbox["height"]))

    shared_auto_scale = min(auto_scale_values) if auto_scale_values else 1.0

    for view_def in template.get("views", []):
        view_id = view_def["id"]
        view_type = view_def["type"]

        if view_type not in raw_views:
            continue

        raw_view = raw_views[view_type]
        bbox = raw_view["bbox"]

        # 计算缩放比例(auto = 整张图共用同一比例)
        target_w = view_def.get("target_width", 200)
        target_h = view_def.get("target_height", 150)

        if view_def.get("scale") == "auto":
            scale = shared_auto_scale
        else:
            try:
                scale = float(view_def["scale"])
            except (ValueError, TypeError):
                scale = shared_auto_scale

        offset_x = view_def["x"] - bbox["min_x"] * scale
        offset_y = view_def["y"] - bbox["min_y"] * scale

        result["views"][view_id] = {
            "label": raw_view["label"],
            "visible": raw_view["visible"],
            "hidden": raw_view["hidden"],
            "bbox": bbox,
            "offset": [offset_x, offset_y],
            "scale": round(scale, 4),
            "view_type": view_type
        }

    # 2. 计算标注
    for dim_def in template.get("dimensions", []):
        view_id = dim_def.get("view", "")

        # text 类型标注不需要视图边线,优先处理
        if dim_def.get("type") == "text":
            dim_result = _calculate_text_dimension(dim_def, params)
            if dim_result:
                result["dimensions"].append(dim_result)
            else:
                result["unmatched"].append(dim_def["id"])
            continue

        # 找到对应的视图
        view_key = None
        for vid, vdata in result["views"].items():
            if vdata["view_type"] == view_id or vid == view_id:
                view_key = vid
                break

        if not view_key:
            result["unmatched"].append(dim_def["id"])
            continue

        view_data = result["views"][view_key]
        segments = _segments_with_fitted_circles(view_data["visible"])
        scale = view_data["scale"]
        offset = view_data["offset"]

        dim_result = _calculate_dimension(
            dim_def, segments, scale, offset,
            anchor_map=anchor_map, params=params, view_type=view_id
        )
        if dim_result:
            result["dimensions"].append(dim_result)
        else:
            result["unmatched"].append(dim_def["id"])

    # 3. 填充标题栏
    title_block = template.get("title_block", {})
    if title_block:
        fields = []
        for field in title_block.get("fields", []):
            value = _resolve_template_string(field["value"], params)
            fields.append({
                "name": field["name"],
                "value": value,
                "x": field["x"],
                "y": field["y"]
            })
        result["title_block"] = {"fields": fields}

    # 4. BOM 表
    result["bom_table"] = template.get("bom_table", {})

    return result


def _calculate_dimension(dim_def, segments, scale, offset, anchor_map=None, params=None, view_type=None):
    """计算单个标注

    Args:
        dim_def: 标注定义
        segments: 视图边线列表(模型坐标)
        scale: 视图缩放比例
        offset: 视图偏移 [ox, oy]
        anchor_map: 锚点字典 {id: anchor_dict}
        params: 参数字典(用于解析模板字符串)
        view_type: 视图类型(front/top/left 等,用于锚点 3D→2D 投影)

    Returns:
        标注结果 dict(含变换后的屏幕坐标), 或 None
    """
    dim_type = dim_def.get("type", "")
    anchor_map = anchor_map or {}
    params = params or {}

    def to_screen(x, y):
        """模型坐标 → 屏幕坐标"""
        return [round(x * scale + offset[0], 2), round(y * scale + offset[1], 2)]

    if dim_type == "linear":
        orientation = dim_def.get("orientation", "horizontal")
        if dim_def.get("from_anchor") and dim_def.get("to_anchor"):
            a1 = anchor_map.get(dim_def.get("from_anchor"))
            a2 = anchor_map.get(dim_def.get("to_anchor"))
            p1 = _anchor_to_2d_point(a1, view_type)
            p2 = _anchor_to_2d_point(a2, view_type)
            if not p1 or not p2:
                return None
            if orientation == "horizontal":
                dist = abs(p2[0] - p1[0])
            elif orientation == "vertical":
                dist = abs(p2[1] - p1[1])
            else:
                dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            calc = {
                "value": round(dist, 1),
                "p1": p1,
                "p2": p2,
                "text": f"{dist:.0f}"
            }
        else:
            edge1 = _match_edge(segments, dim_def.get("edge1_ref"))
            edge2 = _match_edge(segments, dim_def.get("edge2_ref"))
            if not edge1 or not edge2:
                return None
            calc = _calc_linear_dimension(edge1, edge2, orientation)
            if not calc:
                return None

        # 变换到屏幕坐标
        calc["p1_screen"] = to_screen(*calc["p1"])
        calc["p2_screen"] = to_screen(*calc["p2"])
        calc["offset"] = dim_def.get("offset", 20)
        calc["id"] = dim_def["id"]
        calc["type"] = "linear"
        calc["view"] = dim_def.get("view", "")
        calc["orientation"] = orientation
        calc["label"] = dim_def.get("label", "")
        return calc

    elif dim_type == "linear_text":
        # 文字型尺寸线: 两端绑锚点,文本不参与数值计算(如"减速机尺寸")
        cond = dim_def.get("condition")
        if cond:
            cond_value = params.get(cond)
            if not cond_value or cond_value in (False, 0, "0", "", "false", "False"):
                return None
        a1 = anchor_map.get(dim_def.get("from_anchor"))
        a2 = anchor_map.get(dim_def.get("to_anchor"))
        p1 = _anchor_to_2d_point(a1, view_type)
        p2 = _anchor_to_2d_point(a2, view_type)
        if not p1 or not p2:
            return None
        orientation = dim_def.get("orientation", "horizontal")
        if orientation == "horizontal":
            dist = abs(p2[0] - p1[0])
        elif orientation == "vertical":
            dist = abs(p2[1] - p1[1])
        else:
            dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        calc = {
            "p1": p1,
            "p2": p2,
            "value": round(dist, 1),
            "text": _resolve_template_string(dim_def.get("text", ""), params),
        }
        calc["p1_screen"] = to_screen(*calc["p1"])
        calc["p2_screen"] = to_screen(*calc["p2"])
        calc["offset"] = dim_def.get("offset", 20)
        calc["id"] = dim_def["id"]
        # 渲染走 linear 分支(SVG/PDF 均按既有线性标注绘制)
        calc["type"] = "linear"
        calc["view"] = dim_def.get("view", "")
        calc["orientation"] = orientation
        calc["label"] = dim_def.get("label", "")
        return calc

    elif dim_type == "hole":
        circle = _match_edge(segments, dim_def.get("circle_ref"))
        if not circle:
            return None

        calc = _calc_hole_dimension(circle)
        if not calc:
            return None

        calc["center_screen"] = to_screen(*calc["center"])
        leader = dim_def.get("leader", {"dx": 20, "dy": -15})
        calc["leader_end"] = [
            round(calc["center_screen"][0] + leader["dx"], 2),
            round(calc["center_screen"][1] + leader["dy"], 2)
        ]
        calc["id"] = dim_def["id"]
        calc["type"] = "hole"
        calc["view"] = dim_def.get("view", "")
        return calc

    elif dim_type == "angle":
        edge1 = _match_edge(segments, dim_def.get("line1_ref"))
        edge2 = _match_edge(segments, dim_def.get("line2_ref"))
        if not edge1 or not edge2:
            return None

        calc = _calc_angle_dimension(edge1, edge2)
        if not calc:
            return None

        if calc["vertex"]:
            calc["vertex_screen"] = to_screen(*calc["vertex"])
        calc["offset"] = dim_def.get("offset", 20)
        calc["id"] = dim_def["id"]
        calc["type"] = "angle"
        calc["view"] = dim_def.get("view", "")
        return calc

    elif dim_type == "diameter":
        # 优先使用锚点(cylinder.axis 含 radius 字段)
        if dim_def.get("from_anchor"):
            anchor = anchor_map.get(dim_def["from_anchor"])
            if anchor and anchor.get("radius"):
                radius = float(anchor["radius"])
                # 锚点 3D → 2D 投影得到圆心屏幕坐标
                center_2d = _anchor_to_2d_point(anchor, view_type)
                if center_2d:
                    calc = {
                        "value": round(radius * 2, 1),
                        "center": center_2d,
                        "text": f"Ø{radius * 2:.0f}",
                    }
                    calc["center_screen"] = to_screen(*calc["center"])
                    # 引线终点: 从圆心向右上偏移
                    off = dim_def.get("offset", 25)
                    calc["leader_end"] = [
                        round(calc["center_screen"][0] + off, 2),
                        round(calc["center_screen"][1] - off * 0.7, 2)
                    ]
                    calc["id"] = dim_def["id"]
                    calc["type"] = "diameter"
                    calc["view"] = dim_def.get("view", "")
                    calc["label"] = dim_def.get("label", "")
                    return calc

        # 回退: 从视图边线匹配圆
        circle = _match_edge(segments, dim_def.get("circle_ref"))
        if not circle:
            return None

        calc = _calc_hole_dimension(circle)
        if not calc:
            return None

        calc["center_screen"] = to_screen(*calc["center"])
        calc["id"] = dim_def["id"]
        calc["type"] = "diameter"
        calc["view"] = dim_def.get("view", "")
        calc["label"] = dim_def.get("label", "")
        return calc

    elif dim_type == "radius":
        circle = _match_edge(segments, dim_def.get("circle_ref"))
        if not circle:
            return None

        radius = circle["r"]
        calc = {
            "value": round(radius, 1),
            "center": [round(circle["cx"], 2), round(circle["cy"], 2)],
            "text": f"R{radius:.0f}",
            "center_screen": to_screen(circle["cx"], circle["cy"])
        }
        calc["id"] = dim_def["id"]
        calc["type"] = "radius"
        calc["view"] = dim_def.get("view", "")
        return calc

    return None


# 视图投影轴配置(与 drawing_engine.STANDARD_VIEW_CONFIGS 一致)
# x_dir: 屏幕右方向(模型坐标), up_dir: 屏幕上方向(模型坐标)
# 计算方式: x_dir = view_dir × up_dir (与 HLR Projector 的 gp_Ax2 一致)
_VIEW_PROJECTION_AXES = {
    # front: dir=(0,0,1), up=(0,1,0) → x_dir=(-1,0,0), screen: x=-px, y=py
    "front":  {"x_dir": (-1, 0, 0), "up_dir": (0, 1, 0)},
    # back: dir=(0,0,-1), up=(0,1,0) → x_dir=(1,0,0), screen: x=px, y=py
    "back":   {"x_dir": (1, 0, 0),  "up_dir": (0, 1, 0)},
    # left: dir=(1,0,0), up=(0,1,0) → x_dir=(0,0,1), screen: x=pz, y=py
    "left":   {"x_dir": (0, 0, 1),  "up_dir": (0, 1, 0)},
    # right: dir=(-1,0,0), up=(0,1,0) → x_dir=(0,0,-1), screen: x=-pz, y=py
    "right":  {"x_dir": (0, 0, -1), "up_dir": (0, 1, 0)},
    # top: dir=(0,-1,0), up=(0,0,-1) → x_dir=(1,0,0), screen: x=px, y=-pz
    "top":    {"x_dir": (1, 0, 0),  "up_dir": (0, 0, -1)},
    # bottom: dir=(0,1,0), up=(0,0,1) → x_dir=(1,0,0), screen: x=px, y=pz
    "bottom": {"x_dir": (1, 0, 0),  "up_dir": (0, 0, 1)},
}


def _anchor_to_2d_point(anchor, view_type=None):
    """将语义锚点转换为 2D 点(按视图方向投影 3D 坐标)

    Args:
        anchor: 锚点 dict,含 point3d=[x,y,z] 或 point2d=[x,y]
        view_type: 视图类型(front/top/left),用于 3D→2D 投影

    Returns:
        [x_2d, y_2d] 或 None
    """
    if not anchor:
        return None

    # 优先使用预计算的 2D 点
    point2d = anchor.get("point2d")
    if isinstance(point2d, list) and len(point2d) == 2:
        return [round(float(point2d[0]), 2), round(float(point2d[1]), 2)]

    point3d = anchor.get("point3d")
    if not isinstance(point3d, list) or len(point3d) != 3:
        return None

    px, py, pz = float(point3d[0]), float(point3d[1]), float(point3d[2])

    # 无视图类型时,默认取 X-Y 平面投影
    if view_type is None:
        return [round(px, 2), round(py, 2)]

    axes = _VIEW_PROJECTION_AXES.get(view_type)
    if not axes:
        return [round(px, 2), round(py, 2)]

    xd = axes["x_dir"]
    ud = axes["up_dir"]
    screen_x = px * xd[0] + py * xd[1] + pz * xd[2]
    # HLR 投影段的 y 轴 = ax2 的 Y = N × Vx = -up(drawing_engine 实测约定),
    # 锚点必须与边线同空间,故 screen_y 取 -up 方向分量
    screen_y = -(px * ud[0] + py * ud[1] + pz * ud[2])
    return [round(screen_x, 2), round(screen_y, 2)]


def _calculate_text_dimension(dim_def, params):
    """计算文本标注(如电机尺寸说明)

    Args:
        dim_def: 标注定义,含 text 模板字符串
        params: 参数字典

    Returns:
        标注结果 dict, 或 None(条件不满足时)
    """
    # 条件检查(如 has_motor)
    condition = dim_def.get("condition")
    if condition:
        cond_value = params.get(condition)
        if not cond_value or cond_value in (False, 0, "0", "", "false", "False"):
            return None

    text_value = _resolve_template_string(dim_def.get("text", ""), params)
    return {
        "id": dim_def.get("id"),
        "type": "text",
        "view": dim_def.get("view", ""),
        "text": text_value,
        "label": dim_def.get("label", ""),
        "position": dim_def.get("position", {"x": 0, "y": 0})
    }


def _resolve_template_string(template_str, params):
    """解析模板字符串中的 {{变量}} 占位符

    Args:
        template_str: 含 {{var}} 的字符串
        params: 参数 dict

    Returns:
        解析后的字符串
    """
    if not isinstance(template_str, str):
        return str(template_str)

    result = template_str
    for key, value in params.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


# ==================== SVG 渲染 ====================

def render_engineering_svg(template_result, params=None):
    """将 apply_template 的结果渲染为完整工程图 SVG

    生成 A3 图框 + 视图边线 + 标注(尺寸线/引线/文本) + 标题栏。

    Args:
        template_result: apply_template() 的返回值
        params: 参数 dict(用于标题栏变量替换)

    Returns:
        str: 完整 SVG 字符串
    """
    if params is None:
        params = {}

    sheet = template_result.get("sheet", {"width": 420, "height": 297})
    sw = sheet.get("width", 420)
    sh = sheet.get("height", 297)

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{sw * 2}" height="{sh * 2}" '
        f'viewBox="0 0 {sw} {sh}" '
        f'style="background:#fff;border:1px solid #ccc;">',
        f'<rect x="0" y="0" width="{sw}" height="{sh}" fill="white"/>',
        # 图框边线
        f'<rect x="10" y="10" width="{sw - 20}" height="{sh - 20}" '
        f'fill="none" stroke="#333" stroke-width="0.8"/>',
    ]

    # 1. 渲染视图边线
    for view_id, vdata in template_result.get("views", {}).items():
        scale = vdata.get("scale", 1.0)
        ox, oy = vdata.get("offset", [0, 0])
        visible = vdata.get("visible", [])
        hidden = vdata.get("hidden", [])

        # 视图标签
        svg_parts.append(
            f'<text x="{ox + 5}" y="{oy - 5}" '
            f'font-size="3.5" font-family="sans-serif" fill="#666">'
            f'{vdata.get("label", view_id)}</text>'
        )

        # 可见边
        for seg in visible:
            svg_parts.append(_segment_to_svg(seg, scale, ox, oy,
                                              stroke="#333", width=0.4))
        # 隐藏边(虚线)
        for seg in hidden:
            svg_parts.append(_segment_to_svg(seg, scale, ox, oy,
                                              stroke="#999", width=0.3,
                                              dash="1,1"))

    # 2. 渲染标注
    for dim in template_result.get("dimensions", []):
        svg_parts.append(_dimension_to_svg(dim))

    # 3. 标题栏
    title_block = template_result.get("title_block", {})
    if title_block.get("fields"):
        # 标题栏外框
        svg_parts.append(
            f'<rect x="{sw - 110}" y="{sh - 45}" width="100" height="35" '
            f'fill="none" stroke="#333" stroke-width="0.5"/>'
        )
        for field in title_block["fields"]:
            fx, fy = field.get("x", 0), field.get("y", 0)
            svg_parts.append(
                f'<text x="{fx}" y="{fy}" font-size="2.5" '
                f'font-family="sans-serif" fill="#333">'
                f'{field.get("name", "")}: {field.get("value", "")}</text>'
            )

    svg_parts.append('</svg>')
    return '\n'.join(svg_parts)


def _segment_to_svg(seg, scale, ox, oy, stroke="#333", width=0.4, dash=None):
    """将单条边线转换为 SVG 元素(应用缩放+偏移)"""
    def tx(x):
        return round(x * scale + ox, 2)

    def ty(y):
        return round(y * scale + oy, 2)

    dash_attr = f' stroke-dasharray="{dash}"' if dash else ''
    t = seg.get("type", "")

    if t == "line":
        return (f'<line x1="{tx(seg["x1"])}" y1="{ty(seg["y1"])}" '
                f'x2="{tx(seg["x2"])}" y2="{ty(seg["y2"])}" '
                f'stroke="{stroke}" stroke-width="{width}"{dash_attr}/>')
    elif t == "circle":
        return (f'<circle cx="{tx(seg["cx"])}" cy="{ty(seg["cy"])}" '
                f'r="{round(seg["r"] * scale, 2)}" '
                f'stroke="{stroke}" stroke-width="{width}" '
                f'fill="none"{dash_attr}/>')
    elif t == "polyline":
        pts = seg.get("points", [])
        if len(pts) < 2:
            return ""
        pts_str = " ".join(f"{tx(p[0])},{ty(p[1])}" for p in pts)
        return (f'<polyline points="{pts_str}" stroke="{stroke}" '
                f'stroke-width="{width}" fill="none"{dash_attr}/>')
    return ""


def _dimension_to_svg(dim):
    """将标注转换为 SVG 元素(尺寸线/引线/文本)"""
    dt = dim.get("type", "")

    if dt == "linear":
        p1 = dim.get("p1_screen")
        p2 = dim.get("p2_screen")
        if not p1 or not p2:
            return ""
        orient = dim.get("orientation", "horizontal")
        offset = dim.get("offset", 20)

        if orient == "horizontal":
            # 水平尺寸线: 两端在 p1/p2 下方 offset 处
            oy_val = max(p1[1], p2[1]) + offset
            parts = [
                # 引线
                f'<line x1="{p1[0]}" y1="{p1[1]}" x2="{p1[0]}" y2="{oy_val}" '
                f'stroke="#666" stroke-width="0.3" stroke-dasharray="1,1"/>',
                f'<line x1="{p2[0]}" y1="{p2[1]}" x2="{p2[0]}" y2="{oy_val}" '
                f'stroke="#666" stroke-width="0.3" stroke-dasharray="1,1"/>',
                # 尺寸线
                f'<line x1="{p1[0]}" y1="{oy_val}" x2="{p2[0]}" y2="{oy_val}" '
                f'stroke="#1565C0" stroke-width="0.5"/>',
                # 箭头(简单三角)
                _arrow_svg(p1[0], oy_val, "right"),
                _arrow_svg(p2[0], oy_val, "left"),
                # 文本
                f'<text x="{(p1[0] + p2[0]) / 2}" y="{oy_val - 1.5}" '
                f'font-size="3" font-family="sans-serif" fill="#1565C0" '
                f'text-anchor="middle">{dim.get("text", "")}</text>',
            ]
        elif orient == "vertical":
            ox_val = max(p1[0], p2[0]) + offset
            parts = [
                f'<line x1="{p1[0]}" y1="{p1[1]}" x2="{ox_val}" y2="{p1[1]}" '
                f'stroke="#666" stroke-width="0.3" stroke-dasharray="1,1"/>',
                f'<line x1="{p2[0]}" y1="{p2[1]}" x2="{ox_val}" y2="{p2[1]}" '
                f'stroke="#666" stroke-width="0.3" stroke-dasharray="1,1"/>',
                f'<line x1="{ox_val}" y1="{p1[1]}" x2="{ox_val}" y2="{p2[1]}" '
                f'stroke="#1565C0" stroke-width="0.5"/>',
                _arrow_svg(ox_val, p1[1], "down"),
                _arrow_svg(ox_val, p2[1], "up"),
                f'<text x="{ox_val + 2}" y="{(p1[1] + p2[1]) / 2}" '
                f'font-size="3" font-family="sans-serif" fill="#1565C0" '
                f'text-anchor="middle">{dim.get("text", "")}</text>',
            ]
        else:
            parts = [
                f'<line x1="{p1[0]}" y1="{p1[1]}" x2="{p2[0]}" y2="{p2[1]}" '
                f'stroke="#1565C0" stroke-width="0.5"/>',
                f'<text x="{(p1[0] + p2[0]) / 2}" y="{(p1[1] + p2[1]) / 2 - 1.5}" '
                f'font-size="3" font-family="sans-serif" fill="#1565C0" '
                f'text-anchor="middle">{dim.get("text", "")}</text>',
            ]

        if dim.get("label"):
            parts.append(
                f'<text x="{(p1[0] + p2[0]) / 2}" y="{max(p1[1], p2[1]) + 5}" '
                f'font-size="2.5" font-family="sans-serif" fill="#999" '
                f'text-anchor="middle">({dim["label"]})</text>'
            )
        return '\n'.join(parts)

    elif dt in ("hole", "diameter"):
        center = dim.get("center_screen")
        leader_end = dim.get("leader_end")
        if not center:
            return ""
        parts = []
        if leader_end:
            parts.append(
                f'<line x1="{center[0]}" y1="{center[1]}" '
                f'x2="{leader_end[0]}" y2="{leader_end[1]}" '
                f'stroke="#1565C0" stroke-width="0.4"/>'
            )
            parts.append(
                f'<text x="{leader_end[0] + 1}" y="{leader_end[1]}" '
                f'font-size="3" font-family="sans-serif" fill="#1565C0">'
                f'{dim.get("text", "")}</text>'
            )
        else:
            parts.append(
                f'<text x="{center[0]}" y="{center[1] - 2}" '
                f'font-size="3" font-family="sans-serif" fill="#1565C0" '
                f'text-anchor="middle">{dim.get("text", "")}</text>'
            )
        return '\n'.join(parts)

    elif dt == "text":
        pos = dim.get("position", {"x": 0, "y": 0})
        return (
            f'<text x="{pos.get("x", 0)}" y="{pos.get("y", 0)}" '
            f'font-size="3" font-family="sans-serif" fill="#333">'
            f'{dim.get("text", "")}</text>'
        )

    return ""


def _arrow_svg(x, y, direction):
    """生成箭头 SVG(三角形)"""
    s = 1.5  # 箭头大小
    if direction == "right":
        pts = f"{x},{y} {x+s},{y-s/2} {x+s},{y+s/2}"
    elif direction == "left":
        pts = f"{x},{y} {x-s},{y-s/2} {x-s},{y+s/2}"
    elif direction == "up":
        pts = f"{x},{y} {x-s/2},{y-s} {x+s/2},{y-s}"
    elif direction == "down":
        pts = f"{x},{y} {x-s/2},{y+s} {x+s/2},{y+s}"
    else:
        return ""
    return f'<polygon points="{pts}" fill="#1565C0"/>'


# ==================== 端到端集成入口 ====================

def generate_drawing(step_path, template_path=None, anchors_path=None,
                     params=None, views=None):
    """端到端: STEP → HLR 视图 → 锚点投影 → 标注 → SVG 工程图

    Args:
        step_path: STEP 文件路径
        template_path: 模板 JSON 路径(默认加载内置模板)
        anchors_path: 锚点 JSON 路径(默认加载内置锚点)
        params: 参数 dict(model_code, series, date, scale 等)
        views: 视图列表(默认 ["front", "top", "left"])

    Returns:
        {
            "svg": str,           # 完整 SVG 工程图
            "template_result": dict,  # 模板应用结果(含标注数据)
            "elapsed": float
        }
    """
    import time as _time
    t0 = _time.time()

    if params is None:
        params = {}

    # 延迟导入 drawing_engine 避免循环依赖
    import drawing_engine

    if views is None:
        views = ["front", "top", "left"]

    # 1. 生成视图(模型坐标空间)
    views_raw = drawing_engine.generate_drawing_views_raw(step_path, views=views)

    # 2. 加载模板和锚点
    if template_path:
        template = load_template(template_path)
    else:
        template = load_default_template()

    if anchors_path:
        anchors = load_anchors(anchors_path)
    else:
        anchors = load_default_anchors()

    # 合并锚点到 views_data
    views_data = dict(views_raw)
    views_data["anchors"] = anchors

    # 3. 应用模板(标注计算)
    template_result = apply_template(views_data, template, params)

    # 4. 渲染 SVG
    svg = render_engineering_svg(template_result, params)

    elapsed = _time.time() - t0
    return {
        "svg": svg,
        "template_result": template_result,
        "elapsed": round(elapsed, 3)
    }
