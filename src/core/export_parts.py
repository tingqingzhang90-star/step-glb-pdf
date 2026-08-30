# -*- coding: utf-8 -*-
"""
SW 批量导出脚本：从装配体导出所有零件 STEP AP214 + 变换矩阵
目标：250 直连系列

修正点:
1. 避免重复导出同名零件（用 step_name 去重）
2. Transform2 可能为 None（被抑制的组件），需要处理
3. STEP AP214 设置: SetUserPreferenceIntegerValue(75, 2)
   - swUserPreferenceIntegerValue_e.swStepAP = 75（不是 15）
   - swStepAPVersion_e.swStepAP214 = 2（不是 214）
4. 用 Extension.SaveAs（6 参数）导出 STEP，options=0，ExportData=Nothing(VT_DISPATCH)
   - 用 SaveAs3 或 Silent 标志会触发 DISP_E_TYPEMISMATCH
5. 增加错误恢复和日志
6. 同名零件多次出现时（如多个螺母），step_file 保持唯一但 transform 独立记录
"""
import os
import json
import time
import sys
import win32com.client
import pythoncom

# 配置
# 项目根目录(本文件位于 src/core/,需上溯三级: core → src → 项目根)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
# 输入：装配体原文件（保持在原位置，不移动）
ASSEMBLY_PATH = r"E:\分享代码\pdf修改\图库项目\250直连\250直连装配体.SLDASM"
# 输出：所有产出统一到 step__glb_pdf 工作目录
OUTPUT_DIR = os.path.join(_PROJECT_ROOT, "parts_step")
MATRIX_JSON = os.path.join(_PROJECT_ROOT, "data", "parts_transform.json")
LOG_FILE = os.path.join(_PROJECT_ROOT, "logs", "parts_export.log")

# 零件路径回退搜索目录（当装配体引用的路径失效时，按 basename 在这些目录找本机文件）
# 优先级从上到下
PART_SEARCH_DIRS = [
    os.path.dirname(ASSEMBLY_PATH),                  # 装配体所在目录
    r"E:\图库项目\250直连",                           # 其他零件的引用路径
    r"E:\图库项目",                                   # 图库根（按系列名子目录）
    r"E:\分享代码\pdf修改\图库项目",                   # 项目图库根
]

# SW 常量
swDocPART = 1
swDocASSEMBLY = 2
SW_OPEN_DOC_OPTIONS_SILENT = 1
SW_SAVE_AS_CURRENT_VERSION = 0
# 非 PDF 导出必须用 options=0，用 Silent(=1) 会触发 DISP_E_TYPEMISMATCH
# 参考 app/sw_com.py 的 export_file 方法注释
SW_SAVE_AS_OPTIONS_NONE = 0
# swUserPreferenceIntegerValue_e.swStepAP = 75（不是 15！）
SW_USER_PREF_STEP_AP = 75
# swStepAPVersion_e: swStepAP203=1, swStepAP214=2, swStepAP242=3（不是 214！）
SW_STEP_VERSION_AP214 = 2


def make_out_int():
    """创建 SW COM 需要的 byref int VARIANT（用于 errors/warnings 输出参数）"""
    return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)


def make_nothing():
    """构造 COM Nothing (VT_DISPATCH + None)，用于 ExportData 参数。
    非 PDF 导出必须传 Nothing，传 None 会被识别为 VT_EMPTY 触发类型不匹配。
    """
    return win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)


def resolve_part_path(part_path):
    """零件路径回退搜索。

    装配体里记录的引用路径可能是设计电脑的路径（如 C:\\Users\\Administrator\\Desktop\\...），
    本机不存在。此时提取 basename，在候选目录里搜索本机文件。

    返回本机存在的路径；若都找不到，返回原路径（让后续报错）。
    """
    if part_path and os.path.exists(part_path):
        return part_path
    if not part_path:
        return part_path
    basename = os.path.basename(part_path)
    for d in PART_SEARCH_DIRS:
        if not d or not os.path.isdir(d):
            continue
        # 1. 直接在目录下找
        candidate = os.path.join(d, basename)
        if os.path.exists(candidate):
            return candidate
        # 2. 递归在子目录找（最多 2 层，避免太慢）
        for root, dirs, files in os.walk(d):
            # 限制深度
            depth = root[len(d):].count(os.sep)
            if depth >= 2:
                dirs[:] = []
                continue
            if basename in files:
                return os.path.join(root, basename)
    return part_path  # 找不到，返回原路径


