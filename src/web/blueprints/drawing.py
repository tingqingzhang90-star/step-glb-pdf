# -*- coding: utf-8 -*-
"""工程图编辑器页面 + 工程图生成接口

挂载到 /drawing(编辑器页面)与 /api/drawing-views、/api/drawing-pdf、
/api/generate-drawing、/api/drawing-dxf、/api/drawing-data。
OCC 计算走 web.task_pool 子进程。
"""
import datetime
import io
import os
import traceback

from flask import Blueprint, jsonify, request, send_file

from web import common
from web import task_pool

pool = task_pool.get_pool()
bp = Blueprint("drawing", __name__)


@bp.route("/drawing")
def drawing_editor():
    return send_file(common.DRAWING_EDITOR_HTML)


@bp.route("/api/drawing-views/<model_code>")
def api_drawing_views(model_code):
    from core import drawing_engine
    step_path = os.path.join(common.OUT_DIR, model_code, "assembly.step")
    if not os.path.isfile(step_path):
        return jsonify({"ok": False, "error": f"未找到 STEP 文件: {model_code}/assembly.step"}), 404
    try:
        result = pool.run("drawing-views", "views:%s" % model_code, {"step_path": step_path})
        return jsonify({"ok": True, "result": result})
    except task_pool.TaskError as e:
        return jsonify({"ok": False, "error": str(e), "traceback": e.traceback_text}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/drawing-pdf", methods=["POST"])
def api_drawing_pdf():
    """将前端 SVG 数据转换为 PDF 导出"""
    try:
        from reportlab.graphics import renderPDF
        from svglib.svglib import svg2rlg

        data = request.get_json()
        svg_str = data.get("svg", "")
        model = data.get("model", "untitled")

        svg_io = io.StringIO(svg_str)
        drawing = svg2rlg(svg_io)
        if drawing is None:
            return jsonify({"ok": False, "error": "SVG 解析失败"}), 500

        pdf_buffer = io.BytesIO()
        renderPDF.drawToFile(drawing, pdf_buffer, "工程图_" + model)
        pdf_buffer.seek(0)
        return send_file(pdf_buffer, mimetype="application/pdf",
                         as_attachment=True, download_name=f"工程图_{model}.pdf")
    except ImportError:
        return jsonify({"ok": False, "error": "缺少依赖: pip install svglib reportlab"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/generate-drawing/<model_code>", methods=["POST"])
def api_generate_drawing(model_code):
    from drawing import drawing_generator
    step_path = os.path.join(common.OUT_DIR, model_code, "assembly.step")
    if not os.path.isfile(step_path):
        return jsonify({"ok": False, "error": f"未找到 STEP 文件: {model_code}/assembly.step"}), 404
    try:
        data = request.get_json() or {}
        params = {
            "model_code": model_code,
            "stroke": int(data.get("stroke", 100)),
            "bore_diameter": data.get("bore_diameter", "250"),
            "motor_power": data.get("motor_power", ""),
            "rated_speed": data.get("rated_speed", ""),
            "rated_torque": data.get("rated_torque", ""),
            "max_speed": data.get("max_speed", ""),
            "screw_model": data.get("screw_model", ""),
            "screw_lead": data.get("screw_lead", ""),
            "reduction_ratio": data.get("reduction_ratio", ""),
            "positioning_accuracy": data.get("positioning_accuracy", "±0.02"),
        }
        output_pdf = os.path.join(common.OUT_DIR, model_code, "drawing.pdf")
        result = pool.run("drawing-pdf", "pdf:%s" % model_code, {
            "step_path": step_path, "output_pdf": output_pdf, "params": params})
        if not result["success"]:
            return jsonify({"ok": False, "error": result.get("error", "生成失败")}), 500
        return send_file(output_pdf, mimetype="application/pdf",
                         as_attachment=True, download_name=f"工程图_{model_code}.pdf")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "traceback": traceback.format_exc()}), 500


@bp.route("/api/drawing-dxf/<model_code>")
def api_drawing_dxf(model_code):
    from drawing import dxf_exporter
    from drawing.rule_template import drawing_template
    step_path = os.path.join(common.OUT_DIR, model_code, "assembly.step")
    if not os.path.isfile(step_path):
        return jsonify({"ok": False, "error": f"未找到 STEP 文件: {model_code}/assembly.step"}), 404
    try:
        parts = model_code.split("-")
        series = parts[0] if parts else ""
        params = {"model_code": model_code, "series": series,
                  "date": datetime.now().strftime("%Y-%m-%d"), "scale": "2"}
        output_dxf = os.path.join(common.OUT_DIR, model_code, "drawing.dxf")
        dxf_path, elapsed, unmatched = pool.run(
            "drawing-dxf", "dxf:%s" % model_code, {
                "step_path": step_path, "output_dxf": output_dxf, "params": params})
        return send_file(dxf_path, as_attachment=True,
                         download_name=f"工程图_{model_code}.dxf")
    except task_pool.TaskError as e:
        return jsonify({"ok": False, "error": str(e), "traceback": e.traceback_text}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "traceback": traceback.format_exc()}), 500


@bp.route("/api/drawing-data/<model_code>")
def api_drawing_data(model_code):
    from core import drawing_engine
    from drawing.rule_template import drawing_template
    step_path = os.path.join(common.OUT_DIR, model_code, "assembly.step")
    if not os.path.isfile(step_path):
        return jsonify({"ok": False, "error": f"未找到 STEP 文件: {model_code}/assembly.step"}), 404
    try:
        parts = model_code.split("-")
        series = parts[0] if parts else ""
        params = {"model_code": model_code, "series": series,
                  "date": datetime.now().strftime("%Y-%m-%d"), "scale": "2"}
        views_data = pool.run("drawing-views-raw", "raw:%s" % model_code, {"step_path": step_path})
        template = drawing_template.load_default_template()
        anchors = drawing_template.load_default_anchors()
        views_data["anchors"] = anchors
        drawing_data = drawing_template.apply_template(views_data, template, params)
        return jsonify({
            "ok": True, "drawing": drawing_data, "template": template,
            "anchors": anchors, "elapsed": views_data["elapsed"],
            "model_bbox": views_data["model_bbox"],
            "unmatched": drawing_data.get("unmatched", [])})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "traceback": traceback.format_exc()}), 500
