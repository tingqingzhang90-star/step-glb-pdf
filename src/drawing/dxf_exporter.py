# -*- coding: utf-8 -*-
"""
DXF 导出器 — 使用 ezdxf 将工程图数据写入 DXF 文件

功能:
  1. 创建 DXF 文件(R2018 格式,兼容主流 CAD 软件)
  2. 设置图层(轮廓线/隐藏线/中心线/标注/文字/表格/标题栏/图框)
  3. 写入多视图(主视/俯视等,含偏移和缩放)
  4. 写入标注(线性/孔/角度/直径/半径)
  5. 写入标题栏(含字段文字)
  6. 写入 BOM 表格
  7. 写入图框(A3/A4 等)

输出 DXF 可被 cad-viewer(前端)或 SolidWorks/AutoCAD 直接打开。

调用方式:
    from drawing.dxf_exporter import export_drawing_to_dxf
    export_drawing_to_dxf(drawing_data, output_path)
"""
import math
import ezdxf
from ezdxf.enums import TextEntityAlignment


# ==================== 图层定义 ====================

LAYERS = {
    "OUTLINE":      {"color": 7,  "linetype": "CONTINUOUS", "lineweight": 50},  # 粗实线 0.6mm
    "HIDDEN":       {"color": 8,  "linetype": "DASHED",     "lineweight": 13},  # 虚线 0.3mm
    "CENTER":       {"color": 3,  "linetype": "CENTER",     "lineweight": 13},  # 中心线 0.3mm
    "DIMENSION":    {"color": 5,  "linetype": "CONTINUOUS", "lineweight": 13},  # 尺寸线 0.3mm
    "TEXT":         {"color": 7,  "linetype": "CONTINUOUS", "lineweight": 13},  # 文字
    "TABLE":        {"color": 7,  "linetype": "CONTINUOUS", "lineweight": 13},  # 表格
    "TITLE_BLOCK":  {"color": 7,  "linetype": "CONTINUOUS", "lineweight": 13},  # 标题栏
    "BORDER":       {"color": 7,  "linetype": "CONTINUOUS", "lineweight": 50},  # 图框
    "VIEW_LABEL":   {"color": 2,  "linetype": "CONTINUOUS", "lineweight": 13},  # 视图标签
}


def _setup_layers(doc):
    """设置所有图层"""
    for name, props in LAYERS.items():
        if name not in doc.layers:
            doc.layers.add(name, color=props["color"],
                          linetype=props["linetype"],
                          lineweight=props["lineweight"])


# ==================== 视图写入 ====================

def _write_view(msp, view_id, view_data):
    """写入单个视图的边线到 DXF

    Args:
        msp: ModelSpace
        view_id: 视图 ID
        view_data: 视图数据(含 visible/hidden/offset/scale)
    """
    scale = view_data["scale"]
    ox, oy = view_data["offset"]

    def to_dxf(x, y):
        """模型坐标 → DXF 坐标"""
        return x * scale + ox, y * scale + oy

    # 可见边(OUTLINE 层)
    for seg in view_data.get("visible", []):
        _write_segment(msp, seg, "OUTLINE", to_dxf)

    # 隐藏边(HIDDEN 层)
    for seg in view_data.get("hidden", []):
        _write_segment(msp, seg, "HIDDEN", to_dxf)

    # 视图标签
    label = view_data.get("label", view_id)
    bx = view_data["bbox"]
    label_x = ox + bx["min_x"] * scale
    label_y = oy + bx["min_y"] * scale - 8
    msp.text(label, dxfattribs={
        "layer": "VIEW_LABEL",
        "height": 5,
        "style": "SimSun"
    }).set_placement((label_x, label_y, 0), align=TextEntityAlignment.LEFT)


def _write_segment(msp, seg, layer, to_dxf):
    """写入单条边线到 DXF"""
    if seg["type"] == "line":
        x1, y1 = to_dxf(seg["x1"], seg["y1"])
        x2, y2 = to_dxf(seg["x2"], seg["y2"])
        msp.add_line((x1, y1), (x2, y2), dxfattribs={"layer": layer})

    elif seg["type"] == "circle":
        cx, cy = to_dxf(seg["cx"], seg["cy"])
        r = seg["r"] * (to_dxf(1, 0)[0] - to_dxf(0, 0)[0])  # 缩放半径
        msp.add_circle((cx, cy), r, dxfattribs={"layer": layer})

    elif seg["type"] == "polyline":
        points = [to_dxf(x, y) for x, y in seg["points"]]
        if len(points) >= 2:
            msp.add_lwpolyline(points, dxfattribs={"layer": layer})


# ==================== 标注写入 ====================