def log(msg):
    """带时间戳的日志"""
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_transform_matrix(comp):
    """安全提取变换矩阵。返回 None 表示组件被抑制或无变换。"""
    try:
        xform = comp.Transform2
        if xform is None:
            return None
        # MathTransform 的 ArrayData 是 16 个 double（4x4 齐次矩阵）
        # ★ 旋转矩阵[0-8]实际为列主序存储(转置后才是"零件→装配体"变换)
        #   在 rebuild_assembly.py 的 matrix_to_trsf 中已做转置处理
        arr = xform.ArrayData
        if arr is None or len(arr) < 16:
            return None
        # 转为普通 list 方便 JSON 序列化
        return [float(arr[i]) for i in range(16)]
    except Exception as e:
        log(f"  ! 读取变换矩阵失败: {e}")
        return None


def export_single_part(sw, part_path, step_output):
    """打开单个零件并导出 STEP AP214。返回 True/False。"""
    if not os.path.exists(part_path):
        log(f"  ✗ 零件文件不存在: {part_path}")
        return False

    part_name = os.path.basename(part_path)

    # 打开零件（如果已打开则激活）
    errors = make_out_int()
    warnings = make_out_int()
    # OpenDoc6(filename, docType, options, configName, errors, warnings)
    part_doc = sw.OpenDoc6(part_path, swDocPART, SW_OPEN_DOC_OPTIONS_SILENT, "", errors, warnings)
    if part_doc is None:
        log(f"  ✗ 打开零件失败: errors={errors.value}, warnings={warnings.value}")
        return False

    # 设置 AP214 格式（注意 id=75 不是 15，值=2 不是 214）
    sw.SetUserPreferenceIntegerValue(SW_USER_PREF_STEP_AP, SW_STEP_VERSION_AP214)
    sw.SetUserPreferenceToggle(33, True)  # 导出外观
    sw.SetUserPreferenceToggle(34, True)  # 导出面/边属性

    # 强制重建确保几何最新
    try:
        part_doc.ForceRebuild3(False)
    except Exception:
        pass

    # 导出 STEP —— 使用 Extension.SaveAs（6 参数），options=0，ExportData=Nothing
    # 参考 app/sw_com.py 的 export_file：用 Silent 对非 PDF 导出会触发类型不匹配
    err2 = make_out_int()
    warn2 = make_out_int()
    export_data = make_nothing()
    try:
        result = part_doc.Extension.SaveAs(
            step_output,
            SW_SAVE_AS_CURRENT_VERSION,
            SW_SAVE_AS_OPTIONS_NONE,
            export_data,
            err2,
            warn2,
        )
    except Exception as exc:
        log(f"  ✗ SaveAs 异常: {exc}")
        try:
            sw.CloseDoc(part_name)
        except Exception:
            pass
        return False

    # 关闭零件（失败不影响导出结果）
    try:
        sw.CloseDoc(part_name)
    except Exception:
        pass

    if result:
        try:
            size_mb = os.path.getsize(step_output) / 1024 / 1024
            log(f"  ✓ 导出成功: {os.path.basename(step_output)} ({size_mb:.2f} MB)")
            return True
        except OSError:
            log(f"  ✓ 导出返回成功但文件不存在: {step_output}")
            return False
    else:
        log(f"  ✗ 导出失败: errors={err2.value}, warnings={warn2.value}")
        return False


