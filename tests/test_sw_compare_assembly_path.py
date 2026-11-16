# -*- coding: utf-8 -*-
"""SW 选型对比:装配体路径解析测试

回归点:旧实现按 dirname(_PROJECT_ROOT)/pdf修改/图库项目 拼绝对路径,
项目迁到 src 包结构后层级错位,两个候选目录都不存在,OpenDoc6 返回
errors=2(文件未找到)。现统一取 core.paths.LIB_ROOT,并在打开前给出明确报错。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/test_sw_compare_assembly_path.py -v
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from core import paths  # noqa: E402
from web.blueprints import sw_compare_ops as ops  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.isdir(paths.LIB_ROOT),
                               reason="本机无图库项目目录")


def test_assembly_lib_points_to_lib_root():
    assert ops.ASSEMBLY_LIB == paths.LIB_ROOT
    assert os.path.isdir(ops.ASSEMBLY_LIB)


def test_find_assembly_uses_convention_name():
    path = ops._find_assembly("250直连")
    assert os.path.isfile(path)
    assert os.path.basename(path) == "250直连装配体.SLDASM"


def test_find_assembly_falls_back_and_skips_variants():
    # JDG135折返 目录下没有 <系列名>装配体.SLDASM,回退取唯一的 .SLDASM
    path = ops._find_assembly("JDG135折返")
    assert os.path.isfile(path)
    assert os.path.basename(path) == "135折返装配体1.SLDASM"


def test_find_assembly_returns_missing_path_for_unknown_series():
    path = ops._find_assembly("不存在的系列")
    assert not os.path.exists(path)


def test_open_assembly_reports_missing_file_before_com():
    model, err = ops._open_assembly(None, os.path.join(ops.ASSEMBLY_LIB, "无.SLDASM"))
    assert model is None
    assert "装配体文件不存在" in err