def _write_dimension(msp, dim):
    """写入标注到 DXF

    使用 ezdxf 的 DIMENSION 实体或手动绘制标注线。
    """
    dim_type = dim.get("type", "")

    if dim_type == "linear":
        _write_linear_dim(msp, dim)
    elif dim_type == "hole":
        _write_hole_dim(msp, dim)
    elif dim_type == "angle":
        _write_angle_dim(msp, dim)
    elif dim_type == "diameter":
        _write_diameter_dim(msp, dim)
    elif dim_type == "radius":
        _write_radius_dim(msp, dim)


def _write_linear_dim(msp, dim):
    """写入线性标注(手动绘制标注线 + 文字)"""
    p1 = dim.get("p1_screen", dim.get("p1", [0, 0]))
    p2 = dim.get("p2_screen", dim.get("p2", [0, 0]))
    offset = dim.get("offset", 20)
    orientation = dim.get("orientation", "horizontal")
    text = dim.get("text", str(dim.get("value", "")))

    if orientation == "horizontal":
        # 水平标注: 标注线在下方(offset 为正)或上方(负)
        dim_y = p1[1] + offset
        # 延伸线
        msp.add_line((p1[0], p1[1]), (p1[0], dim_y), dxfattribs={"layer": "DIMENSION"})
        msp.add_line((p2[0], p2[1]), (p2[0], dim_y), dxfattribs={"layer": "DIMENSION"})
        # 标注线
        msp.add_line((p1[0], dim_y), (p2[0], dim_y), dxfattribs={"layer": "DIMENSION"})
        # 箭头(简易)
        _draw_arrow(msp, (p1[0], dim_y), "right" if p2[0] > p1[0] else "left")
        _draw_arrow(msp, (p2[0], dim_y), "left" if p2[0] > p1[0] else "right")
        # 文字
        mid_x = (p1[0] + p2[0]) / 2
        msp.text(text, dxfattribs={
            "layer": "DIMENSION", "height": 3.5, "style": "SimSun"
        }).set_placement((mid_x, dim_y + 1), align=TextEntityAlignment.MIDDLE_CENTER)

    elif orientation == "vertical":
        dim_x = p1[0] + offset
        msp.add_line((p1[0], p1[1]), (dim_x, p1[1]), dxfattribs={"layer": "DIMENSION"})
        msp.add_line((p2[0], p2[1]), (dim_x, p2[1]), dxfattribs={"layer": "DIMENSION"})
        msp.add_line((dim_x, p1[1]), (dim_x, p2[1]), dxfattribs={"layer": "DIMENSION"})
        _draw_arrow(msp, (dim_x, p1[1]), "up" if p2[1] > p1[1] else "down")
        _draw_arrow(msp, (dim_x, p2[1]), "down" if p2[1] > p1[1] else "up")
        mid_y = (p1[1] + p2[1]) / 2
        msp.text(text, dxfattribs={
            "layer": "DIMENSION", "height": 3.5, "style": "SimSun"
        }).set_placement((dim_x + 2, mid_y), align=TextEntityAlignment.MIDDLE_LEFT)

    else:  # aligned
        msp.add_line(tuple(p1), tuple(p2), dxfattribs={"layer": "DIMENSION"})
        mid_x = (p1[0] + p2[0]) / 2
        mid_y = (p1[1] + p2[1]) / 2
        msp.text(text, dxfattribs={
            "layer": "DIMENSION", "height": 3.5, "style": "SimSun"
        }).set_placement((mid_x, mid_y + 3), align=TextEntityAlignment.MIDDLE_CENTER)


def _write_hole_dim(msp, dim):
    """写入孔标注(引线 + Ø文字)"""
    center = dim.get("center_screen", dim.get("center", [0, 0]))
    leader_end = dim.get("leader_end", [center[0] + 20, center[1] - 15])
    text = dim.get("text", f"Ø{dim.get('value', '')}")

    # 引线
    msp.add_line(tuple(center), tuple(leader_end), dxfattribs={"layer": "DIMENSION"})
    # 文字
    msp.text(text, dxfattribs={
        "layer": "DIMENSION", "height": 3.5, "style": "SimSun"
    }).set_placement((leader_end[0] + 1, leader_end[1]), align=TextEntityAlignment.MIDDLE_LEFT)


def _write_angle_dim(msp, dim):
    """写入角度标注"""
    vertex = dim.get("vertex_screen", dim.get("vertex", [0, 0]))
    text = dim.get("text", f"{dim.get('value', '')}°")
    offset = dim.get("offset", 20)

    # 简易: 在顶点附近放文字 + 圆弧
    r = offset
    msp.add_arc(tuple(vertex), r, 0, 60, dxfattribs={"layer": "DIMENSION"})
    msp.text(text, dxfattribs={
        "layer": "DIMENSION", "height": 3.5, "style": "SimSun"
    }).set_placement((vertex[0] + offset + 2, vertex[1] + offset), align=TextEntityAlignment.MIDDLE_LEFT)


