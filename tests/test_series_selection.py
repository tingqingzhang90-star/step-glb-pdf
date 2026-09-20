# -*- coding: utf-8 -*-
"""多系列选型适配测试

电机体系各系列不同(250 是三相异步电机、JDG 是汇川伺服),过去型号里的
电机段只允许 MOTOR_CODES 里的编号,新系列直接报错。现在编号与电机名都收。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/test_series_selection.py -v
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from core import paths  # noqa: E402
from core import rebuild_assembly as rb  # noqa: E402
from drawing import anchor_resolver as ar  # noqa: E402


def test_parse_model_code_maps_known_motor_code():
    sel = rb.parse_model_code("250-E-H2K1-L100-D11")
    assert sel["series"] == "250"
    assert sel["motor"] == "11kw电机"


def test_parse_model_code_accepts_motor_name():
    """JDG 系列用汇川伺服,型号里直接写电机名"""
    sel = rb.parse_model_code("JDG45-E-H2K1-L50-汇川100w")
    assert sel["series"] == "JDG45"
    assert sel["stroke"] == "L50"
    assert sel["motor"] == "汇川100w"


def test_parse_model_code_without_motor_segment():
    sel = rb.parse_model_code("JDG45-E-H2K1-L50")
    assert sel["motor"] is None


def test_parse_model_code_strips_yrj_brand_prefix():
    """型号带 YRJ 前缀时,解析出的系列号仍为 250(后端存储可能不带前缀)"""
    sel = rb.parse_model_code("YRJ250-E-H2K1-L100-D11")
    assert sel["series"] == "250"
    assert sel["motor"] == "11kw电机"


def test_parse_model_code_lowercase_yrj_brand_prefix():
    sel = rb.parse_model_code("yrj250-E-H2K1-L100-D11")
    assert sel["series"] == "250"


def test_template_identity_ignores_yrj_prefix():
    from drawing import frontend_template as th
    assert th.template_identity("YRJ250-E-H2K1-L100-D11") == "250-E-H2K1"
    assert th.template_identity("250-E-H2K1") == "250-E-H2K1"


def test_find_model_shape_tolerant_of_yrj_prefix(tmp_path):
    from drawing import frontend_template as th
    # 目录以无前缀写法存储,传入带前缀型号仍能找到
    no_brand = tmp_path / "250-E-H2K1-L100"
    no_brand.mkdir()
    step = no_brand / "assembly.step"
    step.write_text("dummy")
    assert th.find_model_shape(str(tmp_path), "YRJ250-E-H2K1-L100") == str(step)
    # 目录以带前缀写法存储,传入无前缀型号也能找到
    with_brand = tmp_path / "YRJ250-E-H3K2-L200"
    with_brand.mkdir()
    ystep = with_brand / "assembly.step"
    ystep.write_text("dummy")
    assert th.find_model_shape(str(tmp_path), "250-E-H3K2-L200") == str(ystep)


def test_resolve_motor_uses_series_default_when_unspecified():
    config = {"motor": {"汇川100w": {}, "汇川100w刹车": {}}}
    assert rb.resolve_motor(config, None) == "汇川100w"


def test_resolve_motor_keeps_250_default():
    config = {"motor": {"5.5KW电机": {}, "11kw电机": {}}}
    assert rb.resolve_motor(config, None) == "11kw电机"


def test_resolve_motor_rejects_motor_of_other_series():
    config = {"motor": {"汇川100w": {}}}
    with pytest.raises(ValueError):
        rb.resolve_motor(config, "11kw电机")


def test_resolve_motor_passthrough_when_series_has_no_motor_table():
    assert rb.resolve_motor({}, "任意电机") == "任意电机"


def test_load_model_parts_switches_active_series():
    """解析非默认系列后必须切换激活系列

    否则零件查找路径停在默认系列(250直连),会去 250直连 目录里找
    270缸体.step,读取 STEP 直接失败,批量出图接口 500。
    """
    if not os.path.exists(paths.config_path("270直连")):
        pytest.skip("缺少 270直连 系列配置")
    _, series_name, _, motor, _ = ar._load_model_parts("270-E-H3K2-L100-D11")
    assert series_name == "270直连"
    assert motor == "11kw电机"
    assert rb.PARTS_DIR == paths.parts_dir("270直连")
    assert rb.PART_SEARCH_PATH[0] == paths.parts_dir("270直连")
