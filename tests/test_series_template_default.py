# -*- coding: utf-8 -*-
"""系列看板「指定同身份采用模板」测试

覆盖:
- find_template_by_identity 的人工指定优先级,及指定文件缺失时回退自动挑选;
- /api/series/template-default 入参校验(缺身份、模板不存在、跨身份);
- /api/series/coverage 暴露的候选模板与指定状态。

模板目录、配置目录、输出目录全部指向 tmp_path,不碰真实 data/ 与 output/。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/ -v
"""
import json
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from web import app as web_app  # noqa: E402
from web import common as web_common  # noqa: E402
from web.blueprints import template_helpers as th  # noqa: E402


@pytest.fixture
def client():
    web_app.app.config["TESTING"] = True
    return web_app.app.test_client()


@pytest.fixture
def tpl_dir(tmp_path, monkeypatch):
    """模板目录落 tmp_path;指定表在模板目录上一级,同样被隔离"""
    d = tmp_path / "engineering"
    d.mkdir()
    monkeypatch.setattr(th, "TEMPLATES_DIR", str(d))
    return d


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """mount/load/motor 三段的迷你配置,枚举出 160-E-H2K1 一个身份"""
    d = tmp_path / "configs"
    d.mkdir()
    cfg = {"mount": {"H2": {}}, "load": {"K1": {}}, "motor": {"4.4kw电机": {}}}
    (d / "160直连.json").write_text(
        json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(web_common, "CONFIG_DIR", str(d))
    monkeypatch.setattr(web_common, "OUT_DIR", str(tmp_path / "out"))
    return d


def _template_doc(model_id, annotation_count=1):
    return {
        "model_id": model_id,
        "template_identity": th.template_identity(model_id),
        "views": [{"id": "view_1"}],
        "annotations": [{"id": "dim_%d" % i} for i in range(annotation_count)],
    }


def _write(tpl_dir, model_id, annotation_count):
    (tpl_dir / f"{model_id}.json").write_text(
        json.dumps(_template_doc(model_id, annotation_count)), encoding="utf-8")


# -------------------- 查找优先级 --------------------

def test_auto_picks_most_annotated(tpl_dir):
    _write(tpl_dir, "250-E-H2K1-L100-D11", 5)
    _write(tpl_dir, "250-E-H2K1-L200-D11", 1)
    tpl_id, _ = th.find_template_by_identity("250-E-H2K1")
    assert tpl_id == "250-E-H2K1-L100-D11"


def test_pinned_template_wins_over_auto(tpl_dir):
    _write(tpl_dir, "250-E-H2K1-L100-D11", 5)
    _write(tpl_dir, "250-E-H2K1-L200-D11", 1)
    th.set_template_default("250-E-H2K1", "250-E-H2K1-L200-D11")
    tpl_id, _ = th.find_template_by_identity("250-E-H2K1")
    assert tpl_id == "250-E-H2K1-L200-D11"


def test_other_identity_unaffected_by_pin(tpl_dir):
    _write(tpl_dir, "250-E-H2K1-L100-D11", 5)
    _write(tpl_dir, "250-E-H3K2-L100-D11", 2)
    th.set_template_default("250-E-H2K1", "250-E-H2K1-L100-D11")
    tpl_id, _ = th.find_template_by_identity("250-E-H3K2")
    assert tpl_id == "250-E-H3K2-L100-D11"


def test_missing_pinned_file_falls_back(tpl_dir):
    _write(tpl_dir, "250-E-H2K1-L100-D11", 5)
    th.set_template_default("250-E-H2K1", "250-E-H2K1-L900-D11")
    tpl_id, _ = th.find_template_by_identity("250-E-H2K1")
    assert tpl_id == "250-E-H2K1-L100-D11"


def test_clear_pin_restores_auto(tpl_dir):
    _write(tpl_dir, "250-E-H2K1-L100-D11", 5)
    _write(tpl_dir, "250-E-H2K1-L200-D11", 1)
    th.set_template_default("250-E-H2K1", "250-E-H2K1-L200-D11")
    th.set_template_default("250-E-H2K1", None)
    tpl_id, _ = th.find_template_by_identity("250-E-H2K1")
    assert tpl_id == "250-E-H2K1-L100-D11"


# -------------------- 指定接口 --------------------

def test_api_set_and_clear_default(client, tpl_dir):
    _write(tpl_dir, "250-E-H2K1-L200-D11", 1)
    res = client.post("/api/series/template-default", json={
        "identity": "250-E-H2K1", "template_id": "250-E-H2K1-L200-D11"})
    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    assert th.load_template_defaults() == {"250-E-H2K1": "250-E-H2K1-L200-D11"}

    res = client.post("/api/series/template-default", json={
        "identity": "250-E-H2K1", "template_id": None})
    assert res.status_code == 200
    assert th.load_template_defaults() == {}


def test_api_rejects_missing_identity(client, tpl_dir):
    res = client.post("/api/series/template-default",
                      json={"template_id": "250-E-H2K1-L200-D11"})
    assert res.status_code == 400


def test_api_rejects_unknown_template(client, tpl_dir):
    res = client.post("/api/series/template-default", json={
        "identity": "250-E-H2K1", "template_id": "250-E-H2K1-L999-D11"})
    assert res.status_code == 404
    assert th.load_template_defaults() == {}


def test_api_rejects_cross_identity(client, tpl_dir):
    _write(tpl_dir, "250-E-H3K2-L100-D11", 1)
    res = client.post("/api/series/template-default", json={
        "identity": "250-E-H2K1", "template_id": "250-E-H3K2-L100-D11"})
    assert res.status_code == 400
    assert "属于身份" in res.get_json()["error"]
    assert th.load_template_defaults() == {}


# -------------------- 看板数据 --------------------

def test_coverage_exposes_candidates_and_pin(client, tpl_dir, config_dir):
    _write(tpl_dir, "160-E-H2K1-L100-4.4kw电机", 2)
    _write(tpl_dir, "160-E-H2K1-L200-4.4kw电机", 7)
    th.set_template_default("160-E-H2K1", "160-E-H2K1-L100-4.4kw电机")

    row = client.get("/api/series/coverage").get_json()["rows"][0]
    tpl = row["template"]
    assert row["identity"] == "160-E-H2K1"
    assert tpl["pinned"] is True
    assert tpl["template_id"] == "160-E-H2K1-L100-4.4kw电机"
    assert [c["template_id"] for c in tpl["candidates"]] == [
        "160-E-H2K1-L200-4.4kw电机", "160-E-H2K1-L100-4.4kw电机"]


def test_coverage_without_pin_reports_auto(client, tpl_dir, config_dir):
    _write(tpl_dir, "160-E-H2K1-L100-4.4kw电机", 2)
    tpl = client.get("/api/series/coverage").get_json()["rows"][0]["template"]
    assert tpl["saved"] is True
    assert tpl["pinned"] is False
    assert tpl["template_id"] == "160-E-H2K1-L100-4.4kw电机"
