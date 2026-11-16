"""对比生产路径 generate_all_standard_views 的并发(parallel=True)与串行(parallel=False)。

生产默认 parallel=True:每视图启动独立 worker 子进程,各自 read_shape_cached + 重新网格化。
本脚本先预热 .brep 缓存,再各跑多次取中位数,排除首次 STEP 解析的噪声。
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core import drawing_engine as de  # noqa: E402

MODEL = r"E:\分享代码\step__glb_pdf\output\250-E-H2K1-L100-D11\assembly.step"
VIEWS_3 = ["front", "left", "left_top"]
VIEWS_ALL = None  # None = 全部 9+3 视图


def bench(parallel, views, n=3):
    times = []
    for _ in range(n):
        t0 = time.time()
        res = de.generate_all_standard_views(MODEL, view_names=views, parallel=parallel)
        times.append(time.time() - t0)
    times.sort()
    median = times[len(times) // 2]
    return median, times


def main():
    print(f"模型: {MODEL}")
    print(f"存在 assembly.brep: {os.path.isfile(os.path.splitext(MODEL)[0] + '.brep')}")
    # 预热:先以串行跑一次全集,生成/确认 .brep 缓存
    print("\n[预热] 串行跑全集一次,确保 .brep 缓存就绪 ...")
    de.generate_all_standard_views(MODEL, view_names=VIEWS_ALL, parallel=False)

    for label, views in (("三视图(front/left/left_top)", VIEWS_3),
                         ("全集(9+3 视图)", VIEWS_ALL)):
        print(f"\n=== {label} ===")
        med_p, all_p = bench(True, views)
        med_s, all_s = bench(False, views)
        faster = "串行" if med_s < med_p else "并发"
        speedup = med_s / med_p if med_p < med_s else med_p / med_s
        print(f"  并发 parallel=True: 中位数 {med_p:.3f}s  (各次 {[f'{t:.3f}' for t in all_p]})")
        print(f"  串行 parallel=False: 中位数 {med_s:.3f}s  (各次 {[f'{t:.3f}' for t in all_s]})")
        print(f"  => {faster}更快, 加速比 {speedup:.2f}x")


if __name__ == "__main__":
    main()
