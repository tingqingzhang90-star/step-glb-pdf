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
        [0-8]   : 3x3 旋转矩阵（★ 列主序! SW 文档标注行主序，但实际为列主序）
        [9-11]  : 平移向量 (tx, ty, tz) — ★ 单位是米(m)!
        [12]    : 比例因子（通常 1.0）
        [13-15] : 保留（通常 0,0,0）

    ★ 关键1: SW MathTransform 的平移单位是米, STEP 文件用毫米
             必须将平移向量 × 1000
    ★ 关键2: SW ArrayData 旋转矩阵实际为列主序存储（转置后才是"零件→装配体"变换）
             直接按行主序解读会导致旋转方向反转
             验证: 鱼眼轴承杆长422mm(Y轴), 推杆Z=510.8→鱼眼轴承Z=957.8(差447mm≈杆长)
             行主序: 零件Y→装配体-Z(杆向后, 错误)
             列主序: 零件Y→装配体+Z(杆向前, 正确)
             → 必须转置旋转矩阵后再传给 gp_Trsf

    pythonOCC 7.9.x: gp_Trsf.SetValues(a11..a14, a21..a24, a31..a34)
    """
    from OCC.Core.gp import gp_Trsf

    trsf = gp_Trsf()
    # 平移 × 1000 (米 → 毫米)
    # ★ 旋转矩阵转置: SW ArrayData 是列主序, gp_Trsf 需要行主序
    #   SW: [m0,m1,m2] = Col0, [m3,m4,m5] = Col1, [m6,m7,m8] = Col2
    #   转置后: Row0=[m0,m3,m6], Row1=[m1,m4,m7], Row2=[m2,m5,m8]
    trsf.SetValues(
        m[0], m[3], m[6],  m[9] * 1000.0,
        m[1], m[4], m[7],  m[10] * 1000.0,
        m[2], m[5], m[8],  m[11] * 1000.0,
    )
    if abs(m[12] - 1.0) > 1e-9:
        trsf.SetScaleFactor(m[12])
    return trsf


# ---------- 选型装配:型号解析 + 配置驱动显隐 + 缸体拉伸 ----------
_KEY_RE = re.compile(r"^(.+)-(\d+)$")  # "250前盖-1" → 基础名"250前盖"
_HK_RE = re.compile(r"H(\d)K(\d)")      # "H2K1" → mount=H2, load=K1


def _fix_step_header_for_solidworks(step_path):
    """STEP 后处理:UTF-8 中文转 \\X2\\ 转义 + 文件头改为 SolidWorks 格式

    对比 SolidWorks 原生导出和 pythonOCC 导出的 STEP 文件发现两个关键差异:

    1. 中文编码方式不同:
       - SolidWorks: PRODUCT 名称用 \\X2\\HHHH\\X0\\ 转义(ISO 10303-21 标准,纯 ASCII)
         例: PRODUCT('250\\X2\\516d89d287ba6bcd\\X0\\', ...)  ← "250六角螺母"
       - pythonOCC 7.9: 直接以 UTF-8 字节写入中文字符(非 ASCII)
         例: PRODUCT('250缸体', ...)  ← UTF-8 字节 E7 BC B8 E4 BD 93
       - SolidWorks 导入时用系统 ANSI(GBK)读取,UTF-8 字节被当 GBK 误读 → 乱码/横线

    2. 文件头不同:
       - SolidWorks: 'SwSTEP 2.0'/'SolidWorks 2024'/FILE_DESCRIPTION(('STEP AP214'),'1')
       - pythonOCC:  'Open CASCADE STEP processor 7.9'/'Unknown'

    解决方案:
      1. 读取 UTF-8 文件,将所有非 ASCII 字符转为 \\X2\\HHHH\\X0\\ 转义(与 SolidWorks 一致)
      2. 修改文件头 FILE_DESCRIPTION/FILE_NAME/FILE_SCHEMA 为 SolidWorks 格式
      3. 以 latin-1(纯 ASCII) 写回,确保 SolidWorks 能正确解析中文转义

    Args:
        step_path: STEP 文件路径(将被原地修改)
    """
    try:
        t_post = time.time()

        # pythonOCC 7.9 以 UTF-8 编码写入中文字符
        with open(step_path, 'r', encoding='utf-8') as f:
            content = f.read()
        t_read = time.time()

        # ① 用正则批量替换非 ASCII 字符为 \X2\hhhh\X0\ 转义
        # 正则引擎(C 实现)扫描 9MB+ 文本比逐字符 Python 循环快 10-50 倍
        # 连续的非 ASCII 字符合并到一个转义块(与 SolidWorks 格式一致)
        def _escape_match(m):
            return '\\X2\\' + ''.join(format(ord(c), '04x') for c in m.group()) + '\\X0\\'

        content = re.sub(r'[^\x00-\x7f]+', _escape_match, content)
        t_escape = time.time()

        # ② 修改文件头为 SolidWorks 格式
        timestamp = ""
        ts_match = re.search(r"'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})'", content)
        if ts_match:
            timestamp = ts_match.group(1)

        fname = os.path.basename(step_path)
        new_file_name = (
            f"FILE_NAME ('{fname}','{timestamp}', ( '' ), ( '' ), "
            f"'SwSTEP 2.0', 'SolidWorks 2024', '' );"
        )

        content = re.sub(
            r"FILE_DESCRIPTION\s*\([^\n]*\);",
            "FILE_DESCRIPTION ( 'STEP AP214' ), '1' );",
            content, count=1
        )
        content = re.sub(
            r"FILE_NAME\s*\(.*?(?=FILE_SCHEMA)",
            new_file_name + "\n",
            content, count=1, flags=re.DOTALL
        )
        content = re.sub(
            r"FILE_SCHEMA\s*\([^\n]*\);",
            "FILE_SCHEMA ( ( 'AUTOMOTIVE_DESIGN' ) );",
            content, count=1
        )

        # 以 latin-1 写回(此时内容已全部为 ASCII,latin-1 与 ASCII 兼容)
        with open(step_path, 'w', encoding='latin-1') as f:
            f.write(content)
        t_write = time.time()

        log(f"  ✓ STEP 已转换为 SolidWorks 格式(\\X2\\ 转义 + 文件头) "
            f"[读取{(t_read-t_post)*1000:.0f}ms 转义{(t_escape-t_read)*1000:.0f}ms "
            f"文件头+写回{(t_write-t_escape)*1000:.0f}ms]")
    except Exception as e:
        log(f"  ⚠ STEP 后处理失败(不影响功能): {e}")


def _to_ascii_name(name):
    """将中文零件名转为纯 ASCII(备用方案,当前已改用 UTF-8 直接写入)

    原用于解决 SolidWorks 不支持 STEP Unicode 转义的问题。
    现已改用 _decode_step_unicode_escapes() 后处理 STEP 文件,
    将 \\X2\\XXXX\\X0\\ 转义序列替换为实际 UTF-8 字符,
    SolidWorks 可正确识别 UTF-8 编码的 STEP 文件中的中文名称。

    保留此函数作为备用回退方案。

    例: "250前盖" → "250QG"  "250缸体" → "250GT"  "装配体" → "ASM"
        "11kw电机" → "11kwDJ"  "AB180" → "AB180"
    """
    import unicodedata
    # 提取所有 ASCII 字符
    ascii_parts = []
    for ch in name:
        if ch.isascii() and (ch.isalnum() or ch in "_-"):
            ascii_parts.append(ch)
        elif '\u4e00' <= ch <= '\u9fff':
            # 中文: 取拼音首字母(简化映射,覆盖常见零件名)
            _pinyin_map = {
                '前': 'Q', '后': 'H', '左': 'Z', '右': 'Y', '上': 'S', '下': 'X',
                '盖': 'G', '体': 'T', '杆': 'G', '轴': 'Z', '座': 'Z', '套': 'T',
                '缸': 'G', '筒': 'T', '板': 'B', '块': 'K', '环': 'H', '圈': 'Q',
                '销': 'X', '钉': 'D', '螺': 'L', '母': 'M', '垫': 'D', '圈': 'Q',
                '电': 'D', '机': 'J', '泵': 'B', '阀': 'F', '管': 'G', '接': 'J',
                '连': 'L', '接': 'J', '轴': 'Z', '承': 'C', '轮': 'L', '盘': 'P',
                '壳': 'K', '罩': 'Z', '盖': 'G', '端': 'D', '头': 'T', '尾': 'W',
                '中': 'Z', '内': 'N', '外': 'W', '主': 'Z', '副': 'F', '辅': 'F',
                '装': 'Z', '配': 'P', '组': 'Z', '件': 'J', '零': 'L',
            }
            ascii_parts.append(_pinyin_map.get(ch, '_'))
    result = ''.join(ascii_parts)
    # 清理: 去除首尾下划线,压缩连续下划线
    result = re.sub(r'_+', '_', result).strip('_')
    return result if result else 'PART'


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


def write_stl(shape, path, linear_deflection=0.2, angular_deflection=1):
    """三角化 TopoDS_Shape 并导出 STL

    angular_deflection 控制曲面三角化精度:
        值越小 → 曲面上三角片越密 → 相邻三角片法线夹角越小
        设为 0.1 弧度(≈5.7°), 确保曲面法线夹角 < edgeThreshold(20°)
        这样 o3dv 边线渲染只画真正的硬边(面与面交界), 不画曲面网格线
    """
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    from OCC.Core.StlAPI import StlAPI_Writer
    # 三角化
    mesh = BRepMesh_IncrementalMesh(shape, linear_deflection, False, angular_deflection)
    mesh.Perform()
    # 写 STL
    writer = StlAPI_Writer()
    writer.SetASCIIMode(False)
    writer.Write(shape, path)


def extract_hard_edges(shape, discretization=0.5, angle_threshold=15.0):
    """从 STEP B-rep 提取硬边(面与面真实交界,非相切边)

    SolidWorks 只在面与面交界处画轮廓线,曲面上不画三角网格线。
    o3dv 的 EdgeSettings 基于三角面片法线夹角,无法区分两者。
    本函数从 B-rep 拓扑提取真实硬边,离散化为点序列,供前端 Three.js LineSegments 渲染。

    硬边判定逻辑(模拟 SolidWorks 显示规则):
    1. 如果两个面在边处相切(G1或更高连续性) → 不画线
    2. 如果两个面在边处的法向量夹角 < angle_threshold → 不画线(角度阈值过滤)
    3. 否则 → 画线(硬边)

    Args:
        shape: TopoDS_Shape (装配体)
        discretization: 离散化间距(mm),默认 0.5mm
        angle_threshold: 角度阈值(度),默认 15.0°,小于此角度的边不显示

    Returns:
        list of list of [x,y,z]: 每条硬边的点序列
    """
    from OCC.Core.TopExp import TopExp_Explorer, topexp_MapShapesAndAncestors
    from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCC.Core.TopoDS import topods
    from OCC.Core.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
    from OCC.Core.GCPnts import GCPnts_UniformAbscissa
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.GeomAbs import GeomAbs_G1
    from OCC.Core.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCC.Core.gp import gp_Pnt, gp_Vec
    import math

    # 建立边到面的映射(OCC 原生方法,高效)
    edge_face_map = TopTools_IndexedDataMapOfShapeListOfShape()
    topexp_MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, edge_face_map)

    edges_data = []
    explorer = TopExp_Explorer(shape, TopAbs_EDGE)

    while explorer.More():
        edge = topods.Edge(explorer.Current())

        # 查找该边的相邻面(OCC 原生查找,O(1))
        if not edge_face_map.Contains(edge):
            explorer.Next()
            continue

        face_list = edge_face_map.FindFromKey(edge)
        if face_list.Size() < 2:
            # 自由边(只有一个面),跳过
            explorer.Next()
            continue

        # 获取前两个面
        face1 = topods.Face(face_list.First())
        face2 = topods.Face(face_list.Last())

        # 如果两个面相同,跳过
        if face1.IsSame(face2):
            explorer.Next()
            continue

        # 检查连续性: 如果两个面在边处相切(G1或更高),则不是硬边,跳过
        try:
            continuity = BRep_Tool.Continuity(edge, face1, face2)
            if continuity >= GeomAbs_G1:
                # 相切边(如圆柱面与圆角过渡面之间),不画线
                explorer.Next()
                continue
        except Exception:
            # Continuity 检查失败,继续处理
            pass

        # 计算两个面在边中点处的法向量夹角
        try:
            curve_adaptor = BRepAdaptor_Curve(edge)
            u_mid = (curve_adaptor.FirstParameter() + curve_adaptor.LastParameter()) / 2.0
            p_mid = curve_adaptor.Value(u_mid)

            # 对每个面,找到边上中点在面上的最近点,计算法向量
            normals = []
            for face in [face1, face2]:
                # 获取底层几何曲面
                geom_surf = BRep_Tool.Surface(face)
                # 使用投影找到面上最近点
                projector = GeomAPI_ProjectPointOnSurf(p_mid, geom_surf)
                if projector.IsDone() and projector.NbPoints() > 0:
                    # 获取最近点的 UV 参数
                    u_face, v_face = projector.LowerDistanceParameters()
                    # 使用 D1 方法计算法向量: D1U × D1V
                    pnt = gp_Pnt()
                    d1u = gp_Vec()
                    d1v = gp_Vec()
                    geom_surf.D1(u_face, v_face, pnt, d1u, d1v)
                    # 法向量 = d1u × d1v
                    normal = d1u.Crossed(d1v)
                    normals.append(normal)

            if len(normals) == 2:
                norm1, norm2 = normals
                # 归一化法向量
                mag1 = norm1.Magnitude()
                mag2 = norm2.Magnitude()

                if mag1 > 1e-10 and mag2 > 1e-10:
                    n1 = gp_Vec(norm1.X()/mag1, norm1.Y()/mag1, norm1.Z()/mag1)
                    n2 = gp_Vec(norm2.X()/mag2, norm2.Y()/mag2, norm2.Z()/mag2)

                    # 计算法向量夹角
                    dot = n1.Dot(n2)
                    dot = max(-1.0, min(1.0, dot))
                    angle_rad = math.acos(abs(dot))  # 取绝对值,因为法向量方向可能相反
                    angle_deg = math.degrees(angle_rad)

                    # 如果夹角小于阈值,不画线(模拟 SolidWorks 的角度过滤)
                    if angle_deg < angle_threshold:
                        explorer.Next()
                        continue
        except Exception as e:
            # 如果法向量计算失败,保守处理:画线
            pass

        # 硬边: 离散化为点序列
        curve = BRepAdaptor_Curve(edge)
        discretizer = GCPnts_UniformAbscissa(curve, discretization)
        n = discretizer.NbPoints()

        if n >= 2:
            pts = []
            for j in range(1, n + 1):
                u = discretizer.Parameter(j)
                p = curve.Value(u)
                pts.append([p.X(), p.Y(), p.Z()])
            edges_data.append(pts)

        explorer.Next()

    return edges_data


def save_edges_json(edges_data, out_path):
    """保存硬边数据为 JSON 文件"""
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"edges": edges_data}, f, ensure_ascii=False)
    log(f"  ✓ 硬边数据: {out_path} ({len(edges_data)} 条边)")


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


def step3_export_assembly_step(compound, out_path):
    """步骤 3: 导出装配体 STEP(旧版,基于 STEPControl_Writer + Compound)

    ⚠ 此函数将所有零件合并为一个 TopoDS_Compound 后用 STEPControl_Writer 导出,
      导出的 STEP 文件会丢失装配体层次结构和零件名称:
      - SolidWorks 导入时每个零件显示为 "Open CASCADE STEP translator 7.9 X.X.step"
      - 无法展开查看各零件,因为缺少 PRODUCT/NEXT_ASSEMBLY_USAGE_OCCURRENCE 实体

    保留此函数用于:
      1. GLB 导出流程仍需 Compound(已应用变换)
      2. 备用方案(XCAF 导出失败时可回退)
      3. 单零件/单面 STEP 导出(不涉及装配体结构)

    如需保留装配体结构(每个零件有独立名称),请使用 step3_export_assembly_step_xcaf
    """
    from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
    log("\n=== Step 3: 导出装配体 STEP (旧版 Compound 模式) ===")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    t0 = time.time()
    writer = STEPControl_Writer()
    writer.Transfer(compound, STEPControl_AsIs)
    writer.Write(out_path)
    total = time.time() - t0
    size_mb = os.path.getsize(out_path) / 1024 / 1024
    log(f"  ✓ 导出: {out_path} ({size_mb:.2f} MB, {total:.2f}s)")
    return out_path, total


def step3_export_assembly_step_xcaf(shapes, parts_data, out_path, asm_name="装配体"):
    """步骤 3: 导出装配体 STEP(新版,基于 XCAF 保留零件名称+装配体层次结构)

    使用 XCAF(XDE) 文档结构 + STEPCAFControl_Writer 导出,生成的 STEP 文件包含:
      - PRODUCT 实体(每个零件有独立名称,如 "250前盖")
      - NEXT_ASSEMBLY_USAGE_OCCURRENCE(装配体层次结构)
      - SolidWorks 导入时可展开查看各零件,与 SW 原生导出效果一致

    ★ pythonOCC 7.9.3 conda-forge 构建的 XCAF 初始化注意事项(崩溃修复):
      1. 用 TDocStd_Application() 而非 XCAFApp_Application.GetApplication()
      2. 必须先 binxcafdrivers.DefineFormat(app) 注册驱动
      3. TDocStd_Document("XCAF") 直接传字符串,不要用 TCollection_ExtendedString
         (后者会导致 STATUS_STACK_BUFFER_OVERRUN 崩溃)
      4. app.NewDocument("BinXCAF", doc) 用 "BinXCAF" 格式
      参考: https://github.com/tpaviot/pythonocc-core/issues/1428

    Args:
        shapes: dict {name: TopoDS_Shape} 原始零件 shape(未应用变换)
        parts_data: dict {name: {transform_matrix, suppressed, ...}}
        out_path: 输出 STEP 文件完整路径
        asm_name: 装配体名称(默认 "装配体",可用 model_code)
    Returns:
        (out_path, elapsed_time)
    """
    from OCC.Core.BinXCAFDrivers import binxcafdrivers
    from OCC.Core.TDocStd import TDocStd_Application, TDocStd_Document
    from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool
    from OCC.Core.TDataStd import TDataStd_Name
    from OCC.Core.STEPCAFControl import STEPCAFControl_Writer
    from OCC.Core.TopLoc import TopLoc_Location
    from OCC.Core.TopoDS import TopoDS_Compound
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.gp import gp_Trsf

    log("\n=== Step 3: 导出装配体 STEP (XCAF 模式,保留零件名称) ===")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    t0 = time.time()

    # ★ XCAF 文档初始化(修复 conda-forge 崩溃)
    app = TDocStd_Application()
    binxcafdrivers.DefineFormat(app)
    doc = TDocStd_Document("XCAF")
    app.NewDocument("BinXCAF", doc)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool(doc.Main())

    # 1. 为每个未抑制的零件创建 label + 名称
    part_labels = {}  # {name: TDF_Label}
    skipped = 0
    for name, shape in shapes.items():
        info = parts_data.get(name, {})
        if info.get("suppressed", False):
            skipped += 1
            continue
        # 提取基础名(去掉 -N 后缀,如 "250前盖-1" → "250前盖")
        m = _KEY_RE.match(name)
        base_name = m.group(1) if m else name
        # ★ 直接使用中文名称,pythonOCC 会编码为 \X2\HHHH\X0\ 转义序列(STEP 标准)
        #   导出后通过 _fix_step_header_for_solidworks() 修改文件头为 SolidWorks 格式,
        #   使 SolidWorks 用正确的解析器处理 \X2\ 中文转义
        part_label = shape_tool.AddShape(shape, False)
        TDataStd_Name.Set(part_label, base_name)
        part_labels[name] = part_label
        log(f"  ✓ 零件: {base_name}")

    # 2. 创建装配体 label(用空 Compound 作为占位 shape)
    builder = BRep_Builder()
    asm_compound = TopoDS_Compound()
    builder.MakeCompound(asm_compound)
    asm_label = shape_tool.AddShape(asm_compound, True)
    TDataStd_Name.Set(asm_label, asm_name)

    # 3. 为每个零件添加 Component(带变换矩阵作为 Location)
    for name, part_label in part_labels.items():
        info = parts_data.get(name, {})
        matrix = info.get("transform_matrix")
        if matrix:
            trsf = matrix_to_trsf(matrix)
        else:
            trsf = gp_Trsf()  # 单位变换
        loc = TopLoc_Location(trsf)
        shape_tool.AddComponent(asm_label, part_label, loc)

    # 4. 更新装配体并导出
    shape_tool.UpdateAssemblies()

    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)  # ★ 保留零件名称
    t_transfer = time.time()
    writer.Transfer(doc)
    writer.Write(out_path)
    t_write = time.time()

    # ★ 后处理:UTF-8 中文转 \X2\ 转义 + 文件头改为 SolidWorks 格式
    #   SolidWorks 根据文件头判断 STEP 来源,对自身格式能正确解析 \X2\ 中文转义
    _fix_step_header_for_solidworks(out_path)

    t_post = time.time()
    total = t_post - t0
    size_mb = os.path.getsize(out_path) / 1024 / 1024
    log(f"  ✓ 导出: {out_path} ({size_mb:.2f} MB, {total:.2f}s, "
        f"{len(part_labels)} 零件, 跳过 {skipped} 抑制件)")
    log(f"    耗时分解: XCAF构建{(t_transfer-t0)*1000:.0f}ms "
        f"Transfer+Write{(t_write-t_transfer)*1000:.0f}ms "
        f"后处理{(t_post-t_write)*1000:.0f}ms")
    return out_path, total, doc


def step4_cylinder_stretch(cylinder_shape, stroke_num, d1, scale, out_path):
    """步骤 4: 缸体按选型 D1 拉伸验证(out_path 为完整输出路径)

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

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    t1 = time.time()
    write_step(new_shape, out_path)
    log(f"  ✓ 导出验证: {out_path} ({time.time()-t1:.2f}s)")
    return new_shape, elapsed


