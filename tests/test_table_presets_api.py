# -*- coding: utf-8 -*-
"""表格模板接口测试

覆盖 /api/table-presets 的列表/新建/删除与入参校验、空目录、路径穿越防护。
落盘目录用 monkeypatch 指向 tmp_path,独立目录不污染真实 data/table-presets。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/ -v
"""
import json
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from web import app as web_app
from web.blueprints import table_presets as tp


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "PRESETS_DIR", str(tmp_path))
    web_app.app.config["TESTING"] = True
    return web_app.app.test_client()


def _sample_tables():
    return [{"id": "t1", "x": 10, "y": 20, "rows": 2, "cols": 3}]


# -------------------- 列表 --------------------

def test_list_empty_dir(client):
    res = client.get("/api/table-presets")
    assert res.status_code == 200
    assert res.get_json()["presets"] == []


def test_list_returns_saved_presets(client):
    client.post("/api/table-presets",
                json={"name": "标题栏", "tables": _sample_tables()})
    body = client.get("/api/table-presets").get_json()
    assert body["ok"] is True
    assert len(body["presets"]) == 1
    assert body["presets"][0]["name"] == "标题栏"
    # 列表直接返回完整内容,apply 可以本地直接灌回
    assert body["presets"][0]["tables"] == _sample_tables()


# -------------------- 新建 --------------------

def test_save_ok(client, tmp_path):
    res = client.post("/api/table-presets",
                      json={"name": "标题栏", "tables": _sample_tables()})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["id"].startswith("preset_")
    # 落盘文件名用返回 id,内容含完整 tables 供灌回
    doc = json.loads(
        (tmp_path / f"{data['id']}.json").read_text(encoding="utf-8"))
    assert doc["name"] == "标题栏"
    assert doc["tables"] == _sample_tables()


def test_save_rejects_missing_name(client):
    res = client.post("/api/table-presets", json={"tables": _sample_tables()})
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_save_rejects_empty_tables(client):
    res = client.post("/api/table-presets", json={"name": "x", "tables": []})
    assert res.status_code == 400


def test_save_rejects_bad_body(client):
    res = client.post("/api/table-presets", data="not json",
                      content_type="application/json")
    assert res.status_code == 400


# -------------------- 删除 --------------------

def test_delete_ok(client):
    data = client.post(
        "/api/table-presets",
        json={"name": "标题栏", "tables": _sample_tables()}).get_json()
    res = client.delete(f"/api/table-presets/{data['id']}")
    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    assert client.get("/api/table-presets").get_json()["presets"] == []


def test_delete_unknown_id(client):
    res = client.delete("/api/table-presets/preset_does_not_exist")
    assert res.status_code == 404


def test_delete_rejects_path_traversal(client):
    # id 含路径分隔符或非法字符,直接拒绝,不落盘/不读取
    res = client.delete("/api/table-presets/..%2F..%2Fetc")
    assert res.status_code == 400
    res2 = client.delete("/api/table-presets/foo/bar")
    assert res2.status_code == 400