def _write_diameter_dim(msp, dim):
    """写入直径标注(Ø + 直径线)"""
    center = dim.get("center_screen", dim.get("center", [0, 0]))
    text = dim.get("text", f"Ø{dim.get('value', '')}")
    radius = dim.get("radius", 0)
    scale_factor = 1  # 简化

    # 直径线(穿过圆心)
    r_scaled = radius * scale_factor
    p1 = (center[0] - r_scaled, center[1])
    p2 = (center[0] + r_scaled, center[1])
    msp.add_line(p1, p2, dxfattribs={"layer": "DIMENSION"})
    msp.text(text, dxfattribs={
        "layer": "DIMENSION", "height": 3.5, "style": "SimSun"
    }).set_placement((p2[0] + 1, p2[1] + 2), align=TextEntityAlignment.MIDDLE_LEFT)


def _write_radius_dim(msp, dim):
    """写入半径标注(R + 半径线)"""
    center = dim.get("center_screen", dim.get("center", [0, 0]))
    text = dim.get("text", f"R{dim.get('value', '')}")
    radius = dim.get("radius", dim.get("value", 0))

    # 半径线(从圆心到边缘)
    p2 = (center[0] + radius, center[1])
    msp.add_line(tuple(center), p2, dxfattribs={"layer": "DIMENSION"})
    msp.text(text, dxfattribs={
        "layer": "DIMENSION", "height": 3.5, "style": "SimSun"
    }).set_placement((p2[0] + 1, p2[1] + 2), align=TextEntityAlignment.MIDDLE_LEFT)


def _draw_arrow(msp, point, direction, size=3):
    """绘制简易箭头"""
    x, y = point
    if direction == "right":
        pts = [(x, y), (x - size, y - size / 2), (x - size, y + size / 2)]
    elif direction == "left":
        pts = [(x, y), (x + size, y - size / 2), (x + size, y + size / 2)]
    elif direction == "up":
        pts = [(x, y), (x - size / 2, y - size), (x + size / 2, y - size)]
    elif direction == "down":
        pts = [(x, y), (x - size / 2, y + size), (x + size / 2, y + size)]
    else:
        return
    msp.add_lwpolyline(pts + [pts[0]], dxfattribs={"layer": "DIMENSION"})


# ==================== 标题栏 + 图框 + 表格 ====================

def _write_border(msp, sheet):
    """写入图框(A3 等)"""
    w = sheet.get("width", 420)
    h = sheet.get("height", 297)

    # 外框
    msp.add_line((0, 0), (w, 0), dxfattribs={"layer": "BORDER"})
    msp.add_line((w, 0), (w, h), dxfattribs={"layer": "BORDER"})
    msp.add_line((w, h), (0, h), dxfattribs={"layer": "BORDER"})
    msp.add_line((0, h), (0, 0), dxfattribs={"layer": "BORDER"})

    # 内框(留 10mm 边距)
    m = 10
    msp.add_line((m, m), (w - m, m), dxfattribs={"layer": "BORDER"})
    msp.add_line((w - m, m), (w - m, h - m), dxfattribs={"layer": "BORDER"})
    msp.add_line((w - m, h - m), (m, h - m), dxfattribs={"layer": "BORDER"})
    msp.add_line((m, h - m), (m, m), dxfattribs={"layer": "BORDER"})


def _write_title_block(msp, title_block):
    """写入标题栏"""
    fields = title_block.get("fields", [])
    if not fields:
        return

    # 标题栏框(右下角)
    bx, by = 280, 10
    bw, bh = 130, 50

    # 外框
    msp.add_line((bx, by), (bx + bw, by), dxfattribs={"layer": "TITLE_BLOCK"})
    msp.add_line((bx + bw, by), (bx + bw, by + bh), dxfattribs={"layer": "TITLE_BLOCK"})
    msp.add_line((bx + bw, by + bh), (bx, by + bh), dxfattribs={"layer": "TITLE_BLOCK"})
    msp.add_line((bx, by + bh), (bx, by), dxfattribs={"layer": "TITLE_BLOCK"})

    # 字段文字
    for field in fields:
        fx = field.get("x", bx + 5)
        fy = field.get("y", by + 5)
        # 字段名(标签)
        msp.text(field["name"] + ":", dxfattribs={
            "layer": "TITLE_BLOCK", "height": 2.5, "style": "SimSun"
        }).set_placement((fx, fy), align=TextEntityAlignment.MIDDLE_LEFT)
        # 字段值
        msp.text(str(field["value"]), dxfattribs={
            "layer": "TITLE_BLOCK", "height": 3, "style": "SimSun"
        }).set_placement((fx + 30, fy), align=TextEntityAlignment.MIDDLE_LEFT)


