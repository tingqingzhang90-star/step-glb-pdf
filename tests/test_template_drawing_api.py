# -*- coding: utf-8 -*-
"""模板出图接口测试

覆盖 /api/template-drawing/* 五个接口的入参校验、同系列校验、
结果转换与下载路径安全。出图管线用 monkeypatch 打桩,避免依赖
pythonOCC 与真实模型文件(那属于集成测试范畴)。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/ -v
"""
import io
import json
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from web import app as web_app
from web import common as web_common
from web import task_pool
from web.blueprints import template_helpers as th


@pytest.fixture(scope="module")
def srv():
    """聚合路由实际读取的对象,供 monkeypatch 打桩

    模板出图路由读 web.common(OUT_DIR / PROJECT_ROOT)与
    web.blueprints.template_helpers(TEMPLATES_DIR),打桩要打到这些模块上,
    否则路由仍读真实目录。
    """
    class _Srv:
        app = web_app.app
        pool = task_pool.get_pool()
        _template_identity = staticmethod(th.template_identity)
        _reject_cross_series = staticmethod(th.reject_cross_series)

    return _Srv()


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
    monkeypatch.setattr(th, "TEMPLATES_DIR", str(tmp_path))
    res = client.post("/api/template-drawing/upload",
                      json=_template_doc("250-E-H2K1-L900-D99"))
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["template_id"] == "250-E-H2K1-L900-D99"
    assert body["identity"] == "250-E-H2K1"
    assert (tmp_path / "250-E-H2K1-L900-D99.json").exists()


def test_upload_multipart_ok(client, tmp_path, monkeypatch):
    monkeypatch.setattr(th, "TEMPLATES_DIR", str(tmp_path))
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
    monkeypatch.setattr(th, "TEMPLATES_DIR", str(tmp_path))
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
    monkeypatch.setattr(web_common, "OUT_DIR", str(out))

    res = client.get(
        "/api/template-drawing/series-models?identity=250-E-H2K1")
    codes = [m["model_code"] for m in res.get_json()["models"]]
    assert res.get_json()["identity"] == "250-E-H2K1"
    assert "250-E-H2K1-L100-D11" in codes
    assert "250-E-H2K1-L200-D55" in codes
    assert "999-X-YYYY-L1-D1" not in codes
    assert "250-E-H2K1-EMPTY-D1" not in codes


def test_series_models_accepts_template_id(client, tmp_path, monkeypatch):
    monkeypatch.setattr(web_common, "OUT_DIR", str(tmp_path))
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
    monkeypatch.setattr(th, "TEMPLATES_DIR", str(tmp_path))
    res = client.post("/api/template-drawing/generate",
                      json={"template_id": "nope", "models": ["a"]})
    assert res.status_code == 404


def test_generate_rejects_cross_series(client, tmp_path, monkeypatch):
    monkeypatch.setattr(th, "TEMPLATES_DIR", str(tmp_path))
    (tmp_path / "t.json").write_text(
        json.dumps(_template_doc()), encoding="utf-8")
    res = client.post("/api/template-drawing/generate", json={
        "template_id": "t", "models": ["999-X-YYYY-L1-D1"]})
    assert res.status_code == 400
    body = res.get_json()
    assert body["rejected"] == ["999-X-YYYY-L1-D1"]


def _ok_result(model_code):
    return {
        "model_code": model_code, "ok": True,
        "pdf": os.path.join(_PROJECT_ROOT, "output", model_code,
                            "drawing_frontend.pdf"),
        "svg": None, "unmatched": [],
        "dims": [{"id": "dim_1", "status": "matched", "type": "linear",
                  "mode": "single", "reason": ""}],
        "elapsed": 1.0,
    }


