# -*- coding: utf-8 -*-
"""电机表端点测试

覆盖 GET /api/series/motor-table:从图库项目/<系列>/电机.xlsx 下发功率(kW)与扭矩,
供前端选型下拉与扭矩映射使用,前端不再硬编码。读真实图库,不污染目录。
"""
import os
import sys

import pytest

pytest.importorskip("openpyxl")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from core import paths  # noqa: E402
from web import common, app as web_app  # noqa: E402

SERIES = "250直连"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "OUT_DIR", str(tmp_path))
    web_app.app.config["TESTING"] = True
    return web_app.app.test_client()


@pytest.mark.skipif(
    not os.path.isdir(os.path.join(paths.LIB_ROOT, SERIES)),
    reason="缺少真实图库项目/%s 系列" % SERIES,
)
def test_motor_table_returns_power_and_torque(client):
    body = client.get("/api/series/motor-table?series=%s" % SERIES).get_json()
    assert body["ok"] is True
    assert body["series"] == SERIES
    assert body["motors"]
    for m in body["motors"]:
        assert m["code"]
        assert isinstance(m["power_kw"], (int, float))
    powers = {m["power_kw"] for m in body["motors"]}
    # 250直连 电机表含 5.5/7.5/11KW
    assert 5.5 in powers and 7.5 in powers and 11 in powers


def test_motor_table_missing_series_param(client):
    resp = client.get("/api/series/motor-table")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


@pytest.mark.skipif(
    not os.path.isdir(paths.LIB_ROOT),
    reason="缺少图库项目目录",
)
def test_motor_table_unknown_series_empty(client):
    body = client.get("/api/series/motor-table?series=不存在的系列XYZ").get_json()
    assert body["ok"] is True
    assert body["motors"] == []
