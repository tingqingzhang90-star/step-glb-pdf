# -*- coding: utf-8 -*-
"""装配资源查询端点测试

覆盖 GET /api/resources/<model_code>:同型号复用命中判断。
只读端点,按 output/<model_code>/ 下产物是否存在返回标志与相对路径,不触发构建。
用 tmp_path 作为 OUT_DIR,不污染真实目录。
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from web import common, app as web_app  # noqa: E402

MODEL = "250-E-H3K2-L100-D75B"
_FULL_ARTIFACTS = ("assembly.glb", "assembly.step", "cylinder.step",
                   "drawing_source.json", "drawing.pdf")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "OUT_DIR", str(tmp_path))
    web_app.app.config["TESTING"] = True
    return web_app.app.test_client()


def _touch(path):
    with open(path, "wb") as f:
        f.write(b"x")


def test_resources_full_hit(client, tmp_path):
    model_dir = tmp_path / MODEL
    model_dir.mkdir(parents=True, exist_ok=True)
    for name in _FULL_ARTIFACTS:
        _touch(model_dir / name)

    body = client.get(f"/api/resources/{MODEL}").get_json()
    assert body["ok"] is True
    assert body["cached"] is True
    assert body["model"]["available"] is True
    assert body["model"]["glb_file"] == f"{MODEL}/assembly.glb"
    assert body["model"]["step_file"] == f"{MODEL}/assembly.step"
    assert body["cylinder"]["available"] is True
    assert body["drawing_source"]["available"] is True
    assert body["drawing"]["available"] is True
    assert body["drawing"]["pdf_url"] == f"{MODEL}/drawing.pdf"


def test_resources_missing_model(client):
    body = client.get(f"/api/resources/{MODEL}").get_json()
    assert body["ok"] is True
    assert body["cached"] is False
    assert body["model"]["available"] is False
    assert body["model"]["glb_file"] is None
    assert body["drawing_source"]["available"] is False


def test_resources_partial_model_not_available(client, tmp_path):
    model_dir = tmp_path / MODEL
    model_dir.mkdir(parents=True, exist_ok=True)
    _touch(model_dir / "assembly.glb")
    _touch(model_dir / "drawing_source.json")

    body = client.get(f"/api/resources/{MODEL}").get_json()
    assert body["model"]["available"] is False
    assert body["cached"] is False
    assert body["drawing_source"]["available"] is True
