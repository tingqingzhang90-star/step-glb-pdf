"""诊断 drawing_engine 视图方向: 对比模型 bbox 和视图 bbox 判断方向是否正确"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from drawing_engine import read_shape_cached, _project_shape, STANDARD_VIEW_CONFIGS

shape = read_shape_cached('output/250-E-H2K1-L100-D11/assembly.brep')

# 模型 bbox
bbox = Bnd_Box()
brepbndlib.Add(shape, bbox)
xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
print('=== 模型 Bounding Box (STEP 原始坐标) ===')
print(f'X: {xmin:.1f} ~ {xmax:.1f}  (range={xmax-xmin:.1f})')
print(f'Y: {ymin:.1f} ~ {ymax:.1f}  (range={ymax-ymin:.1f})')
print(f'Z: {zmin:.1f} ~ {zmax:.1f}  (range={zmax-zmin:.1f})')
print()

# 使用实际配置
configs = {name: cfg['dir'] for name, cfg in STANDARD_VIEW_CONFIGS.items() if cfg['group'] == 'standard'}

print('=== 各方向投影后的 2D 范围 ===')
for name, dir_vec in configs.items():
    visible, hidden = _project_shape(shape, dir_vec)
    if not visible:
        print(f'{name}: 无边线')
        continue
    xs = []
    ys = []
    for seg in visible:
        if seg['type'] == 'line':
            xs.extend([seg['x1'], seg['x2']])
            ys.extend([seg['y1'], seg['y2']])
        elif seg['type'] == 'circle':
            xs.extend([seg['cx']-seg['r'], seg['cx']+seg['r']])
            ys.extend([seg['cy']-seg['r'], seg['cy']+seg['r']])
    if xs:
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        print(f'{name}: width={w:.1f} × height={h:.1f}  ({len(visible)} edges)')

print()
print('=== 判断 ===')
print('SolidWorks 前视显示圆形端面(小) → 投影方向应沿 cylinder 长轴')
print('SolidWorks 右视显示水平圆柱(大) → 投影方向应垂直 cylinder 长轴')
print()
print('如果 front (dir=-Y) 的 2D bbox 是 "宽×高 ≈ 350×1731"( tall rectangle)')
print('  → 说明 cylinder 长轴沿 Z, 前视方向应该是 dir=-Z 才能看到端面')
print('如果 front (dir=-Y) 的 2D bbox 是 "宽×高 ≈ 350×348"( small square)')
print('  → 说明 cylinder 长轴沿 Y, 前视方向正确')
