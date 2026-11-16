# -*- coding: utf-8 -*-
"""项目路径解析 —— 所有模块的路径唯一真源。

背景:过去 parts_step/ 平铺全部系列零件,export_parts / rebuild_assembly /
build_config 各自拼绝对路径。多系列导出时零件名冲突、路径硬编码指向旧机器,
因此收敛到本模块,任何新代码禁止再自行 os.path.join(PROJECT_ROOT, ...)。
"""
import os
from typing import List

# 本文件位于 src/core/,需上溯三级: core → src → 项目根
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

# 原始 SW 图库(只读,不入库)
LIB_ROOT = os.path.join(PROJECT_ROOT, "图库项目")

# 导出产物:零件库
LIBRARY_ROOT = os.path.join(PROJECT_ROOT, "library")
SERIES_ROOT = os.path.join(LIBRARY_ROOT, "series")
# 跨系列共享件(电机、减速机等),不属于任何单一系列
SHARED_PARTS_DIR = os.path.join(LIBRARY_ROOT, "shared")

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CONFIG_DIR = os.path.join(DATA_DIR, "configs")
TEMPLATE_DIR = os.path.join(DATA_DIR, "templates")
OUT_DIR = os.path.join(PROJECT_ROOT, "output")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")


def series_dir(series: str) -> str:
    """系列根目录: library/series/<series>"""
    return os.path.join(SERIES_ROOT, series)


def parts_dir(series: str) -> str:
    """系列专属零件目录"""
    return os.path.join(series_dir(series), "parts")


def transform_json(series: str) -> str:
    """系列变换矩阵文件"""
    return os.path.join(series_dir(series), "parts_transform.json")


def meta_json(series: str) -> str:
    """系列导出元信息(源装配体、组件数、导出时间)"""
    return os.path.join(series_dir(series), "meta.json")


def config_path(series: str) -> str:
    """系列装配表配置: data/configs/<series>.json"""
    return os.path.join(CONFIG_DIR, f"{series}.json")


def log_path(name: str) -> str:
    """日志文件: logs/<name>.log"""
    return os.path.join(LOG_DIR, f"{name}.log")


def part_search_dirs(series: str) -> List[str]:
    """零件查找顺序:系列专属目录优先,共享件目录兜底"""
    return [parts_dir(series), SHARED_PARTS_DIR]


def list_series() -> List[str]:
    """已建库的系列名,按名称排序"""
    if not os.path.isdir(SERIES_ROOT):
        return []
    return sorted(d for d in os.listdir(SERIES_ROOT)
                  if os.path.isdir(os.path.join(SERIES_ROOT, d)))
