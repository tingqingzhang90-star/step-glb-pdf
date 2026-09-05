# -*- coding: utf-8 -*-
"""模板存取与模板出图的共享辅助

被 web/blueprints/template.py 调用。集中放置纯逻辑(身份解析、模板解析/
落盘/读取、跨系列拒绝、结果转前端结构、批量出图),避免 template 蓝图文件过大。
"""
import json
import os

from flask import jsonify, request

from web import common
from web import task_pool

TEMPLATES_DIR = common.TEMPLATES_DIR


def template_identity(model_id):
    """模板身份 = 型号前三段(系列-连接-安装负载),后两段为系列内变量"""
    return "-".join(str(model_id).split("-")[:3])


def parse_uploaded_template():
    """解析上传的模板(multipart 的 file 字段,或 JSON 请求体)"""
    if request.files:
        f = request.files.get("file")
        if f is None:
            return None, (jsonify({"ok": False, "error": "缺少 file 字段"}), 400)
        try:
            doc = json.loads(f.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            return None, (jsonify({"ok": False, "error": f"模板不是合法 UTF-8 JSON: {e}"}), 400)
    else:
        doc = request.get_json(silent=True)
    if not isinstance(doc, dict):
        return None, (jsonify({"ok": False, "error": "模板内容必须是 JSON 对象"}), 400)
    model_id = doc.get("model_id")
    if not model_id or not isinstance(model_id, str):
        return None, (jsonify({"ok": False, "error": "模板缺少 model_id 字段"}), 400)
    if not doc.get("views"):
        return None, (jsonify({"ok": False, "error": "模板 views 为空"}), 400)
    return doc, None


def save_template_doc(model_id, doc):
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    with open(os.path.join(TEMPLATES_DIR, f"{model_id}.json"), "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False, indent=2)


def load_template_doc(template_id):
    tpl_path = os.path.join(TEMPLATES_DIR, f"{template_id}.json")
    if not os.path.isfile(tpl_path):
        return None, (jsonify({
            "ok": False,
            "error": f"模板不存在: {template_id}(请先上传或保存模板)"}), 404)
    try:
        with open(tpl_path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except (OSError, json.JSONDecodeError) as e:
        return None, (jsonify({"ok": False, "error": f"模板读取失败: {e}"}), 500)


def reject_cross_series(models, tmpl_identity):
    """不同系列几何差异过大,共用模板无意义,返回被拒型号列表"""
    rejected = [m for m in models if template_identity(m) != tmpl_identity]
    if not rejected:
        return None
    return (jsonify({
        "ok": False,
        "error": f"以下型号与模板系列({tmpl_identity})不同: {', '.join(rejected)}",
        "rejected": rejected}), 400)


def to_client_results(results):
    """出图结果转前端结构:PDF 绝对路径改相对项目根,供下载接口使用"""
    out = []
    for r in results:
        pdf_abs = r.get("pdf") or ""
        rel = os.path.relpath(pdf_abs, common.PROJECT_ROOT).replace("\\", "/") \
            if pdf_abs else None
        out.append({
            "model_code": r.get("model_code"),
            "ok": bool(r.get("ok")),
            "error": r.get("error"),
            "pdf": rel,
            "elapsed": r.get("elapsed"),
            "dims": r.get("dims", []),
            "unmatched": r.get("unmatched", []),
        })
    return out


def generate_frontend_batch(template_id, template_doc, models):
    """按型号并行出图,返回 (结果列表, 错误响应)

    拆两步:基准数据整批算一次(同模板去重),之后每个型号各提交一个任务并行跑。
    """
    try:
        base = task_pool.get_pool().run("template-base", "tpl-base:%s" % template_id, {
            "template_doc": template_doc, "out_dir": common.OUT_DIR})
    except task_pool.TaskError as e:
        return None, (jsonify({
            "ok": False, "error": f"基准视图生成失败: {e}",
            "traceback": e.traceback_text}), 500)
    except Exception as e:
        return None, (jsonify({"ok": False, "error": f"基准视图生成失败: {e}"}), 500)

    submitted = []
    for model_code in models:
        try:
            task_id, _ = task_pool.get_pool().submit(
                "template-one", "tpl:%s:%s" % (template_id, model_code),
                {"model_code": model_code, "template_doc": template_doc,
                 "base": base, "out_dir": common.OUT_DIR})
        except Exception as e:
            submitted.append((model_code, None, str(e)))
        else:
            submitted.append((model_code, task_id, None))

    results = []
    for model_code, task_id, submit_error in submitted:
        if task_id is None:
            results.append({"model_code": model_code, "ok": False,
                            "error": submit_error, "elapsed": 0})
            continue
        try:
            results.append(task_pool.get_pool().wait(task_id))
        except task_pool.TaskError as e:
            results.append({"model_code": model_code, "ok": False,
                            "error": str(e), "traceback": e.traceback_text,
                            "elapsed": 0})
    return results, None
