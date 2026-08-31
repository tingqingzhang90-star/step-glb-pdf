# -*- coding: utf-8 -*-
"""零件库路径解析测试

library/ 是导出产物(不入库),本机未导出时整文件跳过。

覆盖:系列目录/共享件目录的层级约定、set_series 切换生效、
已导出系列的每个 step_file 都能被 resolve_part_file 定位到。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/test_library_paths.py -v
"""
import json
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from core import paths  # noqa: E402
from core import rebuild_assembly as rb  # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.path.isdir(paths.SERIES_ROOT),
    reason="零件库 library/ 未导出,跳过路径解析测试",
)


def test_parts_dir_lives_under_series_dir():
    assert paths.parts_dir("250直连") == os.path.join(
        paths.SERIES_ROOT, "250直连", "parts")


def test_shared_dir_is_last_fallback():
    assert paths.part_search_dirs("250直连")[-1] == paths.SHARED_PARTS_DIR


def test_set_series_switches_active_paths():
    rb.set_series("250直连")
    assert rb.PARTS_DIR == paths.parts_dir("250直连")
    assert rb.MATRIX_JSON == paths.transform_json("250直连")


def test_all_parts_of_exported_series_are_resolvable():
    """变换矩阵引用的每个 STEP 都要能在 系列目录 或 共享件目录 找到"""
    series = paths.list_series()
    assert series, "library/series 下没有任何已导出系列"
    for name in series:
        tj = paths.transform_json(name)
        if not os.path.exists(tj):
            continue
        rb.set_series(name)
        with open(tj, "r", encoding="utf-8") as f:
            data = json.load(f)
        missing = sorted({
            info.get("step_file", "")
            for info in data.values()
            if not os.path.exists(rb.resolve_part_file(info.get("step_file", "")))
        })
        assert not missing, f"{name} 缺少零件文件: {missing}"
