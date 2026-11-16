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


def test_resources_tolerant_of_yrj_brand_prefix(client, tmp_path):
    """产物按无前缀目录存储时,带 YRJ 前缀的型号也能命中,且路径指向真实目录"""
    from core import rebuild_assembly as rb

    no_prefix_dir = tmp_path / MODEL
    no_prefix_dir.mkdir(parents=True, exist_ok=True)
    for name in _FULL_ARTIFACTS:
        _touch(no_prefix_dir / name)

    branded = rb.with_brand(MODEL)
    body = client.get(f"/api/resources/{branded}").get_json()
    assert body["ok"] is True
    assert body["cached"] is True
    # 返回的路径必须按真实(无前缀)目录拼,下载才不 404
    assert body["model"]["glb_file"] == f"{MODEL}/assembly.glb"
    assert body["drawing_source"]["file"] == f"{MODEL}/drawing_source.json"
    assert body["drawing"]["pdf_url"] == f"{MODEL}/drawing.pdf"


def test_download_tolerant_of_yrj_brand_prefix(client, tmp_path):
    """/download 用带 YRJ 前缀型号请求、文件按无前缀目录存储时也能下载到"""
    from core import rebuild_assembly as rb

    no_prefix_dir = tmp_path / MODEL
    no_prefix_dir.mkdir(parents=True, exist_ok=True)
    _touch(no_prefix_dir / "drawing_source.json")

    branded = rb.with_brand(MODEL)
    res = client.get(f"/download/{branded}/drawing_source.json")
    assert res.status_code == 200

    # 原始(无前缀)写法仍正常
    assert client.get(f"/download/{MODEL}/drawing_source.json").status_code == 200
    # 不存在的文件仍 404
    assert client.get(f"/download/{branded}/not-exist.json").status_code == 404
