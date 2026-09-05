# -*- coding: utf-8 -*-
"""SW 选型对比面板 + 接口

挂载到 /sw-compare(面板页面)与 /api/options、/api/sw-apply。
SW COM 非线程安全,用 _lock 串行所有选型操作。
"""
import json
import os
import threading

from flask import Blueprint, jsonify, request, Response

from core.rebuild_assembly import (
    parse_model_code, resolve_visibility, load_config,
    compute_cylinder_scale, MOTOR_CODES, _KEY_RE)

from web import common
from web.blueprints import sw_compare_ops as ops

bp = Blueprint("sw_compare", __name__)
_lock = threading.Lock()  # COM 非线程安全,串行执行


@bp.route("/sw-compare")
def index():
    with open(common.SW_COMPARE_PANEL_HTML, encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/html")


@bp.route("/api/sw-apply", methods=["POST"])
def api_sw_apply():
    """在 SW 中切换选型"""
    body = request.get_json(force=True)
    model_code = body.get("model_code", "").strip()
    motor = body.get("motor")
    series = body.get("series")

    if not model_code:
        return jsonify({"ok": False, "error": "缺少 model_code"}), 400

    with _lock:
        result = ops.sw_apply_selection(model_code, motor, series)
    return jsonify(result)
