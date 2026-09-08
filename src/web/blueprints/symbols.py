# -*- coding: utf-8 -*-
"""SVG 符号库:上传 / 列表 / 服务。

符号存于 <PROJECT_ROOT>/data/symbols/,文件名形如 <uuid>_<原名>.svg,
单元格通过相对文件名(cell.symbol)引用。前端拖拽放置时只存文件名,
后端出图再解析为绝对路径绘制。
"""
import os
import re
import uuid

from flask import Blueprint, jsonify, request, send_file, abort

from web import common

bp = Blueprint("symbols", __name__)

_MAX_BYTES = 512 * 1024  # 单符号上限 512KB


def _safe_name(name):
    """清洗文件名:去路径、去危险字符,强制 .svg 后缀"""
    name = os.path.basename(name or "symbol.svg")
    name = re.sub(r"[^\w.\-]", "_", name) or "symbol.svg"
    if not name.lower().endswith(".svg"):
        name += ".svg"
    return name[:80]


def _display_name(stored):
    """去掉 uuid 前缀,还原可读原名"""
    base, _ = os.path.splitext(stored)
    parts = base.split("_", 1)
    if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{32}", parts[0]):
        return parts[1]
    return stored


@bp.route("/api/symbols", methods=["GET"])
def api_list_symbols():
    symbols = []
    if os.path.isdir(common.SYMBOLS_DIR):
        for fn in sorted(os.listdir(common.SYMBOLS_DIR)):
            if not fn.lower().endswith(".svg"):
                continue
            symbols.append({"file": fn, "name": _display_name(fn),
                            "url": f"/api/symbols/{fn}"})
    return jsonify({"ok": True, "symbols": symbols})


@bp.route("/api/symbols/upload", methods=["POST"])
def api_upload_symbol():
    f = request.files.get("file")
    if f is None:
        return jsonify({"ok": False, "error": "缺少 file 字段"}), 400
    raw = f.read()
    if not raw:
        return jsonify({"ok": False, "error": "文件为空"}), 400
    if len(raw) > _MAX_BYTES:
        return jsonify({"ok": False, "error": "SVG 超过 512KB"}), 413
    # 内容校验:必须含 <svg 根标签(容错前导空白/注释)
    if b"<svg" not in raw[:4000].lower():
        return jsonify({"ok": False, "error": "不是合法的 SVG 文件"}), 400
    os.makedirs(common.SYMBOLS_DIR, exist_ok=True)
    stored = f"{uuid.uuid4().hex}_{_safe_name(f.filename)}"
    path = os.path.join(common.SYMBOLS_DIR, stored)
    try:
        with open(path, "wb") as fp:
            fp.write(raw)
    except OSError as e:
        return jsonify({"ok": False, "error": f"写入失败: {e}"}), 500
    return jsonify({"ok": True, "file": stored, "name": _display_name(stored),
                    "url": f"/api/symbols/{stored}"})


@bp.route("/api/symbols/<path:file>", methods=["GET"])
def api_serve_symbol(file):
    # 防目录穿越:只用 basename,忽略 path 余下部分
    fn = os.path.basename(file)
    if not fn.lower().endswith(".svg"):
        abort(400)
    path = os.path.join(common.SYMBOLS_DIR, fn)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype="image/svg+xml")
