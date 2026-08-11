"""检查模型 bounding box,确认坐标系方向"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from drawing_engine import read_shape_cached

shape = read_shape_cached('output/250-E-H2K1-L100-D11/assembly.brep')
bbox = Bnd_Box()
brepbndlib.Add(shape, bbox)
xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()

print('=== Bounding Box (mm) ===')
print(f'X: {xmin:.1f} ~ {xmax:.1f}  (width={xmax-xmin:.1f})')
print(f'Y: {ymin:.1f} ~ {ymax:.1f}  (depth={ymax-ymin:.1f})')
print(f'Z: {zmin:.1f} ~ {zmax:.1f}  (height={zmax-zmin:.1f})')
print()

dims = {'X': xmax-xmin, 'Y': ymax-ymin, 'Z': zmax-zmin}
sorted_dims = sorted(dims.items(), key=lambda x: x[1], reverse=True)
print('维度排序(大→小):')
for axis, val in sorted_dims:
    print(f'  {axis}: {val:.1f}mm')

max_axis = max(dims, key=dims.get)
print(f'\n最大轴: {max_axis} ({dims[max_axis]:.1f}mm)')
if max_axis == 'Z':
    print('=> Z-up (CAD惯例): 高度在Z轴, 前视应沿-Y方向投影')
elif max_axis == 'Y':
    print('=> Y-up (Three.js惯例): 高度在Y轴, 前视应沿-Z方向投影')
else:
    print(f'=> 异常: X轴最大, 模型可能躺倒了')
