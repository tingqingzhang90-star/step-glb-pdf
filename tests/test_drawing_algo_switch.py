"""验证 generate_all_standard_views 的 DRAWING_ALGO 切换。

两种模式都应返回结构一致的 views:
  - algo : 精确 HLRBRep_Algo(默认)
  - poly : HLRBRep_PolyAlgo 离散 + 圆弧拟合(hlr_poly)
调用方通过 .env 的 DRAWING_ALGO 切换, 本测试用显式 algo 参数覆盖, 互不干扰。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core import drawing_engine as de  # noqa: E402

MODEL = r"E:\分享代码\step__glb_pdf\output\250-E-H2K1-L100-D11\assembly.step"
VIEWS = ["front", "left", "left_top"]
VIEW_KEYS = ("label", "edges", "hidden_edges", "bbox", "thumbnail", "seg_count")


@pytest.mark.skipif(not os.path.isfile(MODEL), reason="需本地模型文件")
def test_algo_switch_returns_consistent_structure():
    # 确保 .brep 缓存就绪, 排除首次 STEP 解析噪声
    assert os.path.isfile(os.path.splitext(MODEL)[0] + ".brep")

    for algo in ("algo", "poly"):
        res = de.generate_all_standard_views(MODEL, view_names=VIEWS, algo=algo)
        assert "views" in res
        assert set(res["views"].keys()) == set(VIEWS)
        for v in VIEWS:
            view = res["views"][v]
            for key in VIEW_KEYS:
                assert key in view, "%s/%s 缺少字段 %s" % (algo, v, key)
            assert isinstance(view["edges"], list)
            assert len(view["edges"]) > 0, "%s/%s 边线为空" % (algo, v)


@pytest.mark.skipif(not os.path.isfile(MODEL), reason="需本地模型文件")
def test_poly_mode_recovers_circular_features():
    res = de.generate_all_standard_views(MODEL, view_names=VIEWS, algo="poly")
    circles = sum(
        1 for v in VIEWS
        for seg in res["views"][v]["edges"]
        if seg.get("type") in ("circle", "arc")
    )
    # 该型号含圆柱特征, poly 模式应拟合出圆/弧
    assert circles > 0, "poly 模式未恢复任何圆/弧语义"
