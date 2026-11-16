# -*- coding: utf-8 -*-
"""poly 越界时只对修复副本重试一次，其他异常照常上抛给精确 HLR 降级。"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from core import drawing_engine as DE  # noqa: E402
from drawing import hlr_poly as hp  # noqa: E402
from drawing import hlr_poly_fix as hf  # noqa: E402

_OUT_OF_RANGE = IndexError(
    "OpenCASCADE Error [Standard_OutOfRange]: "
    "NCollection_Array1::ChangeValue (in HLRBRep_PolyAlgo::Update)")


class _FakePoly:
    def __init__(self, failures=()):
        self.failures = list(failures)
        self.updates = 0

    def Update(self):
        self.updates += 1
        if self.failures:
            raise self.failures.pop(0)


class _FakePts:
    def Update(self, poly):
        pass

    def __getattr__(self, name):
        return lambda: None


@pytest.fixture
def stub(monkeypatch):
    """屏蔽与重试判定无关的 OCC 投影后处理。"""
    monkeypatch.setattr(hp, "_build_ax2", lambda *a: "AX2")
    monkeypatch.setattr(DE, "_compute_view_bounds_2d",
                        lambda *a, **k: (0, 0, 1, 1))
    monkeypatch.setattr(DE, "_extract_2d_segments", lambda *a, **k: [])
    monkeypatch.setattr(DE, "_filter_short_segments", lambda *a, **k: [])
    monkeypatch.setattr(DE, "_drop_out_of_bounds_segments",
                        lambda *a, **k: [])
    monkeypatch.setattr(hp, "HLRBRep_PolyHLRToShape", _FakePts)
    return monkeypatch


def _project():
    return hp._project_discrete_one(object(), None, None, False, 1e4, 0.1)


def test_out_of_range_fixes_copy_and_retries(stub):
    original, fixed = object(), object()
    calls, fix_calls = [], []

    def make_poly(shape, ax2):
        poly = _FakePoly([_OUT_OF_RANGE] if not calls else [])
        calls.append((shape, ax2, poly))
        return poly

    def get_fixed(shape, deflection):
        fix_calls.append((shape, deflection))
        return fixed

    stub.setattr(hp, "_make_poly", make_poly)
    stub.setattr(hp, "get_fixed_shape", get_fixed)
    assert hp._project_discrete_one(original, None, None, False, 1e4, 0.1) \
        == ([], [])
    assert len(calls) == 2
    assert calls[0][0] is original and calls[1][0] is fixed
    assert calls[0][2].updates == calls[1][2].updates == 1
    assert fix_calls == [(original, 0.1)]


def test_successful_update_never_fixes(stub):
    stub.setattr(hp, "_make_poly", lambda shape, ax2: _FakePoly())
    stub.setattr(hp, "get_fixed_shape",
                 lambda *a: pytest.fail("正常投影不应触发修复"))
    assert _project() == ([], [])


def test_other_error_not_retried(stub):
    calls = []

    def make_poly(shape, ax2):
        calls.append(shape)
        return _FakePoly([IndexError("普通下标越界")])

    stub.setattr(hp, "_make_poly", make_poly)
    stub.setattr(hp, "get_fixed_shape",
                 lambda *a: pytest.fail("普通异常不应触发修复"))
    with pytest.raises(IndexError, match="普通下标越界"):
        _project()
    assert len(calls) == 1


def test_no_fix_available_reraises(stub):
    stub.setattr(hp, "_make_poly",
                 lambda shape, ax2: _FakePoly([_OUT_OF_RANGE]))
    stub.setattr(hp, "get_fixed_shape", lambda *a: None)
    with pytest.raises(IndexError, match="OutOfRange"):
        _project()


def test_retry_failure_reraises(stub):
    calls = []

    def make_poly(shape, ax2):
        calls.append(shape)
        return _FakePoly([_OUT_OF_RANGE])

    stub.setattr(hp, "_make_poly", make_poly)
    stub.setattr(hp, "get_fixed_shape", lambda *a: object())
    with pytest.raises(IndexError, match="OutOfRange"):
        _project()
    assert len(calls) == 2


@pytest.fixture
def fix_stub(monkeypatch):
    hf._FIXED.clear()

    class _Copy:
        def __init__(self, shape):
            pass

        def Shape(self):
            return object()

    monkeypatch.setattr(hf, "BRepBuilderAPI_Copy", _Copy)
    monkeypatch.setattr(hf.breptools, "Clean", lambda s: None)
    monkeypatch.setattr(hf, "BRepMesh_IncrementalMesh", lambda *a: None)
    yield monkeypatch
    hf._FIXED.clear()


def test_fix_result_cached_per_shape(fix_stub):
    seen = []
    fix_stub.setattr(hf, "_reverse_complex_inners",
                     lambda s: (seen.append(s), 25)[1])
    shape = object()
    first = hf.get_fixed_shape(shape, 0.1)
    assert first is hf.get_fixed_shape(shape, 0.1)
    assert len(seen) == 1


def test_no_complex_inner_returns_none(fix_stub):
    fix_stub.setattr(hf, "_reverse_complex_inners", lambda s: 0)
    shape = object()
    assert hf.get_fixed_shape(shape, 0.1) is None
    assert hf.get_fixed_shape(shape, 0.1) is None


def test_cached_fixed_shape_used_without_failed_update(stub):
    original, fixed = object(), object()
    hf._FIXED[id(original)] = (original, fixed)
    calls = []

    def make_poly(shape, ax2):
        calls.append(shape)
        return _FakePoly()

    stub.setattr(hp, "_make_poly", make_poly)
    stub.setattr(hp, "get_fixed_shape",
                 lambda *a: pytest.fail("已有修复副本不应再触发修复"))
    try:
        assert hp._project_discrete_one(
            original, None, None, False, 1e4, 0.1) == ([], [])
        assert calls == [fixed]
    finally:
        hf._FIXED.pop(id(original), None)


def test_peek_returns_none_for_unfixed_shape():
    assert hf.peek_fixed_shape(object()) is None
