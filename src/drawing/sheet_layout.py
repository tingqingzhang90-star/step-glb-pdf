# -*- coding: utf-8 -*-
"""图纸布局求解 — 统一缩放 + 网格重排 + 长行程自动断裂

输入是图纸 mm 尺寸与各视图 contentBBox(画布 px),纯函数无 OCC 依赖。
把模板视图按原有 x/y 聚成行列网格,列宽/行高取组内最大内容尺寸,统一求
一个缩放系数使「内容 + 最小间距」落进图框可用区,再把网格居中排回去。

统一缩放低于最小可读比例时,对瓶颈方向的轴向长视图生成断裂:省略量按
「把比例拉回阈值所需」计算,至少取配置的最小省略长度。断裂只缩短显示,
边线数组与 meta.mm_coords 一字不动,标注 refs.idx 和数值真值因此不受影响。
"""
import os

from drawing import break_view
from drawing.view_axes import axial_projection

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENV_CACHE = None

# 键名与 .env 变量名一一对应,默认值同时是文档的基准值
_CFG_DEFAULTS = {
    "margin": ("DRAWING_SHEET_MARGIN", 20.0),
    "reserved_bottom": ("DRAWING_SHEET_TITLE_BLOCK_MM", 55.0),
    "min_gap": ("DRAWING_VIEW_MIN_GAP_MM", 12.0),
    "align_tol": ("DRAWING_VIEW_ALIGN_TOL_MM", 20.0),
    "min_readable_scale": ("DRAWING_MIN_READABLE_SCALE", 0.75),
    "max_scale": ("DRAWING_MAX_VIEW_SCALE", 2.0),
    "break_omit_mm": ("DRAWING_BREAK_OMIT_MM", 400.0),
    "break_wave_amp": ("DRAWING_BREAK_WAVE_AMP", 3.0),
    "break_wave_cycles": ("DRAWING_BREAK_WAVE_CYCLES", 3),
    "break_visual_gap": ("DRAWING_BREAK_VISUAL_GAP", 6.0),
}


