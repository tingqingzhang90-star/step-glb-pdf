# -*- coding: utf-8 -*-
"""电机表生成期校验:重复代号与 OnFeature 功率错配会告警,结果保持兼容。"""
import logging
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from core import build_config as bc  # noqa: E402

HEADER = ["电机", "减速机", "OnFeature", "OffFeature"]


def test_warn_on_power_mismatch(caplog):
    rows = [HEADER,
            ["4.4kw电机(配160减速机)", "160减速机",
             "160减速机<1>,汇川5.5kw<3>", ""]]
    with caplog.at_level(logging.WARNING, logger="core.build_config"):
        cfg = bc.build_motor(rows)
    assert "功率不匹配" in caplog.text
    assert cfg["4.4kw电机"]["on"] == ["160减速机", "汇川5.5kw"]


def test_warn_on_duplicate_code_and_keep_last_row(caplog):
    rows = [HEADER,
            ["4.4kw电机(配115减速机)", "115减速机", "汇川4.4kw<1>", ""],
            ["4.4kw电机(配160减速机)", "160减速机", "汇川4.4kw<3>", ""]]
    with caplog.at_level(logging.WARNING, logger="core.build_config"):
        cfg = bc.build_motor(rows)
    assert "代号重复" in caplog.text
    assert cfg["4.4kw电机"]["name"] == "4.4kw电机(配160减速机)"


def test_no_warning_on_valid_table(caplog):
    rows = [HEADER,
            ["4.4kw电机(配160减速机)", "160减速机",
             "160减速机<1>,汇川4.4kw<3>", ""],
            ["5.5kw电机(配160减速机)", "160减速机",
             "160减速机<1>,汇川5.5kw<3>", ""]]
    with caplog.at_level(logging.WARNING, logger="core.build_config"):
        cfg = bc.build_motor(rows)
    assert "功率不匹配" not in caplog.text
    assert "代号重复" not in caplog.text
    assert cfg["4.4kw电机"]["power_kw"] == 4.4
    assert cfg["5.5kw电机"]["power_kw"] == 5.5


def test_parse_power_kw_handles_watt():
    assert bc.parse_power_kw("汇川1500w") == 1.5
    assert bc.parse_power_kw("4.4kw电机") == 4.4
    assert bc.parse_power_kw("160减速机") is None
