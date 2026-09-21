# -*- coding: utf-8 -*-
"""出图算法切换(poly/algo)的前端接口透传测试。

覆盖:
  1. /api/drawing-view-palette/<model>?algo=poly 把 algo 透传进任务池 payload;
  2. 非法 algo 值返回 400;
  3. task_pool._run_view_palette 把 algo 传给 generate_all_standard_views。

不触发真实 OCC 投影:pool.run 与 generate_all_standard_views 均打桩。
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from web import app as web_app  # noqa: E402
import web.blueprints.sw_view as sv  # noqa: E402


class _FakePool:
    def __init__(self):
        self.calls = []

    def run(self, kind, key, payload):
        self.calls.append({"kind": kind, "key": key, "payload": dict(payload)})
        return {"views": {}}


def test_palette_algo_passed_to_pool(monkeypatch):
    fake = _FakePool()
    monkeypatch.setattr(sv, "pool", fake)
    monkeypatch.setattr(sv, "_find_model_shape_path", lambda code: "x.step")
    web_app.app.config["TESTING"] = True
    client = web_app.app.test_client()
    res = client.get("/api/drawing-view-palette/250-X?algo=poly")
    assert res.status_code == 200
    assert fake.calls[0]["payload"]["algo"] == "poly"
    assert fake.calls[0]["payload"]["shape_path"] == "x.step"
    # 去重 key 需带 algo,避免同型号不同算法互相复用结果
    assert "poly" in fake.calls[0]["key"]


def test_palette_algo_defaults_to_none(monkeypatch):
    fake = _FakePool()
    monkeypatch.setattr(sv, "pool", fake)
    monkeypatch.setattr(sv, "_find_model_shape_path", lambda code: "x.step")
    web_app.app.config["TESTING"] = True
    client = web_app.app.test_client()
    res = client.get("/api/drawing-view-palette/250-X")
    assert res.status_code == 200
    assert fake.calls[0]["payload"]["algo"] is None


def test_palette_algo_rejects_invalid(monkeypatch):
    monkeypatch.setattr(sv, "_find_model_shape_path", lambda code: "x.step")
    web_app.app.config["TESTING"] = True
    client = web_app.app.test_client()
    res = client.get("/api/drawing-view-palette/250-X?algo=bad")
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_run_view_palette_passes_algo(monkeypatch):
    import core.drawing_engine as de
    captured = {}

    def fake(shape_path, view_names=None, parallel=True, algo=None):
        captured["algo"] = algo
        return {"views": {}}

    monkeypatch.setattr(de, "generate_all_standard_views", fake)
    import web.task_pool as tp

    tp._run_view_palette({"shape_path": "x.step", "algo": "algo"})
    assert captured["algo"] == "algo"
