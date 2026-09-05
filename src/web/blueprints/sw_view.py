# -*- coding: utf-8 -*-
"""SolidWorks 风格视图调色板接口

挂载到 /api/drawing-view-palette、/api/drawing-view-single。
OCC 投影走 web.task_pool 子进程。
"""
import os

from flask import Blueprint, jsonify

from web import common
from web import task_pool

pool = task_pool.get_pool()
bp = Blueprint("sw_view", __name__)


def _find_model_shape_path(model_code):
    """查找模型形状文件路径(优先 STEP,回退 BRep 缓存)"""
    model_dir = os.path.join(common.OUT_DIR, model_code)
    step_path = os.path.join(model_dir, "assembly.step")
    if os.path.isfile(step_path):
        return step_path
    brep_path = os.path.join(model_dir, "assembly.brep")
    if os.path.isfile(brep_path):
        return brep_path
    return None


@bp.route("/api/drawing-view-palette/<model_code>")
def api_drawing_view_palette(model_code):
    from core import drawing_engine
    shape_path = _find_model_shape_path(model_code)
    if not shape_path:
        return jsonify({"ok": False,
                        "error": f"未找到模型文件(assembly.step 或 assembly.brep): {model_code}"}), 404
    try:
        result = pool.run("view-palette", "palette:%s" % model_code, {"shape_path": shape_path})
        try:
            from drawing import anchor_resolver
            from drawing.dim import dim_envelope
            anchors = anchor_resolver.resolve_anchors(model_code)["anchors"]
            motor_envelope = {}
            gearbox_envelope = {}
            for view_name in result["views"]:
                env = dim_envelope.envelope_faces(anchors, view_name, body_id="motor.body")
                if env:
                    motor_envelope[view_name] = {
                        "orientation": env["orientation"],
                        "face_min": env["face_min"],
                        "face_max": env["face_max"],
                        "span_mm": env["span_mm"],
                        "outline": env["outline"],
                    }
                env2 = dim_envelope.gearbox_envelope_faces(anchors, view_name)
                if env2:
                    gearbox_envelope[view_name] = {
                        "orientation": env2["orientation"],
                        "face_min": env2["face_min"],
                        "face_max": env2["face_max"],
                        "span_mm": env2["span_mm"],
                        "outline": env2["outline"],
                    }
            result["motor_envelope"] = motor_envelope
            result["gearbox_envelope"] = gearbox_envelope
        except Exception:
            result["motor_envelope"] = {}
            result["gearbox_envelope"] = {}
        return jsonify({"ok": True, **result})
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "traceback": traceback.format_exc()}), 500


@bp.route("/api/drawing-view-single/<model_code>/<view_name>")
def api_drawing_view_single(model_code, view_name):
    from core import drawing_engine
    shape_path = _find_model_shape_path(model_code)
    if not shape_path:
        return jsonify({"ok": False, "error": f"未找到模型文件: {model_code}"}), 404
    try:
        view = pool.run("view-single", "view:%s:%s" % (model_code, view_name),
                        {"shape_path": shape_path, "view_name": view_name})
        if view is None:
            return jsonify({"ok": False, "error": f"无效的视图名: {view_name}"}), 400
        return jsonify({"ok": True, "view": view})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