def export_parts():
    pythoncom.CoInitialize()
    # 确保日志目录存在
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    # 清空日志
    try:
        open(LOG_FILE, "w", encoding="utf-8").close()
    except Exception:
        pass

    try:
        log("连接 SolidWorks...")
        sw = win32com.client.Dispatch("SldWorks.Application")
        sw.Visible = False

        # 打开装配体
        log(f"打开装配体: {ASSEMBLY_PATH}")
        errors = make_out_int()
        warnings = make_out_int()
        # OpenDoc6(filename, docType, options, configName, errors, warnings)
        # options: swOpenDocOptions_Silent = 1
        model = sw.OpenDoc6(ASSEMBLY_PATH, swDocASSEMBLY, SW_OPEN_DOC_OPTIONS_SILENT, "", errors, warnings)
        if model is None:
            log(f"打开装配体失败: errors={errors.value}, warnings={warnings.value}")
            return

        asm = model
        # ★ 不要 ForceRebuild3！它会解除零件的抑制状态
        # 获取所有组件（True = 只获取顶层，False = 递归获取所有）
        components = asm.GetComponents(False)
        comp_count = len(components) if components else 0
        log(f"找到 {comp_count} 个组件")

        # ★ 在任何可能改变状态的操作之前，先读取所有组件的抑制状态
        # 打开零件文档等操作会导致 SW 重新解析装配体，解除抑制状态
        comp_states = []
        for i in range(comp_count):
            comp = components[i]
            name = comp.Name2
            try:
                part_path = comp.GetPathName
            except Exception:
                try:
                    part_path = comp.GetPathName()
                except Exception:
                    part_path = ""
            # 路径回退搜索
            if part_path and not os.path.exists(part_path):
                resolved = resolve_part_path(part_path)
                if resolved != part_path:
                    part_path = resolved

            # 检测抑制状态（IsSuppressed 是属性不是方法！）
            is_suppressed = False
            try:
                # IsSuppressed 是属性，不加括号
                is_suppressed = bool(comp.IsSuppressed)
            except Exception as e1:
                log(f"    IsSuppressed 属性访问失败: {e1}")
                try:
                    # 备选: GetSuppressionState — 也是属性
                    state = comp.GetSuppressionState
                    # swComponentSuppressed = 0
                    is_suppressed = (state == 0)
                except Exception as e2:
                    log(f"    GetSuppressionState 也失败: {e2}")

            comp_states.append({
                "name": name,
                "path": part_path,
                "suppressed": is_suppressed,
            })
            log(f"[{i+1}/{comp_count}] {name} — 抑制: {is_suppressed}")

        log(f"\n抑制状态读取完成，开始导出 STEP...")

        os.makedirs(OUTPUT_DIR, exist_ok=True)

        parts_data = {}
        exported_steps = set()  # 记录已导出的 step_name，避免重复
        success_count = 0
        fail_count = 0
        skip_count = 0

        for i in range(comp_count):
            comp = components[i]
            name = comp_states[i]["name"]
            part_path = comp_states[i]["path"]
            is_suppressed = comp_states[i]["suppressed"]
            log(f"\n[{i+1}/{comp_count}] 处理: {name}")

            # 获取变换矩阵
            matrix = get_transform_matrix(comp)
            if matrix is None:
                log(f"  ! 无变换矩阵（可能被抑制），跳过导出但记录占位")
            else:
                log(f"  变换矩阵前4项: {matrix[:4]}")

            log(f"  零件路径: {part_path}")
            log(f"  抑制状态: {is_suppressed}")

            # 导出 STEP（只在第一次遇到该零件时导出，避免重复）
            step_name = ""
            if part_path:
                base_name = os.path.splitext(os.path.basename(part_path))[0]
                step_name = f"{base_name}.step"
                step_output = os.path.join(OUTPUT_DIR, step_name)

                if step_name in exported_steps:
                    log(f"  ⏭ 已导过同名零件，跳过重复导出")
                    skip_count += 1
                elif os.path.exists(step_output) and os.path.getsize(step_output) > 0:
                    # 重跑时跳过已存在的 STEP 文件（节省时间，只导出缺失的）
                    log(f"  ⏭ STEP 已存在 ({os.path.getsize(step_output)/1024:.0f}KB)，跳过")
                    exported_steps.add(step_name)
                    skip_count += 1
                else:
                    if matrix is not None and not is_suppressed:
                        ok = export_single_part(sw, part_path, step_output)
                        if ok:
                            exported_steps.add(step_name)
                            success_count += 1
                        else:
                            fail_count += 1
                    else:
                        # 被抑制的零件也尝试导出（因为我们要做"全量零件库"）
                        ok = export_single_part(sw, part_path, step_output)
                        if ok:
                            exported_steps.add(step_name)
                            success_count += 1
                        else:
                            fail_count += 1

            # 记录数据（每个组件实例独立记录，包含独立变换矩阵）
            parts_data[name] = {
                "step_file": step_name,
                "original_path": part_path,
                "transform_matrix": matrix,
                "suppressed": is_suppressed,
            }

        # 保存变换矩阵 JSON
        with open(MATRIX_JSON, "w", encoding="utf-8") as f:
            json.dump(parts_data, f, ensure_ascii=False, indent=2)
        log(f"\n✓ 变换矩阵已保存: {MATRIX_JSON}")
        log(f"  组件总数: {comp_count}")
        log(f"  导出成功: {success_count}")
        log(f"  导出失败: {fail_count}")
        log(f"  跳过重复: {skip_count}")

        # 关闭装配体
        try:
            sw.CloseDoc(os.path.basename(ASSEMBLY_PATH))
        except Exception:
            pass
        log("\n完成!")

    except Exception as e:
        log(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    export_parts()
