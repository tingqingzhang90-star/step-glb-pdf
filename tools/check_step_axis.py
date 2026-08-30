# -*- coding: utf-8 -*-
"""检查 STEP 文件的坐标系方向"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from core import read_step, shape_bbox

# 鱼眼轴承 STEP 文件
step_path = r"e:\分享代码\step__glb_pdf\parts_step\250鱼眼轴承.step"

if not os.path.exists(step_path):
    print(f"文件不存在: {step_path}")
    sys.exit(1)

print(f"读取 STEP 文件: {step_path}")
shape = read_step(step_path)

# 计算包围盒
bbox = shape_bbox(shape)
xmin, ymin, zmin, xmax, ymax, zmax = bbox

print(f"\n包围盒 (单位: mm):")
print(f"  X: {xmin:.2f} ~ {xmax:.2f} (长度: {xmax - xmin:.2f})")
print(f"  Y: {ymin:.2f} ~ {ymax:.2f} (长度: {ymax - ymin:.2f})")
print(f"  Z: {zmin:.2f} ~ {zmax:.2f} (长度: {zmax - zmin:.2f})")

# 判断主轴
x_len = xmax - xmin
y_len = ymax - ymin
z_len = zmax - zmin

print(f"\n轴向长度:")
print(f"  X 轴: {x_len:.2f} mm")
print(f"  Y 轴: {y_len:.2f} mm")
print(f"  Z 轴: {z_len:.2f} mm")

if y_len > x_len and y_len > z_len:
    print(f"\n结论: STEP 几何是 Y-up 坐标系 (Y 轴最长: {y_len:.2f} mm)")
    print("说明: SolidWorks 导出 STEP 时保留了原始 Y-up 坐标系")
elif z_len > x_len and z_len > y_len:
    print(f"\n结论: STEP 几何是 Z-up 坐标系 (Z 轴最长: {z_len:.2f} mm)")
    print("说明: STEP 文件已转换为标准 STEP Z-up 坐标系")
else:
    print(f"\n结论: 无法确定坐标系方向")
