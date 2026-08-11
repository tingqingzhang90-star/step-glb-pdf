from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.gp import gp_Vec
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_EDGE
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve

r = STEPControl_Reader()
r.ReadFile('output/250-E-H2K1-L100-D11/assembly.step')
r.TransferRoots()
s = r.OneShape()

b = Bnd_Box()
brepbndlib.Add(s, b)
x1, y1, z1, x2, y2, z2 = b.Get()
print(f'BBox: X={x2-x1:.1f}, Y={y2-y1:.1f}, Z={z2-z1:.1f}')

# 找最长的边
exp = TopExp_Explorer(s, TopAbs_EDGE)
longest = 0
d = None
count = 0
while exp.More():
    c = BRepAdaptor_Curve(exp.Current())
    v = gp_Vec(c.Value(c.FirstParameter()), c.Value(c.LastParameter()))
    if v.Magnitude() > longest:
        longest = v.Magnitude()
        d = v.Normalized()
    exp.Next()
    count += 1

print(f'Total edges: {count}')
print(f'Longest edge: {longest:.1f} mm')
print(f'Direction: ({d.X():.4f}, {d.Y():.4f}, {d.Z():.4f})')
print(f'Along Z axis: {abs(d.Z()) > 0.9}')
print(f'Z component: {d.Z():.4f}')

# 找前 5 条最长边
exp2 = TopExp_Explorer(s, TopAbs_EDGE)
edges = []
while exp2.More():
    c = BRepAdaptor_Curve(exp2.Current())
    v = gp_Vec(c.Value(c.FirstParameter()), c.Value(c.LastParameter()))
    edges.append((v.Magnitude(), v.Normalized()))
    exp2.Next()
edges.sort(reverse=True)
print('\nTop 5 longest edges:')
for i, (length, direction) in enumerate(edges[:5]):
    print(f'  {i+1}. len={length:.1f}mm, dir=({direction.X():.3f}, {direction.Y():.3f}, {direction.Z():.3f})')
