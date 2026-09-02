# -*- coding: utf-8 -*-
"""模板出图接口测试

覆盖 /api/template-drawing/* 五个接口的入参校验、同系列校验、
结果转换与下载路径安全。出图管线用 monkeypatch 打桩,避免依赖
pythonOCC 与真实模型文件(那属于集成测试范畴)。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/ -v
"""
import importlib.util
import io
import json
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

_SERVER = os.path.join(_PROJECT_ROOT, "src", "web", "server.py")


def _load_server():
    """按文件路径加载 Flask 服务模块

    注册进 sys.modules,否则 monkeypatch.setattr("cad_server.X") 这种
    字符串形式的目标无法解析。
    """
    if "cad_server" in sys.modules:
        return sys.modules["cad_server"]
    spec = importlib.util.spec_from_file_location("cad_server", _SERVER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cad_server"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def srv():
    return _load_server()


@pytest.fixture
def client(srv):
    srv.app.config["TESTING"] = True
    return srv.app.test_client()


def _template_doc(model_id="250-E-H2K1-L100-D11"):
    return {
        "model_id": model_id,
        "sheet": {"size": "A3", "width": 420, "height": 297},
        "views": [{"id": "view_1", "source_view": "left",
                   "x": 10, "y": -2, "scale": 1}],
        "annotations": [{"id": "dim_1", "type": "linear", "mode": "single"}],
    }


# -------------------- 上传 --------------------

def test_upload_json_body_ok(client, tmp_path, monkeypatch):
    monkeypatch.setattr("cad_server.TEMPLATES_DIR", str(tmp_path))
    res = client.post("/api/template-drawing/upload",
                      json=_template_doc("250-E-H2K1-L900-D99"))
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["template_id"] == "250-E-H2K1-L900-D99"
    assert body["identity"] == "250-E-H2K1"
    assert (tmp_path / "250-E-H2K1-L900-D99.json").exists()


def test_upload_multipart_ok(client, tmp_path, monkeypatch):
    monkeypatch.setattr("cad_server.TEMPLATES_DIR", str(tmp_path))
    data = {"file": (io.BytesIO(json.dumps(_template_doc()).encode("utf-8")),
                     "tpl.json")}
    res = client.post("/api/template-drawing/upload", data=data,
                      content_type="multipart/form-data")
    assert res.status_code == 200
    assert res.get_json()["ok"] is True


def test_upload_rejects_missing_model_id(client):
    res = client.post("/api/template-drawing/upload", json={"views": [{}]})
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_upload_rejects_empty_views(client):
    res = client.post("/api/template-drawing/upload",
                      json={"model_id": "250-E-H2K1-L100-D11", "views": []})
    assert res.status_code == 400


def test_upload_rejects_bad_json(client, tmp_path, monkeypatch):
    monkeypatch.setattr("cad_server.TEMPLATES_DIR", str(tmp_path))
    data = {"file": (io.BytesIO(b"{ not json"), "bad.json")}
    res = client.post("/api/template-drawing/upload", data=data,
                      content_type="multipart/form-data")
    assert res.status_code == 400
    assert "UTF-8 JSON" in res.get_json()["error"]


# -------------------- 同系列型号 --------------------

def test_series_models_requires_identity(client):
    res = client.get("/api/template-drawing/series-models")
    assert res.status_code == 400


def test_series_models_filters_by_identity(client, tmp_path, monkeypatch):
    out = tmp_path
    for code in ("250-E-H2K1-L100-D11", "250-E-H2K1-L200-D55",
                 "999-X-YYYY-L1-D1"):
        d = out / code
        d.mkdir()
        (d / "assembly.step").write_bytes(b"")
    # 无形状文件的目录应被跳过
    (out / "250-E-H2K1-EMPTY-D1").mkdir()
    monkeypatch.setattr("cad_server.OUT_DIR", str(out))

    res = client.get(
        "/api/template-drawing/series-models?identity=250-E-H2K1")
    codes = [m["model_code"] for m in res.get_json()["models"]]
    assert res.get_json()["identity"] == "250-E-H2K1"
    assert "250-E-H2K1-L100-D11" in codes
    assert "250-E-H2K1-L200-D55" in codes
    assert "999-X-YYYY-L1-D1" not in codes
    assert "250-E-H2K1-EMPTY-D1" not in codes


def test_series_models_accepts_template_id(client, tmp_path, monkeypatch):
    monkeypatch.setattr("cad_server.OUT_DIR", str(tmp_path))
    res = client.get(
        "/api/template-drawing/series-models"
        "?template_id=250-E-H2K1-L100-D11")
    assert res.status_code == 200
    assert res.get_json()["identity"] == "250-E-H2K1"


# -------------------- 生成 --------------------

def test_generate_requires_template_id(client):
    res = client.post("/api/template-drawing/generate", json={"models": ["a"]})
    assert res.status_code == 400


def test_generate_rejects_empty_models(client):
    res = client.post("/api/template-drawing/generate",
                      json={"template_id": "x", "models": []})
    assert res.status_code == 400


def test_generate_rejects_unknown_template(client, tmp_path, monkeypatch):
    monkeypatch.setattr("cad_server.TEMPLATES_DIR", str(tmp_path))
    res = client.post("/api/template-drawing/generate",
                      json={"template_id": "nope", "models": ["a"]})
    assert res.status_code == 404


def test_generate_rejects_cross_series(client, tmp_path, monkeypatch):
    monkeypatch.setattr("cad_server.TEMPLATES_DIR", str(tmp_path))
    (tmp_path / "t.json").write_text(
        json.dumps(_template_doc()), encoding="utf-8")
    res = client.post("/api/template-drawing/generate", json={
        "template_id": "t", "models": ["999-X-YYYY-L1-D1"]})
    assert res.status_code == 400
    body = res.get_json()
    assert body["rejected"] == ["999-X-YYYY-L1-D1"]


def test_generate_returns_relative_pdf_path(client, srv, tmp_path, monkeypatch):
    """PDF 绝对路径应转换为相对项目根,供下载接口使用"""
    monkeypatch.setattr("cad_server.TEMPLATES_DIR", str(tmp_path))
    # 出图默认在子进程执行,打桩对子进程无效,故切到 inline 模式(主进程线程)
    monkeypatch.setattr(srv.pool, "inline", True)
    (tmp_path / "t.json").write_text(
        json.dumps(_template_doc()), encoding="utf-8")

    def fake_run(models, template_doc, out_dir):
        return [{
            "model_code": models[0], "ok": True,
            "pdf": os.path.join(_PROJECT_ROOT, "output", models[0],
                                "drawing_frontend.pdf"),
            "svg": None, "unmatched": [],
            "dims": [{"id": "dim_1", "status": "matched",
                      "type": "linear", "mode": "single", "reason": ""}],
            "elapsed": 1.0,
        }]

    # batch_drawing 顶层依赖 pythonOCC,无 OCC 的环境自动跳过
    bd = pytest.importorskip("batch.batch_drawing")
    monkeypatch.setattr(bd, "run_frontend", fake_run)

    res = client.post("/api/template-drawing/generate",
                      json={"template_id": "t",
                            "models": ["250-E-H2K1-L100-D11"]})
    body = res.get_json()
    assert body["ok"] is True
    item = body["results"][0]
    assert item["pdf"] == "output/250-E-H2K1-L100-D11/drawing_frontend.pdf"
    assert item["dims"][0]["status"] == "matched"


def test_generate_reports_pipeline_error(client, srv, tmp_path, monkeypatch):
    monkeypatch.setattr("cad_server.TEMPLATES_DIR", str(tmp_path))
    # 同上:打桩 run_frontend 需要出图在主进程内执行
    monkeypatch.setattr(srv.pool, "inline", True)
    (tmp_path / "t.json").write_text(
        json.dumps(_template_doc()), encoding="utf-8")

    def boom(models, template_doc, out_dir):
        raise RuntimeError("OCC 炸了")

    bd = pytest.importorskip("batch.batch_drawing")
    monkeypatch.setattr(bd, "run_frontend", boom)

    res = client.post("/api/template-drawing/generate",
                      json={"template_id": "t",
                            "models": ["250-E-H2K1-L100-D11"]})
    assert res.status_code == 500
    assert "OCC 炸了" in res.get_json()["error"]


# -------------------- 下载 / 预览 --------------------

def test_download_blocks_path_traversal(client):
    res = client.get("/api/template-drawing/download/..%2F..%2Fetc%2Fpasswd")
    assert res.status_code in (400, 404)


def test_download_returns_404_for_missing_file(client):
    res = client.get("/api/template-drawing/download/output/nope/none.pdf")
    assert res.status_code == 404


def test_download_sends_attachment(client, tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr("cad_server._PROJECT_ROOT", str(tmp_path))
    res = client.get("/api/template-drawing/download/a.pdf")
    assert res.status_code == 200
    assert res.headers["Content-Type"] == "application/pdf"
    assert "attachment" in res.headers["Content-Disposition"]


def test_preview_is_inline_not_attachment(client, tmp_path, monkeypatch):
    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr("cad_server._PROJECT_ROOT", str(tmp_path))
    res = client.get("/api/template-drawing/preview/b.pdf")
    assert res.status_code == 200
    assert res.headers["Content-Type"] == "application/pdf"
    assert "attachment" not in res.headers.get("Content-Disposition", "")


# -------------------- 辅助函数 --------------------

@pytest.mark.parametrize("model_id,expected", [
    ("250-E-H2K1-L100-D11", "250-E-H2K1"),
    ("250-E-H2K1-L200-D55B", "250-E-H2K1"),
    ("999-X-YYYY-L1-D1", "999-X-YYYY"),
])
def test_template_identity(srv, model_id, expected):
    assert srv._template_identity(model_id) == expected


def test_reject_cross_series_returns_none_when_all_match(srv):
    assert srv._reject_cross_series(
        ["250-E-H2K1-L100-D11"], "250-E-H2K1") is None
