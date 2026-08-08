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
import re
import json
import time
import tempfile

# ---------- 配置 ----------
# 路径相对于项目根目录 e:\分享代码\step__glb_pdf
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARTS_DIR = os.path.join(_PROJECT_ROOT, "parts_step")
MATRIX_JSON = os.path.join(_PROJECT_ROOT, "data", "parts_transform.json")
CONFIG_DIR = os.path.join(_PROJECT_ROOT, "data", "configs")
OUT_DIR = os.path.join(_PROJECT_ROOT, "output")
CYLINDER_STEP = "250缸体.step"  # 缸体零件（用于拉伸验证）

# 路径回退修复后，4 个电机/刹车件已能从装配体同目录找到并导出，无需跳过
# 若某个零件确实导出失败，可在此处添加其 step 文件名
MISSING_PARTS = set()

# 电机编号映射 (D=电机, 功率去小数点, B=刹车)
MOTOR_CODES = {
    "D11":  "11kw电机",
    "D55":  "5.5KW电机",
    "D55B": "5.5KW刹车电机",
    "D75":  "7.5kw电机",
    "D75B": "7.5kw电机刹车",
}
# 默认选型参数 (电机已纳入型号: 系列-类型-H*K*-行程-电机编号)
DEFAULT_MODEL_CODE = "250-E-H2K1-L100-D11"
DEFAULT_MOTOR = "11kw电机"


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


# ---------- 选型装配:型号解析 + 配置驱动显隐 + 缸体拉伸 ----------
_KEY_RE = re.compile(r"^(.+)-(\d+)$")  # "250前盖-1" → 基础名"250前盖"
_HK_RE = re.compile(r"H(\d)K(\d)")      # "H2K1" → mount=H2, load=K1


def parse_model_code(code):
    """解析型号编码 → 选型参数

    例: "250-E-H2K1-L100-D11" → {series:250, type:E, mount:H2, load:K1, stroke:L100, motor:11kw电机}
    结构: 系列-连接类型-(安装方式+负载连接)-行程-[电机编号]
    行程可能是 L100 或纯数字(100),统一归一为 L100 形式
    电机编号可选(D11/D55/D55B/D75/D75B),不填则 motor=None(回退 --motor 参数)
    """
    parts = code.split("-")
    if len(parts) < 4:
        raise ValueError(f"型号格式错误(需 系列-类型-H*K*-行程[-电机]): {code}")
    series = parts[0]
    conn_type = parts[1]
    hk = parts[2]
    stroke_raw = parts[3]
    m = _HK_RE.search(hk)
    if not m:
        raise ValueError(f"型号中 H*K* 段解析失败: {hk}")
    mount = "H" + m.group(1)
    load = "K" + m.group(2)
    # 行程归一:L100 → L100; 100 → L100
    if re.match(r"^\d+$", stroke_raw):
        stroke = "L" + stroke_raw
    else:
        stroke = stroke_raw
    # 电机编号(可选,第5段)
    motor_code = parts[4] if len(parts) >= 5 else None
    motor = MOTOR_CODES.get(motor_code) if motor_code else None
    if motor_code and not motor:
        raise ValueError(f"未知电机编号: {motor_code} (可选: {', '.join(MOTOR_CODES)})")
    return {"series": series, "type": conn_type, "mount": mount,
            "load": load, "stroke": stroke,
            "motor_code": motor_code, "motor": motor}


