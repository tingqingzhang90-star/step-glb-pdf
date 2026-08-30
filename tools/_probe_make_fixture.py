# -*- coding: utf-8 -*-
"""临时探针: 从基准型号调色板提取真实边线下标,生成前端风格模板夹具(验证后删除)"""
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from core import drawing_engine
from drawing import anchor_resolver

BASE = "250-E-H2K1-L100-D11"
OUT_DIR = os.path.join(_ROOT, "output")
TPL_PATH = os.path.join(_ROOT, "data", "templates", "engineering", f"{BASE}.json")


def vertical_edges_at(edges, x_target, tol=3.0):
    """left 视图中 mm x 坐标 ≈ x_target 的竖直边索引列表"""
    hits = []
    for i, seg in enumerate(edges):
        if seg.get("type") != "line":
            continue
        m = (seg.get("meta") or {}).get("mm_coords")
        if not m or len(m) < 4:
            continue
        if (seg["meta"].get("orientation") != "vertical"):
            continue
        if abs(m[0] - x_target) < tol and abs(m[2] - x_target) < tol:
            hits.append((i, m))
    return hits


def circles(edges):
    out = []
    for i, seg in enumerate(edges):
        meta = seg.get("meta") or {}
        if seg.get("type") == "circle":
            out.append((i, meta.get("radius"), meta.get("center_mm"),
                        seg.get("r")))
        elif seg.get("type") == "polyline" and meta.get("curve") == "circle":
            out.append((i, meta.get("radius"), meta.get("center_mm"), None))
    return out


def main():
    shape = os.path.join(OUT_DIR, BASE, "assembly.step")
    palette = drawing_engine.generate_all_standard_views(shape)
    profile = anchor_resolver.resolve_anchors(BASE)
    anchors = {a["id"]: a for a in profile["anchors"]}

    back_z = anchors["cylinder.back_end"]["point3d"][2]
    front_z = anchors["cylinder.front_end"]["point3d"][2]
    motor = anchors.get("motor.body")
    mmin, mmax = motor["bbox_min"], motor["bbox_max"]
    print(f"back_end z={back_z}, front_end z={front_z}")
    print(f"motor bbox z: [{mmin[2]}, {mmax[2]}]")

    left = palette["views"]["left"]
    front = palette["views"]["front"]
    print(f"left edges: {len(left['edges'])}, front edges: {len(front['edges'])}")

    # 缸体两端竖直边
    back_hits = vertical_edges_at(left["edges"], back_z)
    front_hits = vertical_edges_at(left["edges"], front_z)
    print(f"\nback_end 附近竖直边: {[(i, m) for i, m in back_hits]}")
    print(f"front_end 附近竖直边: {[(i, m) for i, m in front_hits]}")

    # 电机区竖直边(z < mmax[2])
    motor_v = []
    for i, seg in enumerate(left["edges"]):
        if seg.get("type") != "line":
            continue
        m = (seg.get("meta") or {}).get("mm_coords")
        if not m or seg["meta"].get("orientation") != "vertical":
            continue
        if max(m[0], m[2]) <= mmax[2] + 5:
            motor_v.append((i, m))
    print(f"\n电机区竖直边: {[(i, m) for i, m in motor_v]}")

    # 圆
    print(f"\nleft circles: {circles(left['edges'])}")
    print(f"front circles: {circles(front['edges'])}")

    # ---- 生成模板 ----
    assert back_hits and front_hits, "缸体两端边未找到"
    idx_back = back_hits[0][0]
    idx_front = front_hits[0][0]
    assert motor_v, "电机区边未找到"
    motor_v_sorted = sorted(motor_v, key=lambda t: min(t[1][0], t[1][2]))
    idx_motor_a = motor_v_sorted[0][0]
    idx_motor_b = motor_v_sorted[-1][0]

    fc = circles(front["edges"])
    lc = circles(left["edges"])
    idx_circle, circle_view = None, None
    if fc:
        idx_circle, circle_view = max(fc, key=lambda t: t[1] or 0)[0], "view_2"
    elif lc:
        idx_circle, circle_view = max(lc, key=lambda t: t[1] or 0)[0], "view_1"

    doc = {
        "sheet": {"size": "A0", "width": 1189, "height": 841},
        "model_id": BASE,
        "template_kind": "frontend-instance",
        "template_identity": "-".join(BASE.split("-")[:3]),
        "schema_version": 1,
        "views": [
            {"id": "view_1", "source_view": "left", "label": "左视",
             "x": 80, "y": 100, "scale": 1.5,
             "px_per_mm": left["bbox"].get("scale")},
            {"id": "view_2", "source_view": "front", "label": "主视",
             "x": 780, "y": 150, "scale": 0.8,
             "px_per_mm": front["bbox"].get("scale")},
        ],
        "annotations": [
            {"id": "dim_1", "type": "linear", "mode": "parallel", "text": "",
             "customText": None, "bind_motor": False,
             "refs": [
                 {"viewId": "view_1", "idx": idx_back, "type": "edges"},
                 {"viewId": "view_1", "idx": idx_front, "type": "edges"}],
             "offset": 60, "radius": None, "side": None,
             "leaderAngle": None, "leaderLength": None, "color": "#303133"},
            {"id": "dim_2", "type": "linear", "mode": "parallel", "text": "",
             "customText": "减速机尺寸", "bind_motor": True,
             "refs": [
                 {"viewId": "view_1", "idx": idx_motor_a, "type": "edges"},
                 {"viewId": "view_1", "idx": idx_motor_b, "type": "edges"}],
             "offset": -90, "radius": None, "side": None,
             "leaderAngle": None, "leaderLength": None, "color": "#409eff"},
        ],
    }
    if idx_circle is not None:
        doc["annotations"].append({
            "id": "dim_3", "type": "diameter", "mode": None, "text": "",
            "customText": None, "bind_motor": False,
            "refs": [{"viewId": circle_view, "idx": idx_circle, "type": "edges"}],
            "offset": None, "radius": None, "side": None,
            "leaderAngle": -0.785, "leaderLength": 45, "color": "#303133"})
        doc["annotations"].append({
            "id": "dim_4", "type": "center-mark", "mode": None, "text": "",
            "customText": None, "bind_motor": False,
            "refs": [{"viewId": circle_view, "idx": idx_circle, "type": "edges"}],
            "offset": None, "radius": None, "side": None,
            "leaderAngle": None, "leaderLength": None, "color": "#303133"})

    os.makedirs(os.path.dirname(TPL_PATH), exist_ok=True)
    with open(TPL_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"\n模板已写入: {TPL_PATH}")
    print(f"idx_back={idx_back}, idx_front={idx_front}, "
          f"idx_motor=({idx_motor_a},{idx_motor_b}), "
          f"circle=({idx_circle},{circle_view})")


if __name__ == "__main__":
    main()
