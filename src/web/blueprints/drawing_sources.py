# -*- coding: utf-8 -*-
"""图纸源文件清单接口

output/ 下的每个型号子目录都会产出 drawing_source.json(可由前端「导出源文件」
回灌画布)。这里把它们聚合成下拉可选项,避免每次都靠文件选择器手动找文件。

仅读 output 目录,不做任何写入;型号子目录名经白名单校验,杜绝路径穿越。
"""
import json
import os

from flask import Blueprint, jsonify

from web import common

bp = Blueprint("drawing_sources", __name__)

OUT_DIR = common.OUT_DIR
_SOURCE_NAME = "drawing_source.json"
# 子目录名只允许字母数字、中文、空格、下划线、连字符、点
_NAME_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    "_.- " + "".join(chr(c) for c in range(0x4E00, 0x9FFF + 1))
)


def _safe_name(name):
    """拒绝路径穿越与非法字符(型号子目录名)"""
    return bool(name) and all(ch in _NAME_CHARS for ch in name)


def _read_meta(path):
    """只抽 model_id / sheet.size,避免把几百 KB 的源文件整体读进列表响应"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            head = ""
            while len(head) < 4096:
                chunk = f.read(1024)
                if not chunk:
                    break
                head += chunk
                if "}" in head and '"views"' in head:
                    break
        doc = json.loads(head)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    sheet = doc.get("sheet") or {}
    return {
        "model_id": doc.get("model_id") or None,
        "sheet": sheet.get("size") or None,
    }


@bp.route("/api/drawing-sources", methods=["GET"])
def api_list_drawing_sources():
    """列出 output 下全部含 drawing_source.json 的型号目录"""
    if not os.path.isdir(OUT_DIR):
        return jsonify({"ok": True, "sources": []})
    sources = []
    for name in sorted(os.listdir(OUT_DIR)):
        dir_path = os.path.join(OUT_DIR, name)
        if not os.path.isdir(dir_path):
            continue
        src_path = os.path.join(dir_path, _SOURCE_NAME)
        if not os.path.isfile(src_path):
            continue
        meta = _read_meta(src_path) or {}
        sources.append({
            "name": name,
            "model_id": meta.get("model_id"),
            "sheet": meta.get("sheet"),
        })
    return jsonify({"ok": True, "sources": sources})


@bp.route("/api/drawing-sources/<path:name>", methods=["GET"])
def api_get_drawing_source(name):
    """返回指定型号目录的 drawing_source.json 原文,供前端 apply 灌回画布"""
    if not _safe_name(name):
        return jsonify({"ok": False, "error": "非法目录名"}), 400
    src_path = os.path.join(OUT_DIR, name, _SOURCE_NAME)
    if not os.path.isfile(src_path):
        return jsonify({"ok": False, "error": "源文件不存在"}), 404
    try:
        with open(src_path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        return jsonify({"ok": False, "error": f"读取失败: {e}"}), 500
    return jsonify({"ok": True, "name": name, "raw": raw})