def load_config(series_name):
    """加载系列配置 JSON(由 build_config.py 生成)"""
    path = os.path.join(CONFIG_DIR, f"{series_name}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_visibility(config, mount, load, motor):
    """根据选型参数计算每个零件基础名的显隐(True=显示)

    逻辑:常显件(base_parts)恒显示;安装方式/负载/电机表的
    OnFeature 显示、OffFeature 抑制。on 优先于 off(同零件不会跨表冲突)。
    """
    visible = {}
    for n in config.get("base_parts", []):
        visible[n] = True
    # 先收集 off,再 on 覆盖(on 优先显示)
    for spec in (config.get("mount", {}).get(mount, {}),
                 config.get("load", {}).get(load, {}),
                 config.get("motor", {}).get(motor, {})):
        for n in spec.get("off", []):
            visible[n] = False
        for n in spec.get("on", []):
            visible[n] = True
    return visible


def apply_selection(parts_data, visibility):
    """将选型显隐应用到 parts_data,覆盖 suppressed 字段

    未出现在 visibility 中的零件(既非 base 也非受控)默认显示。
    返回 (显示数, 抑制数)。
    """
    shown = 0
    hidden = 0
    for key, info in parts_data.items():
        m = _KEY_RE.match(key)
        base = m.group(1) if m else key
        is_on = visibility.get(base, True)
        info["suppressed"] = not is_on
        if is_on:
            shown += 1
        else:
            hidden += 1
    return shown, hidden


def compute_cylinder_scale(config, stroke):
    """计算缸体拉伸参数: D1 = stroke + C, scale = D1 / base_D1

    返回 (stroke_num, D1, scale) 或 None(无缸体配置)
    """
    cyl = config.get("cylinder") or {}
    if not cyl:
        return None
    m = re.match(r"^L?(\d+)$", stroke)
    if not m:
        raise ValueError(f"行程格式错误: {stroke}")
    stroke_num = int(m.group(1))
    c = cyl.get("C")
    base_d1 = cyl.get("base_D1")
    if c is None or base_d1 is None:
        # 回退:查表
        table = cyl.get("table", {})
        if stroke in table:
            d1 = table[stroke]
            return stroke_num, d1, d1 / base_d1 if base_d1 else 1.0
        raise ValueError(f"无法计算缸体 D1(stroke={stroke})")
    d1 = stroke_num + c
    return stroke_num, d1, d1 / base_d1


def stretch_shape_axis(shape, axis_idx, scale):
    """沿指定轴(axis_idx: 0=X,1=Y,2=Z)非均匀缩放 shape"""
    from OCC.Core.gp import gp_GTrsf
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_GTransform
    gtrsf = gp_GTrsf()
    for i in range(1, 4):
        for j in range(1, 4):
            gtrsf.SetValue(i, j, 1.0 if i == j else 0.0)
        gtrsf.SetValue(i, 4, 0.0)
    gtrsf.SetValue(axis_idx + 1, axis_idx + 1, scale)
    tr = BRepBuilderAPI_GTransform(gtrsf)
    tr.Perform(shape, True)
    return tr.ModifiedShape(shape)


def shape_bbox(shape):
    """返回 shape 的包围盒 (xmin,ymin,zmin,xmax,ymax,zmax)"""
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    bbox = Bnd_Box()
    brepbndlib.Add(shape, bbox)
    return bbox.Get()


def find_cylinder_axis(shape):
    """根据包围盒最长边确定缸体主轴索引(0=X,1=Y,2=Z)"""
    xmin, ymin, zmin, xmax, ymax, zmax = shape_bbox(shape)
    lens = [xmax - xmin, ymax - ymin, zmax - zmin]
    return lens.index(max(lens))


def read_step(path):
    """读取 STEP 文件，返回 TopoDS_Shape（带 BRep 缓存）

    首次读取 STEP 后缓存为 .brep 二进制文件，后续直接读 .brep（快 10-100x）
    """
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.BRepTools import breptools_Read, breptools_Write
    from OCC.Core.TopoDS import TopoDS_Shape
    from OCC.Core.BRep import BRep_Builder

    # 尝试读取 BRep 缓存
    brep_path = path.rsplit(".", 1)[0] + ".brep"
    if os.path.exists(brep_path):
        try:
            shape = TopoDS_Shape()
            builder = BRep_Builder()
            breptools_Read(shape, brep_path, builder)
            if not shape.IsNull():
                return shape
        except Exception:
            pass  # 缓存损坏，回退到 STEP

    # 读取 STEP
    reader = STEPControl_Reader()
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"读取 STEP 失败: {path}")
    reader.TransferRoots()
    shape = reader.OneShape()

    # 写入 BRep 缓存
    try:
        breptools_Write(shape, brep_path)
    except Exception:
        pass  # 缓存写入失败不影响主流程

    return shape


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
    """步骤 1: 读取零件 STEP（跳过被抑制的零件，避免无谓 IO）"""
    log("\n=== Step 1: 读取零件 STEP ===")
    shapes = {}
    t0 = time.time()
    skipped_suppressed = 0
    for name, info in parts_data.items():
        # ★ 先检查抑制状态，被抑制的零件不需要读取（省 9s+）
        if info.get("suppressed", False):
            skipped_suppressed += 1
            continue
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
    log(f"  小计: 读取 {len(shapes)} 个, 跳过抑制 {skipped_suppressed} 个, 总耗时 {total:.2f}s")
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


def step3_export_assembly_step(compound, out_name):
    """步骤 3: 导出装配体 STEP(文件名由调用方指定,避免覆盖)"""
    from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
    log("\n=== Step 3: 导出装配体 STEP ===")
    out_path = os.path.join(OUT_DIR, out_name)
    t0 = time.time()
    writer = STEPControl_Writer()
    writer.Transfer(compound, STEPControl_AsIs)
    writer.Write(out_path)
    total = time.time() - t0
    size_mb = os.path.getsize(out_path) / 1024 / 1024
    log(f"  ✓ 导出: {out_path} ({size_mb:.2f} MB, {total:.2f}s)")
    return out_path, total


