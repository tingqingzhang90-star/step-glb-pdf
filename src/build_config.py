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

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_ROOT = os.path.join(_PROJECT_ROOT, "图库项目")
OUT_DIR = os.path.join(_PROJECT_ROOT, "data", "configs")

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
    """'H2(底部安装方式)' → 'H2';'K1(螺纹头)' → 'K1'"""
    if not s:
        return ""
    return str(s).split("(")[0].strip()


def read_xlsx_rows(path):
    """读取 xlsx 第一个 sheet 的全部行(去全空行)"""
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return [r for r in rows if not all(c is None for c in r)]


def build_mount_or_load(rows, label):
    """安装方式/负载连接方式表 → {代号: {on:[...], off:[...]}}"""
    cfg = {}
    for r in rows[1:]:  # 跳过表头
        if not r or not r[0]:
            continue
        code = strip_code(r[0])
        if not code:
            continue
        cfg[code] = {
            "on": parse_feature_list(r[1]),
            "off": parse_feature_list(r[2]),
        }
    return cfg


def build_motor(rows):
    """电机表 → {电机型号: {reducer, on:[...], off:[...]}}"""
    cfg = {}
    for r in rows[1:]:  # 跳过表头
        if not r or not r[0]:
            continue
        cfg[str(r[0]).strip()] = {
            "reducer": str(r[1]).strip() if r[1] else "",
            "on": parse_feature_list(r[2]),
            "off": parse_feature_list(r[3]),
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("series_dir", nargs="?",
                    default=os.path.join(LIB_ROOT, "250直连"))
    ap.add_argument("--parts", default=os.path.join(_PROJECT_ROOT, "data", "parts_transform.json"))
    args = ap.parse_args()

    series_dir = args.series_dir
    series_name = os.path.basename(series_dir.rstrip("\\/"))
    print(f"系列目录: {series_dir}")
    print(f"系列名:   {series_name}")

    # 读取 4 张表(文件名固定)
    def xlsx(name):
        p = os.path.join(series_dir, name)
        if not os.path.exists(p):
            print(f"  ⚠ 缺失: {name}")
            return None
        return read_xlsx_rows(p)

    mount_rows = xlsx("安装方式.xlsx")
    load_rows = xlsx("负载连接方式.xlsx")
    motor_rows = xlsx("电机.xlsx")
    cyl_rows = xlsx("缸体长度.xlsx")
    # 部分系列电机表名为"电机减速机.xlsx"
    if motor_rows is None:
        motor_rows = xlsx("电机减速机.xlsx")
        if motor_rows is not None:
            print("  (使用 电机减速机.xlsx 作为电机表)")

    mount = build_mount_or_load(mount_rows, "mount") if mount_rows else {}
    load = build_mount_or_load(load_rows, "load") if load_rows else {}
    motor = build_motor(motor_rows) if motor_rows else {}
    cylinder = build_cylinder(cyl_rows) if cyl_rows else {}

    # 计算 base_parts(常显件)
    controlled = collect_controlled(mount, load, motor)
    if os.path.exists(args.parts):
        all_names, _ = load_part_names(args.parts)
        base_parts = sorted(n for n in set(all_names) if n not in controlled)
        cylinder_part = detect_cylinder_part(args.parts)
    else:
        base_parts = []
        cylinder_part = None
        print(f"  ⚠ 零件表不存在,base_parts 留空: {args.parts}")

    config = {
        "series": series_name,
        "cylinder": cylinder,
        "cylinder_part": cylinder_part,
        "base_parts": base_parts,
        "controlled_count": len(controlled),
        "mount": mount,
        "load": load,
        "motor": motor,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{series_name}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"\n✓ 配置已生成: {out_path}")
    print(f"  安装方式: {list(mount.keys())}")
    print(f"  负载连接: {list(load.keys())}")
    print(f"  电机:     {list(motor.keys())}")
    print(f"  缸体:     C={cylinder.get('C')}, base_D1={cylinder.get('base_D1')}, "
          f"formula={cylinder.get('formula')}")
    print(f"  缸体零件: {cylinder_part or '(未检测到,需手动配置)'}")
    print(f"  常显件({len(base_parts)}): {base_parts}")
    print(f"  受控件:   {len(controlled)}")


if __name__ == "__main__":
    main()
