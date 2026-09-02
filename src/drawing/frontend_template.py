# -*- coding: utf-8 -*-
"""前端实例模板装载与基准边线还原

模板 refs 只记 {viewId, idx, type}(边线数组下标),复用前必须按基准
型号重新生成同一套调色板视图,把下标还原成带 mm 真值的边线对象。
调色板生成管线与前端 /api/drawing-view-palette 完全同源,保证下标一致。
"""
import json
import os

from core import drawing_engine


def load_frontend_template(path):
    """读取前端保存的实例模板 JSON"""
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    if not doc.get("model_id"):
        raise ValueError(f"模板缺少 model_id: {path}")
    if not doc.get("views"):
        raise ValueError(f"模板无视图: {path}")
    return doc


def template_identity(model_id):
    """模板身份 = 型号前三段,同身份共用一份模板"""
    return "-".join(str(model_id).split("-")[:3])


def find_model_shape(out_dir, model_code):
    """模型形状文件(优先 STEP,回退 BRep 缓存)"""
    model_dir = os.path.join(out_dir, model_code)
    for name in ("assembly.step", "assembly.brep"):
        p = os.path.join(model_dir, name)
        if os.path.isfile(p):
            return p
    raise FileNotFoundError(f"未找到模型文件: {model_dir}/assembly.step|brep")


def template_view_names(template_doc):
    """模板实际用到的标准视图名(去重保序)

    基准型号与目标型号必须共用这个集合:视图子集会决定 uniform_scale,
    两边用同一子集才能保证缩放基准一致(否则标注重绑会整体错位)。
    """
    names = []
    for v in template_doc.get("views", []):
        src = v.get("source_view")
        if src and src not in names:
            names.append(src)
    if not names:
        raise ValueError("模板没有任何视图,无法出图")
    return names


def resolve_base_views(template_doc, out_dir, view_names=None):
    """按 model_id 重新生成调色板,还原每个放置视图的边线语境

    Args:
        view_names: 只投影这些视图,None 表示按模板视图集自动推导。
            出图时只需模板用到的那几个,不必生成全部 9+3 个。

    Returns:
        dict: view_id -> {"source_view", "edges", "hidden_edges", "bbox"}
    """
    if view_names is None:
        view_names = template_view_names(template_doc)
    shape_path = find_model_shape(out_dir, template_doc["model_id"])
    palette = drawing_engine.generate_all_standard_views(
        shape_path, view_names=view_names)
    views = {}
    for v in template_doc["views"]:
        src = v.get("source_view")
        pv = palette.get("views", {}).get(src)
        if not pv:
            raise ValueError(f"基准型号不支持视图: {src}")
        views[v["id"]] = {
            "source_view": src,
            "edges": pv.get("edges", []),
            "hidden_edges": pv.get("hidden_edges", []),
            "bbox": pv.get("bbox", {}),
        }
    return views


def resolve_base_refs(template_doc, base_views):
    """还原每条标注引用的基准边线(下标 → 边线对象)

    Returns:
        list: 每项 {"dim", "refs": [{"ref", "view", "seg"}或{"ref", "error"}]}
    """
    resolved = []
    for ann in template_doc.get("annotations", []):
        item = {"dim": ann, "refs": []}
        for ref in ann.get("refs", []):
            entry = {"ref": ref}
            view = base_views.get(ref.get("viewId"))
            if view is None:
                entry["error"] = f"视图不存在: {ref.get('viewId')}"
            else:
                segs = (view["hidden_edges"] if ref.get("type") == "hiddenEdges"
                        else view["edges"])
                idx = ref.get("idx")
                if not isinstance(idx, int) or not (0 <= idx < len(segs)):
                    entry["error"] = f"基准边线下标越界: idx={idx}"
                else:
                    entry["view"] = view
                    entry["seg"] = segs[idx]
            item["refs"].append(entry)
        resolved.append(item)
    return resolved
