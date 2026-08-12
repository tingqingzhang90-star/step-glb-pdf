# -*- coding: utf-8 -*-
"""
SLDDRW 工程图模板提取框架 (SolidWorks COM 通用提取器)

从 .SLDDRW 工程图文件中提取:
  1. 图纸信息: 纸张尺寸 / 比例 / 投影角
  2. 视图布局: 视图名称 / 位置 / 比例 / 投影方向 / 轮廓范围
  3. 标注信息: 类型 / 值 / 文本 / 位置 / 所在视图
  4. 标注绑定实体的"几何指纹": 实体类型 + 曲线几何特征(直线方向/圆心半径)
     —— 解决拓扑命名问题(TNP)的关键, 模型变化后按指纹重新匹配
  5. 注释文本 (技术要求等)

输出统一的"原始模板 JSON", 供 slddrw_to_template.py 映射为可复用模板。

用法:
    # 提取单个文件
    conda run -n pdf1 python tools/slddrw_extractor.py "图库项目/250直连/YRJ250-H3K2-E.SLDDRW"

    # 批量提取目录下所有 SLDDRW
    conda run -n pdf1 python tools/slddrw_extractor.py --batch "图库项目/250直连"

依赖: SolidWorks 已安装(通过 COM 连接), pywin32
"""
import os
import sys
import json
import glob
import time
import traceback

import pythoncom
import win32com.client
import win32com.client.gencache

SW_DRAWING_LIBID = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"
SW_DRAWING_MAJOR = 32
SW_DRAWING_MINOR = 0

# SolidWorks 常量
swDocDRAWING = 3
swOpenDocOptions_Silent = 1
swOpenDocOptions_ReadOnly = 2

# swDimensionType_e → 语义类型名
DIM_TYPE_NAMES = {
    1: "ordinate",
    2: "linear",
    3: "angular",
    4: "arc_length",
    5: "radial",
    6: "diameter",
    7: "hor_ordinate",
    8: "vert_ordinate",
    9: "z_axis",
    10: "chamfer",
    11: "hor_linear",
    12: "vert_linear",
    13: "scalar",
}

# swSelectType_e 常用实体类型
ENTITY_TYPE_NAMES = {
    1: "edge",
    2: "face",
    3: "vertex",
    4: "datum_plane",
    5: "datum_axis",
    6: "reference_curve",
}

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slddrw_extracted")
_SW_MODULE = None


def sw_module():
    """加载 makepy 生成的 SolidWorks 类型库包装模块"""
    global _SW_MODULE
    if _SW_MODULE is None:
        import importlib
        module_name = "win32com.gen_py.83A33D31-27C5-11CE-BFD4-00400513BB57x0x32x0"
        _SW_MODULE = importlib.import_module(module_name)
    return _SW_MODULE


def _as_dispatch(obj):
    if obj is None:
        return None
    if hasattr(obj, "_oleobj_"):
        return obj
    try:
        return win32com.client.Dispatch(obj)
    except Exception:
        return obj


def _wrap_com(obj, interface_name):
    obj = _as_dispatch(obj)
    if obj is None:
        return None
    try:
        return getattr(sw_module(), interface_name)(obj)
    except Exception:
        return obj


def _value(obj):
    if obj is None:
        return None
    if callable(obj) and not hasattr(obj, "_oleobj_"):
        return obj()
    return obj


def _member(obj, name):
    return _value(getattr(obj, name, None))


# ==================== COM 连接 ====================

def connect_solidworks():
    """连接正在运行的 SolidWorks 实例(优先), 否则启动新实例"""
    try:
        app = win32com.client.gencache.EnsureDispatch("SldWorks.Application")
        print("[COM] 已使用 makepy 绑定连接 SolidWorks")
    except Exception:
        app = win32com.client.Dispatch("SldWorks.Application")
        print("[COM] 已使用动态 Dispatch 连接 SolidWorks")
    app.Visible = True
    return app


def open_drawing(app, path):
    """打开工程图文档(只读+静默)"""
    path = os.path.abspath(path)
    try:
        spec = app.GetOpenDocSpec(path)
        spec.DocumentType = swDocDRAWING
        spec.Silent = True
        spec.ReadOnly = True
        spec.LoadModel = True
        doc = app.OpenDoc7(spec)
    except Exception as exc:
        raise RuntimeError(f"无法打开工程图: {path} ({exc})") from exc

    if doc is None:
        raise RuntimeError(f"无法打开工程图: {path}")
    return doc


