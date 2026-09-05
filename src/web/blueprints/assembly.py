# -*- coding: utf-8 -*-
"""装配体生成面板 + 构建任务 + 文件下载 + 3D 查看器

挂载到 /(面板)、/viewer、/static/o3dv、/download 与 /api/options、
/api/build、/api/task、/api/tasks、/api/files、/api/build-info。
OCC 计算全部走 web.task_pool 子进程,多用户并行不互相阻塞。
"""
import glob
import json
import os

from flask import (Blueprint, jsonify, request, send_file,
                   send_from_directory)

from web import common
from web import task_pool
from core import rebuild_assembly as rb

pool = task_pool.get_pool()
bp = Blueprint("assembly", __name__)


@bp.route("/")
def index():
    return send_file(common.ASSEMBLY_PANEL_HTML)


@bp.route("/viewer")
def viewer():
    return send_file(common.VIEWER_HTML)


@bp.route("/api/options")
def api_options():
    """装配面板与 SW 对比面板共用的选型选项端点

    合并前分别在 5001 与 5002 两个服务,合并后统一返回双方所需字段:
    装配面板读 series / motor_codes,SW 对比面板读 options。
    """
    series_list = []
    options = []
    for p in sorted(glob.glob(os.path.join(common.CONFIG_DIR, "*.json"))):
        name = os.path.splitext(os.path.basename(p))[0]
        try:
            with open(p, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            continue
        series_list.append({
            "name": name,
            "mount": sorted(cfg.get("mount", {}).keys()),
            "load": sorted(cfg.get("load", {}).keys()),
            "motor": list(cfg.get("motor", {}).keys()),
            "strokes": sorted(cfg.get("cylinder", {}).get("table", {}).keys(),
                              key=lambda s: int(s.replace("L", "")) if s.replace("L", "").isdigit() else 0),
        })
        options.append({
            "series": name,
            "mounts": list(cfg.get("mount", {}).keys()),
            "loads": list(cfg.get("load", {}).keys()),
            "motors": list(cfg.get("motor", {}).keys()),
            "strokes": list(cfg.get("cylinder", {}).get("table", {}).keys()),
        })
    motor_codes = [{"code": k, "name": v} for k, v in rb.MOTOR_CODES.items()]
    return jsonify({"series": series_list, "motor_codes": motor_codes, "options": options})


def _build_result_payload(result):
    """构建结果里的绝对路径转相对(便于前端下载)"""
    result = dict(result or {})

    def rel(p):
        return os.path.relpath(p, common.OUT_DIR).replace("\\", "/") if p else None
    result["step_file"] = rel(result.get("step_path"))
    result["glb_file"] = rel(result.get("glb_path"))
    result["cylinder_file"] = rel(result.get("cylinder_path"))
    return result


@bp.route("/api/build", methods=["POST"])
def api_build():
    """提交装配构建任务(多用户并行,异步)"""
    data = request.get_json(force=True) or {}
    model_code = (data.get("model_code") or "").strip()
    if not model_code:
        return jsonify({"ok": False, "error": "model_code 不能为空"}), 400
    motor = (data.get("motor") or "").strip() or None
    series = (data.get("series") or "").strip() or None
    payload = {"model_code": model_code, "motor": motor, "series": series}

    # 同型号并发构建会写同一个 output 目录,按型号去重
    task_id, dedup = pool.submit("build", model_code, payload)
    if not data.get("wait"):
        return jsonify({"ok": True, "task_id": task_id, "dedup": dedup}), 202
    try:
        result = pool.wait(task_id, timeout=float(data.get("timeout") or 900))
    except task_pool.TaskError as e:
        return jsonify({"ok": False, "error": str(e),
                        "traceback": e.traceback_text,
                        "task_id": task_id}), 500
    except TimeoutError as e:
        return jsonify({"ok": False, "error": str(e), "task_id": task_id}), 504
    return jsonify({"ok": True, "task_id": task_id,
                    "result": _build_result_payload(result)})


@bp.route("/api/task/<task_id>")
def api_task(task_id):
    st = pool.status(task_id)
    if st is None:
        return jsonify({"ok": False, "error": "任务不存在或已清理: %s" % task_id}), 404
    if st["status"] == "done" and st.get("kind") == "build":
        st["result"] = _build_result_payload(st.get("result"))
    return jsonify({"ok": True, "task": st})


@bp.route("/api/tasks")
def api_tasks():
    return jsonify({"ok": True, "stats": pool.stats(),
                    "tasks": pool.list_tasks()})


@bp.route("/api/files")
def api_files():
    groups = []
    if os.path.isdir(common.OUT_DIR):
        for dname in sorted(os.listdir(common.OUT_DIR)):
            dpath = os.path.join(common.OUT_DIR, dname)
            if not os.path.isdir(dpath):
                continue
            files = []
            has_info = False
            for fname in os.listdir(dpath):
                fp = os.path.join(dpath, fname)
                if os.path.isfile(fp):
                    st = os.stat(fp)
                    files.append({
                        "name": fname,
                        "rel": f"{dname}/{fname}",
                        "size": st.st_size,
                        "mtime": int(st.st_mtime),
                    })
                    if fname == "build_info.json":
                        has_info = True
            files.sort(key=lambda f: f["mtime"], reverse=True)
            if files:
                groups.append({"model": dname, "files": files, "has_info": has_info})
    groups.sort(key=lambda g: max(f["mtime"] for f in g["files"]), reverse=True)
    return jsonify({"groups": groups, "total": sum(len(g["files"]) for g in groups)})


@bp.route("/api/build-info/<model_code>")
def api_build_info(model_code):
    info_path = os.path.join(common.OUT_DIR, model_code, "build_info.json")
    if not os.path.isfile(info_path):
        return jsonify({"ok": False, "error": "未找到构建记录"}), 404
    try:
        with open(info_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"ok": True, "result": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/download/<path:filename>")
def download(filename):
    return send_from_directory(common.OUT_DIR, filename, as_attachment=True)