def _write_bom_table(msp, bom_table, bom_data=None):
    """写入 BOM 表格"""
    pos = bom_table.get("position", {"x": 300, "y": 200})
    columns = bom_table.get("columns", ["序号", "名称", "数量", "备注"])
    col_width = 25
    row_height = 8

    x = pos["x"]
    y = pos["y"]

    # 表头
    for i, col in enumerate(columns):
        cx = x + i * col_width
        msp.text(col, dxfattribs={
            "layer": "TABLE", "height": 3, "style": "SimSun"
        }).set_placement((cx + 2, y + 1), align=TextEntityAlignment.MIDDLE_LEFT)
        # 竖线
        msp.add_line((cx, y), (cx, y + row_height), dxfattribs={"layer": "TABLE"})

    # 表头底线和顶线
    msp.add_line((x, y), (x + len(columns) * col_width, y), dxfattribs={"layer": "TABLE"})
    msp.add_line((x, y + row_height), (x + len(columns) * col_width, y + row_height), dxfattribs={"layer": "TABLE"})

    # 数据行
    if bom_data:
        for row_idx, row in enumerate(bom_data):
            ry = y - (row_idx + 1) * row_height
            for i, col in enumerate(columns):
                cx = x + i * col_width
                val = row.get(col, "")
                msp.text(str(val), dxfattribs={
                    "layer": "TABLE", "height": 3, "style": "SimSun"
                }).set_placement((cx + 2, ry + 1), align=TextEntityAlignment.MIDDLE_LEFT)
                msp.add_line((cx, ry), (cx, ry + row_height), dxfattribs={"layer": "TABLE"})
            msp.add_line((x, ry), (x + len(columns) * col_width, ry), dxfattribs={"layer": "TABLE"})

    # 右边线
    msp.add_line((x + len(columns) * col_width, y - (len(bom_data) if bom_data else 0) * row_height),
                 (x + len(columns) * col_width, y + row_height), dxfattribs={"layer": "TABLE"})


# ==================== 主导出函数 ====================

def export_drawing_to_dxf(drawing_data, output_path, bom_data=None):
    """将工程图数据导出为 DXF 文件

    Args:
        drawing_data: apply_template() 的返回值
        output_path: 输出 DXF 文件路径
        bom_data: BOM 表数据(可选)

    Returns:
        output_path
    """
    # 创建 DXF 文档(R2018)
    doc = ezdxf.new("R2018", setup=True)

    # 设置中文字体样式
    if "SimSun" not in doc.styles:
        doc.styles.add("SimSun", font="simsun.ttc")

    # 设置图层
    _setup_layers(doc)

    msp = doc.modelspace()

    # 1. 图框
    sheet = drawing_data.get("sheet", {"width": 420, "height": 297})
    _write_border(msp, sheet)

    # 2. 视图
    for view_id, view_data in drawing_data.get("views", {}).items():
        _write_view(msp, view_id, view_data)

    # 3. 标注
    for dim in drawing_data.get("dimensions", []):
        _write_dimension(msp, dim)

    # 4. 标题栏
    if drawing_data.get("title_block"):
        _write_title_block(msp, drawing_data["title_block"])

    # 5. BOM 表
    if drawing_data.get("bom_table"):
        _write_bom_table(msp, drawing_data["bom_table"], bom_data)

    # 保存
    doc.saveas(output_path)
    return output_path


def generate_dxf_from_step(step_path, output_path, template=None, params=None,
                           views=None, bom_data=None):
    """从 STEP 文件生成 DXF 工程图(完整流水线)

    Args:
        step_path: STEP 文件路径
        output_path: 输出 DXF 路径
        template: 模板 dict(为 None 则用默认模板)
        params: 标题栏参数(model_code, series, date, scale 等)
        views: 视图列表(默认 ["front", "top"])
        bom_data: BOM 表数据

    Returns:
        (output_path, elapsed_time, unmatched_dims)
    """
    import time
    from core.drawing_engine import generate_drawing_views_raw
    from drawing.rule_template.drawing_template import (
        apply_template, load_default_template)

    t0 = time.time()

    # 1. 投影
    views_data = generate_drawing_views_raw(step_path, views=views)

    # 2. 加载模板
    if template is None:
        template = load_default_template()

    # 3. 应用模板(匹配边线 + 计算标注)
    drawing_data = apply_template(views_data, template, params)

    # 4. 导出 DXF
    export_drawing_to_dxf(drawing_data, output_path, bom_data)

    elapsed = time.time() - t0
    return output_path, round(elapsed, 3), drawing_data.get("unmatched", [])
