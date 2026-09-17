# -*- coding: utf-8 -*-
"""零件导出面板(图库系列 → 系列零件库)

挂载到 /part-export(面板页面)与 /api/series、/api/preview、/api/config、
/api/export、/api/export/status、/api/export/cancel。

SW COM 是 STA 且单个系列导出要几分钟:用全局 _task_lock 串行,后台线程执行,
取消走 _cancel_event。合并到统一服务后,此锁只串行导出请求,不阻塞 OCC 子进程任务。
"""
import json
import os
import sys
import threading
import time
import traceback

from flask import Blueprint, jsonify, request, send_file

from web import common
from core import build_config as bc
from core import part_exporter as pe
from core import paths

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

bp = Blueprint("part_export", __name__)

_MAX_LOGS = 500
_task_lock = threading.Lock()
_cancel_event = threading.Event()
_task = {"running": False, "finished": True, "logs": []}


def _log(msg):
    _task.setdefault("logs", []).append(msg)
    if len(_task["logs"]) > _MAX_LOGS:
        _task["logs"] = _task["logs"][-_MAX_LOGS:]


def _reset_task(series):
    return {
        "running": True, "finished": False, "series": series, "assembly": None,
        "total": 0, "done": 0, "stats": {}, "logs": [], "error": None,
        "result": None, "started_at": time.strftime("%H:%M:%S"),
    }


def _run_export(series, assembly, overwrite):
    """后台线程执行导出,进度写进全局 _task 供前端轮询"""

    def on_progress(event, payload):
        if _cancel_event.is_set():
            raise RuntimeError("已取消")
        if event == "start":
            _task["assembly"] = payload["assembly"]
            _task["total"] = payload["total"]
            _log(f"装配体: {os.path.basename(payload['assembly'])}")
            _log(f"组件数: {payload['total']}")
        elif event == "component":
            _task["done"] = payload["index"]
            _task["stats"][payload["status"]] = _task["stats"].get(payload["status"], 0) + 1
            reason = payload.get("reason")
            tail = f" ({reason})" if reason else ""
            _log(f"[{payload['index']}/{_task['total']}] {payload['name']} → "
                 f"{payload['status']}{tail}")
        elif event == "done":
            _task["result"] = payload
            _log(f"共享件: {payload.get('shared') or '无'}")
            _log(f"完成: 导出 {payload.get('exported', 0)} / "
                 f"跳过 {payload.get('skipped', 0)} / 失败 {payload.get('failed', 0)}")

    try:
        pe.export_series(series, assembly, overwrite, on_progress)
        # 零件表刚落盘,顺手生成系列配置,省得再跑一次 build_config
        try:
            config = bc.build_series_config(series)
            bc.write_series_config(config)
            _task["config"] = _config_summary(config)
            _log(f"系列配置已生成: 电机 {list(config['motor'])}")
        except Exception as cfg_exc:
            _log(f"系列配置生成失败: {cfg_exc}")
    except Exception as exc:
        _task["error"] = str(exc)
        _log(f"错误: {exc}")
        _log(traceback.format_exc(limit=3))
    finally:
        _task["running"] = False
        _task["finished"] = True


def _series_status(series):
    """系列的零件库现状:已导出零件数、导出时间、共享件"""
    parts_dir = paths.parts_dir(series)
    count = 0
    if os.path.isdir(parts_dir):
        count = len([f for f in os.listdir(parts_dir) if f.lower().endswith(".step")])
    meta = {}
    meta_path = paths.meta_json(series)
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    return {"part_count": count,
            "exported_at": meta.get("exported_at"),
            "component_count": meta.get("component_count"),
            "shared": meta.get("shared_parts", []),
            "has_config": os.path.exists(paths.config_path(series))}


def _config_summary(config):
    """配置摘要,供面板展示(不回传整份配置,太大)"""
    return {"mount": sorted(config.get("mount", {})),
            "load": sorted(config.get("load", {})),
            "motor": list(config.get("motor", {})),
            "cylinder_part": config.get("cylinder_part"),
            "base_parts": len(config.get("base_parts", [])),
            "controlled_count": config.get("controlled_count", 0)}


@bp.route("/part-export")
def index():
    return send_file(common.PART_EXPORT_PANEL_HTML)


@bp.route("/api/series")
def api_series():
    """扫描图库,返回每个系列的装配体候选与导出状态"""
    if not os.path.isdir(paths.LIB_ROOT):
        return jsonify({"ok": False, "error": f"图库不存在: {paths.LIB_ROOT}"}), 500
    items = []
    for name in sorted(os.listdir(paths.LIB_ROOT)):
        if not os.path.isdir(os.path.join(paths.LIB_ROOT, name)):
            continue
        items.append({
            "series": name,
            "assemblies": [{"path": p, "name": os.path.basename(p)}
                           for p in pe.list_assemblies(name)],
            "status": _series_status(name),
        })
    return jsonify({"ok": True, "lib_root": paths.LIB_ROOT, "series": items})


@bp.route("/api/preview")
def api_preview():
    """打开装配体列出组件,用于导出前检查零件路径能否在本机解析"""
    series = request.args.get("series", "")
    if not series:
        return jsonify({"ok": False, "error": "缺少 series"}), 400
    try:
        info = pe.preview_components(series, request.args.get("assembly"))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    comps = [{
        "name": c["name"],
        "file": os.path.basename(c["path"]) if c["path"] else "",
        "resolved": bool(c["path"]) and os.path.exists(c["path"]),
        "suppressed": c["suppressed"],
        "has_matrix": c["transform_matrix"] is not None,
    } for c in info["components"]]
    return jsonify({"ok": True, "assembly": info["assembly"], "components": comps})


@bp.route("/api/config", methods=["POST"])
def api_config():
    """为系列生成 data/configs/<系列>.json(装配表 → 选型配置)"""
    body = request.get_json(silent=True) or {}
    series = body.get("series", "")
    if not series:
        return jsonify({"ok": False, "error": "缺少 series"}), 400
    try:
        config = bc.build_series_config(series)
        out_path = bc.write_series_config(config)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "path": out_path, "config": _config_summary(config)})


@bp.route("/api/export", methods=["POST"])
def api_export():
    global _task
    body = request.get_json(silent=True) or {}
    series = body.get("series", "")
    if not series:
        return jsonify({"ok": False, "error": "缺少 series"}), 400
    with _task_lock:
        if _task.get("running"):
            return jsonify({"ok": False, "error": "已有导出任务在运行"}), 409
        _cancel_event.clear()
        _task = _reset_task(series)
        threading.Thread(
            target=_run_export,
            args=(series, body.get("assembly"), bool(body.get("overwrite"))),
            daemon=True,
        ).start()
    return jsonify({"ok": True})


@bp.route("/api/export/status")
def api_status():
    return jsonify({"ok": True, "task": _task})


@bp.route("/api/export/cancel", methods=["POST"])
def api_cancel():
    _cancel_event.set()
    return jsonify({"ok": True})
