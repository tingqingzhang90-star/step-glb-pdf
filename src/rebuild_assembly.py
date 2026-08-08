# -*- coding: utf-8 -*-
"""
pythonOCC 验证脚本：250 直连装配体重建 + 缸体拉伸可行性

目标：
1. 读取 16 个零件 STEP，应用变换矩阵，合并为装配体（测速）
2. 导出装配体 STEP（测速）
3. 缸体沿轴向缩放，模拟 D1=stroke+C 拉伸（测速）
4. 装配体 GLB 导出（pythonOCC→STL→trimesh→GLB，测速）
5. 输出速度对比报告

前置条件:
    conda install -n pdf -c conda-forge pythonocc-core
    pip install trimesh numpy

运行:
    conda run -n pdf python rebuild_assembly.py
"""
import os
import sys
import json
import time
import tempfile

# ---------- 配置 ----------
# 路径相对于项目根目录 e:\分享代码\step__glb_pdf
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARTS_DIR = os.path.join(_PROJECT_ROOT, "parts_step")
MATRIX_JSON = os.path.join(_PROJECT_ROOT, "data", "parts_transform.json")
OUT_DIR = os.path.join(_PROJECT_ROOT, "output")
CYLINDER_STEP = "250缸体.step"  # 缸体零件（用于拉伸验证）

# 路径回退修复后，4 个电机/刹车件已能从装配体同目录找到并导出，无需跳过
# 若某个零件确实导出失败，可在此处添加其 step 文件名
MISSING_PARTS = set()


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def check_env():
    """检查 pythonOCC 和 trimesh 是否可用"""
    missing = []
    try:
        from OCC.Core.STEPControl import STEPControl_Reader
        from OCC.Core.TopoDS import TopoDS_Compound
        from OCC.Core.BRep import BRep_Builder
        from OCC.Core.gp import gp_Trsf, gp_XYZ, gp_GTrsf
        from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform, BRepBuilderAPI_GTransform
        from OCC.Core.IFSelect import IFSelect_RetDone
        log("✓ pythonOCC (OCC.Core) 可用")
    except ImportError as e:
        missing.append(f"pythonOCC: {e}")

    try:
        import trimesh
        import numpy
        log(f"✓ trimesh {trimesh.__version__} + numpy {numpy.__version__}")
    except ImportError as e:
        missing.append(f"trimesh/numpy: {e}")

    if missing:
        log("✗ 缺少依赖:")
        for m in missing:
            log(f"  - {m}")
        log("安装命令: conda install -n pdf -c conda-forge pythonocc-core && pip install trimesh numpy")
        return False
    return True


# ---------- 坐标系转换: SolidWorks (Y-up) → STEP/OpenCASCADE (Z-up) ----------
# SW 的 Y 轴对应 STEP 的 Z 轴, SW 的 Z 轴对应 STEP 的 -Y 轴
# 旋转矩阵 R (SW→STEP):
#   [1  0  0]
#   [0  0  1]
#   [0 -1  0]
_SW_TO_STEP_R = [
    1.0, 0.0, 0.0,
    0.0, 0.0, 1.0,
    0.0,-1.0, 0.0,
]

def _mat3_mul(A, B):
    """3x3 矩阵乘法 (行主序)"""
    C = [0.0]*9
    for i in range(3):
        for j in range(3):
            s = 0.0
            for k in range(3):
                s += A[i*3+k] * B[k*3+j]
            C[i*3+j] = s
    return C

def _vec3_mul(M, v):
    """3x3 矩阵 × 3D 向量"""
    return [
        M[0]*v[0] + M[1]*v[1] + M[2]*v[2],
        M[3]*v[0] + M[4]*v[1] + M[5]*v[2],
        M[6]*v[0] + M[7]*v[1] + M[8]*v[2],
    ]

def sw_to_step_transform(m):
    """将 SW 坐标系下的 4x4 变换矩阵转换为 STEP/OCC 坐标系
    
    输入 m (16个元素, 行主序):
        [0-8]   : 3x3 旋转矩阵 (行主序)
        [9-11]  : 平移 (tx, ty, tz)
        [12]    : 比例因子
        [13-15] : 保留
    
    转换公式:
        R_new = R_sw2step · R_old · R_sw2step^T
        t_new = R_sw2step · t_old
    """
    R = _SW_TO_STEP_R
    Rt = [  # R 的转置 = R^T
        1.0, 0.0, 0.0,
        0.0, 0.0,-1.0,
        0.0, 1.0, 0.0,
    ]
    
    # 提取原旋转矩阵和平移
    old_rot = list(m[0:9])
    old_t   = [m[9], m[10], m[11]]
    
    # R_new = R · old_rot · R^T
    tmp = _mat3_mul(R, old_rot)      # R · old_rot
    new_rot = _mat3_mul(tmp, Rt)     # (R·old_rot) · R^T
    
    # t_new = R · t_old
    new_t = _vec3_mul(R, old_t)
    
    # 组装新矩阵 (保持原格式)
    result = list(new_rot) + new_t + [m[12], m[13], m[14], m[15]]
    return result


