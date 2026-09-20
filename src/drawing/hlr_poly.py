# -*- coding: utf-8 -*-
"""路线 D B 层 — 自研离散投影链路（PolyAlgo + 圆弧拟合 + 进程池并行）。

独立于 core.drawing_engine 的精确 HLR(Algo)路径，作为可平替的另一种投影
实现。输出结构与 generate_all_standard_views 完全一致，调用方零改动即可切换。

相比现有 Algo 路径的差异：
  - 用 HLRBRep_PolyAlgo（三角网格离散 HLR）替代精确 B-Rep 求交，速度更快；
  - 离散后的圆/弧经 drawing.hlr_arcfit 拟合恢复 type=circle/arc 与 center_mm/radius；
  - 每个 worker 进程内按 (model_path, deflection) 缓存已三角化的 shape，同 worker
    处理多视图只 load+tessellate 一次（现有 Algo 并行 worker 每视图都重读）；
  - 主进程扇出：每视图一个任务进同一个有界进程池，进程数被 max_workers 封顶，
    不会随视图/用户数爆炸。在任务池子进程内被调用时自动降级串行，杜绝嵌套池。

用法：
    from drawing.hlr_poly import generate_all_standard_views_poly
    data = generate_all_standard_views_poly(
        "output/250-E-H2K1-L100/assembly.step",
        view_names=["front", "left", "left_top"],   # 工程图常用 3 视图
        deflection=2.0, do_fit=True,
    )
    # data 结构与 drawing_engine.generate_all_standard_views 完全一致
"""
import os
import time
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed

from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Ax3, gp_Trsf
from OCC.Core.HLRBRep import HLRBRep_PolyAlgo, HLRBRep_PolyHLRToShape
from OCC.Core.HLRAlgo import HLRAlgo_Projector
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib

from core import drawing_engine as DE
from drawing.hlr_arcfit import fit_circular_features


# 进程级 shape 缓存: key = (model_path, deflection)。
# ProcessPoolExecutor 复用同一 worker 进程处理多个任务,故同一 worker 内首个视图
# load+tessellate,后续视图直接复用,使昂贵的加载摊薄到 ~1 次/worker。
_SHAPE_CACHE = {}


def _build_ax2(view_dir, up_dir):
    """构造投影坐标系 gp_Ax2（与 drawing_engine._project_shape_poly 完全一致）。"""
    if up_dir is None:
        if abs(view_dir.Z()) < 0.9:
            up_dir = gp_Dir(0, 0, 1)
        else:
            up_dir = gp_Dir(0, 1, 0)
    x_dir = gp_Dir(
        view_dir.Y() * up_dir.Z() - view_dir.Z() * up_dir.Y(),
        view_dir.Z() * up_dir.X() - view_dir.X() * up_dir.Z(),
        view_dir.X() * up_dir.Y() - view_dir.Y() * up_dir.X(),
    )
    return gp_Ax2(gp_Pnt(0, 0, 0), view_dir, x_dir)


def _get_shape(model_path, deflection):
    key = (model_path, deflection)
    item = _SHAPE_CACHE.get(key)
    if item is not None:
        return item
    shape = DE.read_shape_cached(model_path)
    BRepMesh_IncrementalMesh(shape, deflection)
    box = Bnd_Box()
    brepbndlib.Add(shape, box)
    max_ext = 1e4
    if not box.IsVoid():
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
        max_ext = max(xmax - xmin, ymax - ymin, zmax - zmin)
    item = (shape, max_ext)
    _SHAPE_CACHE[key] = item
    return item


def _project_discrete_one(shape, view_dir, up_dir, show_hidden, max_extent):
    """单个视图的 PolyAlgo 离散投影（复用 drawing_engine 的后处理 helper）。"""
    ax2 = _build_ax2(view_dir, up_dir)
    bounds = DE._compute_view_bounds_2d(shape, ax2, margin=1.0)

    poly = HLRBRep_PolyAlgo()
    poly.Load(shape)
    poly.Projector(HLRAlgo_Projector(ax2))
    poly.Update()

    pts = HLRBRep_PolyHLRToShape()
    pts.Update(poly)

    vis_raw = []
    vis_raw.extend(DE._extract_2d_segments(pts.OutLineVCompound(), max_extent=max_extent))
    vis_raw.extend(DE._extract_2d_segments(pts.VCompound(), max_extent=max_extent))
    vis_raw.extend(DE._extract_2d_segments(pts.Rg1LineVCompound(), max_extent=max_extent))
    vis = DE._filter_short_segments(vis_raw, min_length=2.0)
    vis = DE._drop_out_of_bounds_segments(vis, bounds)

    hid = []
    if show_hidden:
        hid_raw = []
        hid_raw.extend(DE._extract_2d_segments(pts.HCompound(), max_extent=max_extent))
        hid_raw.extend(DE._extract_2d_segments(pts.OutLineHCompound(), max_extent=max_extent))
        hid = DE._filter_short_segments(hid_raw, min_length=2.0)
        hid = DE._drop_out_of_bounds_segments(hid, bounds)
    return vis, hid