# ==================== 安全取值工具 ====================

def _safe(fn, default=None):
    """COM 调用兜底: 失败返回 default"""
    try:
        return fn()
    except Exception:
        return default


def _to_list(variant):
    """VARIANT 数组 → Python list"""
    if variant is None:
        return []
    try:
        return list(variant)
    except TypeError:
        return [variant]


def _m_to_mm(v):
    """米 → 毫米(SolidWorks API 内部单位是米)"""
    try:
        return round(float(v) * 1000.0, 3)
    except (TypeError, ValueError):
        return None


# ==================== 几何指纹提取 ====================

def extract_entity_fingerprint(entity):
    """提取标注绑定实体的几何指纹

    指纹内容(尽最大努力提取, 失败的字段为 None):
      - entity_type: edge / face / vertex / ...
      - component: 所属零件名(装配体中定位零件)
      - curve: 边的曲线几何(直线: 起终点+方向; 圆: 圆心+半径+轴向)

    模型再生后拓扑 ID 会漂移, 但同一语义边的几何特征
    (所属零件 + 曲线类型 + 方向/半径)保持稳定 → 用于重新匹配。
    """
    fp = {"entity_type": None, "component": None, "curve": None}
    if entity is None:
        return fp

    etype = _safe(lambda: entity.GetType())
    fp["entity_type"] = ENTITY_TYPE_NAMES.get(etype, f"unknown_{etype}")

    # 所属零件
    comp = _safe(lambda: entity.GetComponent())
    if comp is not None:
        fp["component"] = _safe(lambda: comp.Name2)

    # 边 → 曲线几何
    if etype == 1:  # edge
        curve_info = {}
        edge = entity
        curve = _safe(lambda: edge.GetCurve())
        if curve is not None:
            if _safe(lambda: curve.IsLine(), False):
                params = _to_list(_safe(lambda: edge.GetCurveParams3().Get())) or \
                         _to_list(_safe(lambda: edge.GetCurveParams2()))
                curve_info["kind"] = "line"
                if len(params) >= 6:
                    curve_info["start_mm"] = [_m_to_mm(v) for v in params[0:3]]
                    curve_info["end_mm"] = [_m_to_mm(v) for v in params[3:6]]
            elif _safe(lambda: curve.IsCircle(), False):
                cp = _to_list(_safe(lambda: curve.CircleParams))
                curve_info["kind"] = "circle"
                if len(cp) >= 7:
                    curve_info["center_mm"] = [_m_to_mm(v) for v in cp[0:3]]
                    curve_info["axis"] = [round(float(v), 6) for v in cp[3:6]]
                    curve_info["radius_mm"] = _m_to_mm(cp[6])
            else:
                curve_info["kind"] = "other"
        fp["curve"] = curve_info or None

    # 面 → 面类型 + 法向/轴
    elif etype == 2:  # face
        surf_info = {}
        face = entity
        surf = _safe(lambda: face.GetSurface())
        if surf is not None:
            if _safe(lambda: surf.IsPlane(), False):
                pp = _to_list(_safe(lambda: surf.PlaneParams))
                surf_info["kind"] = "plane"
                if len(pp) >= 6:
                    surf_info["normal"] = [round(float(v), 6) for v in pp[0:3]]
                    surf_info["root_mm"] = [_m_to_mm(v) for v in pp[3:6]]
            elif _safe(lambda: surf.IsCylinder(), False):
                cp = _to_list(_safe(lambda: surf.CylinderParams))
                surf_info["kind"] = "cylinder"
                if len(cp) >= 7:
                    surf_info["origin_mm"] = [_m_to_mm(v) for v in cp[0:3]]
                    surf_info["axis"] = [round(float(v), 6) for v in cp[3:6]]
                    surf_info["radius_mm"] = _m_to_mm(cp[6])
            else:
                surf_info["kind"] = "other"
        fp["curve"] = surf_info or None

    return fp


# ==================== 标注提取 ====================

