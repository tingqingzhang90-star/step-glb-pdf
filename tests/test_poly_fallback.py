# -*- coding: utf-8 -*-
"""poly 投影遇到 OCC 数组越界时降级精确 HLR,其他异常照常抛出。"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

import core.drawing_engine as de  # noqa: E402
import drawing.hlr_poly as hp  # noqa: E402


class _AlgoBranchReached(Exception):
    """标记控制流已走到精确 HLR 分支,避免测试真的跑 OCC 投影。"""


def _raise_out_of_range(*args, **kwargs):
    raise IndexError(
        "OpenCASCADE Error [Standard_OutOfRange]: "
        "NCollection_Array1::ChangeValue (in HLRBRep_PolyAlgo::Update)")


def test_poly_out_of_range_falls_back_to_algo(monkeypatch):
    monkeypatch.setattr(hp, "generate_all_standard_views_poly",
                        _raise_out_of_range)

    def reach_algo(*args, **kwargs):
        raise _AlgoBranchReached()

    monkeypatch.setattr(de, "read_shape_cached", reach_algo)
    with pytest.raises(_AlgoBranchReached):
        de.generate_all_standard_views(
            "dummy.step", view_names=["front"], algo="poly", parallel=False)


def test_poly_other_error_not_swallowed(monkeypatch):
    def raise_plain(*args, **kwargs):
        raise IndexError("普通下标越界")

    monkeypatch.setattr(hp, "generate_all_standard_views_poly", raise_plain)
    with pytest.raises(IndexError, match="普通下标越界"):
        de.generate_all_standard_views(
            "dummy.step", view_names=["front"], algo="poly", parallel=False)
