# -*- coding: utf-8 -*-
"""系列模板覆盖度面板

页面 /series 提供可视化看板:哪些模板身份缺基准模型、哪些缺人工标注模板;
/api/series/coverage 返回覆盖度明细;/api/series/template-default 人工指定
某身份出图统一采用的模板。基准模型生成复用装配蓝图的 /api/build,本蓝图
不重复构建逻辑。
"""
from flask import Blueprint, jsonify, request, send_file

from web import common
from web import series_catalog
from web.blueprints import template_helpers as th

bp = Blueprint("series", __name__)


@bp.route("/series")
def series_panel():
    return send_file(common.SERIES_PANEL_HTML)


@bp.route("/api/series/coverage")
def api_series_coverage():
    rows = series_catalog.coverage()
    return jsonify({
        "ok": True,
        "summary": series_catalog.coverage_summary(rows),
        "rows": rows,
    })


@bp.route("/api/series/template-default", methods=["POST"])
def api_set_template_default():
    """指定某身份出图统一采用的模板;template_id 传空表示恢复自动挑选"""
    body = request.get_json(silent=True) or {}
    identity = (body.get("identity") or "").strip()
    template_id = (body.get("template_id") or "").strip() or None
    if not identity:
        return jsonify({"ok": False, "error": "缺少 identity"}), 400

    if template_id:
        doc, err = th.load_template_doc(template_id)
        if err:
            return err
        doc_identity = doc.get("template_identity") or th.template_identity(
            doc.get("model_id", ""))
        if doc_identity != identity:
            return jsonify({"ok": False, "error": (
                f"模板 {template_id} 属于身份 {doc_identity},"
                f"不能指定给 {identity}")}), 400

    try:
        th.set_template_default(identity, template_id)
    except OSError as e:
        return jsonify({"ok": False, "error": f"指定表写入失败: {e}"}), 500
    return jsonify({"ok": True, "identity": identity,
                    "template_id": template_id})
