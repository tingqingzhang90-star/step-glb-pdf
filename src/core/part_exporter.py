# -*- coding: utf-8 -*-
"""参数化零件导出:SW 装配体 → 系列零件库 library/series/<系列>/parts

由 export_parts.py 重构而来。原脚本的 ASSEMBLY_PATH / OUTPUT_DIR 是模块级常量,
只能导 250直连;改为按系列参数化后,CLI 与 Web 面板共用同一套逻辑。

SW COM 的几个坑,原因都写在对应调用处:
  - 必须先快照抑制状态:打开任一零件文档会让 SW 重新解析装配体并解除抑制
  - Extension.SaveAs 六参数 + options=0:options 用 Silent 会 DISP_E_TYPEMISMATCH
  - ExportData 必须是 VT_DISPATCH 的 Nothing,传 None 会被当成 VT_EMPTY
  - STEP AP214 的用户选项 id 是 75、值是 2,都不是字面上的 214
"""
import json
import os
import sys
import time

import pythoncom
import win32com.client

_PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if os.path.join(_PROJECT_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from core import paths  # noqa: E402

SW_DOC_PART = 1
SW_DOC_ASSEMBLY = 2
SW_OPEN_SILENT = 1
SW_SAVE_CURRENT_VERSION = 0
SW_SAVE_OPTIONS_NONE = 0
SW_USER_PREF_STEP_AP = 75
SW_STEP_AP214 = 2

# 跨系列通用的标准件(电机/减速机),导出后统一移入 library/shared
SHARED_KEYWORDS = ("kw", "ab180")

# SolidWorks swFileLoadError_e(部分):OpenDoc6 打开失败的具体原因
_SW_LOAD_ERRORS = {
    0: "无错误",
    1: "文件类型无效",
    2: "文件不存在",
    4: "导入失败",
    5: "文档已打开",
    8: "无法确定版本",
    12: "一般错误",
    13: "无法打开",
    17: "不支持的文件",
    18: "已在另一个实例中打开",
    23: "文件是更高版本(本机 SolidWorks 版本过低,打不开用更新版本保存的文件)",
    24: "需要强制重建",
    26: "大装配体审阅模式",
    65536: "同名文档已在 SolidWorks 中打开(代码将自动复用已打开的文档;若仍失败请先关闭该文件)",
}

# SolidWorks swFileSaveError_e(部分):SaveAs 返回 False 但无异常时的具体原因
_SW_SAVE_ERRORS = {
    0: "无错误",
    1: "文件已被打开,无法另存",
    2: "文件只读",
    4: "未选择要保存的对象",
    8: "文件名为空",
    16: "源文件不存在",
    32: "目标格式不可用",
    64: "用户取消另存",
    128: "装配体含在位编辑特征,无法另存",
    256: "需要同时保存引用",
    512: "另存成功但未关闭源文档",
}


def _int_ref():
    """SW COM 需要的 byref int 输出参数(errors / warnings)"""
    return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)


def _nothing():
    return win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)


def list_assemblies(series):
    """系列目录下的候选装配体绝对路径(排除 SW 的 ~$ 临时文件)"""
    d = os.path.join(paths.LIB_ROOT, series)
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, f) for f in os.listdir(d)
                  if f.upper().endswith(".SLDASM") and not f.startswith("~$"))


def resolve_assembly(series, assembly=None):
    """确定装配体:显式指定优先,否则要求系列目录下恰好一个候选

    assembly 只给文件名时,按 <图库>/<系列>/ 解析。
    """
    if assembly:
        if not os.path.isabs(assembly):
            assembly = os.path.join(paths.LIB_ROOT, series, assembly)
        if not os.path.exists(assembly):
            raise FileNotFoundError(f"装配体不存在: {assembly}")
        return assembly
    found = list_assemblies(series)
    if not found:
        raise FileNotFoundError(f"{series} 目录下没有装配体")
    if len(found) > 1:
        raise ValueError(f"{series} 下有多个装配体,请指定: {found}")
    return found[0]


