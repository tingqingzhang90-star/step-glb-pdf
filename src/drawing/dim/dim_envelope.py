# -*- coding: utf-8 -*-
"""电机包络投影 — 各视图下减速机两端面线段的唯一计算入口

规则式模板(drawing_template)与前端实例模板(dim_rebind)共用本模块,
避免两处各写一份导致支持的视图范围不一致。

motor.axis_min/max_face 的 point3d 是端面**中心**,直接当尺寸线端点会让
延伸线穿过减速机实体。这里改从 motor.body 包围盒 8 角点的投影求真实
轮廓,再按两端面中心连线判定轴向,得出贴合包络的端面线段。

轴向垂直于投影面的视图(如 front 看 Z 轴机型)两端面重合,返回 None,
调用方按"该视图不可标注"处理,不画零长度尺寸线。
"""
import math

from drawing.rule_template.drawing_template import _anchor_to_2d_point

_DEGENERATE_MM = 1.0  # 两端面投影间距低于此值即视为轴向退化


def _outline_2d(bbox_min, bbox_max, view_name):
    """包围盒 8 角点投影后的 2D 包络矩形 (xmin, ymin, xmax, ymax)"""
    corners = [(x, y, z) for x in (bbox_min[0], bbox_max[0])
               for y in (bbox_min[1], bbox_max[1])
               for z in (bbox_min[2], bbox_max[2])]
    pts = [_anchor_to_2d_point({"point3d": list(c)}, view_name) for c in corners]
    xs = [p[0] for p in pts if p]
    ys = [p[1] for p in pts if p]
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def envelope_faces(anchors, view_name, body_id="motor.body"):
    """指定包络体在视图下的两个端面线段(模型 mm 投影坐标)

    Args:
        anchors: 锚点列表(resolve_anchors()["anchors"] 或 anchor_map.values())
        view_name: 视图名(front/left/top/...)
        body_id: 包络体 anchor id,如 "motor.body"(电机+减速机) 或 "gearbox.body"(仅减速机)

    Returns:
        None 表示该视图不可标注(无包络,或轴向与投影垂直导致端面重合);
        否则 {"orientation", "face_min", "face_max", "outline", "span_mm"}。
        face_min/face_max 均为 ((x1,y1),(x2,y2)) 形式的端面轮廓线段。
    """
    by_id = {a["id"]: a for a in anchors}
    body = by_id.get(body_id)
    if not body or not body.get("bbox_min") or not body.get("bbox_max"):
        return None

    prefix = body_id.replace(".body", "")
    c1 = _anchor_to_2d_point(by_id.get(f"{prefix}.axis_min_face"), view_name)
    c2 = _anchor_to_2d_point(by_id.get(f"{prefix}.axis_max_face"), view_name)
    if not c1 or not c2:
        return None

    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    span = math.hypot(dx, dy)
    if span < _DEGENERATE_MM:
        return None

    outline = _outline_2d(body["bbox_min"], body["bbox_max"], view_name)
    if not outline:
        return None
    xmin, ymin, xmax, ymax = outline

    # 端面中心连线落在哪根轴上,轴向就是哪根;另一根轴取包络轮廓范围
    if abs(dx) >= abs(dy):
        faces = (((c1[0], ymin), (c1[0], ymax)), ((c2[0], ymin), (c2[0], ymax)))
        orient = "horizontal"
    else:
        faces = (((xmin, c1[1]), (xmax, c1[1])), ((xmin, c2[1]), (xmax, c2[1])))
        orient = "vertical"
    return {
        "orientation": orient,
        "face_min": faces[0],
        "face_max": faces[1],
        "outline": outline,
        "span_mm": round(span, 2),
    }


def gearbox_envelope_faces(anchors, view_name):
    """仅减速机包络在指定视图下的两个端面线段"""
    return envelope_faces(anchors, view_name, body_id="gearbox.body")


def envelope_endpoints(face, orientation, offset):
    """取端面线段上"朝向尺寸线"的端点,避免延伸线穿过包络内部

    偏移量为正时尺寸线画在视图下方/右方,故取屏幕下/右端点作延伸线起点。

    Args:
        face: 端面线段 ((x1,y1),(x2,y2))
        orientation: horizontal / vertical
        offset: 尺寸线偏移量(带符号)

    Returns:
        [x, y] 端点坐标
    """
    (ax, ay), (bx, by) = face
    if orientation == "horizontal":
        return [ax, max(ay, by)] if offset >= 0 else [ax, min(ay, by)]
    return [max(ax, bx), ay] if offset >= 0 else [min(ax, bx), ay]
