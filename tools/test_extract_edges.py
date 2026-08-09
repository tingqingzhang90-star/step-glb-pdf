# -*- coding: utf-8 -*-
"""测试从 STEP 文件提取 B-rep 拓扑边并离散化为点序列"""
import os
import glob

from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_EDGE
from OCC.Core.TopoDS import topods
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
from OCC.Core.GCPnts import GCPnts_UniformAbscissa

# 查找 parts_step 目录下的 .step 文件
parts_dir = os.path.join(os.path.dirname(__file__), '..', 'parts_step')
step_files = glob.glob(os.path.join(parts_dir, '*.step'))

if not step_files:
    print("未找到 .step 文件")
    exit(1)

step_path = step_files[0]
print(f"读取 STEP 文件: {os.path.basename(step_path)}")

# 读取 STEP
reader = STEPControl_Reader()
status = reader.ReadFile(step_path)
if status != 1:
    print(f"读取失败, 状态码: {status}")
    exit(1)

reader.TransferRoots()
shape = reader.OneShape()

# 遍历 TopoDS_Edge
explorer = TopExp_Explorer(shape, TopAbs_EDGE)
edges = []
while explorer.More():
    edge = topods.Edge(explorer.Current())
    edges.append(edge)
    explorer.Next()

print(f"\n总边数: {len(edges)}")

# 对前 10 条边离散化
print("\n前 10 条边的离散化结果:")
print("-" * 50)
for i, edge in enumerate(edges[:10]):
    curve = BRepAdaptor_Curve(edge)
    # 用均匀弧长参数离散化, 间距 0.5mm
    discretizer = GCPnts_UniformAbscissa(curve, 0.5)
    n = discretizer.NbPoints()
    pts = []
    for j in range(1, n + 1):
        u = discretizer.Parameter(j)
        p = curve.Value(u)
        pts.append((p.X(), p.Y(), p.Z()))
    print(f"  边 {i}: {n} 个点, 首点=({pts[0][0]:.2f}, {pts[0][1]:.2f}, {pts[0][2]:.2f}), "
          f"末点=({pts[-1][0]:.2f}, {pts[-1][1]:.2f}, {pts[-1][2]:.2f})")

print("\n完成.")
