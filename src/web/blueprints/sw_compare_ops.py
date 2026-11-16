# -*- coding: utf-8 -*-
"""SolidWorks COM 选型操作

把 SW COM 调用集中在此(函数内才 import pythoncom / win32com.client,
因此 import 本模块不会触碰 COM,无 SW 环境也能正常导入)。
被 web/blueprints/sw_compare.py 调用。
"""
import os
import time

from core.paths import LIB_ROOT
from core.rebuild_assembly import (
    parse_model_code, resolve_visibility, load_config,
    compute_cylinder_scale, MOTOR_CODES, _KEY_RE,
)

# SW COM 常量
SW_DOC_ASSEMBLY = 2
SW_OPEN_SILENT = 1
SW_SUPPRESSED = 0    # swComponentSuppressed
SW_RESOLVED = 2      # swComponentResolved

# 装配体根目录:统一取 core.paths 的图库路径,不再自行上溯拼绝对路径
# (旧实现按 dirname(_PROJECT_ROOT)/pdf修改/图库项目 拼,迁到 src 包结构后层级错位,
#  两个候选目录都不存在,OpenDoc6 返回 errors=2)
ASSEMBLY_LIB = LIB_ROOT


def _find_assembly(series_name):
    """按约定查找系列装配体: <LIB_ROOT>/<series>/<series>装配体.SLDASM"""
    cand = os.path.join(ASSEMBLY_LIB, series_name, f"{series_name}装配体.SLDASM")
    if os.path.exists(cand):
        return cand
    d = os.path.join(ASSEMBLY_LIB, series_name)
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if (f.upper().endswith(".SLDASM")
                    and not f.startswith("~$")
                    and "ce" not in f and "_parallel" not in f):
                return os.path.join(d, f)
    return cand


def _make_byref_int():
    import pythoncom
    import win32com.client
    return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)


def _resolve_selection(model_code, motor, series_name):
    """型号 → 系列 / 可见性表 / 缸体 D1 与缩放,纯计算不触碰 COM"""
    params = parse_model_code(model_code)
    motor_name = params["motor"] or motor or "11kw电机"
    if series_name is None:
        series_name = f"{params['series']}直连"
    config = load_config(series_name)
    visibility = resolve_visibility(config, params["mount"], params["load"], motor_name)
    cyl_info = compute_cylinder_scale(config, params["stroke"])
    return {
        "series": series_name, "motor_name": motor_name, "config": config,
        "visibility": visibility,
        "d1": cyl_info[1] if cyl_info else None,
        "scale": cyl_info[2] if cyl_info else None,
        "cylinder_part": config.get("cylinder_part"),
    }


def _open_assembly(sw, asm_path):
    """重新打开装配体文档(每次选型都重开,确保干净状态)

    失败返回 (None, 错误信息),成功返回 (model, None)。
    """
    if not os.path.exists(asm_path):
        return None, f"装配体文件不存在: {asm_path}"
    asm_name = os.path.basename(asm_path)
    try:
        sw.CloseDoc(asm_name)
    except Exception:
        pass
    time.sleep(0.5)
    errors = _make_byref_int()
    warnings = _make_byref_int()
    model = sw.OpenDoc6(asm_path, SW_DOC_ASSEMBLY, SW_OPEN_SILENT, "",
                        errors, warnings)
    if model is None:
        return None, f"打开装配体失败(errors={errors.value})"
    try:
        model.ResolveAllLightWeightComponents(False)
    except Exception:
        pass
    return model, None


def _apply_suppression(components, visibility):
    """按可见性表设置组件抑制状态,返回 (详情列表, 计数)"""
    details = []
    counts = {"resolved": 0, "suppressed": 0, "errors": 0}
    for i, comp in enumerate(components or []):
        try:
            raw_name = comp.Name2
        except Exception:
            raw_name = f"<组件{i}>"
        name = str(raw_name).split("@")[0]
        m = _KEY_RE.match(name)
        base = m.group(1) if m else name
        should_show = visibility.get(base, True)
        try:
            # 用 SetSuppression2 而非 SetSuppressionState(后者静默失败)
            if should_show:
                comp.SetSuppression2(SW_RESOLVED)
                counts["resolved"] += 1
                state = "显示"
            else:
                comp.SetSuppression2(SW_SUPPRESSED)
                counts["suppressed"] += 1
                state = "抑制"
        except Exception as e:
            counts["errors"] += 1
            state = f"错误: {e}"
        details.append({"name": name, "base": base, "state": state})
    return details, counts


def _set_cylinder_d1(part_doc, d1_mm, part_label=""):
    """通过零件尺寸参数修改缸体 D1(参考 PythonServer/toolkit/cylinder_d1.py)

    1. 优先尝试硬编码 D1@凸台-拉伸1(160 系列)
    2. 失败后枚举零件参数找第一个 D1@*
    返回 (是否成功, 消息)
    """
    label = f" ({part_label})" if part_label else ""
    try:
        param = part_doc.Parameter("D1@凸台-拉伸1")
        param.SetSystemValue3(d1_mm / 1000.0, 2, "")  # 2=米制,值用米
        return True, f"D1={d1_mm}mm @ 凸台-拉伸1{label}"
    except Exception:
        pass
    try:
        cnt = int(part_doc.GetParameterCount())
        for i in range(cnt):
            try:
                p = part_doc.GetParameter(i)
                name = str(p.Name)
                if name.startswith("D1@"):
                    p.SetSystemValue3(d1_mm / 1000.0, 2, "")
                    return True, f"D1={d1_mm}mm @ {name}{label}"
            except Exception:
                continue
    except Exception:
        pass
    msg = f"未找到 D1@ 尺寸参数{label}(需手动改缸体尺寸)"
    try:
        sample = []
        if hasattr(part_doc, "GetParameterCount"):
            cnt2 = int(part_doc.GetParameterCount())
            for i in range(min(cnt2, 20)):
                try:
                    sample.append(str(part_doc.GetParameter(i).Name))
                except Exception:
                    pass
        if sample:
            msg += f"; param_sample={sample}"
    except Exception:
        pass
    return False, msg


