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

from core import rebuild_assembly as rb  # noqa: E402


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
