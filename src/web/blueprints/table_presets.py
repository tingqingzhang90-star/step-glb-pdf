# -*- coding: utf-8 -*-
"""表格模板(整套表格布局)存取接口

前端把当前图纸上的整套表格(含坐标)存到后端,幅面一致时按原坐标灌回画布。
落盘 data/table-presets/<id>.json,与工程图模板(data/templates/engineering/)平行;
data/* 已在 .gitignore 忽略,用户数据不入库。表格模板是通用布局,全局共享,
不绑定具体型号。
"""
import json
import os
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request

from web import common

bp = Blueprint("table_presets", __name__)

# 模块级目录,便于测试 monkeypatch;id 只允许字母数字下划线连字符,文件名据此拼
PRESETS_DIR = common.TABLE_PRESETS_DIR
_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def _safe_id(preset_id):
    """拒绝路径穿越与非法字符,文件落盘前必须过这一关"""
    return bool(preset_id) and all(ch in _ID_CHARS for ch in preset_id)


@bp.route("/api/table-presets", methods=["GET"])
def api_list_table_presets():
    """列出全部模板,直接返回完整内容供 apply 灌回画布"""
    if not os.path.isdir(PRESETS_DIR):
        return jsonify({"ok": True, "presets": []})
    presets = []
    for name in sorted(os.listdir(PRESETS_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(PRESETS_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        # 表格模板数据量通常不大,列表直接返回完整内容,apply 可直接灌回画布
        presets.append(doc)
    return jsonify({"ok": True, "presets": presets})


@bp.route("/api/table-presets", methods=["POST"])
def api_save_table_preset():
    """保存一整套表格为模板,id 由后端生成避免冲突"""
    doc = request.get_json(silent=True)
    if not isinstance(doc, dict):
        return jsonify({"ok": False, "error": "请求体必须是 JSON 对象"}), 400
    name = (doc.get("name") or "").strip()
    tables = doc.get("tables")
    if not name:
        return jsonify({"ok": False, "error": "缺少模板名称"}), 400
    if not isinstance(tables, list) or not tables:
        return jsonify({"ok": False, "error": "tables 必须是非空数组"}), 400
    preset_id = "preset_%s" % uuid.uuid4().hex[:12]
    record = {
        "id": preset_id,
        "name": name,
        "createdAt": datetime.now().isoformat(),
        "tables": tables,
    }
    try:
        os.makedirs(PRESETS_DIR, exist_ok=True)
        with open(os.path.join(PRESETS_DIR, f"{preset_id}.json"),
                  "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    except OSError as e:
        return jsonify({"ok": False, "error": f"写入失败: {e}"}), 500
    return jsonify({"ok": True, "id": preset_id, "name": name,
                    "createdAt": record["createdAt"]})


@bp.route("/api/table-presets/<path:preset_id>", methods=["DELETE"])
def api_delete_table_preset(preset_id):
    if not _safe_id(preset_id):
        return jsonify({"ok": False, "error": "非法 id"}), 400
    path = os.path.join(PRESETS_DIR, f"{preset_id}.json")
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "模板不存在"}), 404
    try:
        os.remove(path)
    except OSError as e:
        return jsonify({"ok": False, "error": f"删除失败: {e}"}), 500
    return jsonify({"ok": True})