def _env_values():
    """项目根 .env 兜底(os.environ 优先),与 drawing_engine 的读取惯例一致"""
    global _ENV_CACHE
    if _ENV_CACHE is None:
        values = {}
        try:
            with open(os.path.join(_ROOT, ".env"), "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        values[k.strip()] = v.strip().strip("'\"")
        except OSError:
            pass
        _ENV_CACHE = values
    return _ENV_CACHE


def load_cfg(overrides=None):
    """读取全部配置项;非法数值回退默认值,overrides 用于测试与图纸切换"""
    env = _env_values()
    cfg = {}
    for name, (key, default) in _CFG_DEFAULTS.items():
        raw = os.environ.get(key) or env.get(key)
        try:
            cfg[name] = float(raw) if raw is not None else default
        except ValueError:
            cfg[name] = default
    cfg["break_wave_cycles"] = max(1, int(cfg["break_wave_cycles"]))
    cfg["break_visual_gap"] = max(1.0, cfg["break_visual_gap"])
    cfg["min_readable_scale"] = max(0.01, cfg["min_readable_scale"])
    if overrides:
        cfg.update(overrides)
    return cfg


def _clusters(values, tol):
    """把一维坐标按相邻差 ≤ tol 聚类,返回按坐标升序的索引组"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    groups, current, prev = [], [], None
    for i in order:
        if prev is not None and values[i] - prev > tol:
            groups.append(current)
            current = []
        current.append(i)
        prev = values[i]
    if current:
        groups.append(current)
    return groups


def _axis_of(source_view):
    """视图局部长轴方向;端视图(轴向垂直投影面)与斜投影返回 None"""
    try:
        ap = axial_projection(source_view)
    except (ValueError, KeyError):
        return None
    return ap[0] if ap else None


def _prepare(views):
    """把模板视图归一成求解用的 item(尺寸均为画布 px)"""
    items = []
    for v in views:
        cb = v.get("contentBBox") or {}
        bbox = v.get("bbox") or {}
        w, h = float(cb.get("width") or 0), float(cb.get("height") or 0)
        if w <= 0 or h <= 0:
            k = float(bbox.get("scale") or 1.0)
            w = float(bbox.get("orig_width") or 400) * k
            h = float(bbox.get("orig_height") or 300) * k
        items.append({
            "id": v["id"],
            "x0": float(v.get("x") or 0), "y0": float(v.get("y") or 0),
            "bx": float(cb.get("x") or 0), "by": float(cb.get("y") or 0),
            "w": w, "h": h,
            "k": float(bbox.get("scale") or v.get("px_per_mm") or 1.0),
            "axis": _axis_of(v.get("source_view")),
            "col": 0, "row": 0, "trim": 0.0, "spec": None,
        })
    return items


def _assign_grid(items, tol):
    """按模板 x/y 聚成行列,保持原有对齐组与左右上下相对布局"""
    cols = _clusters([it["x0"] for it in items], tol)
    rows = _clusters([it["y0"] for it in items], tol)
    for ci, group in enumerate(cols):
        for idx in group:
            items[idx]["col"] = ci
    for ri, group in enumerate(rows):
        for idx in group:
            items[idx]["row"] = ri
    return len(cols), len(rows)


def _grid_sizes(items, ncols, nrows):
    """列宽/行高取组内最大内容尺寸;断裂视图按 shift 缩短对应方向"""
    cw, rh = [0.0] * ncols, [0.0] * nrows
    for it in items:
        w = it["w"] - it["trim"] if it["axis"] == "x" else it["w"]
        h = it["h"] - it["trim"] if it["axis"] == "y" else it["h"]
        cw[it["col"]] = max(cw[it["col"]], w)
        rh[it["row"]] = max(rh[it["row"]], h)
    return cw, rh


def _fit(cw, rh, avail_w, avail_h, max_scale):
    """统一缩放系数与其横/纵上限(用于判断哪个方向是瓶颈)"""
    total_w, total_h = sum(cw), sum(rh)
    sw = avail_w / total_w if total_w > 1e-6 else max_scale
    sh = avail_h / total_h if total_h > 1e-6 else max_scale
    return max(0.02, min(sw, sh, max_scale)), sw, sh


def _break_targets(items, axis, budget, cfg):
    """给瓶颈方向的轴向视图分配省略量并生成 BreakSpec,返回是否生效"""
    gap = cfg["break_visual_gap"]
    key = "col" if axis == "x" else "row"
    candidates = [it for it in items if it["axis"] == axis]
    groups = {it[key] for it in candidates}
    if not groups:
        return False
    per_group = budget / len(groups)
    changed = False
    for it in candidates:
        span = it["w"] if axis == "x" else it["h"]
        want = max(per_group, cfg["break_omit_mm"] * it["k"] - gap)
        want = min(want, span - 3 * gap - 1.0)
        if want <= 1.0:
            continue
        lo = it["bx"] if axis == "x" else it["by"]
        spec = break_view.build_spec(
            axis, lo, lo + span, (want + gap) / it["k"], it["k"],
            wave_amp=cfg["break_wave_amp"],
            wave_cycles=cfg["break_wave_cycles"], visual_gap=gap)
        if spec is None:
            continue
        it["spec"], it["trim"] = spec, spec.shift
        changed = True
    return changed


def _place(items, cw, rh, scale, avail_w, avail_h, cfg):
    """网格居中排回图纸:内容左/上边界对齐到所属格子左上角"""
    # 落盘只保留 5 位小数,位置必须用同一个已取整的比例算,否则消费方
    # 按 view.scale 反推的矩形会比求解时略宽,在小图纸上越出图框
    scale = round(scale, 5)
    total_w = sum(cw) * scale + cfg["min_gap"] * (len(cw) - 1)
    total_h = sum(rh) * scale + cfg["min_gap"] * (len(rh) - 1)
    ox = cfg["margin"] + (avail_w + cfg["min_gap"] * (len(cw) - 1) - total_w) / 2.0
    oy = cfg["margin"] + (avail_h + cfg["min_gap"] * (len(rh) - 1) - total_h) / 2.0
    col_x, row_y, acc = [], [], ox
    for w in cw:
        col_x.append(acc)
        acc += w * scale + cfg["min_gap"]
    acc = oy
    for h in rh:
        row_y.append(acc)
        acc += h * scale + cfg["min_gap"]
    out = {}
    for it in items:
        out[it["id"]] = {
            "x": round(col_x[it["col"]] - it["bx"] * scale, 3),
            "y": round(row_y[it["row"]] - it["by"] * scale, 3),
            "scale": round(scale, 5),
            "break": break_view.to_dict(it["spec"]),
        }
    return out


def solve_layout(sheet, views, cfg=None):
    """求解每视图的 x/y/scale 与断裂配置,保证所有视图落在图框可用区内

    Args:
        sheet: {"width": mm, "height": mm},缺省按 A3 横放
        views: 模板视图列表,需含 id/source_view/x/y/contentBBox/bbox
        cfg: 配置覆盖项(None 时按 .env 读取)

    Returns:
        {view_id: {"x", "y", "scale", "break"}},break 为落盘 dict 或 None
    """
    cfg = load_cfg(cfg)
    items = _prepare(views)
    if not items:
        return {}
    ncols, nrows = _assign_grid(items, cfg["align_tol"])
    m = cfg["margin"]
    avail_w = max(float(sheet.get("width") or 420) - 2 * m
                  - cfg["min_gap"] * (ncols - 1), 10.0)
    avail_h = max(float(sheet.get("height") or 297) - 2 * m
                  - cfg["reserved_bottom"] - cfg["min_gap"] * (nrows - 1), 10.0)
    cw, rh = _grid_sizes(items, ncols, nrows)
    scale, sw, sh = _fit(cw, rh, avail_w, avail_h, cfg["max_scale"])
    if scale < cfg["min_readable_scale"]:
        axis = "x" if sw <= sh else "y"
        budget = (sum(cw) if axis == "x" else sum(rh)) - (
            avail_w if axis == "x" else avail_h) / cfg["min_readable_scale"]
        if budget > 0 and _break_targets(items, axis, budget, cfg):
            cw, rh = _grid_sizes(items, ncols, nrows)
            scale, _, _ = _fit(cw, rh, avail_w, avail_h, cfg["max_scale"])
    return _place(items, cw, rh, scale, avail_w, avail_h, cfg)
