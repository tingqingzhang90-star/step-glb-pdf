# -*- coding: utf-8 -*-
"""装配体生成面板 + 构建任务 + 文件下载 + 3D 查看器

挂载到 /(面板)、/viewer、/static/o3dv、/download 与 /api/options、
/api/build、/api/task、/api/tasks、/api/files、/api/build-info、/api/system-info。
OCC 计算全部走 web.task_pool 子进程,多用户并行不互相阻塞。
"""
import glob
import json
import os
import sys

from flask import (Blueprint, jsonify, request, send_file,
                   send_from_directory, redirect)

from web import common
from web import task_pool
from core import rebuild_assembly as rb
from core import build_config
from core import storage

pool = task_pool.get_pool()
bp = Blueprint("assembly", __name__)


@bp.route("/")
def index():
    return send_file(common.ASSEMBLY_PANEL_HTML)


@bp.route("/viewer")
def viewer():
    return send_file(common.VIEWER_HTML)


def _code_name_list(table):
    """配置里的 {代号: {name, on, off}} → [{code, name}]

    name 为表首列原文(如 "H2(底部法兰）"),UI 展示用;code 用于型号拼接。
    老配置无 name 时回退代号。
    """
    out = []
    for code, v in (table or {}).items():
        name = v.get("name") if isinstance(v, dict) else None
        out.append({"code": code, "name": name or code})
    return out


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
            "mounts": _code_name_list(cfg.get("mount", {})),
            "loads": _code_name_list(cfg.get("load", {})),
            "motors": list(cfg.get("motor", {}).keys()),
            "strokes": list(cfg.get("cylinder", {}).get("table", {}).keys()),
        })
    motor_codes = [{"code": k, "name": v} for k, v in rb.MOTOR_CODES.items()]
    return jsonify({"series": series_list, "motor_codes": motor_codes, "options": options})


@bp.route("/api/series/motor-table")
def api_series_motor_table():
    """某系列电机表(图库项目/<系列>/电机.xlsx)→ 含功率(kW)与额定扭矩(Nm)

    选型界面电机功率下拉与扭矩不再在前端硬编码,统一由本接口从 Excel 下发,
    保证单一数据源。扭矩列缺失时 torque 为 null,前端回退公式估算。
    """
    series = (request.args.get("series") or "").strip()
    if not series:
        return jsonify({"ok": False, "error": "缺少 series 参数"}), 400
    table = build_config.motor_table_for_series(series)
    motors = [{
        "code": code,
        "name": m.get("name"),
        "reducer": m.get("reducer"),
        "power_kw": m.get("power_kw"),
        "torque": m.get("torque"),
        "brake": m.get("brake"),
    } for code, m in table.items()]
    return jsonify({"ok": True, "series": series, "motors": motors})


@bp.route("/api/series/screw-table")
def api_series_screw_table():
    """系列(表「名称」列)→ 丝杆选项(丝杆型号/导程/缸径),读 data/screw_table.xlsx

    选型界面据此下发导程下拉,并在选定导程后回填丝杆型号与缸径到工程图规格表。
    系列名兼容无 YRJ/EDA 前缀(按数字段匹配)。
    """
    series = (request.args.get("series") or "").strip()
    if not series:
        return jsonify({"ok": False, "error": "缺少 series 参数"}), 400
    screws = build_config.screw_table_for_series(series)
    return jsonify({"ok": True, "series": series, "screws": screws})


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


def _round_gb(v):
    """字节 → GiB,保留 1 位;None 原样返回"""
    return round(v / (1024 ** 3), 1) if v is not None else None


def _system_memory_gb():
    """系统内存(GB):total/available/used/percent。多平台:
    优先 psutil;否则 Windows 用 ctypes GlobalMemoryStatusEx;
    Linux 回退 /proc/meminfo;都不可用则字段为 None。"""
    total = available = used = percent = None
    try:
        import psutil  # 可选依赖,有则用最准
        vm = psutil.virtual_memory()
        total, available, used = vm.total, vm.available, vm.used
        percent = vm.percent
    except Exception:
        if sys.platform.startswith("win"):
            # Windows:ctypes 调 kernel32.GlobalMemoryStatusEx(无需装任何依赖)
            try:
                import ctypes
                class _MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]
                st = _MEMORYSTATUSEX()
                st.dwLength = ctypes.sizeof(st)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                    total = st.ullTotalPhys
                    available = st.ullAvailPhys
                    used = total - available
                    percent = st.dwMemoryLoad
            except Exception:
                pass
        else:
            # 回退:Linux /proc/meminfo(MemAvailable 需较新内核)
            try:
                info = {}
                with open("/proc/meminfo") as fh:
                    for line in fh:
                        k, _, v = line.partition(":")
                        if v:
                            info[k.strip()] = int(v.strip().split()[0]) * 1024
                if "MemTotal" in info:
                    total = info["MemTotal"]
                    available = info.get("MemAvailable",
                                        info.get("MemFree", 0)
                                        + info.get("Buffers", 0)
                                        + info.get("Cached", 0))
                    used = total - info.get("MemFree", 0) \
                        - info.get("Buffers", 0) - info.get("Cached", 0)
                    percent = (used / total * 100) if total else None
            except Exception:
                pass
    return {
        "total_gb": _round_gb(total),
        "available_gb": _round_gb(available),
        "used_gb": _round_gb(used),
        "percent": round(percent, 1) if percent is not None else None,
    }


