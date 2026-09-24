# -*- coding: utf-8 -*-
"""前端实例模板装载与基准边线还原

模板 refs 只记 {viewId, idx, type}(边线数组下标),复用前必须按基准
型号重新生成同一套调色板视图,把下标还原成带 mm 真值的边线对象。
调色板生成管线与前端 /api/drawing-view-palette 完全同源,保证下标一致。
"""
import hashlib
import json
import os

from core import drawing_engine
from core.rebuild_assembly import normalize_model_code, model_code_candidates


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
    """模板身份 = 型号前三段,同身份共用一份模板(忽略 YRJ 品牌前缀)"""
    return "-".join(normalize_model_code(model_id).split("-")[:3])


def find_model_shape(out_dir, model_code):
    """模型形状文件(优先 STEP,回退 BRep 缓存),兼容带/不带 YRJ 前缀的目录名"""
    for code in model_code_candidates(model_code):
        model_dir = os.path.join(out_dir, code)
        for name in ("assembly.step", "assembly.brep"):
            p = os.path.join(model_dir, name)
            if os.path.isfile(p):
                return p
    raise FileNotFoundError(f"未找到模型文件: {model_code}/assembly.step|brep")


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


def resolve_base_views(template_doc, out_dir, view_names=None, parallel=True):
    """按 model_id 重新生成调色板,还原每个放置视图的边线语境

    Args:
        view_names: 只投影这些视图,None 表示按模板视图集自动推导。
            出图时只需模板用到的那几个,不必生成全部 9+3 个。
        parallel: 视图间是否用进程池并行投影。嵌套进程池的 spawn 开销
            (~2s,各 worker 导入 pythonOCC)远小于 3 视图串行投影耗时
            (实测 13s → 6.6s),默认开启;单视图自动退化为串行。

    Returns:
        dict: view_id -> {"source_view", "edges", "hidden_edges", "bbox"}
    """
    if view_names is None:
        view_names = template_view_names(template_doc)
    shape_path = find_model_shape(out_dir, template_doc["model_id"])
    palette = drawing_engine.generate_all_standard_views(
        shape_path, view_names=view_names, parallel=parallel)
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


# 基准缓存键版本:投影管线输出行为变更时 +1,旧缓存全部失效
_BASE_CACHE_VERSION = "v1"


def base_cache_path(template_doc, out_dir):
    """基准数据的磁盘缓存路径

    键 = 模板全文哈希 + 基准 shape 文件指纹(mtime/size)+ 管线版本,
    模板编辑、基准模型重建、投影代码变更任一发生即自动失效。
    """
    shape_path = find_model_shape(out_dir, template_doc["model_id"])
    stat = os.stat(shape_path)
    payload = json.dumps(template_doc, sort_keys=True, ensure_ascii=False)
    tpl_digest = hashlib.md5(payload.encode("utf-8")).hexdigest()
    key = "%s:%s:%d:%d" % (_BASE_CACHE_VERSION, tpl_digest,
                           stat.st_mtime_ns, stat.st_size)
    name = hashlib.md5(key.encode("utf-8")).hexdigest()
    return os.path.join(out_dir, "_base_cache", name + ".json")


def load_base_cache(path):
    """读基准缓存;字段缺失(旧版/损坏)按未命中处理"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and all(
            k in data for k in ("view_names", "views", "refs", "profile")):
        return data
    return None


def save_base_cache(path, base):
    """写基准缓存;临时文件 + 原子替换防并发写坏,失败不影响出图主流程"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(base, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def _resolve_ref(ref, base_views):
    """单个引用 → {"ref", "view", "seg"} 或 {"ref", "error"}"""
    entry = {"ref": ref}
    view = base_views.get(ref.get("viewId"))
    if view is None:
        entry["error"] = f"视图不存在: {ref.get('viewId')}"
        return entry
    segs = (view["hidden_edges"] if ref.get("type") == "hiddenEdges"
            else view["edges"])
    idx = ref.get("idx")
    if not isinstance(idx, int) or not (0 <= idx < len(segs)):
        entry["error"] = f"基准边线下标越界: idx={idx}"
        return entry
    entry["view"] = view
    entry["seg"] = segs[idx]
    return entry


def resolve_base_refs(template_doc, base_views):
    """还原每条标注引用的基准边线(下标 → 边线对象)

    Returns:
        list: 每项 {"dim", "refs": [...], "group_refs": [...]}
        group_refs 是孔组引用(分度圆直径标注的 groupRefs),与 refs 同构
    """
    resolved = []
    for ann in template_doc.get("annotations", []):
        item = {"dim": ann, "refs": [], "group_refs": []}
        for ref in ann.get("refs", []):
            item["refs"].append(_resolve_ref(ref, base_views))
        for ref in ann.get("groupRefs") or []:
            item["group_refs"].append(_resolve_ref(ref, base_views))
        resolved.append(item)
    return resolved
