# -*- coding: utf-8 -*-
"""前端实例模板存取 + 模板出图接口

挂载到 /api/drawing-template、/api/drawing-templates、
/api/template-drawing/{upload,series-models,generate,download,preview}。
"""
import json
import os

from flask import Blueprint, jsonify, request, send_file

from drawing import frontend_template
from web import common
from web.blueprints import template_helpers as th

bp = Blueprint("template", __name__)


@bp.route("/api/drawing-template", methods=["POST"])
def api_save_drawing_template():
    """保存前端编辑器当前图纸为实例模板"""
    doc = request.get_json(silent=True)
    if not isinstance(doc, dict):
        return jsonify({"ok": False, "error": "请求体必须是 JSON 对象"}), 400
    model_id = doc.get("model_id")
    views = doc.get("views")
    if not model_id or not isinstance(model_id, str):
        return jsonify({"ok": False, "error": "缺少 model_id(请先导入模型)"}), 400
    if not views:
        return jsonify({"ok": False, "error": "views 为空(请先放置视图)"}), 400
    doc = dict(doc)
    doc["template_kind"] = "frontend-instance"
    doc["template_identity"] = th.template_identity(model_id)
    doc.setdefault("schema_version", "1.0")
    os.makedirs(th.TEMPLATES_DIR, exist_ok=True)
    path = os.path.join(th.TEMPLATES_DIR, f"{model_id}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
    except OSError as e:
        return jsonify({"ok": False, "error": f"写入失败: {e}"}), 500
    return jsonify({"ok": True, "template_id": model_id,
                    "identity": doc["template_identity"], "path": path})


@bp.route("/api/drawing-templates", methods=["GET"])
def api_list_drawing_templates():
    if not os.path.isdir(th.TEMPLATES_DIR):
        return jsonify({"ok": True, "templates": []})
    templates = []
    for name in sorted(os.listdir(th.TEMPLATES_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(th.TEMPLATES_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        templates.append({
            "template_id": doc.get("model_id"),
            "identity": doc.get("template_identity"),
            "view_count": len(doc.get("views", [])),
            "annotation_count": len(doc.get("annotations", [])),
            "file": name,
        })
    return jsonify({"ok": True, "templates": templates})


@bp.route("/api/template-drawing/upload", methods=["POST"])
def api_upload_drawing_template():
    """上传前端导出的实例模板 JSON(multipart 或 application/json)"""
    doc, err = th.parse_uploaded_template()
    if err:
        return err
    model_id, views = doc["model_id"], doc["views"]
    doc = dict(doc)
    doc["template_kind"] = "frontend-instance"
    doc["template_identity"] = th.template_identity(model_id)
    doc.setdefault("schema_version", "1.0")
    try:
        th.save_template_doc(model_id, doc)
    except OSError as e:
        return jsonify({"ok": False, "error": f"写入失败: {e}"}), 500
    return jsonify({
        "ok": True, "template_id": model_id, "identity": doc["template_identity"],
        "view_count": len(views), "annotation_count": len(doc.get("annotations", []))})


@bp.route("/api/template-drawing/series-models")
def api_series_models():
    """列出与指定模板身份同系列、且已生成过模型的全部型号"""
    identity = request.args.get("identity", "").strip()
    template_id = request.args.get("template_id", "").strip()
    if not identity and template_id:
        identity = th.template_identity(template_id)
    if not identity:
        return jsonify({"ok": False, "error": "缺少 identity 或 template_id"}), 400
    if not os.path.isdir(common.OUT_DIR):
        return jsonify({"ok": True, "identity": identity, "models": []})
    models = []
    for name in sorted(os.listdir(common.OUT_DIR)):
        model_dir = os.path.join(common.OUT_DIR, name)
        if not os.path.isdir(model_dir):
            continue
        if th.template_identity(name) != identity:
            continue
        has_step = os.path.isfile(os.path.join(model_dir, "assembly.step"))
        has_brep = os.path.isfile(os.path.join(model_dir, "assembly.brep"))
        if not (has_step or has_brep):
            continue
        models.append({
            "model_code": name,
            "has_pdf": os.path.isfile(os.path.join(model_dir, "drawing_frontend.pdf")),
        })
    return jsonify({"ok": True, "identity": identity, "models": models})


@bp.route("/api/template-drawing/generate", methods=["POST"])
def api_generate_from_template():
    """用实例模板对选定型号批量生成工程图 PDF"""
    body = request.get_json(silent=True) or {}
    template_id = body.get("template_id")
    models = body.get("models") or []
    if not template_id:
        return jsonify({"ok": False, "error": "缺少 template_id"}), 400
    if not isinstance(models, list) or not models:
        return jsonify({"ok": False, "error": "models 必须是非空数组"}), 400
    template_doc, err = th.load_template_doc(template_id)
    if err:
        return err
    tmpl_identity = template_doc.get("template_identity") or \
        th.template_identity(template_doc.get("model_id", ""))
    err = th.reject_cross_series(models, tmpl_identity)
    if err:
        return err
    results, err = th.generate_frontend_batch(template_id, template_doc, models)
    if err:
        return err
    return jsonify({
        "ok": True, "identity": tmpl_identity, "template_id": template_id,
        "results": th.to_client_results(results)})


@bp.route("/api/template-drawing/prepare-source", methods=["POST"])
def api_prepare_source_from_template():
    """把选定模板重绑到目标型号,产出可直接编辑的 drawing_source.json

    看板「继续标注」的入口。模板里固化的是**模板型号**的边线引用,跨型号直接载入
    会几何错位,所以这里走与批量出图完全相同的重绑链路(dim_rebind 几何指纹匹配),
    把标注落到目标型号的边线上并落盘源文件;编辑器载入后即可在原标注基础上继续加注。

    返回 unmatched 供编辑器提示"哪些标注在本型号找不到对应几何,已跳过"。
    """
    body = request.get_json(silent=True) or {}
    template_id = (body.get("template_id") or "").strip()
    model = (body.get("model") or "").strip()
    if not template_id or not model:
        return jsonify({"ok": False, "error": "缺少 template_id 或 model"}), 400

    template_doc, err = th.load_template_doc(template_id)
    if err:
        return err
    tmpl_identity = template_doc.get("template_identity") or \
        th.template_identity(template_doc.get("model_id", ""))
    err = th.reject_cross_series([model], tmpl_identity)
    if err:
        return err

    # 目标型号必须已有几何:否则重绑无从谈起(与看板「生成模型」前置一致)
    try:
        shape_path = frontend_template.find_model_shape(common.OUT_DIR, model)
    except FileNotFoundError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    results, err = th.generate_frontend_batch(template_id, template_doc, [model])
    if err:
        return err
    r = (results or [{}])[0]
    if not r.get("ok"):
        return jsonify({"ok": False, "error": r.get("error") or "重绑生成失败"}), 500

    # 源文件目录名取实际落盘目录(型号可能带/不带 YRJ 前缀),前端据此调
    # /api/drawing-sources/<dir> 取回原文
    source_dir = os.path.basename(os.path.dirname(shape_path))
    return jsonify({
        "ok": True,
        "model": model,
        "source_dir": source_dir,
        "source": f"{source_dir}/drawing_source.json",
        "template_id": template_id,
        "view_count": len(template_doc.get("views", [])),
        "unmatched": r.get("unmatched", []),
    })


@bp.route("/api/template-drawing/download/<path:relpath>")
def api_download_template_pdf(relpath):
    """下载生成的工程图 PDF(relpath 为相对项目根的路径)"""
    abs_path = os.path.abspath(os.path.join(common.PROJECT_ROOT, relpath))
    if not abs_path.startswith(os.path.abspath(common.PROJECT_ROOT) + os.sep):
        return jsonify({"ok": False, "error": "非法路径"}), 400
    if not os.path.isfile(abs_path):
        return jsonify({"ok": False, "error": "文件不存在"}), 404
    return send_file(abs_path, mimetype="application/pdf", as_attachment=True,
                     download_name=os.path.basename(abs_path))


@bp.route("/api/template-drawing/preview/<path:relpath>")
def api_preview_template_pdf(relpath):
    """在线预览生成的工程图 PDF(浏览器内嵌打开,非下载)"""
    abs_path = os.path.abspath(os.path.join(common.PROJECT_ROOT, relpath))
    if not abs_path.startswith(os.path.abspath(common.PROJECT_ROOT) + os.sep):
        return jsonify({"ok": False, "error": "非法路径"}), 400
    if not os.path.isfile(abs_path):
        return jsonify({"ok": False, "error": "文件不存在"}), 404
    return send_file(abs_path, mimetype="application/pdf")