@bp.route("/api/system-info")
def api_system_info():
    """进程池(OCC)运行环境:worker 数、BUILD_POOL_WORKERS、CPU 核数、系统内存,
    以及按部署经验(可用内存 ÷ 0.45GB/worker)估出的建议 worker 上限。
    前端顶栏实时展示,用于判断 BUILD_POOL_WORKERS 能开多大。"""
    workers = pool.max_workers
    env_workers = os.environ.get("BUILD_POOL_WORKERS", "").strip() or None
    cpu = os.cpu_count() or 1
    mem = _system_memory_gb()
    suggested = (int(mem["available_gb"] // 0.45)
                 if mem["available_gb"] is not None else None)
    return jsonify({
        "ok": True,
        "workers": workers,
        "env_workers": env_workers,
        "cpu_count": cpu,
        "memory": mem,
        "suggested_max_workers": suggested,
    })


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


@bp.route("/api/resources/<model_code>")
def api_resources(model_code):
    """查询某型号已生成的资源,供前端"同型号复用"命中判断(只读,不触发构建)

    同型号(型号前缀一致)已有产物时前端可直接取路径,跳过 OCC 构建。
    cached 要求 3D(glb+step)与工程图源都已在盘上。
    """
    model_dir = os.path.join(common.OUT_DIR, model_code)

    # 型号可能带 YRJ 品牌前缀,后端目录可能带也可能不带,候选写法逐一尝试,
    # 命中真实目录后用其名拼资源路径(否则按带前缀目录拼的下载地址会 404)
    real_code = model_code
    for cand in rb.model_code_candidates(model_code):
        if os.path.isdir(os.path.join(common.OUT_DIR, cand)):
            real_code = cand
            model_dir = os.path.join(common.OUT_DIR, cand)
            break

    def rel(name):
        return f"{real_code}/{name}" if os.path.isfile(os.path.join(model_dir, name)) else None

    glb_file = rel("assembly.glb")
    step_file = rel("assembly.step")
    cylinder_file = rel("cylinder.step")
    source_file = rel("drawing_source.json")
    pdf_file = rel("drawing.pdf")
    model_available = bool(glb_file and step_file)
    return jsonify({
        "ok": True,
        "model_code": model_code,
        "cached": model_available and bool(source_file),
        "model": {"available": model_available, "glb_file": glb_file, "step_file": step_file},
        "cylinder": {"available": bool(cylinder_file), "file": cylinder_file},
        "drawing_source": {"available": bool(source_file), "file": source_file},
        "drawing": {"available": bool(pdf_file), "pdf_url": pdf_file},
    })


@bp.route("/download/<path:filename>")
def download(filename):
    """下载 OUT_DIR 下的产物文件。

    品牌前缀容错:型号目录可能带也可能不带 YRJ 前缀(前端可能用带前缀型号
    直接拼下载地址),首段按候选写法逐一尝试;命中即返回真实文件,否则回退原路径。
    """
    # 结果若已镜像到对象存储,直接 302 到外链(前端无需改动)
    u = storage.url((filename or "").replace("\\", "/"))
    if u:
        return redirect(u)
    norm = (filename or "").replace("\\", "/")
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    out_root = os.path.abspath(common.OUT_DIR)
    if len(parts) >= 2 and parts[0] not in ("..",):
        for cand in rb.model_code_candidates(parts[0]):
            if not cand or cand == parts[0] or cand.startswith("."):
                continue
            alt = os.path.abspath(os.path.join(out_root, cand, *parts[1:]))
            if alt.startswith(out_root + os.sep) and os.path.isfile(alt):
                return send_file(alt, as_attachment=True)
    return send_from_directory(common.OUT_DIR, filename, as_attachment=True)
