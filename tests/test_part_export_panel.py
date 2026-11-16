# -*- coding: utf-8 -*-
"""零件导出面板(5003)接口测试

用 Flask test_client,不启动服务、不连接 SolidWorks。
导出与预览都替换成假实现,只验证路由、状态聚合与任务互斥。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/test_part_export_panel.py -v
"""
import os
import sys
import time

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

pytest.importorskip("flask")
pytest.importorskip("win32com.client")

from web import part_export_server as srv  # noqa: E402


def _use_tmp_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(srv.paths, "LIB_ROOT", str(tmp_path / "图库项目"))
    monkeypatch.setattr(srv.paths, "SERIES_ROOT", str(tmp_path / "series"))
    monkeypatch.setattr(srv.paths, "SHARED_PARTS_DIR", str(tmp_path / "shared"))


def test_api_series_reports_status(monkeypatch, tmp_path):
    lib = tmp_path / "图库项目"
    (lib / "190直连").mkdir(parents=True)
    (lib / "190直连" / "190直连装配体.SLDASM").write_text("", encoding="utf-8")
    (lib / "160").mkdir(parents=True)
    _use_tmp_paths(monkeypatch, tmp_path)

    data = srv.app.test_client().get("/api/series").get_json()

    assert data["ok"] is True
    by_name = {s["series"]: s for s in data["series"]}
    asm = by_name["190直连"]["assemblies"]
    assert asm[0]["name"] == "190直连装配体.SLDASM"
    assert os.path.isfile(asm[0]["path"])  # 前端回传后要能直接当路径用
    assert by_name["190直连"]["status"]["part_count"] == 0
    assert by_name["160"]["assemblies"] == []


def test_api_series_counts_exported_parts(monkeypatch, tmp_path):
    _use_tmp_paths(monkeypatch, tmp_path)
    parts = tmp_path / "series" / "250折返" / "parts"
    parts.mkdir(parents=True)
    (parts / "250缸体.step").write_text("x", encoding="utf-8")
    (lib := tmp_path / "图库项目" / "250折返").mkdir(parents=True)

    data = srv.app.test_client().get("/api/series").get_json()
    item = next(s for s in data["series"] if s["series"] == "250折返")
    assert item["status"]["part_count"] == 1


def test_api_preview_returns_components(monkeypatch, tmp_path):
    part = tmp_path / "250缸体.SLDPRT"
    part.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        srv.pe, "preview_components",
        lambda series, assembly=None: {
            "assembly": "E:/x/250折返装配体.SLDASM",
            "components": [{"name": "250缸体-1", "path": str(part),
                            "suppressed": False, "transform_matrix": [0.0] * 16}],
        })
    _use_tmp_paths(monkeypatch, tmp_path)

    data = srv.app.test_client().get("/api/preview?series=250折返").get_json()

    assert data["ok"] is True
    assert data["components"][0]["file"] == "250缸体.SLDPRT"
    assert data["components"][0]["resolved"] is True
    assert data["components"][0]["has_matrix"] is True


def test_api_config_generates_series_config(monkeypatch, tmp_path):
    monkeypatch.setattr(
        srv.bc, "build_series_config",
        lambda series: {"series": series, "mount": {"H2": {}}, "load": {"K1": {}},
                        "motor": {"汇川100w": {}}, "cylinder_part": "45缸体",
                        "base_parts": ["45缸体"], "controlled_count": 13})
    monkeypatch.setattr(srv.bc, "write_series_config",
                        lambda config: str(tmp_path / "configs" / "JDG45直连.json"))
    _use_tmp_paths(monkeypatch, tmp_path)

    data = srv.app.test_client().post("/api/config",
                                      json={"series": "JDG45直连"}).get_json()

    assert data["ok"] is True
    assert data["config"]["motor"] == ["汇川100w"]
    assert data["config"]["cylinder_part"] == "45缸体"
    assert data["config"]["base_parts"] == 1


def test_api_config_reports_missing_series(monkeypatch, tmp_path):
    _use_tmp_paths(monkeypatch, tmp_path)
    res = srv.app.test_client().post("/api/config", json={})
    assert res.status_code == 400


def test_api_export_rejects_concurrent_task(monkeypatch, tmp_path):
    monkeypatch.setattr(srv.pe, "export_series", lambda *a, **k: time.sleep(0.6))
    # 导出线程结束时会顺带生成系列配置,不拦住会往真实 data/configs 里写测试垃圾
    monkeypatch.setattr(
        srv.bc, "build_series_config",
        lambda series: {"series": series, "mount": {}, "load": {}, "motor": {},
                        "cylinder_part": None, "base_parts": [], "controlled_count": 0})
    monkeypatch.setattr(srv.bc, "write_series_config",
                        lambda config: str(tmp_path / (config["series"] + ".json")))
    _use_tmp_paths(monkeypatch, tmp_path)
    client = srv.app.test_client()

    assert client.post("/api/export", json={"series": "A"}).get_json()["ok"] is True
    second = client.post("/api/export", json={"series": "B"})
    assert second.status_code == 409

    time.sleep(0.8)  # 等后台线程结束,避免污染后续用例
    assert srv.app.test_client().get("/api/export/status").get_json()["task"]["finished"]


def test_api_export_requires_series(monkeypatch, tmp_path):
    _use_tmp_paths(monkeypatch, tmp_path)
    res = srv.app.test_client().post("/api/export", json={})
    assert res.status_code == 400
