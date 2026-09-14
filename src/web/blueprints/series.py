# -*- coding: utf-8 -*-
"""系列模板覆盖度面板

页面 /series 提供可视化看板:哪些模板身份缺基准模型、哪些缺人工标注模板;
接口 /api/series/coverage 返回覆盖度明细。基准模型生成复用装配蓝图的
/api/build,本蓝图不重复构建逻辑。
"""
from flask import Blueprint, jsonify, send_file

from web import common
from web import series_catalog

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
