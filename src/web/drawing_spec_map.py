# -*- coding: utf-8 -*-
"""规格回填映射(单点维护)

职责:
  1. 根据 model_id 定位 output/<model_id>/drawing_source.json(同系列复用)。
  2. 把前端传来的 spec(规格字段)回填进 drawing_source.json 的
     title_block.fields[].value 与 技术参数表 cells[].text。
  3. 几何字段(stroke / motor / series)驱动派生值(行程、缸长 D1、电机安装方式)。

不改动 views / annotations 几何,只写可编辑内容;路径经白名单校验,杜绝穿越。
"""
import json
import os
import re
from datetime import date

from web import common
from core import rebuild_assembly as rb

SOURCE_NAME = "drawing_source.json"

# 技术参数表中,标签 → (r, c) 的回填位置(其余标签如缸径/额定扭矩/丝杆型号/
# 重复定位精度按业务要求先不动,保持原值)
PARAM_CELLS = {
    "产品型号": (1, 1),
    "有效行程(mm)": (2, 3),
    "电机功率(KW)": (3, 1),
    "额定转速(rpm)": (3, 3),
    "最高转速（rpm）": (4, 3),
    "丝杆导程（mm）": (5, 3),
    "减速比": (6, 1),
    "额定推力(KN)": (7, 1),
    "额定速度(mm/s)": (8, 1),
    "电机安装方式": (9, 1),
    "电机品牌型号": (10, 1),
    "其他说明": (11, 1),
}

_NAME_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    "_.- " + "".join(chr(c) for c in range(0x4E00, 0x9FFF + 1))
)


def _safe_name(name):
    return bool(name) and all(ch in _NAME_CHARS for ch in name)


def find_drawing_source(model_id):
    """返回 output/<model_id>/drawing_source.json 的绝对路径,不存在返回 None"""
    if not _safe_name(model_id):
        return None
    p = os.path.join(common.OUT_DIR, model_id, SOURCE_NAME)
    return p if os.path.isfile(p) else None


def _load_series_config(model_id):
    """由 model_id 推断系列配置(直连/折返)"""
    sel = rb.parse_model_code(model_id)
    series_name = f"{sel['series']}直连" if sel["type"].upper() == "E" \
        else f"{sel['series']}折返"
    try:
        return rb.load_config(series_name), series_name, sel
    except Exception:
        return None, series_name, sel


def _stroke_number(model_id, spec):
    s = spec.get("stroke")
    if s is not None and str(s).strip() != "":
        return int(float(str(s)))
    m = re.search(r"L(\d+)", model_id)
    return int(m.group(1)) if m else None


def _motor_name(motor_key, series_cfg):
    """电机的完整写法:优先系列配置里的 name,其次全局编号表,最后原样返回 key

    型号末段写编号(D75B)时,刹车/功率信息只存在 name 里,判定刹车必须走这里。
    """
    if not motor_key:
        return ""
    mc = (series_cfg or {}).get("motor", {}).get(motor_key) or {}
    return mc.get("name") or rb.MOTOR_CODES.get(motor_key) or str(motor_key)


def format_motor_installation(model_id, motor_key, series_cfg):
    """电机安装方式:方向(直连/折返) + 刹车 + 减速机"""
    sel = rb.parse_model_code(model_id)
    direction = "折返" if sel["type"].upper() == "F" else "直连"
    parts = [direction]
    if "刹车" in _motor_name(motor_key, series_cfg):
        parts.append("带刹车")
    reducer = (series_cfg or {}).get("motor", {}).get(motor_key, {}).get("reducer")
    if reducer:
        parts.append(f"配{reducer}")
    return " ".join(parts)


def format_motor_brand_model(motor_key, series_cfg):
    """电机品牌型号:优先 brand+model,缺省回退 motor key(零侵入)"""
    mc = (series_cfg or {}).get("motor", {}).get(motor_key, {})
    brand, model = mc.get("brand"), mc.get("model")
    if brand and model:
        return f"{brand} {model}"
    return motor_key or ""


def _set_title_field(doc, key, value):
    for f in doc.get("title_block", {}).get("fields", []):
        if f.get("key") == key:
            f["value"] = value
            return True
    return False


def _find_param_table(doc):
    for t in doc.get("tables", []):
        for cell in t.get("cells", []):
            if cell.get("text") == "技术参数":
                return t
    return None


def _set_cell(table, r, c, text):
    for cell in table.get("cells", []):
        if cell.get("r") == r and cell.get("c") == c:
            cell["text"] = text
            return True
    return False


def apply_spec(doc, model_id, spec, series_cfg=None):
    """原地回填 spec 到 doc,返回 doc。只写 title_block.value 与 tables.cells.text。"""
    if series_cfg is None:
        series_cfg, _, _ = _load_series_config(model_id)
    sel = rb.parse_model_code(model_id)
    stroke_num = _stroke_number(model_id, spec)

    # ---- 标题栏 ----
    _set_title_field(doc, "model", model_id)
    if stroke_num is not None:
        _set_title_field(doc, "stroke", f"{stroke_num}mm")
    _set_title_field(doc, "name", f"{sel['series']}液压缸")
    _set_title_field(doc, "scale", "1:1")
    _set_title_field(doc, "date", date.today().strftime("%Y-%m-%d"))
    if stroke_num is not None and series_cfg:
        c_const = (series_cfg.get("cylinder") or {}).get("C")
        if c_const is not None:
            _set_title_field(doc, "d1", f"{stroke_num + int(c_const)}mm")

    # ---- 技术参数表 ----
    table = _find_param_table(doc)
    if not table:
        return doc

    def put(label, text):
        r, c = PARAM_CELLS[label]
        _set_cell(table, r, c, text)

    put("产品型号", model_id)
    if stroke_num is not None:
        put("有效行程(mm)", f"{stroke_num}mm")

    motor = spec.get("motor")
    motor_power = spec.get("motorPower")
    if motor_power is not None and str(motor_power) != "":
        put("电机功率(KW)", str(motor_power))
    rated = spec.get("motorRatedSpeed")
    if rated is not None and str(rated) != "":
        put("额定转速(rpm)", str(rated))
    maxsp = spec.get("motorMaxSpeed")
    if maxsp is not None and str(maxsp) != "":
        put("最高转速（rpm）", str(maxsp))
    travel = spec.get("travel")
    if travel is not None and str(travel) != "":
        put("丝杆导程（mm）", f"{travel}mm")
    ratio = spec.get("reductionRatio")
    if ratio is not None and str(ratio) != "":
        put("减速比", str(ratio))

    thrust = spec.get("screwThrust")
    if thrust not in (None, ""):
        try:
            # 前端单位为 kgf,表要 KN:严格物理换算 1 kgf = 0.00980665 kN
            kn = float(thrust) * 0.00980665
            put("额定推力(KN)", f"{kn:.2f}")
        except (TypeError, ValueError):
            pass
    speed = spec.get("ratedSpeed")
    if speed is not None and str(speed) != "":
        put("额定速度(mm/s)", str(speed))

    if motor:
        put("电机安装方式", format_motor_installation(model_id, motor, series_cfg))
        put("电机品牌型号", format_motor_brand_model(motor, series_cfg))

    remark_parts = []
    if spec.get("sizeStandard"):
        remark_parts.append(str(spec["sizeStandard"]))
    if spec.get("remark"):
        remark_parts.append(str(spec["remark"]))
    if remark_parts:
        put("其他说明", " ".join(remark_parts))

    return doc
