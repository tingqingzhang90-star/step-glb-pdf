# -*- coding: utf-8 -*-
"""系列配置生成测试

电机表有 [电机, 减速机, On, Off] 与 [电机减速机, On, Off] 两种列结构,
JDG 系列用后者,按下标硬取会 IndexError,这里锁住按表头定位的行为。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/test_build_config.py -v
"""
import json
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

pytest.importorskip("openpyxl")

from core import build_config as bc  # noqa: E402
from core import paths  # noqa: E402


def _write_xlsx(path, rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    wb.save(path)


def test_build_motor_reads_four_column_table():
    rows = [["电机", "减速机", "OnFeature", "OffFeature"],
            ["11kw电机", "AB182", "AB220-L1<1>,11kw<1>", "7.5kw<1>"]]
    cfg = bc.build_motor(rows)
    assert cfg["11kw电机"]["reducer"] == "AB182"
    assert cfg["11kw电机"]["on"] == ["AB220-L1", "11kw"]
    assert cfg["11kw电机"]["off"] == ["7.5kw"]


def test_build_motor_reads_three_column_table():
    """JDG 系列只有三列,少一列减速机"""
    rows = [["电机减速机", "OnFeature", "OffFeature"],
            ["汇川100w", "汇川100w<1>", "汇川100w刹车<1>"]]
    cfg = bc.build_motor(rows)
    assert cfg["汇川100w"]["on"] == ["汇川100w"]
    assert cfg["汇川100w"]["off"] == ["汇川100w刹车"]
    assert cfg["汇川100w"]["reducer"] == ""


def test_build_series_config_end_to_end(monkeypatch, tmp_path):
    lib = tmp_path / "图库项目" / "测试系列"
    lib.mkdir(parents=True)
    _write_xlsx(lib / "安装方式.xlsx",
                [["安装方式", "OnFeature", "OffFeature"],
                 ["H2(测试底部法兰)", "测试前盖<1>", "测试前法兰<1>"]])
    _write_xlsx(lib / "负载连接方式.xlsx",
                [["负载连接方式", "OnFeature", "OffFeature"],
                 ["K1(测试螺纹头)", "测试螺纹头<1>", ""]])
    _write_xlsx(lib / "电机减速机.xlsx",
                [["电机减速机", "OnFeature", "OffFeature"],
                 ["汇川100w", "汇川100w<1>", ""]])
    _write_xlsx(lib / "缸体长度.xlsx",
                [["行程", "D1"], ["L50", "135"], ["L51", "136"]])
    monkeypatch.setattr(bc, "LIB_ROOT", str(tmp_path / "图库项目"))

    parts = tmp_path / "parts_transform.json"
    with open(parts, "w", encoding="utf-8") as f:
        json.dump({"测试缸体-1": {"step_file": "测试缸体.step"},
                   "测试前盖-1": {"step_file": "测试前盖.step"},
                   "测试螺纹头-1": {"step_file": "测试螺纹头.step"},
                   "测试前法兰-1": {"step_file": "测试前法兰.step"}}, f)

    config = bc.build_series_config("测试系列", str(parts))

    assert config["series"] == "测试系列"
    assert config["cylinder_part"] == "测试缸体"
    assert list(config["motor"]) == ["汇川100w"]
    assert config["mount"]["H2"]["on"] == ["测试前盖"]
    assert config["mount"]["H2"]["off"] == ["测试前法兰"]
    # 首列"代号(文字说明)"拆开:代号作 key 拼型号,原文留在 name 供面板展示
    assert config["mount"]["H2"]["name"] == "H2(测试底部法兰)"
    assert config["load"]["K1"]["name"] == "K1(测试螺纹头)"
    # 受控件 = 三张表 on/off 里出现过的名字(含电机本身),零件表里剩下的进 base_parts
    assert config["base_parts"] == ["测试缸体"]
    assert config["controlled_count"] == 4


def test_write_series_config_lands_in_configs(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "CONFIG_DIR", str(tmp_path / "configs"))
    config = {"series": "测试系列", "mount": {}, "load": {}, "motor": {}}
    out = bc.write_series_config(config)
    assert out == os.path.join(str(tmp_path / "configs"), "测试系列.json")
    assert os.path.exists(out)
