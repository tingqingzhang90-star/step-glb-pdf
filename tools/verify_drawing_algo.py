# -*- coding: utf-8 -*-
"""出图算法回归:algo(精确 HLR) vs poly(离散 + 圆弧拟合)的圆直径比对

poly 链路把圆离散成弦再拟合回圆/弧,拟合一旦失真,标注量出来的直径就和真实值
对不上。这个脚本按"圆心 + 半径"联合配对(图上有真实同心圆,只按圆心配会随机)
比较两种算法在同一型号同一视图上的直径,报出超差项与 poly 独有的圆/弧。

用法:
    conda run -n pdf1 python tools/verify_drawing_algo.py [型号] [视图...]
默认型号 250-E-H3K1-L100-D55,默认视图 front left left_top。
判据: 配对差 |diff| ≤ 0.05mm 视为一致(弦端点在圆上,真值误差本该远小于此)。
"""
import sys
import os
import math

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'src'))
from core import drawing_engine as DE  # noqa: E402

TOL_MM = 0.05
# 离散投影的弦端点在圆上,但拟合半径受网格精度限制:大圆按 0.5mm 网格离散时,
# 半弧拟合的半径误差约 0.2-0.5mm,无法达到 0.05mm。用 max(0.05, deflection) 作为
# 现实判据,既能抓出"半径被拟成一半"这类真错,又不被网格本身误差误报。
DEFLECTION = 0.5
REAL_TOL = max(TOL_MM, DEFLECTION)
model = sys.argv[1] if len(sys.argv) > 1 else '250-E-H3K1-L100-D55'
views = sys.argv[2:] or ['front', 'left', 'left_top']
step = os.path.join(os.path.dirname(_HERE), 'output', model, 'assembly.step')
if not os.path.isfile(step):
    print('STEP 不存在:', step)
    sys.exit(2)


def views_of(res):
    v = res.get('views') if isinstance(res, dict) else res
    if isinstance(v, dict):
        return v
    return {x.get('name'): x for x in (v or [])}


def circles_of(view):
    """圆与弧统一取出 (圆心x, 圆心y, 半径mm);algo 侧不产 type=circle,只有弧"""
    out = []
    for s in view.get('edges') or []:
        m = s.get('meta') or {}
        r = m.get('radius')
        if not r:
            continue
        if s.get('type') == 'circle':
            out.append((s.get('cx'), s.get('cy'), r))
        elif m.get('curve') == 'circle' and m.get('center'):
            c = m['center']
            out.append((c[0], c[1], r))
    return [c for c in out if c[0] is not None]


def dedup(cs):
    """同圆心(±0.5)+同半径(±0.5)的重复圆只留一份。

    同一孔/轮廓在 HLR 里会被拆成多段弧,各段单独拟合出略不同的半径(实测同孔
    23.6/24.0),algo 侧也会重复输出同一圆。不先去重,贪心配对会把 12 份 algo 圆
    错误链到 12 份 poly 圆,放大虚假超差。"""
    seen = {}
    out = []
    for c in cs:
        k = (round(c[0], 0), round(c[1], 0), round(c[2], 0))
        if k in seen:
            continue
        seen[k] = True
        out.append(c)
    return out


print('型号:', model, ' 视图:', ' '.join(views))
va = views_of(DE.generate_all_standard_views(step, view_names=views, algo='algo',
                                            include_hidden=False, parallel=False))
vp = views_of(DE.generate_all_standard_views(step, view_names=views, algo='poly',
                                            include_hidden=False, parallel=False))

total = bad = 0
worst = 0.0
for name in views:
    a = dedup(circles_of(va.get(name) or {}))
    p = dedup(circles_of(vp.get(name) or {}))
    # 全局最优指派:把 (algo, poly) 候选对按 |半径差| 升序贪心配对,半径最接近的先成组,
    # 避免"10 个同心圆对 7 个"时列表顺序导致的错链(如 146 错配到 64)。圆心须重合。
    cands = []
    for ai, (ax, ay, ar) in enumerate(a):
        for pi, (px, py, pr) in enumerate(p):
            dc = math.hypot(ax - px, ay - py)
            if dc > 2.0:
                continue
            cands.append((abs(pr - ar), ai, pi, ar, pr))
    cands.sort(key=lambda t: t[0])
    used_a, used_p, rows = set(), set(), []
    for (dr, ai, pi, ar, pr) in cands:
        if ai in used_a or pi in used_p:
            continue
        # 半径差过大视为无法对应(某侧多余轮廓),不强行配对
        if dr > max(3.0, 0.02 * ar):
            continue
        used_a.add(ai)
        used_p.add(pi)
        rows.append((a[ai][0], a[ai][1], ar * 2, pr * 2))
    only_algo = [c for i, c in enumerate(a) if i not in used_a]
    only_poly = [c for i, c in enumerate(p) if i not in used_p]
    print('-- %-9s algo=%d poly=%d 配对=%d algo独有=%d poly独有=%d'
          % (name, len(a), len(p), len(rows), len(only_algo), len(only_poly)))
    for ax, ay, da, dp in sorted(rows, key=lambda t: -abs(t[3] - t[2]))[:8]:
        diff = dp - da
        mark = '  <== 超差' if abs(diff) > REAL_TOL else ''
        print('    配对 center=(%8.2f,%8.2f) D_algo=%9.3f D_poly=%9.3f diff=%+8.3f%s'
              % (ax, ay, da, dp, diff, mark))
    for (px, py, pr) in only_poly[:6]:
        print('    poly 独有 center=(%8.2f,%8.2f) D=%9.3f' % (px, py, pr * 2))
    for (ax, ay, ar) in only_algo[:6]:
        print('    algo 独有 center=(%8.2f,%8.2f) D=%9.3f' % (ax, ay, ar * 2))
    if rows:
        diffs = [abs(t[3] - t[2]) for t in rows]
        n_bad = len([d for d in diffs if d > REAL_TOL])
        total += len(rows)
        bad += n_bad
        worst = max(worst, max(diffs))
        print('    严格(0.05)超差=%d  现实(%.2f)超差=%d/%d  最大|差|=%.3f 平均|差|=%.3f'
              % (len([d for d in diffs if d > TOL_MM]), REAL_TOL, n_bad, len(rows),
                 max(diffs), sum(diffs) / len(diffs)))

print()
print('总计: 配对 %d 组, 现实超差 %d 组, 全局最大差 %.3f mm' % (total, bad, worst))