def project_view_subset(model_path, view_names, deflection=2.0,
                        show_hidden=False, do_fit=True):
    """worker 任务:投影一组视图,返回 {view: {visible, hidden, project_time}}。

    纯 dict 结构,可跨进程 pickle。供主进程扇出到进程池调用。
    """
    shape, max_ext = _get_shape(model_path, deflection)
    max_r = (max_ext or 1e4) * 2
    out = {}
    for v in view_names:
        cfg = DE.STANDARD_VIEW_CONFIGS.get(v)
        if cfg is None:
            continue
        t0 = time.perf_counter()
        vis, hid = _project_discrete_one(shape, cfg["dir"], cfg["up"],
                                         show_hidden, max_ext)
        fv = fit_circular_features(vis, max_radius=max_r) if do_fit else vis
        fh = (fit_circular_features(hid, max_radius=max_r)
              if (do_fit and show_hidden) else hid)
        out[v] = {
            "visible": fv,
            "hidden": fh,
            "project_time": round(time.perf_counter() - t0, 3),
        }
    return out


def generate_all_standard_views_poly(step_path, include_hidden=False,
                                     thumb_width=200, thumb_height=150,
                                     canvas_width=400, canvas_height=300,
                                     view_names=None, parallel=True,
                                     max_workers=None, deflection=2.0,
                                     do_fit=True):
    """生成标准视图(离散 HLR + 圆弧拟合),输出结构与 generate_all_standard_views 一致。

    Args:
        step_path: STEP/BRep 文件路径
        include_hidden: 是否生成隐藏边(虚线)
        view_names: 只生成这些视图;None 表示全部。工程图常用 ["front", "left", "left_top"]
        parallel: 视图间是否进程池并行。在任务池子进程内被调用时自动降级串行,
            避免嵌套进程池导致进程数失控(多用户并发场景)
        max_workers: 并行内部进程数上限;None 自动(<=9)
        deflection: PolyAlgo 三角化精度(mm),越小越精确越慢
        do_fit: 是否对离散段做圆弧拟合恢复 circle/arc 语义

    Returns: 与 drawing_engine.generate_all_standard_views 同构的 dict
    """
    t0 = time.time()

    shape0 = DE.read_shape_cached(step_path)
    box = Bnd_Box()
    brepbndlib.Add(shape0, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    model_bbox = {
        "width": round(float(xmax - xmin), 2),
        "height": round(float(ymax - ymin), 2),
        "depth": round(float(zmax - zmin), 2),
    }

    if view_names is None:
        view_names = list(DE.STANDARD_VIEW_CONFIGS.keys())
    else:
        unknown = [n for n in view_names if n not in DE.STANDARD_VIEW_CONFIGS]
        if unknown:
            raise ValueError("未知视图名: %s,可选: %s"
                             % (unknown, list(DE.STANDARD_VIEW_CONFIGS)))
        view_names = list(dict.fromkeys(view_names))
    if not view_names:
        raise ValueError("view_names 不能为空")

    # 防嵌套: 已在任务池子进程内时, 强制串行, 避免进程数随用户数爆炸
    if parallel and multiprocessing.current_process().name != "MainProcess":
        parallel = False
    # 少视图时单进程缓存复用比多进程冷加载更快: 每个 worker 都要冷加载+三角化
    # shape, N 视图分给 N 个 worker 即 N 次冷加载; 串行单进程只 1 次, 且缓存跨
    # 全部视图复用。工程图常用 3 视图(front/left/left_top)走这条最快路径。
    if parallel and len(view_names) <= 4:
        parallel = False

    raw = {}
    if (not parallel) or (max_workers is not None and max_workers <= 1):
        for v in view_names:
            raw.update(project_view_subset(step_path, [v], deflection,
                                          include_hidden, do_fit))
    else:
        if max_workers is None:
            max_workers = min(9, len(view_names), max(1, os.cpu_count() or 4))
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(project_view_subset, step_path, [v],
                              deflection, include_hidden, do_fit)
                    for v in view_names]
            for f in as_completed(futs):
                raw.update(f.result())

    raw = {n: raw[n] for n in DE.STANDARD_VIEW_CONFIGS if n in raw}

    # 统一缩放比例(所有视图比例一致)
    max_2d = 1.0
    for rv in raw.values():
        segs = rv["visible"] + rv["hidden"]
        if not segs:
            continue
        min_x, min_y, max_x, max_y = DE._compute_bbox([segs])
        max_2d = max(max_2d, max_x - min_x, max_y - min_y)
    margin = 10
    avail = min(canvas_width - 2 * margin, canvas_height - 2 * margin)
    uniform_scale = avail / max_2d if max_2d > 0.01 else 1.0

    result_views = {}
    for v, rv in raw.items():
        cfg = DE.STANDARD_VIEW_CONFIGS[v]
        vis_r = DE._assign_bbox_roles(rv["visible"])
        hid_r = DE._assign_bbox_roles(rv["hidden"])
        thumb_v, thumb_h, _ = DE._normalize_view(
            vis_r, hid_r, thumb_width, thumb_height)
        thumbnail = DE._segments_to_svg(thumb_v, thumb_h, thumb_width, thumb_height)
        canvas_v, canvas_h, canvas_bbox = DE._normalize_view(
            vis_r, hid_r, canvas_width, canvas_height, uniform_scale=uniform_scale)
        result_views[v] = {
            "label": cfg["label"],
            "group": cfg["group"],
            "thumbnail": thumbnail,
            "edges": canvas_v,
            "hidden_edges": canvas_h,
            "bbox": canvas_bbox,
            "seg_count": len(canvas_v),
            "hidden_count": len(canvas_h),
            "project_time": rv.get("project_time", 0.0),
        }

    elapsed = time.time() - t0
    return {
        "views": result_views,
        "model_bbox": model_bbox,
        "scale_info": {
            "uniform_scale": round(uniform_scale, 4),
            "max_2d_extent_mm": round(max_2d, 2),
        },
        "elapsed": round(elapsed, 3),
        "timing": {"total": round(elapsed, 3), "parallel": parallel,
                   "workers": max_workers},
    }