def extract_dimensions(view):
    """提取视图上的所有显示标注(尺寸)"""
    dims = []
    disp_dim = _safe(lambda: view.GetFirstDisplayDimension5())
    guard = 0
    while disp_dim is not None and guard < 500:
        guard += 1
        d = {}
        dtype = _safe(lambda: disp_dim.Type2)
        d["dim_type_raw"] = dtype
        d["dim_type"] = DIM_TYPE_NAMES.get(dtype, f"unknown_{dtype}")

        dim_obj = _safe(lambda: disp_dim.GetDimension2(0))
        if dim_obj is not None:
            d["full_name"] = _safe(lambda: dim_obj.FullName)
            d["name"] = _safe(lambda: dim_obj.Name)
            # 系统值单位是米; 角度是弧度
            sys_val = _safe(lambda: dim_obj.SystemValue)
            if sys_val is not None:
                if dtype == 3:  # angular → 度
                    import math
                    d["value"] = round(float(sys_val) * 180.0 / math.pi, 3)
                    d["unit"] = "deg"
                else:
                    d["value"] = _m_to_mm(sys_val)
                    d["unit"] = "mm"

        ann = _safe(lambda: disp_dim.GetAnnotation())
        if ann is not None:
            pos = _to_list(_safe(lambda: ann.GetPosition()))
            if len(pos) >= 2:
                d["position_mm"] = [_m_to_mm(pos[0]), _m_to_mm(pos[1])]
            d["text"] = _safe(lambda: disp_dim.GetText(0))  # swDimensionTextAll=0

            # ★ 绑定实体几何指纹(TNP 关键)
            ent_count = _safe(lambda: ann.GetAttachedEntityCount3(), 0) or 0
            fingerprints = []
            if ent_count > 0:
                entities = _to_list(_safe(lambda: ann.GetAttachedEntities3()))
                for ent in entities:
                    fingerprints.append(extract_entity_fingerprint(ent))
            d["attached_entities"] = fingerprints

        dims.append(d)
        disp_dim = _safe(lambda: disp_dim.GetNext5())
    return dims


def extract_notes(view):
    """提取视图上的注释文本(技术要求等)"""
    notes = []
    note = _safe(lambda: view.GetFirstNote())
    guard = 0
    while note is not None and guard < 200:
        guard += 1
        n = {"text": _safe(lambda: note.GetText())}
        ann = _safe(lambda: note.GetAnnotation())
        if ann is not None:
            pos = _to_list(_safe(lambda: ann.GetPosition()))
            if len(pos) >= 2:
                n["position_mm"] = [_m_to_mm(pos[0]), _m_to_mm(pos[1])]
        notes.append(n)
        note = _safe(lambda: note.GetNext())
    return notes


# ==================== 视图提取 ====================

def extract_view(view):
    """提取单个工程视图的布局信息"""
    view = _as_dispatch(view)
    v = {
        "name": _safe(lambda: _member(view, "Name")) or _safe(lambda: _member(view, "GetName2")),
        "orientation": _safe(lambda: _member(view, "GetOrientationName")),
        "scale": _safe(lambda: _member(view, "ScaleDecimal")),
        "referenced_doc": None,
        "referenced_model_name": _safe(lambda: _member(view, "GetReferencedModelName")),
        "position_mm": None,
        "outline_mm": None,
        "sheet_name": None,
        "view_type": _safe(lambda: _member(view, "Type")),
    }

    ref_doc = _safe(lambda: _member(view, "ReferencedDocument"))
    if ref_doc is not None:
        ref_doc = _as_dispatch(ref_doc)
        v["referenced_doc"] = _safe(lambda: os.path.basename(_member(ref_doc, "GetPathName")))

    sheet = _as_dispatch(_safe(lambda: _member(view, "Sheet")))
    if sheet is not None:
        v["sheet_name"] = _safe(lambda: _member(sheet, "GetName"))

    pos = _to_list(_safe(lambda: _member(view, "Position")))
    if len(pos) >= 2:
        v["position_mm"] = [_m_to_mm(pos[0]), _m_to_mm(pos[1])]

    outline = _to_list(_safe(lambda: _member(view, "GetOutline")))
    if len(outline) >= 4:
        v["outline_mm"] = [_m_to_mm(x) for x in outline[:4]]  # xmin,ymin,xmax,ymax

    v["dimensions"] = extract_dimensions(view)
    v["notes"] = extract_notes(view)
    return v


# ==================== 主提取流程 ====================

def _first_view(doc):
    return _as_dispatch(_safe(lambda: doc._oleobj_.InvokeTypes(34, 0, 1, (9, 0), (),)))


def _next_view(view):
    view = _as_dispatch(view)
    return _as_dispatch(_safe(lambda: view._oleobj_.InvokeTypes(1, 0, 1, (9, 0), (),)))


