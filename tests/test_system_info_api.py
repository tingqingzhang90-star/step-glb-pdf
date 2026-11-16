# -*- coding: utf-8 -*-
"""进程池系统信息接口与内存/回收配置测试

覆盖:
  * GET /api/system-info 返回结构、本机应取到真实内存(非全 null)、建议上限推导
  * _system_memory_gb():多平台内存采集(本机 Windows 走 ctypes 回退)
  * _max_tasks_per_child():环境变量开关与 Python 3.11+ 版本守卫
  * _default_workers():BUILD_POOL_WORKERS 优先、兜底 min(4, CPU 核数)

均不启动真实进程池(只构造对象/读 env),不依赖 pythonOCC。

运行:
    pytest tests/test_system_info_api.py -v
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from web import app as web_app
from web import task_pool
from web.blueprints import assembly


@pytest.fixture(scope="module")
def srv():
    class _Srv:
        app = web_app.app
        pool = task_pool.get_pool()
    return _Srv()


@pytest.fixture
def client(srv):
    srv.app.config["TESTING"] = True
    return srv.app.test_client()


def test_system_info_endpoint_shape(client):
    res = client.get("/api/system-info")
    assert res.status_code == 200
    d = res.get_json()
    assert d["ok"] is True
    # worker / cpu 必须为正整数
    assert isinstance(d["workers"], int) and d["workers"] >= 1
    assert isinstance(d["cpu_count"], int) and d["cpu_count"] >= 1
    # env_workers 要么为 None,要么为字符串
    assert d["env_workers"] is None or isinstance(d["env_workers"], str)
    # memory 四字段齐全
    mem = d["memory"]
    for k in ("total_gb", "available_gb", "used_gb", "percent"):
        assert k in mem


def test_system_info_memory_not_all_null(client):
    """本机(Windows)应能经 ctypes 取到真实内存,不应全为 null"""
    d = client.get("/api/system-info").get_json()
    mem = d["memory"]
    assert mem["total_gb"] is not None, "未取到系统总内存(total_gb 为 null)"
    assert mem["total_gb"] > 0
    assert mem["available_gb"] is not None, "未取到可用内存(available_gb 为 null)"
    assert 0 <= (mem["percent"] or 0) <= 100


def test_system_info_suggested_derived_from_available(client):
    d = client.get("/api/system-info").get_json()
    mem = d["memory"]
    if mem["available_gb"] is not None:
        assert d["suggested_max_workers"] == int(mem["available_gb"] // 0.45)
    else:
        assert d["suggested_max_workers"] is None


def test_system_memory_gb_values():
    mem = assembly._system_memory_gb()
    assert mem["total_gb"] is not None and mem["total_gb"] > 0
    assert mem["available_gb"] is not None
    assert mem["used_gb"] is not None
    # 三值自洽:used ≈ total - available 的字节级关系已在 GiB 取整,仅校验量级
    assert mem["used_gb"] <= mem["total_gb"] + 1


def test_max_tasks_per_child_default_none(monkeypatch):
    monkeypatch.delenv("BUILD_POOL_MAX_TASKS_PER_CHILD", raising=False)
    assert task_pool._max_tasks_per_child() is None


def test_max_tasks_per_child_from_env(monkeypatch):
    monkeypatch.setenv("BUILD_POOL_MAX_TASKS_PER_CHILD", "8")
    if sys.version_info >= (3, 11):
        assert task_pool._max_tasks_per_child() == 8
    else:
        # 旧版本忽略该参数,等同关闭
        assert task_pool._max_tasks_per_child() is None


def test_max_tasks_per_child_zero_disabled(monkeypatch):
    monkeypatch.setenv("BUILD_POOL_MAX_TASKS_PER_CHILD", "0")
    assert task_pool._max_tasks_per_child() is None


def test_max_tasks_per_child_non_digit_disabled(monkeypatch):
    monkeypatch.setenv("BUILD_POOL_MAX_TASKS_PER_CHILD", "abc")
    assert task_pool._max_tasks_per_child() is None


def test_default_workers_env_override(monkeypatch):
    monkeypatch.setenv("BUILD_POOL_WORKERS", "12")
    assert task_pool._default_workers() == 12
    # 非法/过小值兜底为 1
    monkeypatch.setenv("BUILD_POOL_WORKERS", "0")
    assert task_pool._default_workers() == 1
    monkeypatch.setenv("BUILD_POOL_WORKERS", "abc")
    assert task_pool._default_workers() >= 1


def test_task_pool_passes_max_tasks_per_child(monkeypatch):
    """构造 TaskPool 时,进程池应带上 max_tasks_per_child(3.11+ 且 env 开启)

    用 stub 捕获 ProcessPoolExecutor 构造参数,避免测试里真起 worker 进程
    (Windows spawn 会重导主模块、拖慢且可能触发 OCC 导入)。
    """
    import concurrent.futures as cf

    captured = {}
    real_ppe = cf.ProcessPoolExecutor

    class _Stub(real_ppe):
        def __init__(self, *a, **kw):
            captured.update(kw)
            # 不调用父类 __init__,避免真正创建进程
    # task_pool 顶部已 `from concurrent.futures import ProcessPoolExecutor`,
    # 必须打它模块命名空间里的名字,而非 cf 的
    monkeypatch.setattr(task_pool, "ProcessPoolExecutor", _Stub)

    monkeypatch.setenv("BUILD_POOL_MAX_TASKS_PER_CHILD", "8")
    if sys.version_info >= (3, 11):
        pool = task_pool.TaskPool(max_workers=2)
        pool._ensure_executor()
        assert captured.get("max_tasks_per_child") == 8
    else:
        pool = task_pool.TaskPool(max_workers=2)
        pool._ensure_executor()
        assert "max_tasks_per_child" not in captured

    monkeypatch.setattr(cf, "ProcessPoolExecutor", real_ppe)
