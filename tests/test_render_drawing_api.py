# -*- coding: utf-8 -*-
"""render 出图端点测试

覆盖 POST /api/render-drawing:同系列复用 drawing_source.json、规格回填、
渲染出 PDF,且只写可编辑内容、不触发几何 build。

用真实 output 下的某份 drawing_source.json 作为只读夹具,复制到 tmp_path 后
monkeypatch OUT_DIR,落盘与源文件均不污染真实目录。
"""
import glob
import json
import os
import shutil
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from web import common, app as web_app  # noqa: E402
from web.drawing_spec_map import (  # noqa: E402
    find_drawing_source, format_motor_installation, apply_spec)


def _find_fixture_source():
    hits = glob.glob(os.path.join(common.OUT_DIR, "*", "drawing_source.json"))
    return hits[0] if hits else None


@pytest.fixture
def client_and_model(tmp_path, monkeypatch):
    src = _find_fixture_source()
    if not src:
        pytest.skip("真实 output 下无 drawing_source.json 夹具")
    model_id = os.path.basename(os.path.dirname(src))
    dest_dir = tmp_path / model_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest_dir / "drawing_source.json")
    monkeypatch.setattr(common, "OUT_DIR", str(tmp_path))
    web_app.app.config["TESTING"] = True
    return web_app.app.test_client(), model_id


def test_render_ok_and_fills_spec(client_and_model):
    client, model_id = client_and_model
    src_path = os.path.join(common.OUT_DIR, model_id, "drawing_source.json")
    with open(src_path, "r", encoding="utf-8") as f:
        before_source = f.read()
    spec = {
        "motor": "5.5KW电机",
        "motorPower": "5.5",
        "motorRatedSpeed": "3000",
        "motorMaxSpeed": "4500",
        "travel": "10",
        "reductionRatio": "2",
        "screwThrust": "5000",
        "ratedSpeed": "500",
        "sizeStandard": "标准",
        "remark": "测试备注",
    }
    res = client.post("/api/render-drawing",
                      json={"model_id": model_id, "spec": spec})
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["pdf_url"].endswith("drawing.pdf")

    pdf_path = os.path.join(common.OUT_DIR, model_id, "drawing.pdf")
    assert os.path.isfile(pdf_path) and os.path.getsize(pdf_path) > 0

    # 源文件未被写回:端点只渲染 PDF,不落盘 drawing_source.json
    src_path = os.path.join(common.OUT_DIR, model_id, "drawing_source.json")
    with open(src_path, "r", encoding="utf-8") as f:
        after = f.read()
    assert after == before_source, "端点不应修改 drawing_source.json"


def test_apply_spec_fills_rated_torque(client_and_model):
    client, model_id = client_and_model
    src_path = os.path.join(common.OUT_DIR, model_id, "drawing_source.json")
    with open(src_path, encoding="utf-8") as f:
        doc = json.load(f)
    apply_spec(doc, model_id, {"motorRatedTorque": 2.4})
    table = next(t for t in doc["tables"]
                 if any(c.get("text") == "技术参数" for c in t.get("cells", [])))
    cell = next(c for c in table["cells"] if c.get("r") == 4 and c.get("c") == 1)
    assert cell["text"] == "2.4"


def test_apply_spec_prefers_selection_names(client_and_model):
    client, model_id = client_and_model
    src_path = os.path.join(common.OUT_DIR, model_id, "drawing_source.json")
    with open(src_path, encoding="utf-8") as f:
        doc = json.load(f)
    apply_spec(doc, model_id, {"installationName": "H3(前法兰)", "motorBrandName": "安川"})
    table = next(t for t in doc["tables"]
                 if any(c.get("text") == "技术参数" for c in t.get("cells", [])))
    install = next(c for c in table["cells"] if c.get("r") == 9 and c.get("c") == 1)
    brand = next(c for c in table["cells"] if c.get("r") == 10 and c.get("c") == 1)
    assert install["text"] == "H3(前法兰)"
    assert brand["text"] == "安川"


def test_render_rejects_empty_model(client_and_model):
    client, _ = client_and_model
    res = client.post("/api/render-drawing", json={"model_id": "", "spec": {}})
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_render_404_when_source_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "OUT_DIR", str(tmp_path))
    web_app.app.config["TESTING"] = True
    client = web_app.app.test_client()
    res = client.post("/api/render-drawing",
                      json={"model_id": "250-E-H2K1-L999-无此型号电机", "spec": {}})
    assert res.status_code == 404
    assert res.get_json()["ok"] is False


def test_find_drawing_source_uses_safe_name(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "OUT_DIR", str(tmp_path))
    assert find_drawing_source("../etc/passwd") is None
    assert find_drawing_source("") is None


# -------------------- 电机安装方式(刹车判定) --------------------

@pytest.mark.parametrize("model_id,motor_key,series_cfg,expected", [
    # 型号写编号:刹车信息在系列配置的 name 里
    ("250-E-H2K1-L100-D75B", "D75B",
     {"motor": {"D75B": {"name": "D75B(7.5kw电机刹车）", "reducer": "AB-182"}}},
     "直连 带刹车 配AB-182"),
    ("250-F-H2K1-L100-D55B", "D55B",
     {"motor": {"D55B": {"name": "D55B(5.5KW刹车电机）", "reducer": "AB-182"}}},
     "折返 带刹车 配AB-182"),
    ("250-E-H2K1-L100-D75", "D75",
     {"motor": {"D75": {"name": "D75(7.5kw电机）"}}},
     "直连"),
    # 配置里没写 name 时回退全局编号表:D11(11kw电机)不带刹车
    ("250-E-H2K1-L100-D11", "D11", {}, "直连"),
    # 旧型号写电机名,仍要能识别刹车
    ("250-E-H2K1-L100-5.5KW刹车电机", "5.5KW刹车电机", {}, "直连 带刹车"),
])
def test_format_motor_installation_brake(model_id, motor_key, series_cfg, expected):
    assert format_motor_installation(model_id, motor_key, series_cfg) == expected
