# -*- coding: utf-8 -*-
"""服务端轻量出图端点

POST /api/render-drawing
  入参: { "model_id": "250-E-H2K1-L100-5.5KW电机", "spec": { ... } }
  行为:
    1. 定位 output/<model_id>/drawing_source.json(同系列复用,不触发几何 build)。
    2. 把 spec 回填进 title_block.fields[].value 与 技术参数表 cells[].text。
    3. 渲染为 PDF,返回 { "pdf_url", "elapsed", "autogen_elapsed",
       "render_elapsed" }:elapsed 为接口总耗时(秒),autogen_elapsed 为模板
       自动重绑耗时(快路径命中已有源文件时为 null),render_elapsed 为 PDF 渲染耗时。
  约定:仅当该 model_id 已有 drawing_source.json 时出图;否则返回明确错误,
        由运营在 cad-viewer-app 预生成或走后续重绑引擎,不在本阶段自动 build。
"""
import json
import os
import time

from flask import Blueprint, jsonify, request

from core import rebuild_assembly as rb
from web import common
from web.drawing_spec_map import find_drawing_source, apply_spec
from web.blueprints import template_helpers as th
from drawing.drawing_source_render import render_drawing_source_pdf

bp = Blueprint("render", __name__)

_OUT_NAME = "drawing.pdf"


def _try_autogen_drawing_source(model_id):
    """drawing_source.json 缺失时,用同系列已保存的前端模板自动生成。

    返回 (源文件路径, 错误说明)。仅在以下情况才会真正触发 OCC 重绑:
      1) 该系列存在已保存的前端模板;
      2) 本型号已生成 3D 模型(assembly.step/brep 存在)。
    否则返回 (None, 错误说明/None),由调用方回退到原来的 404。
    """
    try:
        identity = th.template_identity(model_id)
        template_id, template_doc = th.find_template_by_identity(identity)
    except Exception:
        return None, None
    if not template_doc:
        return None, None

    # 型号可能带 YRJ 品牌前缀,后端目录可能带也可能不带,候选写法逐一尝试
    model_dir = None
    for cand in rb.model_code_candidates(model_id):
        d = os.path.join(common.OUT_DIR, cand)
        if os.path.isdir(d):
            model_dir = d
            break
    if not model_dir:
        return None, None
    has_shape = (os.path.isfile(os.path.join(model_dir, "assembly.step")) or
                 os.path.isfile(os.path.join(model_dir, "assembly.brep")))
    if not has_shape:
        return None, (
            f"未找到型号 {model_id} 的 drawing_source.json,"
            f"且本型号尚未生成 3D 模型(缺少 assembly.step/brep),无法用模板重绑生成")

    try:
        results, err = th.generate_frontend_batch(
            template_id, template_doc, [model_id])
    except Exception as e:
        return None, f"用模板自动生成失败: {e}"
    if err is not None:
        # err 为 (jsonify, code) 元组;给出明确文案,不再手动解析 Response
        return None, "用模板自动生成失败(基准视图生成或出图异常)"
    if not results or not results[0].get("ok"):
        return None, f"用模板自动生成失败: {results[0].get('error') if results else '无结果'}"
    return find_drawing_source(model_id), None


@bp.route("/api/render-drawing", methods=["POST"])
def api_render_drawing():
    t_start = time.time()
    data = request.get_json(force=True) or {}
    model_id = (data.get("model_id") or "").strip()
    spec = data.get("spec") or {}
    if not model_id:
        return jsonify({"ok": False, "error": "model_id 不能为空"}), 400

    src_path = find_drawing_source(model_id)
    autogen_elapsed = None
    if not src_path:
        # 自闭环:同系列已有模板时,自动重绑生成 drawing_source.json 再出图,
        # 不必每次手动预跑模板流程。
        t_auto = time.time()
        src_path, gen_err = _try_autogen_drawing_source(model_id)
        autogen_elapsed = round(time.time() - t_auto, 3)
    if not src_path:
        reason = gen_err or (
            f"未找到型号 {model_id} 的 drawing_source.json,"
            "且未找到同系列已保存的前端模板,请先在 cad-viewer-app 预生成模板")
        return jsonify({"ok": False, "error": reason}), 404

    try:
        with open(src_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return jsonify({"ok": False, "error": f"读取源文件失败: {e}"}), 500

    # 原地回填规格(只改可编辑内容,不动几何)
    apply_spec(doc, model_id, spec)

    model_dir = os.path.dirname(src_path)
    out_pdf = os.path.join(model_dir, _OUT_NAME)
    t_render = time.time()
    try:
        out_abs = render_drawing_source_pdf(doc, out_pdf)
    except Exception as e:  # 渲染失败不污染已有源文件
        return jsonify({"ok": False, "error": f"渲染失败: {e}"}), 500
    render_elapsed = round(time.time() - t_render, 3)

    # pdf_url 为 OUT_DIR 下真实落盘的相对路径(可能按去品牌前缀目录存储),
    # 编码由前端 downloadUrl() 按段处理
    rel = os.path.relpath(out_abs, common.OUT_DIR).replace("\\", "/")
    return jsonify({
        "ok": True,
        "model_id": model_id,
        "pdf_url": rel,
        "pdf_path": rel,
        # 生成耗时(秒):elapsed 为接口总耗时;autogen_elapsed 为模板自动重绑
        # 耗时(仅首次/新系列有,快路径为 null),render_elapsed 为 PDF 渲染耗时。
        "elapsed": round(time.time() - t_start, 3),
        "autogen_elapsed": autogen_elapsed,
        "render_elapsed": render_elapsed,
    })
