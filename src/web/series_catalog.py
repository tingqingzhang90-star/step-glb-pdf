# -*- coding: utf-8 -*-
"""系列模板覆盖度盘点

按"配置(系列×连接) × 安装方式 × 负载方式"枚举模板身份,逐个判定:
- 基准模型是否已生成(assembly.step 是否存在)
- 是否已保存人工标注模板(find_template_by_identity)

只自动生成基准模型(L100 + 首个电机),人工标注不在后端做。
"""
import glob
import json
import os

from web import common
from web.blueprints.template_helpers import (
    find_template_by_identity, load_template_defaults, load_template_index)


def _series_type_from_name(name):
    return "F" if "折返" in name else "E"


def _series_from_name(name):
    return name.replace("直连", "").replace("折返", "")


def load_configs():
    """读取配置目录全部选型配置,返回 [(名称, 配置字典)]"""
    configs = []
    for path in sorted(glob.glob(os.path.join(common.CONFIG_DIR, "*.json"))):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        configs.append((name, cfg))
    return configs


def enumerate_template_identities():
    """枚举全部模板身份,返回 identity 字典列表

    一个模板身份 = 系列-连接-安装负载(如 250-E-H2K1),每个身份对应一个
    基准模型(行程取 L100、电机取配置首个),供人工标注出模板。
    """
    identities = []
    for name, cfg in load_configs():
        series = _series_from_name(name)
        stype = _series_type_from_name(name)
        mounts = list(cfg.get("mount", {}).keys())
        loads = list(cfg.get("load", {}).keys())
        motors = list(cfg.get("motor", {}).keys())
        if not (mounts and loads and motors):
            continue
        base_motor = motors[0]
        for m in mounts:
            for l in loads:
                identity = f"{series}-{stype}-{m}{l}"
                base_model = f"{identity}-L100-{base_motor}"
                identities.append({
                    "identity": identity,
                    "series": series,
                    "type": stype,
                    "mount": m,
                    "load": l,
                    "base_motor": base_motor,
                    "base_model": base_model,
                })
    return identities


def _template_state(identity, index, defaults):
    """单个身份的模板状态:采用的模板、是否人工指定、可选的候选模板

    候选 = 该身份下已保存的全部模板,供看板下拉人工指定;指定后 saved/
    pinned 都指向那一份,不再走"标注最多"的自动挑选。
    """
    candidates = sorted(
        (i for i in index if i["identity"] == identity),
        key=lambda i: (-i["annotation_count"], -i["view_count"], i["template_id"]))
    chosen = defaults.get(identity)
    tpl_id, doc = find_template_by_identity(identity, index=index)
    if doc:
        state = {
            "saved": True,
            "template_id": tpl_id,
            "view_count": len(doc.get("views", [])),
            "annotation_count": len(doc.get("annotations", [])),
            "pinned": bool(chosen and tpl_id == chosen),
        }
    else:
        state = {"saved": False, "template_id": None,
                 "view_count": 0, "annotation_count": 0, "pinned": False}
    state["candidates"] = [
        {"template_id": c["template_id"], "view_count": c["view_count"],
         "annotation_count": c["annotation_count"]} for c in candidates]
    return state


def coverage():
    """逐个身份的覆盖度:模型是否生成、模板是否已保存、可指定哪些模板"""
    index = load_template_index()
    defaults = load_template_defaults()
    rows = []
    for item in enumerate_template_identities():
        base = item["base_model"]
        step_path = os.path.join(common.OUT_DIR, base, "assembly.step")
        glb_path = os.path.join(common.OUT_DIR, base, "assembly.glb")
        model_built = os.path.isfile(step_path)
        # 3D 查看器优先用 GLB(渲染优化),无则退回 STEP;两者都没有(model 未生成)则为 None
        if model_built:
            model_url = ("/download/%s/assembly.glb" % base
                         if os.path.isfile(glb_path)
                         else "/download/%s/assembly.step" % base)
        else:
            model_url = None
        rows.append({**item, "model_built": model_built, "model_url": model_url,
                     "template": _template_state(item["identity"], index, defaults)})
    return rows


def coverage_summary(rows):
    total = len(rows)
    no_model = sum(1 for r in rows if not r["model_built"])
    no_template = sum(1 for r in rows
                      if r["model_built"] and not r["template"]["saved"])
    ready = sum(1 for r in rows
                if r["model_built"] and r["template"]["saved"])
    return {"total": total, "no_model": no_model,
            "no_template": no_template, "ready": ready}
