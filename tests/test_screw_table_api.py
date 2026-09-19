# -*- coding: utf-8 -*-
"""系列丝杆表端点测试

覆盖 GET /api/series/screw-table:按系列「名称」下发丝杆型号/导程/缸径,
供选型界面导程下拉与工程图规格回填使用。读真实 data/screw_table.xlsx,不污染目录。
"""
import os
import sys

import pytest

pytest.importorskip("openpyxl")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from core import build_config  # noqa: E402
from web import common, app as web_app  # noqa: E402

_HAS_TABLE = os.path.isfile(build_config.SCREW_TABLE_XLSX)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "OUT_DIR", str(tmp_path))
    web_app.app.config["TESTING"] = True
    return web_app.app.test_client()


@pytest.mark.skipif(not _HAS_TABLE, reason="缺少 data/screw_table.xlsx")
def test_screw_table_prefix_insensitive(client):
    a = client.get("/api/series/screw-table?series=YRJ45").get_json()
    b = client.get("/api/series/screw-table?series=45").get_json()
    assert a["ok"] is True and b["ok"] is True
    assert a["screws"] and a["screws"] == b["screws"]
    lead_map = {s["lead"]: s for s in a["screws"]}
    assert lead_map["04"]["screw_model"] == "1204"
    assert lead_map["04"]["bore"] == "30"
    assert lead_map["05"]["screw_model"] == "1205"


def test_screw_table_missing_series_param(client):
    resp = client.get("/api/series/screw-table")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_screw_table_unknown_series_empty(client):
    body = client.get("/api/series/screw-table?series=不存在的系列XYZ").get_json()
    assert body["ok"] is True
    assert body["screws"] == []