def matrix_to_trsf(m):
    """SW MathTransform (16 doubles) → pythonOCC gp_Trsf

    SW ArrayData 格式:
        [0-8]   : 3x3 旋转矩阵（行主序）
        [9-11]  : 平移向量 (tx, ty, tz) — ★ 单位是米(m)!
        [12]    : 比例因子（通常 1.0）
        [13-15] : 保留（通常 0,0,0）

    ★ 关键: SW MathTransform 的平移单位是米, STEP 文件用毫米
             必须将平移向量 × 1000

    pythonOCC 7.9.x: gp_Trsf.SetValues(a11..a14, a21..a24, a31..a34)
    """
    from OCC.Core.gp import gp_Trsf

    trsf = gp_Trsf()
    # 平移 × 1000 (米 → 毫米)
    trsf.SetValues(
        m[0], m[1], m[2],  m[9] * 1000.0,
        m[3], m[4], m[5],  m[10] * 1000.0,
        m[6], m[7], m[8],  m[11] * 1000.0,
    )
    if abs(m[12] - 1.0) > 1e-9:
        trsf.SetScaleFactor(m[12])
    return trsf


def read_step(path):
    """读取 STEP 文件，返回 TopoDS_Shape"""
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.IFSelect import IFSelect_RetDone
    reader = STEPControl_Reader()
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"读取 STEP 失败: {path}")
    reader.TransferRoots()
    return reader.OneShape()


def write_step(shape, path):
    """导出 TopoDS_Shape 到 STEP 文件"""
    from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    writer.Write(path)


def write_stl(shape, path, linear_deflection=0.5, angular_deflection=0.5):
    """三角化 TopoDS_Shape 并导出 STL"""
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    from OCC.Core.StlAPI import StlAPI_Writer
    # 三角化
    mesh = BRepMesh_IncrementalMesh(shape, linear_deflection, False, angular_deflection)
    mesh.Perform()
    # 写 STL
    writer = StlAPI_Writer()
    writer.SetASCIIMode(False)
    writer.Write(shape, path)


def step1_read_all_parts(parts_data):
    """步骤 1: 读取所有零件 STEP"""
    log("\n=== Step 1: 读取所有零件 STEP ===")
    shapes = {}
    t0 = time.time()
    for name, info in parts_data.items():
        step_file = info.get("step_file", "")
        if not step_file or step_file in MISSING_PARTS:
            log(f"  ⏭ 跳过 {name} (缺失或无 step_file)")
            continue
        path = os.path.join(PARTS_DIR, step_file)
        if not os.path.exists(path):
            log(f"  ✗ 文件不存在: {path}")
            continue
        t1 = time.time()
        try:
            shape = read_step(path)
            shapes[name] = shape
            elapsed = time.time() - t1
            log(f"  ✓ {name} ← {step_file} ({elapsed*1000:.0f}ms)")
        except Exception as e:
            log(f"  ✗ 读取失败 {name}: {e}")
    total = time.time() - t0
    log(f"  小计: 读取 {len(shapes)} 个零件, 总耗时 {total:.2f}s")
    return shapes, total


def step2_apply_transform_and_merge(shapes, parts_data):
    """步骤 2: 应用变换矩阵 + 合并为装配体（跳过被抑制的零件）"""
    from OCC.Core.TopoDS import TopoDS_Compound
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
    log("\n=== Step 2: 应用变换矩阵 + 合并装配体 ===")
    t0 = time.time()
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    applied = 0
    suppressed_count = 0
    for name, shape in shapes.items():
        info = parts_data.get(name, {})
        # ★ 跳过被抑制的零件（SW 装配体中未激活的组件）
        if info.get("suppressed", False):
            log(f"  ⏭ {name} 被抑制，跳过")
            suppressed_count += 1
            continue
        matrix = info.get("transform_matrix")
        if not matrix:
            log(f"  ! {name} 无变换矩阵, 用原形状")
            builder.Add(compound, shape)
            applied += 1
            continue
        try:
            trsf = matrix_to_trsf(matrix)
            transform = BRepBuilderAPI_Transform(trsf)
            transform.Perform(shape, True)
            new_shape = transform.ModifiedShape(shape)
            builder.Add(compound, new_shape)
            applied += 1
        except Exception as e:
            log(f"  ✗ 变换失败 {name}: {e}")
            builder.Add(compound, shape)
    total = time.time() - t0
    log(f"  小计: 应用变换 {applied} 个, 跳过抑制 {suppressed_count} 个, 合并完成, 总耗时 {total*1000:.0f}ms")
    return compound, total