def _resolve_part_path(part_path, search_dirs):
    """装配体引用的常是设计机上的旧路径,按 basename 在本机候选目录回退查找"""
    if not part_path or os.path.exists(part_path):
        return part_path
    base = os.path.basename(part_path)
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        hit = os.path.join(d, base)
        if os.path.exists(hit):
            return hit
        for root, dirs, files in os.walk(d):
            if root[len(d):].count(os.sep) >= 2:
                dirs[:] = []
                continue
            if base in files:
                return os.path.join(root, base)
    return part_path


def _component_state(comp, search_dirs):
    """快照单个组件:名称 / 本机路径 / 抑制状态 / 变换矩阵"""
    path = ""
    try:
        path = comp.GetPathName
        if callable(path):  # 部分 SW 版本暴露成方法
            path = path()
    except Exception:
        path = ""
    if path and not os.path.exists(path):
        path = _resolve_part_path(path, search_dirs)
    suppressed = False
    try:
        suppressed = bool(comp.IsSuppressed)  # 是属性,不能加括号
    except Exception:
        pass
    matrix = None
    try:
        arr = comp.Transform2.ArrayData
        if arr and len(arr) >= 16:
            matrix = [float(arr[i]) for i in range(16)]
    except Exception:
        matrix = None
    return {"name": comp.Name2, "path": path,
            "suppressed": suppressed, "transform_matrix": matrix}


def collect_components(asm, search_dirs):
    """快照全部组件。必须在打开任何零件文档之前调用"""
    return [_component_state(c, search_dirs) for c in (asm.GetComponents(False) or [])]


def _doc_title(doc):
    """取文档标题(不带扩展名),CloseDoc / 同名匹配用。GetPathName 在某些版本是方法。"""
    try:
        p = doc.GetPathName
        if callable(p):
            p = p()
        return os.path.splitext(os.path.basename(p or ""))[0] if p else ""
    except Exception:
        return ""


def _open_documents(sw):
    """取 SW 当前已打开的文档列表,兼容 GetDocuments 是属性还是方法两种暴露方式"""
    try:
        getter = sw.GetDocuments
        docs = getter() if callable(getter) else getter
    except Exception:
        return []
    if not docs:
        return []
    return list(docs)


def _already_open_model(sw, path):
    """文档已被同一 SW 实例打开时(如用户在界面里开着),取回已打开的模型

    先按完整路径匹配;匹配不到再按标题(文件名)匹配 —— 用户在交互式会话里打开的
    零件,其路径往往是设计机的旧路径,与本机解析出的路径不一致,OpenDoc6 会返回 65536,
    必须靠文件名复用,否则该零件永远打不开、导出失败。
    """
    docs = _open_documents(sw)
    if not docs:
        return None
    target = os.path.abspath(path).lower()
    target_title = os.path.splitext(os.path.basename(path))[0].lower()
    for doc in docs:
        try:
            p = doc.GetPathName
            if callable(p):
                p = p()
        except Exception:
            p = ""
        if p:
            if os.path.abspath(p).lower() == target:
                return doc
            if os.path.splitext(os.path.basename(p))[0].lower() == target_title:
                return doc
    return None


def _open(sw, path, doc_type):
    """打开文档,返回 (model, 错误码, 警告码, 是否复用已打开文档)。

    model 为 None 表示打开失败;borrowed=True 时该模型是 SW 中已打开的,
    调用方不应 CloseDoc(否则会关掉用户界面里打开的文件)。
    """
    errors, warnings = _int_ref(), _int_ref()
    model = sw.OpenDoc6(path, doc_type, SW_OPEN_SILENT, "", errors, warnings)
    borrowed = False
    if model is None:
        # OpenDoc6 返回空但文档可能已在 SW 中打开(错误码 65536),直接复用
        model = _already_open_model(sw, path)
        borrowed = model is not None
    return model, errors.value, warnings.value, borrowed


def _load_error_text(code, path):
    reason = _SW_LOAD_ERRORS.get(code, f"未知错误码 {code}")
    return f"打开装配体失败({reason}): {path}"