def test_generate_returns_relative_pdf_path(client, srv, tmp_path, monkeypatch):
    """PDF 绝对路径应转换为相对项目根,供下载接口使用"""
    monkeypatch.setattr(th, "TEMPLATES_DIR", str(tmp_path))
    # 出图默认在子进程执行,打桩对子进程无效,故切到 inline 模式(主进程线程)
    monkeypatch.setattr(srv.pool, "inline", True)
    (tmp_path / "t.json").write_text(
        json.dumps(_template_doc()), encoding="utf-8")

    # batch_drawing 顶层依赖 pythonOCC,无 OCC 的环境自动跳过
    bd = pytest.importorskip("batch.batch_drawing")
    monkeypatch.setattr(
        bd, "prepare_base",
        lambda template_doc, out_dir, parallel_views=False: {
            "view_names": ["left"], "views": {}, "refs": [], "profile": {}})
    monkeypatch.setattr(
        bd, "generate_one_frontend",
        lambda model_code, template_doc, base_views, base_refs, base_profile,
               out_dir, view_names=None: _ok_result(model_code))

    res = client.post("/api/template-drawing/generate",
                      json={"template_id": "t",
                            "models": ["250-E-H2K1-L100-D11"]})
    body = res.get_json()
    assert body["ok"] is True
    item = body["results"][0]
    assert item["pdf"] == "output/250-E-H2K1-L100-D11/drawing_frontend.pdf"
    assert item["dims"][0]["status"] == "matched"


def test_generate_reports_pipeline_error(client, srv, tmp_path, monkeypatch):
    """基准任务失败应整体返回 500"""
    monkeypatch.setattr(th, "TEMPLATES_DIR", str(tmp_path))
    monkeypatch.setattr(srv.pool, "inline", True)
    (tmp_path / "t.json").write_text(
        json.dumps(_template_doc()), encoding="utf-8")

    def boom(template_doc, out_dir, parallel_views=False):
        raise RuntimeError("OCC 炸了")

    bd = pytest.importorskip("batch.batch_drawing")
    monkeypatch.setattr(bd, "prepare_base", boom)

    res = client.post("/api/template-drawing/generate",
                      json={"template_id": "t",
                            "models": ["250-E-H2K1-L100-D11"]})
    assert res.status_code == 500
    assert "OCC 炸了" in res.get_json()["error"]


def test_generate_submits_one_task_per_model(client, srv, tmp_path, monkeypatch):
    """批次内每个型号各提交一个任务,才能并行而不是排队

    去重 key 按 模板+型号 生成:同型号并发请求合并成同一任务,避免
    两个用户同时写同一个 output 目录。
    """
    monkeypatch.setattr(th, "TEMPLATES_DIR", str(tmp_path))
    (tmp_path / "t.json").write_text(
        json.dumps(_template_doc()), encoding="utf-8")

    submitted = []

    def fake_run(kind, key, payload, timeout=None):
        submitted.append((kind, key))
        return {"view_names": ["left"], "views": {}, "refs": [], "profile": {}}

    def fake_submit(kind, key, payload, client=None):
        submitted.append((kind, key))
        return "tpl-one-%d" % len(submitted), False

    def fake_wait(task_id, timeout=None):
        return _ok_result("250-E-H2K1-L100-D11")

    monkeypatch.setattr(srv.pool, "run", fake_run)
    monkeypatch.setattr(srv.pool, "submit", fake_submit)
    monkeypatch.setattr(srv.pool, "wait", fake_wait)

    models = ["250-E-H2K1-L100-D11", "250-E-H2K1-L200-D55"]
    res = client.post("/api/template-drawing/generate",
                      json={"template_id": "t", "models": models})
    assert res.status_code == 200
    assert len(res.get_json()["results"]) == 2

    # 1 个基准任务 + 每型号各 1 个出图任务
    assert submitted == [
        ("template-base", "tpl-base:t"),
        ("template-one", "tpl:t:250-E-H2K1-L100-D11"),
        ("template-one", "tpl:t:250-E-H2K1-L200-D55"),
    ]


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
    monkeypatch.setattr(web_common, "PROJECT_ROOT", str(tmp_path))
    res = client.get("/api/template-drawing/download/a.pdf")
    assert res.status_code == 200
    assert res.headers["Content-Type"] == "application/pdf"
    assert "attachment" in res.headers["Content-Disposition"]


def test_preview_is_inline_not_attachment(client, tmp_path, monkeypatch):
    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(web_common, "PROJECT_ROOT", str(tmp_path))
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