def extract_slddrw(app, slddrw_path):
    """提取单个 SLDDRW → 原始模板 dict"""
    t0 = time.time()
    doc = open_drawing(app, slddrw_path)
    try:
        result = {
            "source_file": os.path.basename(slddrw_path),
            "extracted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sheets": [],
        }

        sheet_count = _safe(lambda: _value(getattr(doc, "GetSheetCount", None)), 0) or 0
        sheet_names = _to_list(_safe(lambda: _value(getattr(doc, "GetSheetNames", None)), []))
        if not sheet_names and sheet_count:
            current_sheet = _as_dispatch(_safe(lambda: doc._oleobj_.InvokeTypes(70, 0, 1, (9, 0), (),)))
            current_name = _safe(lambda: _member(current_sheet, "GetName")) if current_sheet is not None else None
            sheet_names = [current_name] if current_name else []

        for sheet_name in sheet_names:
            _safe(lambda: doc.ActivateSheet(sheet_name))
            sheet = _as_dispatch(_safe(lambda: doc._oleobj_.InvokeTypes(70, 0, 1, (9, 0), (),)))
            sheet_info = {"name": sheet_name, "views": []}

            if sheet is not None:
                props = _to_list(_safe(lambda: _member(sheet, "GetProperties2"))) or \
                        _to_list(_safe(lambda: _member(sheet, "GetProperties")))
                if len(props) >= 7:
                    sheet_info["paper_size_code"] = props[0]
                    sheet_info["scale"] = f"{props[2]:g}:{props[3]:g}"
                    sheet_info["first_angle_projection"] = bool(props[4])
                    sheet_info["width_mm"] = _m_to_mm(props[5])
                    sheet_info["height_mm"] = _m_to_mm(props[6])

            # 遍历视图链: 第一个 view 是图纸本身, 后续才是模型视图
            view = _next_view(_first_view(doc))
            guard = 0
            while view is not None and guard < 80:
                guard += 1
                view_info = extract_view(view)
                if view_info.get("sheet_name") in (None, sheet_name):
                    sheet_info["views"].append(view_info)
                view = _next_view(view)

            result["sheets"].append(sheet_info)

        result["elapsed_s"] = round(time.time() - t0, 2)
        return result
    finally:
        _safe(lambda: app.CloseDoc(doc.GetTitle()))


def save_json(data, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[保存] {out_path}")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    pythoncom.CoInitialize()
    app = connect_solidworks()

    if args[0] == "--batch":
        folder = args[1]
        files = sorted(glob.glob(os.path.join(folder, "*.SLDDRW")))
        print(f"[批量] 共 {len(files)} 个文件")
        summary = []
        for f in files:
            name = os.path.splitext(os.path.basename(f))[0]
            out_path = os.path.join(OUT_DIR, name + ".json")
            try:
                data = extract_slddrw(app, f)
                save_json(data, out_path)
                n_views = sum(len(s["views"]) for s in data["sheets"])
                n_dims = sum(len(v["dimensions"]) for s in data["sheets"] for v in s["views"])
                summary.append(f"  {name}: 视图={n_views} 标注={n_dims} 耗时={data['elapsed_s']}s")
            except Exception as e:
                summary.append(f"  {name}: 失败 - {e}")
                traceback.print_exc()
        print("\n[批量提取汇总]")
        for line in summary:
            print(line)
    else:
        f = args[0]
        name = os.path.splitext(os.path.basename(f))[0]
        data = extract_slddrw(app, f)
        out_path = os.path.join(OUT_DIR, name + ".json")
        save_json(data, out_path)
        # 打印摘要
        for s in data["sheets"]:
            print(f"\n图纸 [{s['name']}] {s.get('width_mm')}x{s.get('height_mm')}mm "
                  f"比例={s.get('scale')} 视图数={len(s['views'])}")
            for v in s["views"]:
                print(f"  视图 {v['name']} ({v['orientation']}) scale={v['scale']} "
                      f"pos={v['position_mm']} 标注={len(v['dimensions'])} 注释={len(v['notes'])}")
                for d in v["dimensions"][:10]:
                    ents = len(d.get("attached_entities", []))
                    print(f"    - {d.get('dim_type')} {d.get('name')} = {d.get('value')}{d.get('unit','')} "
                          f"绑定实体={ents}")


if __name__ == "__main__":
    main()
