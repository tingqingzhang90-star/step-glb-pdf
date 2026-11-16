# -*- coding: utf-8 -*-
"""模板存取与模板出图的共享辅助

被 web/blueprints/template.py 调用。集中放置纯逻辑(身份解析、模板解析/
落盘/读取、跨系列拒绝、结果转前端结构、批量出图),避免 template 蓝图文件过大。
"""
import json
import os

from flask import jsonify, request

from core.rebuild_assembly import normalize_model_code
from web import common
from web import task_pool

TEMPLATES_DIR = common.TEMPLATES_DIR
# 人工指定模板表:与模板目录同级另存,避免被模板扫描当成模板文件
DEFAULTS_FILENAME = "identity_defaults.json"


def template_identity(model_id):
    """模板身份 = 型号前三段(系列-连接-安装负载),后两段为系列内变量。

    品牌前缀 YRJ 不影响系列身份,按去前缀写法归一(与 drawing.frontend_template
    保持一致),如 YRJ250-E-H3K2 == 250-E-H3K2,避免带前缀型号匹配不到无前缀模板。
    """
    return "-".join(normalize_model_code(model_id).split("-")[:3])


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


def load_template_index():
    """扫一遍模板目录,返回全部模板摘要(带正文,重绑可直接用)

    模板文件带固化视图几何、单份可达 MB 级,所以一次扫完在内存里筛选,
    好过每个身份各扫一遍。返回列表元素:{template_id, identity,
    view_count, annotation_count, doc}。
    """
    if not os.path.isdir(TEMPLATES_DIR):
        return []
    items = []
    for name in sorted(os.listdir(TEMPLATES_DIR)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(TEMPLATES_DIR, name), "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        items.append({
            "template_id": doc.get("model_id") or name[:-5],
            "identity": doc.get("template_identity") or template_identity(
                doc.get("model_id", "")),
            "view_count": len(doc.get("views", [])),
            "annotation_count": len(doc.get("annotations", [])),
            "doc": doc,
        })
    return items


def _defaults_path():
    return os.path.join(os.path.dirname(TEMPLATES_DIR), DEFAULTS_FILENAME)


def load_template_defaults():
    """读取「身份 → 出图采用模板」的人工指定表,缺失或损坏按未指定处理"""
    try:
        with open(_defaults_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def set_template_default(identity, template_id):
    """指定某身份出图统一采用的模板;template_id 传 None 表示恢复自动挑选"""
    defaults = load_template_defaults()
    if template_id:
        defaults[identity] = template_id
    else:
        defaults.pop(identity, None)
    path = _defaults_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(defaults, f, ensure_ascii=False, indent=2, sort_keys=True)
    return defaults


def find_template_by_identity(identity, index=None):
    """查找指定系列身份(型号前三段)出图要用的模板

    优先用看板上人工指定的那一份;没指定时挑标注最多的一个(视图/标注更全,
    重绑成功率更高)。指定的模板文件已不存在时退回自动挑选。
    index 传 load_template_index() 结果可避免批量盘点时重复扫目录。
    返回 (template_id, doc);无匹配返回 (None, None)。
    """
    if not identity:
        return None, None
    items = load_template_index() if index is None else index
    chosen = load_template_defaults().get(identity)
    if chosen:
        for item in items:
            if item["template_id"] == chosen:
                return item["template_id"], item["doc"]
    best = None  # (score, template_id, doc)
    for item in items:
        if item["identity"] != identity:
            continue
        score = item["annotation_count"] * 100 + item["view_count"]
        if best is None or score > best[0]:
            best = (score, item["template_id"], item["doc"])
    return (best[1], best[2]) if best else (None, None)


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
