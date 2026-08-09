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
    # 返回内置默认模板
    return _get_builtin_template()


def _get_builtin_template():
    """内置默认模板(液压缸)"""
    return {
        "name": "液压缸工程图模板",
        "sheet": {"size": "A3", "width": 420, "height": 297},
        "views": [
            {"id": "front", "type": "front", "x": 80, "y": 180, "scale": "auto"},
            {"id": "top",   "type": "top",   "x": 80, "y": 40,  "scale": "auto"}
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
                "type": "hole",
                "view": "front",
                "circle_ref": {"method": "largest_circle"},
                "leader": {"dx": 25, "dy": -20}
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


# ==================== 边线匹配引擎 ====================

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
        "views": {},
        "dimensions": [],
        "title_block": {},
        "bom_table": {},
        "unmatched": []
    }

    raw_views = views_data.get("views", {})

    # 1. 布局视图: 计算每个视图的偏移和缩放
    for view_def in template.get("views", []):
        view_id = view_def["id"]
        view_type = view_def["type"]

        if view_type not in raw_views:
            continue

        raw_view = raw_views[view_type]
        bbox = raw_view["bbox"]

        # 计算缩放比例(auto = 适应视图区域)
        target_w = view_def.get("target_width", 200)
        target_h = view_def.get("target_height", 150)

        if view_def.get("scale") == "auto":
            if bbox["width"] > 0 and bbox["height"] > 0:
                scale = min(target_w / bbox["width"], target_h / bbox["height"])
            else:
                scale = 1.0
        else:
            try:
                scale = float(view_def["scale"])
            except (ValueError, TypeError):
                scale = 1.0

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
        view_key = None

        # 找到对应的视图
        for vid, vdata in result["views"].items():
            if vdata["view_type"] == view_id or vid == view_id:
                view_key = vid
                break

        if not view_key:
            result["unmatched"].append(dim_def["id"])
            continue

        view_data = result["views"][view_key]
        segments = view_data["visible"]
        scale = view_data["scale"]
        offset = view_data["offset"]

        dim_result = _calculate_dimension(dim_def, segments, scale, offset)
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


def _calculate_dimension(dim_def, segments, scale, offset):
    """计算单个标注

    Args:
        dim_def: 标注定义
        segments: 视图边线列表(模型坐标)
        scale: 视图缩放比例
        offset: 视图偏移 [ox, oy]

    Returns:
        标注结果 dict(含变换后的屏幕坐标), 或 None
    """
    dim_type = dim_def.get("type", "")

    def to_screen(x, y):
        """模型坐标 → 屏幕坐标"""
        return [round(x * scale + offset[0], 2), round(y * scale + offset[1], 2)]

    if dim_type == "linear":
        edge1 = _match_edge(segments, dim_def.get("edge1_ref"))
        edge2 = _match_edge(segments, dim_def.get("edge2_ref"))
        if not edge1 or not edge2:
            return None

        orientation = dim_def.get("orientation", "horizontal")
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