def step5_export_glb(compound, out_path):
    """步骤 5: 装配体 GLB 导出 (pythonOCC → STL → trimesh → GLB,out_path 为完整输出路径)"""
    log("\n=== Step 5: 装配体 GLB 导出 ===")
    import trimesh
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    stl_path = os.path.join(tempfile.gettempdir(), "assembly_tmp.stl")
    glb_path = out_path

    # 5.1 三角化 + STL 导出
    t0 = time.time()
    write_stl(compound, stl_path, linear_deflection=0.2, angular_deflection=1)
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

    # 5.3 硬边提取已禁用(耗时约 40s,影响生成体验)
    # 如需恢复,取消下方注释即可。函数 extract_hard_edges/save_edges_json 保留备用。
    # t2 = time.time()
    # edges_data = extract_hard_edges(compound, discretization=0.5)
    # edges_path = os.path.join(os.path.dirname(glb_path), "edges.json")
    # save_edges_json(edges_data, edges_path)
    # t_edges = time.time() - t2
    # log(f"  ✓ 硬边提取: {t_edges:.2f}s")
    t_edges = 0.0

    # 清理 STL
    try:
        os.remove(stl_path)
    except Exception:
        pass

    return glb_path, t_stl + t_glb + t_edges


def step5_export_glb_xcaf(doc, out_path, linear_deflection=0.2, angular_deflection=1.0):
    """步骤 5(新): 用 OCC 原生 RWGltf_CafWriter 直接从 XCAF 文档导出 GLB

    跳过 STL→trimesh 中转链路,全 C++ 实现,无中间文件 I/O。
    三角化参数与原 step5_export_glb 保持一致,不影响精度。

    对比原方案:
      原: pythonOCC三角化 → 写STL文件 → trimesh读STL → 写GLB (5.87s)
      新: 预三角化 → RWGltf_CafWriter.Perform → 写GLB     (预计 2-3s)

    Args:
        doc: XCAF 文档(来自 step3_export_assembly_step_xcaf 的返回值)
        out_path: GLB 输出路径
        linear_deflection: 线性偏移(默认 0.2mm,与原方案一致)
        angular_deflection: 角度偏移(默认 1.0 弧度,与原方案一致)
    Returns:
        (out_path, total_time)
    """
    from OCC.Core.RWGltf import RWGltf_CafWriter
    from OCC.Core.TColStd import TColStd_IndexedDataMapOfStringString
    from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool
    from OCC.Core.TDF import TDF_LabelSequence
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    from OCC.Core.TopoDS import TopoDS_Shape
    from OCC.Core.Message import Message_ProgressRange

    log("\n=== Step 5 (XCAF): 装配体 GLB 导出 ===")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # 1. 预三角化 XCAF 文档中所有零件 shape(使用与原方案相同的参数)
    t0 = time.time()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetShapes(labels)
    mesh_count = 0
    for i in range(1, labels.Length() + 1):
        label = labels.Value(i)
        shape = TopoDS_Shape()
        if shape_tool.GetShape(label, shape) and not shape.IsNull():
            BRepMesh_IncrementalMesh(
                shape, linear_deflection, False, angular_deflection, True
            )
            mesh_count += 1
    t_mesh = time.time() - t0
    log(f"  ✓ 预三角化 {mesh_count} 个 shape ({t_mesh:.2f}s)")

    # 2. 用 RWGltf_CafWriter 导出 GLB(全 C++,无中间文件)
    t1 = time.time()
    writer = RWGltf_CafWriter(out_path, True)  # True = binary GLB
    writer.SetParallel(True)  # 启用并行写入
    attributes = TColStd_IndexedDataMapOfStringString()
    writer.Perform(doc, attributes, Message_ProgressRange())
    t_glb = time.time() - t1

    glb_size_mb = os.path.getsize(out_path) / 1024 / 1024
    total = t_mesh + t_glb
    log(f"  ✓ GLB 导出: {out_path} ({glb_size_mb:.2f} MB, "
        f"三角化 {t_mesh:.2f}s + 写入 {t_glb:.2f}s = {total:.2f}s)")

    return out_path, total


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

    # 缸体拉伸(主流程) + 配合零件位移补偿(通用数据驱动)
    # cylinder_part 来自配置 JSON, 不硬编码关键词; 主轴方向自动检测
    t_stretch_main = 0.0
    cyl_part_name = config.get("cylinder_part")
    if cyl and cyl_part_name:
        for key, shape in list(shapes.items()):
            m = _KEY_RE.match(key)
            base = m.group(1) if m else key
            if base == cyl_part_name:
                axis = find_cylinder_axis(shape)
                axis_name = ['X', 'Y', 'Z'][axis]

                # 计算拉伸后主轴方向位移 delta(mm)
                bbox = shape_bbox(shape)
                cyl_min = bbox[axis]
                cyl_max = bbox[axis + 3]
                cyl_len = cyl_max - cyl_min
                new_len = cyl_len * scale
                delta_mm = new_len - cyl_len  # 正值=沿主轴正向延伸

                ts = time.time()
                shapes[key] = stretch_shape_axis(shape, axis, scale)
                t_stretch_main = time.time() - ts
                log(f"  ✓ 主流程 {key} 沿 {axis_name} 轴拉伸 ×{scale:.3f}"
                    f" (主轴位移 {delta_mm:+.1f}mm)")

                # 配合零件位移补偿: 沿主轴方向坐标 > 缸体中心的零件同步位移
                if abs(delta_mm) > 0.01:
                    cyl_center_mm = parts_data[key]["transform_matrix"][9 + axis] * 1000.0
                    delta_m = delta_mm / 1000.0  # 变换矩阵平移单位是米
                    adjusted = 0
                    for pkey, pinfo in parts_data.items():
                        if pinfo.get("suppressed", False):
                            continue
                        pm = _KEY_RE.match(pkey)
                        pbase = pm.group(1) if pm else pkey
                        if pbase == cyl_part_name:
                            continue
                        pcoord_mm = pinfo["transform_matrix"][9 + axis] * 1000.0
                        if pcoord_mm > cyl_center_mm:
                            pinfo["transform_matrix"][9 + axis] += delta_m
                            adjusted += 1
                    log(f"  ✓ 配合零件位移补偿: {adjusted} 件 沿 {axis_name} 轴 × {delta_mm:+.1f}mm")
                break
    elif cyl and not cyl_part_name:
        log("  ⚠ 配置缺少 cylinder_part, 跳过缸体拉伸(请重新运行 build_config.py)")

    # Step 2: 合并
    compound, t_merge = step2_apply_transform_and_merge(shapes, parts_data)

    # 输出到型号子目录 output/<model_code>/
    model_dir = os.path.join(OUT_DIR, model_code)
    os.makedirs(model_dir, exist_ok=True)
    asm_path = os.path.join(model_dir, "assembly.step")
    glb_path = os.path.join(model_dir, "assembly.glb")
    cyl_path = os.path.join(model_dir, "cylinder.step")

    # Step 3: 装配体 STEP
    # ★ 使用 XCAF 模式导出,保留零件名称和装配体层次结构
    #   旧版 step3_export_assembly_step(compound, asm_path) 会丢失零件名称,
    #   SolidWorks 导入时所有零件显示为 "Open CASCADE STEP translator..."
    #   新版 step3_export_assembly_step_xcaf 使用 XCAF/XDE 文档结构,
    #   生成 PRODUCT + NEXT_ASSEMBLY_USAGE_OCCURRENCE 实体,与 SW 原生导出一致
    asm_step, t_step, xcaf_doc = step3_export_assembly_step_xcaf(
        shapes, parts_data, asm_path, asm_name=model_code)

    # Step 4: 缸体验证
    t_stretch = 0.0
    cyl_out = None
    cylinder_src = os.path.join(PARTS_DIR, CYLINDER_STEP)
    if os.path.exists(cylinder_src) and cyl:
        cylinder_shape = read_step(cylinder_src)
        _, t_stretch = step4_cylinder_stretch(cylinder_shape, stroke_num, d1, scale, cyl_path)
        cyl_out = cyl_path

    # Step 5: GLB (用 OCC 原生 RWGltf_CafWriter,跳过 STL→trimesh 中转)
    glb_path, t_glb = step5_export_glb_xcaf(xcaf_doc, glb_path)

    total = t_read + t_stretch_main + t_merge + t_step + t_stretch + t_glb
    result = {
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
    # 保存构建元数据到 output 子目录,供前端加载历史结果
    def _rel(p):
        return os.path.relpath(p, OUT_DIR).replace("\\", "/") if p else None
    info = dict(result)
    info["step_file"] = _rel(asm_step)
    info["glb_file"] = _rel(glb_path)
    info["cylinder_file"] = _rel(cyl_out)
    info_path = os.path.join(model_dir, "build_info.json")
    try:
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return result


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