def step3_export_assembly_step(compound):
    """步骤 3: 导出装配体 STEP"""
    from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
    log("\n=== Step 3: 导出装配体 STEP ===")
    out_path = os.path.join(OUT_DIR, "250直连_assembly_rebuilt.step")
    t0 = time.time()
    writer = STEPControl_Writer()
    writer.Transfer(compound, STEPControl_AsIs)
    writer.Write(out_path)
    total = time.time() - t0
    size_mb = os.path.getsize(out_path) / 1024 / 1024
    log(f"  ✓ 导出: {out_path} ({size_mb:.2f} MB, {total:.2f}s)")
    return out_path, total


def step4_cylinder_stretch(cylinder_shape):
    """步骤 4: 缸体沿 Z 轴缩放验证（模拟 D1=stroke+C 拉伸）

    物理意义:
        缸体长度 = D1 = stroke + C
        假设原 STEP 对应 stroke=100, 新 stroke=200
        缩放因子 = (200+C) / (100+C)
    本步骤只验证 pythonOCC 能对 BRep 几何做非均匀缩放（沿 Z 轴）
    """
    from OCC.Core.gp import gp_GTrsf
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_GTransform
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_EDGE
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.GCPnts import GCPnts_AbscissaPoint
    log("\n=== Step 4: 缸体沿 Z 轴缩放验证（模拟 D1 拉伸）===")

    # 先测量缸体边界框（确定轴向和长度）
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    bbox = Bnd_Box()
    brepbndlib.Add(cylinder_shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    length_x = xmax - xmin
    length_y = ymax - ymin
    length_z = zmax - zmin
    log(f"  缸体边界框: X={length_x:.2f} Y={length_y:.2f} Z={length_z:.2f}")
    log(f"  原点: ({xmin:.2f}, {ymin:.2f}, {zmin:.2f}) → ({xmax:.2f}, {ymax:.2f}, {zmax:.2f})")

    # 假设缸体沿 Z 轴（最长边通常是缸体长度方向）
    # 如果 Z 不是最长，调整轴
    axis_idx = 2  # 0=X, 1=Y, 2=Z
    axis_name = "Z"
    max_len = max(length_x, length_y, length_z)
    if length_x == max_len:
        axis_idx, axis_name = 0, "X"
    elif length_y == max_len:
        axis_idx, axis_name = 1, "Y"
    log(f"  缸体主轴: {axis_name} (长度 {max_len:.2f})")

    # 模拟: stroke 从 100 → 200, D1 = stroke + C (C 是常数)
    # 假设 C = 100, 原 D1 = 200, 新 D1 = 300, 缩放因子 = 1.5
    scale_factor = 1.5
    log(f"  模拟: stroke 100→200, 假设 C=100, D1 200→300")
    log(f"  沿 {axis_name} 轴缩放因子 = {scale_factor}")

    # 构造非均匀缩放变换（仅沿主轴缩放）
    gtrsf = gp_GTrsf()
    # 初始化为单位矩阵
    for i in range(1, 4):
        for j in range(1, 4):
            gtrsf.SetValue(i, j, 1.0 if i == j else 0.0)
        gtrsf.SetValue(i, 4, 0.0)  # 平移列
    # 沿主轴缩放
    gtrsf.SetValue(axis_idx + 1, axis_idx + 1, scale_factor)

    t0 = time.time()
    transform = BRepBuilderAPI_GTransform(gtrsf)
    transform.Perform(cylinder_shape, True)
    new_shape = transform.ModifiedShape(cylinder_shape)
    elapsed = time.time() - t0
    log(f"  ✓ 缸体缩放完成 ({elapsed*1000:.0f}ms)")

    # 验证新边界框
    new_bbox = Bnd_Box()
    brepbndlib.Add(new_shape, new_bbox)
    nxmin, nymin, nzmin, nxmax, nymax, nzmax = new_bbox.Get()
    log(f"  缩放后边界框: X={nxmax-nxmin:.2f} Y={nymax-nymin:.2f} Z={nzmax-nzmin:.2f}")
    new_axis_len = [nxmax-nxmin, nymax-nymin, nzmax-nzmin][axis_idx]
    log(f"  主轴长度: {max_len:.2f} → {new_axis_len:.2f} (期望 {max_len*scale_factor:.2f})")

    # 导出验证
    out_path = os.path.join(OUT_DIR, "250缸体_stretched.step")
    t1 = time.time()
    write_step(new_shape, out_path)
    log(f"  ✓ 导出: {out_path} ({time.time()-t1:.2f}s)")
    return out_path, elapsed


def step5_export_glb(compound):
    """步骤 5: 装配体 GLB 导出 (pythonOCC → STL → trimesh → GLB)"""
    log("\n=== Step 5: 装配体 GLB 导出 ===")
    import trimesh
    stl_path = os.path.join(tempfile.gettempdir(), "assembly_tmp.stl")
    glb_path = os.path.join(OUT_DIR, "250直连_assembly.glb")

    # 5.1 三角化 + STL 导出
    t0 = time.time()
    write_stl(compound, stl_path, linear_deflection=0.5, angular_deflection=0.5)
    t_stl = time.time() - t0
    stl_size_mb = os.path.getsize(stl_path) / 1024 / 1024
    log(f"  ✓ STL 中转: {stl_path} ({stl_size_mb:.2f} MB, {t_stl:.2f}s)")

    # 5.2 trimesh → GLB
    t1 = time.time()
    mesh = trimesh.load(stl_path, file_type="stl")
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.dump(concatenate=True)
    mesh.export(glb_path, file_type="glb")
    t_glb = time.time() - t1
    glb_size_mb = os.path.getsize(glb_path) / 1024 / 1024
    log(f"  ✓ GLB 导出: {glb_path} ({glb_size_mb:.2f} MB, {t_glb:.2f}s)")

    # 清理 STL
    try:
        os.remove(stl_path)
    except Exception:
        pass

    return glb_path, t_stl + t_glb


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    log("=" * 60)
    log("pythonOCC 验证: 250 直连装配体重建 + 缸体拉伸")
    log("=" * 60)

    if not check_env():
        sys.exit(1)

    # 加载变换矩阵
    with open(MATRIX_JSON, "r", encoding="utf-8") as f:
        parts_data = json.load(f)
    log(f"\n加载变换矩阵: {len(parts_data)} 个组件")

    # Step 1: 读取所有 STEP
    shapes, t_read = step1_read_all_parts(parts_data)

    # Step 2: 应用变换 + 合并
    compound, t_merge = step2_apply_transform_and_merge(shapes, parts_data)

    # Step 3: 导出装配体 STEP
    asm_step, t_step = step3_export_assembly_step(compound)

    # Step 4: 缸体拉伸验证
    cylinder_path = os.path.join(PARTS_DIR, CYLINDER_STEP)
    if os.path.exists(cylinder_path):
        cylinder_shape = read_step(cylinder_path)
        _, t_stretch = step4_cylinder_stretch(cylinder_shape)
    else:
        log(f"\n跳过 Step 4: 缸体 STEP 不存在 {cylinder_path}")
        t_stretch = 0

    # Step 5: GLB 导出
    glb_path, t_glb = step5_export_glb(compound)

    # 速度汇总
    total = t_read + t_merge + t_step + t_stretch + t_glb
    log("\n" + "=" * 60)
    log("速度汇总")
    log("=" * 60)
    log(f"  Step 1 读取所有 STEP      : {t_read:.2f}s")
    log(f"  Step 2 应用变换+合并       : {t_merge*1000:.0f}ms")
    log(f"  Step 3 导出装配体 STEP    : {t_step:.2f}s")
    log(f"  Step 4 缸体拉伸           : {t_stretch*1000:.0f}ms")
    log(f"  Step 5 GLB 导出           : {t_glb:.2f}s")
    log(f"  -----------------------------")
    log(f"  总耗时                    : {total:.2f}s")
    log("")
    log("对比原方案 (SW COM + 沙箱):")
    log("  原方案 worker 总耗时: ~55s (STEP 16MB + GLB + PDF)")
    log("  原方案主要瓶颈: SW COM (apply_config + SaveAs + 工程图)")
    log("")
    log("说明:")
    log("  - 本脚本未含 PDF 生成 (PDF 仍依赖 SW 工程图, 是剩余瓶颈)")
    log("  - 缸体拉伸用 Z 轴缩放近似, 真正特征参数化需 SW 离线预生成离散库")
    log("  - 4 个电机/刹车件缺失, 实际装配体为 16 个零件")
    log("  - pythonOCC 方案优势: 不依赖 SW, 可多进程并发, 适合多用户")


if __name__ == "__main__":
    main()