def step4_cylinder_stretch(cylinder_shape, stroke_num, d1, scale, out_name):
    """步骤 4: 缸体按选型 D1 拉伸验证(真实参数,文件名由调用方指定)

    D1 = stroke + C, scale = D1 / base_D1
    沿缸体主轴(最长边)非均匀缩放,导出拉伸后缸体验证。
    """
    from OCC.Core.gp import gp_GTrsf
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_GTransform
    log("\n=== Step 4: 缸体按选型拉伸验证 ===")

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

    log(f"  选型: stroke={stroke_num}, D1={d1}, 沿 {axis_name} 轴缩放 ×{scale:.3f}")

    # 构造非均匀缩放变换（仅沿主轴缩放）
    gtrsf = gp_GTrsf()
    for i in range(1, 4):
        for j in range(1, 4):
            gtrsf.SetValue(i, j, 1.0 if i == j else 0.0)
        gtrsf.SetValue(i, 4, 0.0)
    gtrsf.SetValue(axis_idx + 1, axis_idx + 1, scale)

    t0 = time.time()
    transform = BRepBuilderAPI_GTransform(gtrsf)
    transform.Perform(cylinder_shape, True)
    new_shape = transform.ModifiedShape(cylinder_shape)
    elapsed = time.time() - t0
    log(f"  ✓ 缸体拉伸完成 ({elapsed*1000:.0f}ms)")

    # 验证新边界框
    new_bbox = Bnd_Box()
    brepbndlib.Add(new_shape, new_bbox)
    nxmin, nymin, nzmin, nxmax, nymax, nzmax = new_bbox.Get()
    new_axis_len = [nxmax-nxmin, nymax-nymin, nzmax-nzmin][axis_idx]
    log(f"  主轴长度: {max_len:.2f} → {new_axis_len:.2f} (期望 {max_len*scale:.2f})")

    out_path = os.path.join(OUT_DIR, out_name)
    t1 = time.time()
    write_step(new_shape, out_path)
    log(f"  ✓ 导出验证: {out_path} ({time.time()-t1:.2f}s)")
    return new_shape, elapsed


def step5_export_glb(compound, out_name):
    """步骤 5: 装配体 GLB 导出 (pythonOCC → STL → trimesh → GLB,文件名由调用方指定)"""
    log("\n=== Step 5: 装配体 GLB 导出 ===")
    import trimesh
    stl_path = os.path.join(tempfile.gettempdir(), "assembly_tmp.stl")
    glb_path = os.path.join(OUT_DIR, out_name)

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


