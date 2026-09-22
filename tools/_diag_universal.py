# -*- coding: utf-8 -*-
"""跨系列 × 全视图验证 poly 修复通用性。

实时追加写结果文件(避免 stdout 被吞),支持按系列分批:
  python _diag_universal.py tools/_u1.txt 160 190 250

每个(系列,视图)跑 algo(真值) 与 poly(修复后),比对:
  - 漏圆: algo 有而 poly 无(目标=0)
  - 多余圆: poly 有而 algo 无
  - 配对后的直径最大差
"""
import sys
import os
import math

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'src'))
from core import drawing_engine as DE  # noqa: E402

OUT = os.path.join(os.path.dirname(_HERE), 'output')
ALL_VIEWS = list(DE.STANDARD_VIEW_CONFIGS.keys())

MODELS = [
    ('160', '160-E-H2K1-L100-4.4kw电机'),
    ('190', '190-E-H2K1-L100-5.5KW电机'),
    ('250', '250-E-H2K1-L100'),
    ('270', '270-E-H2K1-L100-11kw电机'),
    ('320', '320-E-H2K1-L100-7.5kw电机'),
    ('380', '380-E-H2K1-L100-69kw'),
    ('JDG45', 'JDG45-E-H2K1-L100-汇川100w'),
    ('JDG110', 'JDG110-E-H3K1-L100-汇川1500w'),
    ('YRJ250', 'YRJ250-E-H2K1-L190-D11'),
]


def circles_of(view):
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
    seen, out = {}, []
    for c in cs:
        k = (round(c[0], 0), round(c[1], 0), round(c[2], 0))
        if k in seen:
            continue
        seen[k] = True
        out.append(c)
    return out


def key(c):
    return (round(c[0], 0), round(c[1], 0), round(c[2], 1))


def compare(a, p):
    cands = []
    for ai, (ax, ay, ar) in enumerate(a):
        for pi, (px, py, pr) in enumerate(p):
            if math.hypot(ax - px, ay - py) > 2.0:
                continue
            cands.append((abs(pr - ar), ai, pi, ar, pr))
    cands.sort(key=lambda t: t[0])
    used_a, used_p, rows = set(), set(), []
    for (dr, ai, pi, ar, pr) in cands:
        if ai in used_a or pi in used_p:
            continue
        if dr > max(3.0, 0.02 * ar):
            continue
        used_a.add(ai)
        used_p.add(pi)
        rows.append((ar * 2, pr * 2))
    diffs = [abs(d - t) for t, d in rows]
    return len(rows), (max(diffs) if diffs else 0.0)


ARGS = sys.argv[1:]
outfile = '_u_all.txt'
series = None
if ARGS and ARGS[0].endswith('.txt'):
    outfile = os.path.basename(ARGS[0])
    series = ARGS[1:]
elif ARGS:
    series = ARGS
if series:
    MODELS = [m for m in MODELS if m[0] in series]

res_path = os.path.join(_HERE, outfile)


def log(msg):
    with open(res_path, 'a', encoding='utf-8') as f:
        f.write(msg + '\n')


log('=' * 70)
log('视图=%d: %s' % (len(ALL_VIEWS), ','.join(ALL_VIEWS)))
log('系列=%d: %s' % (len(MODELS), ','.join(m[0] for m in MODELS)))
log('=' * 70)

gt = gl = gm = 0
gw = 0.0
for series_code, model in MODELS:
    step = os.path.join(OUT, model, 'assembly.step')
    try:
        ra = DE.generate_all_standard_views(step, view_names=ALL_VIEWS, algo='algo',
                                            include_hidden=False, parallel=True)
        rp = DE.generate_all_standard_views(step, view_names=ALL_VIEWS, algo='poly',
                                            include_hidden=False, parallel=True)
    except Exception as e:
        log('%-8s %-30s 失败: %s' % (series_code, model, e))
        continue
    st = sl = se = 0
    worst = 0.0
    per = []
    for v in ALL_VIEWS:
        va = ra.get('views', {}).get(v) or {}
        vp = rp.get('views', {}).get(v) or {}
        sa = set(key(c) for c in dedup(circles_of(va)))
        sp = set(key(c) for c in dedup(circles_of(vp)))
        n, w = compare(dedup(circles_of(va)), dedup(circles_of(vp)))
        st += n
        worst = max(worst, w)
        lost = len(sa - sp)
        extra = len(sp - sa)
        sl += lost
        se += extra
        if sa - sp or sp - sa:
            per.append('%s 漏%d多%d' % (v, lost, extra))
    gt += st
    gl += sl
    gm += se
    gw = max(gw, worst)
    detail = (' | '.join(per[:4])) if per else '各视图圆集合完全一致'
    log('%-8s %-30s 配对=%-4d 漏圆=%-3d 多余=%-3d 最大|差|=%.3f  %s'
        % (series_code, model, st, sl, se, worst, detail))

log('=' * 70)
log('汇总: 配对总数=%d  漏圆=%d  多余圆=%d  全局最大|差|=%.3f' % (gt, gl, gm, gw))
