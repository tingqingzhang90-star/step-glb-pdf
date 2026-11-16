# -*- coding: utf-8 -*-
"""临时:诊断 poly 拟合出的异常圆/弧(直径与设计值不符的那些)"""
import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))
from core import drawing_engine as DE  # noqa: E402
from drawing.hlr_poly import _get_shape, _project_discrete_one, _fit_one  # noqa: E402

STEP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'output', '250-E-H3K1-L100-D55', 'assembly.step')


def dump(name, segs, lo, hi):
    print('--- %s: 直径落在 [%.1f, %.1f] 的圆/弧' % (name, lo, hi))
    rows = []
    for s in segs:
        m = s.get('meta') or {}
        r = m.get('radius')
        if not r:
            continue
        d = r * 2
        if not (lo <= d <= hi):
            continue
        pts = s.get('points')
        if pts:
            chord = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
            total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
        else:
            chord = total = None
        rows.append((d, s.get('type'), m.get('curve'), m.get('arc_span'),
                     len(pts) if pts else 0, chord, total,
                     m.get('fit_rms'), m.get('center')))
    for d, t, curve, span, n, chord, total, rms, center in sorted(rows):
        print('    D=%9.3f type=%-8s curve=%-6s span=%-6s pts=%-4d chord=%s total=%s rms=%s c=(%.1f,%.1f)'
              % (d, t, curve, ('%.2f' % span) if span else '-', n,
                 ('%.2f' % chord) if chord else '-', ('%.2f' % total) if total else '-',
                 rms, center[0], center[1]))
    print('    合计 %d 条' % len(rows))


shape, max_ext = _get_shape(STEP, 0.5)
max_r = (max_ext or 1e4) * 2
for view in ('front', 'left', 'left_top'):
    cfg = DE.STANDARD_VIEW_CONFIGS[view]
    vis, _hid = _project_discrete_one(shape, cfg['dir'], cfg['up'], False, max_ext)
    fitted = _fit_one(vis, 0.5, max_r)
    print('=== %s : 原始 line 段 %d -> 拟合后 %d 条' %
          (view, len([s for s in vis if s.get('type') == 'line']), len(fitted)))
    dump(view + ' 大直径', fitted, 50.0, 1e9)
    dump(view + ' 小碎片', fitted, 0.0, 4.0)
    print()