def build_assembly(model_code, motor=None, series=None):
    """按选型装配并导出 STEP/GLB,返回产物路径字典(供 server/API 调用)

    Args:
        model_code: 型号编码,如 "250-E-H2K1-L100-D11"
        motor: 电机选型(型号含电机编号时此项被覆盖)
        series: 系列目录名(覆盖型号推断,如 "250直连")
    Returns:
        dict: {model_code, motor, series, shown, hidden, d1, scale,
               step_path, glb_path, cylinder_path, total_time, times}
    """
    os.makedirs(OUT_DIR, exist_ok=True)

    sel = parse_model_code(model_code)
    motor = sel.get("motor") or motor or DEFAULT_MOTOR
    log(f"选型解析: 系列={sel['series']} 类型={sel['type']} "
        f"安装={sel['mount']} 负载={sel['load']} 行程={sel['stroke']} 电机={motor}")

    # 确定系列目录名
    if series:
        series_name = series
    elif sel['type'].upper() == 'E':
        series_name = f"{sel['series']}直连"
    else:
        series_name = f"{sel['series']}折返"

    # 加载配置
    config_path = os.path.join(CONFIG_DIR, f"{series_name}.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置不存在: {config_path},请先运行 build_config.py")
    config = load_config(series_name)

    # 计算选型显隐
    visibility = resolve_visibility(config, sel['mount'], sel['load'], motor)
    with open(MATRIX_JSON, "r", encoding="utf-8") as f:
        parts_data = json.load(f)
    shown, hidden = apply_selection(parts_data, visibility)
    log(f"零件显隐: 显示 {shown} 个, 抑制 {hidden} 个 (共 {len(parts_data)})")

    # 缸体拉伸参数
    cyl = compute_cylinder_scale(config, sel['stroke'])
    if cyl:
        stroke_num, d1, scale = cyl
        log(f"缸体拉伸: stroke={stroke_num} → D1={d1}, 缩放 ×{scale:.3f}")
    else:
        stroke_num, d1, scale = None, None, 1.0

    # Step 1: 读取零件
    shapes, t_read = step1_read_all_parts(parts_data)

    # 缸体拉伸(主流程)
    t_stretch_main = 0.0
    if cyl:
        for key, shape in list(shapes.items()):
            m = _KEY_RE.match(key)
            base = m.group(1) if m else key
            if "缸体" in base:
                axis = find_cylinder_axis(shape)
                ts = time.time()
                shapes[key] = stretch_shape_axis(shape, axis, scale)
                t_stretch_main = time.time() - ts
                log(f"  ✓ 主流程缸体 {key} 沿 {['X','Y','Z'][axis]} 轴拉伸 ×{scale:.3f}")
                break

    # Step 2: 合并
    compound, t_merge = step2_apply_transform_and_merge(shapes, parts_data)

    # 输出文件名带型号(避免覆盖)
    prefix = model_code
    asm_name = f"{prefix}_assembly.step"
    glb_name = f"{prefix}_assembly.glb"
    cyl_name = f"{prefix}_cylinder.step"

    # Step 3: 装配体 STEP
    asm_step, t_step = step3_export_assembly_step(compound, asm_name)

    # Step 4: 缸体验证
    t_stretch = 0.0
    cyl_out = None
    cylinder_src = os.path.join(PARTS_DIR, CYLINDER_STEP)
    if os.path.exists(cylinder_src) and cyl:
        cylinder_shape = read_step(cylinder_src)
        _, t_stretch = step4_cylinder_stretch(cylinder_shape, stroke_num, d1, scale, cyl_name)
        cyl_out = os.path.join(OUT_DIR, cyl_name)

    # Step 5: GLB
    glb_path, t_glb = step5_export_glb(compound, glb_name)

    total = t_read + t_stretch_main + t_merge + t_step + t_stretch + t_glb
    return {
        "model_code": model_code,
        "motor": motor,
        "series": series_name,
        "shown": shown,
        "hidden": hidden,
        "d1": d1,
        "scale": round(scale, 3) if cyl else None,
        "step_path": asm_step,
        "glb_path": glb_path,
        "cylinder_path": cyl_out,
        "total_time": round(total, 2),
        "times": {
            "read": round(t_read, 2),
            "stretch": round(t_stretch_main, 3),
            "merge": round(t_merge, 3),
            "step": round(t_step, 2),
            "cylinder": round(t_stretch, 3),
            "glb": round(t_glb, 2),
        },
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description="按选型装配 3D 模型并导出 STEP/GLB")
    ap.add_argument("model_code", nargs="?", default=DEFAULT_MODEL_CODE,
                    help="型号编码,如 250-E-H2K1-L100-D11 (末段电机编号可选)")
    ap.add_argument("--motor", default=DEFAULT_MOTOR, help="电机选型(型号含电机编号时覆盖)")
    ap.add_argument("--series", default=None, help="系列目录名(覆盖型号推断,如 250直连)")
    args = ap.parse_args()

    log("=" * 60)
    log(f"pythonOCC 选型装配: {args.model_code}")
    log("=" * 60)

    if not check_env():
        sys.exit(1)

    result = build_assembly(args.model_code, args.motor, args.series)

    log("\n" + "=" * 60)
    log(f"速度汇总 ({result['model_code']})")
    log("=" * 60)
    t = result['times']
    log(f"  Step 1 读取零件 STEP     : {t['read']:.2f}s")
    log(f"  缸体拉伸(主流程)         : {t['stretch']*1000:.0f}ms")
    log(f"  Step 2 应用变换+合并      : {t['merge']*1000:.0f}ms")
    log(f"  Step 3 导出装配体 STEP   : {t['step']:.2f}s")
    log(f"  Step 4 缸体拉伸验证       : {t['cylinder']*1000:.0f}ms")
    log(f"  Step 5 GLB 导出          : {t['glb']:.2f}s")
    log(f"  -----------------------------")
    log(f"  总耗时                   : {result['total_time']:.2f}s")
    log(f"  显示 {result['shown']} 件 / 抑制 {result['hidden']} 件 / D1={result['d1'] or 'N/A'}")
    log(f"  装配体 STEP: {result['step_path']}")
    log(f"  装配体 GLB : {result['glb_path']}")
    if result['cylinder_path']:
        log(f"  缸体 STEP  : {result['cylinder_path']}")


if __name__ == "__main__":
    main()