def preview_components(series, assembly=None):
    """只扫描不导出,返回组件清单(面板用它做导出前的路径体检)"""
    asm_path = resolve_assembly(series, assembly)
    search = [os.path.dirname(asm_path), paths.LIB_ROOT]
    pythoncom.CoInitialize()
    try:
        sw = win32com.client.Dispatch("SldWorks.Application")
        sw.Visible = False
        model, err, _, _ = _open(sw, asm_path, SW_DOC_ASSEMBLY)
        if model is None:
            raise RuntimeError(_load_error_text(err, asm_path))
        return {"assembly": asm_path, "components": collect_components(model, search)}
    finally:
        pythoncom.CoUninitialize()


def export_single_part(sw, part_path, step_output):
    """打开单个零件另存为 STEP AP214,返回 (成功, 失败原因)

    失败原因用于面板日志与产物诊断;成功时原因为空串。
    """
    if not os.path.exists(part_path):
        return False, f"零件文件不存在: {part_path}"
    part_name = os.path.basename(part_path)
    doc, open_err, _, borrowed = _open(sw, part_path, SW_DOC_PART)
    if doc is None:
        return False, _load_error_text(open_err, part_path)
    sw.SetUserPreferenceIntegerValue(SW_USER_PREF_STEP_AP, SW_STEP_AP214)
    sw.SetUserPreferenceToggle(33, True)  # 导出外观
    sw.SetUserPreferenceToggle(34, True)  # 导出面/边属性
    errors, warnings = _int_ref(), _int_ref()
    try:
        # options 必须为 0:非 PDF 导出传 Silent 会触发 DISP_E_TYPEMISMATCH
        ok = doc.Extension.SaveAs(step_output, SW_SAVE_CURRENT_VERSION,
                                  SW_SAVE_OPTIONS_NONE, _nothing(), errors, warnings)
    except Exception as exc:
        ok = False
        reason = f"SaveAs 异常: {exc}"
    else:
        reason = ""
        if not ok:
            # SaveAs 返回 False 但无异常:用错误/警告码给出可读原因
            reason = (_SW_SAVE_ERRORS.get(errors.value)
                      or f"SaveAs 失败(err={errors.value}, warn={warnings.value})")
    # 借用的文档(用户已在 SW 中打开)不能关,否则会关掉界面里的文件
    if not borrowed:
        try:
            sw.CloseDoc(_doc_title(doc) or os.path.splitext(part_name)[0])
        except Exception:
            pass
    saved = bool(ok) and os.path.exists(step_output) and os.path.getsize(step_output) > 0
    if not saved and not reason:
        reason = "STEP 输出为空(另存未生成有效文件)"
    return saved, reason


def _move_shared_parts(parts_dir, parts_data):
    """标准件移入 library/shared,避免每个系列各存一份

    与已有共享件体积不一致时不移动:同名不等于同件,留在系列目录里,
    查找顺序是系列目录优先,不会误用。
    """
    os.makedirs(paths.SHARED_PARTS_DIR, exist_ok=True)
    moved = []
    for name in sorted({v["step_file"] for v in parts_data.values() if v["step_file"]}):
        base = os.path.splitext(name)[0].lower()
        if not any(k in base for k in SHARED_KEYWORDS):
            continue
        src = os.path.join(parts_dir, name)
        dst = os.path.join(paths.SHARED_PARTS_DIR, name)
        if not os.path.exists(src):
            continue
        if os.path.exists(dst) and os.path.getsize(dst) != os.path.getsize(src):
            continue
        os.replace(src, dst)
        moved.append(name)
    return moved


