"""直接测试 HLR 投影,确认视图方向是否正确"""
import sys
sys.path.insert(0, 'src')
from core import read_shape_cached, _project_shape
from OCC.Core.gp import gp_Dir
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib

shape = read_shape_cached('output/250-E-H2K1-L100-D11/assembly.step')

# 模型 bbox
b = Bnd_Box()
brepbndlib.Add(shape, b)
x1, y1, z1, x2, y2, z2 = b.Get()
print(f'STEP BBox: X={x2-x1:.1f}, Y={y2-y1:.1f}, Z={z2-z1:.1f}')
print(f'  X range: [{x1:.1f}, {x2:.1f}]')
print(f'  Y range: [{y1:.1f}, {y2:.1f}]')
print(f'  Z range: [{z1:.1f}, {z2:.1f}]')

# 测试前视: dir=-Z(沿Z轴负方向投影,显示X-Y平面)
print('\n=== 前视 (dir=-Z, up=Y) ===')
visible, hidden = _project_shape(shape, gp_Dir(0, 0, -1), gp_Dir(0, 1, 0))
if visible:
    xs = [s.get('x1', s.get('cx', 0)) for s in visible] + [s.get('x2', s.get('cx', 0)) for s in visible]
    ys = [s.get('y1', s.get('cy', 0)) for s in visible] + [s.get('y2', s.get('cy', 0)) for s in visible]
    print(f'  边线数: {len(visible)}')
    print(f'  X 范围: [{min(xs):.1f}, {max(xs):.1f}] (宽 {max(xs)-min(xs):.1f})')
    print(f'  Y 范围: [{min(ys):.1f}, {max(ys):.1f}] (高 {max(ys)-min(ys):.1f})')

# 测试右视: dir=-X(沿X轴负方向投影,显示Y-Z平面)
print('\n=== 右视 (dir=-X, up=Y) ===')
visible, hidden = _project_shape(shape, gp_Dir(-1, 0, 0), gp_Dir(0, 1, 0))
if visible:
    xs = [s.get('x1', s.get('cx', 0)) for s in visible] + [s.get('x2', s.get('cx', 0)) for s in visible]
    ys = [s.get('y1', s.get('cy', 0)) for s in visible] + [s.get('y2', s.get('cy', 0)) for s in visible]
    print(f'  边线数: {len(visible)}')
    print(f'  X 范围: [{min(xs):.1f}, {max(xs):.1f}] (宽 {max(xs)-min(xs):.1f})')
    print(f'  Y 范围: [{min(ys):.1f}, {max(ys):.1f}] (高 {max(ys)-min(ys):.1f})')

# 测试上视: dir=-Y(沿Y轴负方向投影,显示X-Z平面)
print('\n=== 上视 (dir=-Y, up=Z) ===')
visible, hidden = _project_shape(shape, gp_Dir(0, -1, 0), gp_Dir(0, 0, 1))
if visible:
    xs = [s.get('x1', s.get('cx', 0)) for s in visible] + [s.get('x2', s.get('cx', 0)) for s in visible]
    ys = [s.get('y1', s.get('cy', 0)) for s in visible] + [s.get('y2', s.get('cy', 0)) for s in visible]
    print(f'  边线数: {len(visible)}')
    print(f'  X 范围: [{min(xs):.1f}, {max(xs):.1f}] (宽 {max(xs)-min(xs):.1f})')
    print(f'  Y 范围: [{min(ys):.1f}, {max(ys):.1f}] (高 {max(ys)-min(ys):.1f})')
