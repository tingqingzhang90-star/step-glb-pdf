# -*- coding: utf-8 -*-
"""服务端轻量出图端点

POST /api/render-drawing
  入参: { "model_id": "250-E-H2K1-L100-5.5KW电机", "spec": { ... } }
  行为:
    1. 定位 output/<model_id>/drawing_source.json(同系列复用,不触发几何 build)。
    2. 把 spec 回填进 title_block.fields[].value 与 技术参数表 cells[].text。
    3. 渲染为 PDF,返回 { "pdf_url": "/download/<model_id>/drawing.pdf" }。
  约定:仅当该 model_id 已有 drawing_source.json 时出图;否则返回明确错误,
        由运营在 cad-viewer-app 预生成或走后续重绑引擎,不在本阶段自动 build。
"""
import json
import os

from flask import Blueprint, jsonify, request

from web import common
from web.drawing_spec_map import find_drawing_source, apply_spec
from drawing.drawing_source_render import render_drawing_source_pdf

bp = Blueprint("render", __name__)

_OUT_NAME = "drawing.pdf"


@bp.route("/api/render-drawing", methods=["POST"])
def api_render_drawing():
    data = request.get_json(force=True) or {}
    model_id = (data.get("model_id") or "").strip()
    spec = data.get("spec") or {}
    if not model_id:
        return jsonify({"ok": False, "error": "model_id 不能为空"}), 400

    src_path = find_drawing_source(model_id)
    if not src_path:
        return jsonify({
            "ok": False,
            "error": (
                f"未找到型号 {model_id} 的 drawing_source.json,"
                "请先在 cad-viewer-app 预生成或确认同系列模板已存在"
            )
        }), 404

    try:
        with open(src_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return jsonify({"ok": False, "error": f"读取源文件失败: {e}"}), 500

    # 原地回填规格(只改可编辑内容,不动几何)
    apply_spec(doc, model_id, spec)

    model_dir = os.path.dirname(src_path)
    out_pdf = os.path.join(model_dir, _OUT_NAME)
    try:
        out_abs = render_drawing_source_pdf(doc, out_pdf)
    except Exception as e:  # 渲染失败不污染已有源文件
        return jsonify({"ok": False, "error": f"渲染失败: {e}"}), 500

    # pdf_url 为 OUT_DIR 下未编码相对路径,编码由前端 downloadUrl() 按段处理
    rel = f"{model_id}/{_OUT_NAME}"
    return jsonify({
        "ok": True,
        "model_id": model_id,
        "pdf_url": rel,
        "pdf_path": os.path.relpath(out_abs, common.OUT_DIR).replace("\\", "/"),
    })
