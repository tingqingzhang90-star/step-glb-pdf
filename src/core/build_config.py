# -*- coding: utf-8 -*-
"""预处理:把系列目录下的 xlsx 装配表转成结构化 JSON 配置

将 SolidWorks 的"配置驱动装配表"(安装方式/负载连接方式/电机/缸体长度)
解析为统一的 JSON,供 rebuild_assembly.py 运行时直接读取,避免每次解析 xlsx。

用法:
    conda run -n pdf1 python src/build_config.py [系列目录] [--parts PARTS_JSON]
    默认系列目录: 图库项目/250直连
    默认零件表:   data/parts_transform.json
输出: data/configs/<系列名>.json

装配逻辑说明:
    每张表通过 OnFeature(启用)/OffFeature(抑制)控制零件显隐。
    零件名格式 "零件名<数量>",与 parts_transform.json 的 key "零件名-实例号"
    通过"基础名"匹配(去掉 <-数量> 和 <-实例号> 后比较)。
    不出现在任何表 On/Off 里的零件为常显基础件(如缸体、推杆、直连盒)。
"""
import os
import re
import sys
import json
import argparse

# Windows 控制台默认 GBK,打印中文系列名会 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 本文件位于 src/core/,需上溯三级: core → src → 项目根
_PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
# 允许以脚本方式直跑(python src/core/build_config.py)
if os.path.join(_PROJECT_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from core import paths  # noqa: E402  依赖上面的 sys.path 补齐

LIB_ROOT = paths.LIB_ROOT

# "250底部法兰前盖<1>" → ("250底部法兰前盖", 1)
_FEATURE_RE = re.compile(r"^(.+?)<(\d+)>$")
# "250底部法兰前盖-1" → ("250底部法兰前盖", 1)
_KEY_RE = re.compile(r"^(.+)-(\d+)$")


def parse_feature_list(s):
    """解析 'AB180<1>,5.5kw<1>' → ['AB180', '5.5kw']"""
    if not s:
        return []
    out = []
    for tok in str(s).split(","):
        tok = tok.strip()
        if not tok:
            continue
        m = _FEATURE_RE.match(tok)
        out.append(m.group(1) if m else tok)
    return out


def strip_code(s):
    """'H2(底部安装方式)' → 'H2';'K1(螺纹头)' → 'K1';'D55(5.5KW电机）' → 'D55'

    兼容半角 '(' 与全角 '（',取第一个括号前的内容。
    """
    if not s:
        return ""
    s = str(s)
    for ch in ("(", "（"):
        if ch in s:
            return s.split(ch)[0].strip()
    return s.strip()


def read_xlsx_rows(path):
    """读取 xlsx 第一个 sheet 的全部行(去全空行)"""
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return [r for r in rows if not all(c is None for c in r)]


def build_mount_or_load(rows, label):
    """安装方式/负载连接方式表 → {代号: {name, on:[...], off:[...]}}

    首列写法带文字说明(如 "H2(底部安装方式)"):代号作 key 用于型号拼接,
    原文整体存回 name,供选型面板展示。
    """
    cfg = {}
    for r in rows[1:]:  # 跳过表头
        if not r or not r[0]:
            continue
        raw = str(r[0]).strip()
        code = strip_code(raw)
        if not code:
            continue
        cfg[code] = {
            "name": raw,
            "on": parse_feature_list(r[1]),
            "off": parse_feature_list(r[2]),
        }
    return cfg


def build_motor(rows):
    """电机表 → {电机编号: {name, reducer, on:[...], off:[...]}}

    支持两种表头:
      1) [电机, 减速机, OnFeature, OffFeature]   # 250:电机列写法"D55(5.5KW电机）"
      2) [电机减速机, OnFeature, OffFeature]      # JDG 等无减速机/编号列
    电机列既可是"D55(5.5KW电机）"合并写法,也可是纯名称/纯编号。按表头定位列,
    不按下标硬取,否则少一列的系列(JDG 等)会 IndexError。

    配置 key 统一用 strip_code 抽出的编号(便于型号里写编号),原始写法存回 name,
    供 UI 展示与按名称反查。
    """
    header = [str(c).strip().lower() if c else "" for c in rows[0]]
    if "onfeature" in header and "offfeature" in header:
        idx_on = header.index("onfeature")
        idx_off = header.index("offfeature")
    else:
        idx_on, idx_off = (2, 3) if len(rows[0]) >= 4 else (1, 2)
    idx_reducer = 1 if idx_on >= 2 else None

    cfg = {}
    for r in rows[1:]:  # 跳过表头
        if not r or not r[0]:
            continue
        raw = str(r[0]).strip()
        code = strip_code(raw)
        if not code:
            continue
        reducer = r[idx_reducer] if idx_reducer is not None and idx_reducer < len(r) else ""
        cfg[code] = {
            "name": raw,
            "reducer": str(reducer).strip() if reducer else "",
            "on": parse_feature_list(r[idx_on]) if idx_on < len(r) else [],
            "off": parse_feature_list(r[idx_off]) if idx_off < len(r) else [],
        }
    return cfg


def build_cylinder(rows):
    """缸体长度表 → {C, base_D1, base_stroke, formula, table}

    D1 = stroke + C(线性关系),base 取最小行程对应值。
    """
    table = {}
    for r in rows[1:]:
        if not r or not r[0]:
            continue
        stroke = str(r[0]).strip()        # L100
        d1 = r[1]
        try:
            d1 = int(d1)
        except (TypeError, ValueError):
            continue
        table[stroke] = d1
    if not table:
        return {}
    # 验证线性关系 D1 = stroke + C
    def stroke_num(s):
        m = re.match(r"^L(\d+)$", s)
        return int(m.group(1)) if m else None
    cs = set()
    for s, d1 in table.items():
        n = stroke_num(s)
        if n is not None:
            cs.add(d1 - n)
    c = cs.pop() if len(cs) == 1 else None  # 唯一 C 才采用公式
    # base: 最小行程
    base = min(table.items(), key=lambda kv: stroke_num(kv[0]) or 0)
    return {
        "C": c,
        "base_D1": base[1],
        "base_stroke": stroke_num(base[0]),
        "formula": f"D1 = stroke + {c}" if c is not None else "non-linear",
        "table": table,
    }


def collect_controlled(mount, load, motor):
    """收集所有受控零件基础名(出现在任一表 on/off 里)"""
    names = set()
    for d in (mount, load):
        for v in d.values():
            names.update(v["on"])
            names.update(v["off"])
    for v in motor.values():
        names.update(v["on"])
        names.update(v["off"])
    return names


def load_part_names(parts_path):
    """从 parts_transform.json 读取全部零件基础名"""
    with open(parts_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    names = []
    for key in data:
        m = _KEY_RE.match(key)
        names.append(m.group(1) if m else key)
    return names, list(data.keys())


def detect_cylinder_part(parts_path):
    """从零件表自动检测被拉伸的缸体零件基础名

    通用规则: 零件名包含"缸体"二字的为基础件缸体。
    找不到返回 None(由调用方决定是否报错)。
    """
    names, _ = load_part_names(parts_path)
    candidates = [n for n in set(names) if "缸体" in n]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        # 多个含"缸体"的,取系列号开头的主缸体(如 "250缸体" 优先于 "250缸体盖")
        series_prefix = names[0].split("-")[0] if names else ""
        main = [c for c in candidates if c.startswith(series_prefix[:3])]
        if len(main) == 1:
            return main[0]
        return candidates[0]
    return None


def _read_tables(series_dir):
    """读取系列目录下的装配表

    电机表在不同系列里叫"电机.xlsx"或"电机减速机.xlsx",两个名字都试。
    """
    def xlsx(name):
        p = os.path.join(series_dir, name)
        if not os.path.exists(p):
            print(f"  [缺失] {name}")
            return None
        return read_xlsx_rows(p)

    motor = xlsx("电机.xlsx")
    if motor is None:
        motor = xlsx("电机减速机.xlsx")
    return {"mount": xlsx("安装方式.xlsx"),
            "load": xlsx("负载连接方式.xlsx"),
            "motor": motor,
            "cylinder": xlsx("缸体长度.xlsx")}


def build_series_config(series_name, parts_json=None):
    """装配表 + 零件表 → 系列配置字典"""
    rows = _read_tables(os.path.join(LIB_ROOT, series_name))
    mount = build_mount_or_load(rows["mount"], "mount") if rows["mount"] else {}
    load = build_mount_or_load(rows["load"], "load") if rows["load"] else {}
    motor = build_motor(rows["motor"]) if rows["motor"] else {}
    cylinder = build_cylinder(rows["cylinder"]) if rows["cylinder"] else {}

    controlled = collect_controlled(mount, load, motor)
    parts_path = parts_json or paths.transform_json(series_name)
    if os.path.exists(parts_path):
        all_names, _ = load_part_names(parts_path)
        base_parts = sorted(n for n in set(all_names) if n not in controlled)
        cylinder_part = detect_cylinder_part(parts_path)
    else:
        base_parts, cylinder_part = [], None
        print(f"  [缺失] 零件表,base_parts 留空: {parts_path}")
    return {
        "series": series_name,
        "cylinder": cylinder,
        "cylinder_part": cylinder_part,
        "base_parts": base_parts,
        "controlled_count": len(controlled),
        "mount": mount,
        "load": load,
        "motor": motor,
    }


def write_series_config(config):
    """落盘 data/configs/<系列>.json,返回写入路径"""
    os.makedirs(paths.CONFIG_DIR, exist_ok=True)
    out_path = paths.config_path(config["series"])
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="系列装配表 → data/configs/<系列>.json")
    ap.add_argument("series", nargs="?", default="250直连",
                    help="系列名(图库项目下的子目录名)")
    ap.add_argument("--all", action="store_true",
                    help="为所有已导出零件的系列生成配置")
    ap.add_argument("--parts", default=None,
                    help="零件表路径,默认 library/series/<系列>/parts_transform.json")
    args = ap.parse_args()

    targets = paths.list_series() if args.all else [args.series]
    if not targets:
        print("没有可处理的系列,先用 part_exporter 导出零件")
        return
    for name in targets:
        print(f"系列: {name}")
        config = build_series_config(name, args.parts)
        out_path = write_series_config(config)
        print(f"  配置: {out_path}")
        print(f"  安装 {list(config['mount'])}")
        print(f"  负载 {list(config['load'])}")
        print(f"  电机 {list(config['motor'])}")
        print(f"  缸体零件 {config['cylinder_part'] or '(未检测到)'}")
        print(f"  常显件 {len(config['base_parts'])} 受控件 {config['controlled_count']}")


if __name__ == "__main__":
    main()
