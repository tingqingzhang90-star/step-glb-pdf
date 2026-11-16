# -*- coding: utf-8 -*-
"""用真实的 250-E 装配体演示 HLR 投影：装配体 → 三视图 SVG

用法:
    python examples/quickstart.py                     # 内置的 250-E-H2K1-L100-D55
    python examples/quickstart.py --step 模型.step    # 换成自己的 STEP

完整 Web 服务(型号编码 → 装配重建 → 模板出图)需要系列零件库与模板数据，
那份数据不在仓库里；本示例只演示 HLR 投影这一步。
"""
import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from core.drawing_engine import generate_all_standard_views  # noqa: E402

_MODEL = os.path.join(_ROOT, "examples", "data", "250-E-H2K1-L100-D55.brep")
_VIEWS = ["front", "left", "left_top"]


def main():
    ap = argparse.ArgumentParser(description="250-E 装配体 → 三视图 SVG")
    ap.add_argument("--step", default=None, help="自备 STEP 路径;不传则用内置模型")
    args = ap.parse_args()

    out_dir = os.path.join(_ROOT, "examples", "output")
    os.makedirs(out_dir, exist_ok=True)
    if args.step:
        model_path = args.step
        if not os.path.exists(model_path):
            raise SystemExit(f"STEP 文件不存在: {model_path}")
    else:
        if not os.path.exists(_MODEL):
            raise SystemExit(f"示例模型缺失: {_MODEL}")
        # read_shape_cached 的 BREP-only 模式:传同名 .step(不存在),它会回退
        # 读取旁边的 .brep;仓库里只放 BREP,省去几十 MB 的 STEP 转换产物
        model_path = os.path.splitext(_MODEL)[0] + ".step"

    result = generate_all_standard_views(
        model_path, view_names=_VIEWS, parallel=False)
    for name, view in result["views"].items():
        svg_path = os.path.join(out_dir, f"{name}.svg")
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(view.get("thumbnail") or "")
        print(f"{name}: {view['seg_count']} 条边线 → {svg_path}")
    print(f"投影耗时 {result['elapsed']}s,统一比例 {result['scale_info']['uniform_scale']}")


if __name__ == "__main__":
    main()
