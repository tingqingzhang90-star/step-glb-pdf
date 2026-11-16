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
import logging

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
logger = logging.getLogger(__name__)

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


def parse_power_kw(text):
    """从名称里解析功率(kW),支持 '4.4kw' 与 '汇川1500w';解析不出返回 None"""
    m = re.search(r"([\d.]+)\s*(kw|w)", str(text), re.I)
    if not m:
        return None
    value = float(m.group(1))
    return value / 1000 if m.group(2).lower() == "w" else value


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
    """电机表 → {电机编号: {name, reducer, on, off, torque, power_kw, brake}}

    支持两种表头:
      1) [电机, 减速机, OnFeature, OffFeature]   # 250:电机列写法"D55(5.5KW电机）"
      2) [电机减速机, OnFeature, OffFeature]      # JDG 等无减速机/编号列
    电机列既可是"D55(5.5KW电机）"合并写法,也可是纯名称/纯编号。按表头定位列,
    不按下标硬取,否则少一列的系列(JDG 等)会 IndexError。

    配置 key 统一用 strip_code 抽出的编号(便于型号拼接),原始写法存回 name,
    供 UI 展示与按名称反查。

    扭矩列(如「扭矩(Nm)」)为可选:存在则一并读取,供选型界面按电机直接取额定扭矩,
    缺失时前端回退 T=P*9550/n 估算。功率从电机名列解析(kW/KW 或 W,汇川1500w 等),
    统一为 kW;刹车由名称含"刹车/抱闸"或编号以 B 结尾判断。
    重复代号与 OnFeature 功率错配会写 warning 日志但不阻断生成:多个系列存在
    同名多行(不同减速机),硬报错会让面板无法生成任何配置。
    """
    header = [str(c).strip().lower() if c else "" for c in rows[0]]
    if "onfeature" in header and "offfeature" in header:
        idx_on = header.index("onfeature")
        idx_off = header.index("offfeature")
    else:
        idx_on, idx_off = (2, 3) if len(rows[0]) >= 4 else (1, 2)
    idx_reducer = 1 if idx_on >= 2 else None
    idx_torque = next((i for i, h in enumerate(header) if "扭矩" in h), None)

    cfg = {}
    seen = {}
    for lineno, r in enumerate(rows[1:], start=2):
        if not r or not r[0]:
            continue
        raw = str(r[0]).strip()
        code = strip_code(raw)
        if not code:
            continue
        # 同名多行(不同减速机)互相覆盖,保留既有行为但要留痕
        if code in seen:
            logger.warning("电机表代号重复: %s 第 %d 行覆盖第 %d 行(%s),前面的减速机选项会丢失",
                           code, lineno, seen[code], raw)
        seen[code] = lineno
        reducer = r[idx_reducer] if idx_reducer is not None and idx_reducer < len(r) else ""
        power_kw = parse_power_kw(raw)
        on_list = parse_feature_list(r[idx_on]) if idx_on < len(r) else []
        off_list = parse_feature_list(r[idx_off]) if idx_off < len(r) else []
        # OnFeature 里电机零件的功率必须与行名一致,否则装错电机而配置不报错
        for feat in on_list:
            feat_kw = parse_power_kw(feat)
            if (feat_kw is not None and power_kw is not None
                    and ("汇川" in feat or "电机" in feat)
                    and abs(feat_kw - power_kw) > 1e-6):
                logger.warning("电机表功率不匹配: 第 %d 行 %s -> OnFeature %s",
                               lineno, raw, feat)
        brake = ("刹车" in raw) or ("抱闸" in raw) or (code.endswith("B"))
        torque = None
        if idx_torque is not None and idx_torque < len(r) and r[idx_torque] not in (None, ""):
            try:
                torque = float(r[idx_torque])
            except (TypeError, ValueError):
                torque = None
        cfg[code] = {
            "name": raw,
            "reducer": str(reducer).strip() if reducer else "",
            "on": on_list,
            "off": off_list,
            "torque": torque,
            "power_kw": power_kw,
            "brake": brake,
        }
    return cfg


def motor_table_for_series(series_name):
    """读取系列电机.xlsx → {code: {...含 torque/power_kw/brake}};无表返回 {}。

    供后端 /api/series/motor-table 下发,使选型界面电机(功率/扭矩)数据单一来源为
    图库项目/<系列>/电机.xlsx,不在前端重复维护。
    """
    series_dir = os.path.join(LIB_ROOT, series_name)
    if not os.path.isdir(series_dir):
        return {}
    rows = _read_tables(series_dir).get("motor")
    if not rows:
        return {}
    return build_motor(rows)


# 系列「名称 → 丝杆型号/导程/缸径」对照表(后端维护,单 xlsx 多 sheet):
# 选型按系列取导程下拉,选定导程后回填丝杆型号与缸径到工程图规格表。
# 路径相对项目根(data/ 下),迁移部署只需把文件放到 data/screw_table.xlsx。
SCREW_TABLE_XLSX = os.path.join(paths.DATA_DIR, "screw_table.xlsx")


def _norm_series(name):
    """系列归一化:取首个数字段(YRJ45 / EDA45 / 45 → "45"),兼容前端不带前缀的写法"""
    m = re.search(r"\d+", str(name or ""))
    return m.group(0) if m else str(name or "").strip()


def _cell(row, j):
    return row[j] if (j is not None and 0 <= j < len(row)) else None


def _find_screw_header(rows):
    """定位含「丝杆型号」的表头行 → (行号, {name/screw/lead/bore: 列号});无则 None"""
    for i, r in enumerate(rows):
        labels = [str(c).strip() for c in r if c is not None]
        if "丝杆型号" not in labels:
            continue
        cols = {}
        for j, c in enumerate(r):
            t = str(c).strip() if c is not None else ""
            if t == "名称":
                cols["name"] = j
            elif t == "丝杆型号":
                cols["screw"] = j
            elif t == "导程":
                cols["lead"] = j
            elif t == "缸径":
                cols["bore"] = j
        if "screw" in cols:
            return i, cols
    return None


def _screw_cell(v):
    """单元格值 → 展示用字符串(整数去掉小数尾零)"""
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _screw_groups():
    """data/screw_table.xlsx → {归一化系列: [{screw_model, lead, bore}]}

    「名称」列即系列,非空即开启新分组,该系列从本行起直到下一个名称前都属于它。
    """
    if not os.path.isfile(SCREW_TABLE_XLSX):
        return {}
    from openpyxl import load_workbook
    wb = load_workbook(SCREW_TABLE_XLSX, data_only=True, read_only=True)
    groups = {}
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        found = _find_screw_header(rows)
        if not found:
            continue
        h_idx, cols = found
        cur = None
        for r in rows[h_idx + 1:]:
            name = _cell(r, cols.get("name"))
            if name is not None and str(name).strip():
                cur = _norm_series(name)
                groups.setdefault(cur, [])
            screw = _cell(r, cols.get("screw"))
            if cur is None or screw is None or not str(screw).strip():
                continue
            groups[cur].append({
                "screw_model": str(screw).strip(),
                "lead": _screw_cell(_cell(r, cols.get("lead"))),
                "bore": _screw_cell(_cell(r, cols.get("bore"))),
            })
    wb.close()
    return groups


def screw_table_for_series(series_name):
    """系列(兼容无 YRJ/EDA 前缀)→ [{screw_model, lead, bore}];无匹配返回 []"""
    return _screw_groups().get(_norm_series(series_name), [])


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