def _get_model_doc2_robust(sw_app, comp):
    """获取组件的零件文档,带轻量化 fallback(参考 sw_com.Component.get_model_doc2)

    1. 优先 comp.GetModelDoc2()
    2. 轻量化返回 None 时:SetComponentState(FULLY_RESOLVED) → GetPathName
       → OpenDoc6 重新打开零件文档返回。

    背景:SolidWorks 默认以轻量化方式打开装配体组件,此时 GetModelDoc2()
    返回 null/不完整对象,对其调用 Parameter() 会报 DISP_E_MEMBERNOTFOUND
    "找不到成员"。必须强制 fully-resolve 后用 OpenDoc6 重开零件,才能拿到
    完整的 IPartDoc,使 Parameter()/GetParameter() 可用。

    返回:零件文档 IDispatch 或 None。
    """
    SW_DOC_PART = 1
    SW_OPEN_SILENT = 1
    SW_COMPONENT_FULLY_RESOLVED = 2
    try:
        md = comp.GetModelDoc2
        doc = md() if callable(md) else md
        if doc is not None:
            return doc
    except Exception:
        pass
    try:
        comp.SetComponentState(SW_COMPONENT_FULLY_RESOLVED)
    except Exception:
        pass
    try:
        gp = comp.GetPathName
        path = gp() if callable(gp) else gp
    except Exception:
        path = None
    if not path:
        return None
    try:
        errors = _make_byref_int()
        warnings = _make_byref_int()
        opened = sw_app.OpenDoc6(path, SW_DOC_PART, SW_OPEN_SILENT, "", errors, warnings)
        return opened
    except Exception:
        return None


def _update_cylinder_d1(sw, components, cylinder_part, d1):
    """缸体已 resolved 后改 D1 尺寸参数,返回提示消息"""
    cyl_msg = ""
    try:
        for c in components:
            cn = str(c.Name2 or "").split("@")[0]
            if cn == cylinder_part or cn.startswith(cylinder_part + "-"):
                part_doc = _get_model_doc2_robust(sw, c)
                if part_doc is not None:
                    _, cyl_msg = _set_cylinder_d1(part_doc, d1, cn)
                break
    except Exception as e:
        cyl_msg = f"缸体 D1 修改异常: {e}"
    return cyl_msg


def _build_result(model_code, sel, asm_path, cyl_msg, total, counts, details):
    """组装返回给前端的结果(纯数据,不触碰 COM)"""
    return {
        "ok": True, "model_code": model_code, "motor": sel["motor_name"],
        "series": sel["series"], "assembly": asm_path, "d1": sel["d1"],
        "scale": round(sel["scale"], 3) if sel["scale"] else None,
        "cyl_msg": cyl_msg, "total": total,
        "resolved": counts["resolved"], "suppressed": counts["suppressed"],
        "errors": counts["errors"], "details": details,
        "elapsed_hint": "SW 窗口已打开,请切换到 SolidWorks 查看装配体",
    }


def sw_apply_selection(model_code, motor=None, series_name=None):
    """在 SW 中重新打开装配体并应用选型(抑制/取消抑制)

    COM 调用顺序敏感,编排保持:打开 → 进编辑模式 → 抑制 → 重建
    → 改缸体 D1 → 强制重建。每次都重新打开文件,确保干净状态。
    """
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        sel = _resolve_selection(model_code, motor, series_name)
        sw = win32com.client.Dispatch("SldWorks.Application")
        sw.Visible = True

        asm_path = _find_assembly(sel["series"])
        model, err = _open_assembly(sw, asm_path)
        if model is None:
            return {"ok": False, "error": err}

        components = model.GetComponents(False) or []
        # 必须先 EditAssembly() 进入编辑装配体模式,否则 SetSuppression2 会静默失败
        try:
            model.EditAssembly()
        except Exception:
            pass
        details, counts = _apply_suppression(components, sel["visibility"])
        # SetSuppression2 后必须 EditRebuild3() 才能生效
        try:
            model.EditRebuild3()
        except Exception:
            pass

        cyl_msg = ""
        if sel["d1"] and sel["cylinder_part"]:
            cyl_msg = _update_cylinder_d1(
                sw, components, sel["cylinder_part"], sel["d1"])
        try:
            model.ForceRebuild3(False)
        except Exception:
            pass

        # 不关闭装配体,让用户在 SW 中查看
        return _build_result(model_code, sel, asm_path, cyl_msg,
                             len(components), counts, details)
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()}
    finally:
        pythoncom.CoUninitialize()