def _write_outputs(series, asm_path, parts_data, shared):
    """落盘变换矩阵与导出元信息"""
    os.makedirs(paths.series_dir(series), exist_ok=True)
    with open(paths.transform_json(series), "w", encoding="utf-8") as f:
        json.dump(parts_data, f, ensure_ascii=False, indent=2)
    meta = {
        "series": series,
        "assembly": asm_path,
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "component_count": len(parts_data),
        "step_ap": 214,
        "shared_parts": shared,
    }
    with open(paths.meta_json(series), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def export_series(series, assembly=None, overwrite=False, on_progress=None):
    """导出一个系列的全部零件,返回统计字典

    Args:
        series: 图库项目下的系列目录名
        assembly: 装配体路径,省略时取系列目录下的唯一候选
        overwrite: 覆盖已存在的 STEP,默认跳过(断点续导)
        on_progress: 回调 on_progress(event, payload),event 为
            start / component / done
    """
    asm_path = resolve_assembly(series, assembly)
    parts_dir = paths.parts_dir(series)
    os.makedirs(parts_dir, exist_ok=True)
    emit = on_progress or (lambda *_: None)

    pythoncom.CoInitialize()
    try:
        sw = win32com.client.Dispatch("SldWorks.Application")
        sw.Visible = False
        model, err, _, asm_borrowed = _open(sw, asm_path, SW_DOC_ASSEMBLY)
        if model is None:
            raise RuntimeError(_load_error_text(err, asm_path))
        comps = collect_components(model, [os.path.dirname(asm_path), paths.LIB_ROOT])
        emit("start", {"series": series, "assembly": asm_path, "total": len(comps)})

        parts_data = {}
        done = set()
        stats = {}
        for i, c in enumerate(comps, 1):
            step_name = ""
            status = "no_path"
            reason = ""
            if c["path"]:
                base = os.path.splitext(os.path.basename(c["path"]))[0]
                step_name = f"{base}.step"
                target = os.path.join(parts_dir, step_name)
                has_file = os.path.exists(target) and os.path.getsize(target) > 0
                if step_name in done or (has_file and not overwrite):
                    status = "skipped"
                else:
                    ok, reason = export_single_part(sw, c["path"], target)
                    if ok:
                        done.add(step_name)
                        status = "exported"
                    else:
                        status = "failed"
                stats[status] = stats.get(status, 0) + 1
            parts_data[c["name"]] = {
                "step_file": step_name,
                "original_path": c["path"],
                "transform_matrix": c["transform_matrix"],
                "suppressed": c["suppressed"],
            }
            if reason:
                parts_data[c["name"]]["reason"] = reason
            emit("component", {"index": i, "name": c["name"],
                               "status": status, "file": step_name, "reason": reason})

        shared = _move_shared_parts(parts_dir, parts_data)
        _write_outputs(series, asm_path, parts_data, shared)
        emit("done", dict(stats, shared=shared))
        return dict(stats, series=series, assembly=asm_path,
                    components=len(comps), shared=shared)
    finally:
        # 装配体是我们打开的才关,借用(用户已在 SW 中打开)的不关
        if not asm_borrowed:
            try:
                sw.CloseDoc(_doc_title(model) or os.path.splitext(os.path.basename(asm_path))[0])
            except Exception:
                pass
        pythoncom.CoUninitialize()


def main():
    import argparse
    ap = argparse.ArgumentParser(description="从 SW 装配体导出零件 STEP 到系列零件库")
    ap.add_argument("series", help="图库项目下的系列目录名,如 250折返")
    ap.add_argument("--assembly", help="装配体路径,同目录有多个装配体时必填")
    ap.add_argument("--overwrite", action="store_true", help="覆盖已存在的 STEP")

    def on_progress(event, payload):
        if event == "start":
            print(f"装配体: {payload['assembly']}")
            print(f"组件数: {payload['total']}")
        elif event == "component":
            print(f"  [{payload['index']}] {payload['name']}: {payload['status']}")
        elif event == "done":
            print(f"导出 {payload.get('exported', 0)} / "
                  f"跳过 {payload.get('skipped', 0)} / "
                  f"失败 {payload.get('failed', 0)} / "
                  f"共享件 {payload.get('shared', [])}")

    args = ap.parse_args()
    export_series(args.series, args.assembly, args.overwrite, on_progress)


if __name__ == "__main__":
    main()
