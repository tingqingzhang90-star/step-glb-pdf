# -*- coding: utf-8 -*-
"""调试:检查 HLR 输出的边是 3D 坐标还是已投影到投影面的 2D 坐标"""
import sys, os
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
from core import drawing_engine as d
from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir
from OCC.Core.HLRAlgo import HLRAlgo_Projector
from OCC.Core.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_EDGE
from OCC.Core.TopoDS import topods
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve

step = os.path.join(_PROJECT_ROOT, "output", "250-E-H3K2-L100-D11", "assembly.step")
shape = d.read_shape_cached(step)

cfg = d.STANDARD_VIEW_CONFIGS["top"]
vd = cfg["dir"]
up = cfg["up"]
xd = gp_Dir(
    vd.Y() * up.Z() - vd.Z() * up.Y(),
    vd.Z() * up.X() - vd.X() * up.Z(),
    vd.X() * up.Y() - vd.Y() * up.X()
)
ax2 = gp_Ax2(gp_Pnt(0, 0, 0), vd, xd)

hlr = HLRBRep_Algo()
hlr.Add(shape)
hlr.Projector(HLRAlgo_Projector(ax2))
hlr.Update()
hlr.Hide()
hs = HLRBRep_HLRToShape(hlr)

outline = hs.OutLineVCompound()
print(f"OutLineVCompound is null: {outline.IsNull()}")

exp = TopExp_Explorer(outline, TopAbs_EDGE)
count = 0
while exp.More() and count < 10:
    edge = topods.Edge(exp.Current())
    adaptor = BRepAdaptor_Curve(edge)
    ct = adaptor.GetType()
    u1 = adaptor.FirstParameter()
    u2 = adaptor.LastParameter()
    p1 = adaptor.Value(u1)
    p2 = adaptor.Value(u2)
    print(f"  edge#{count}: type={ct} u=({u1:.2f},{u2:.2f}) "
          f"p1=({p1.X():.2f},{p1.Y():.2f},{p1.Z():.2f}) "
          f"p2=({p2.X():.2f},{p2.Y():.2f},{p2.Z():.2f})")
    count += 1
    exp.Next()

# 也检查 VCompound
print("\nVCompound:")
vc = hs.VCompound()
exp2 = TopExp_Explorer(vc, TopAbs_EDGE)
count = 0
while exp2.More() and count < 5:
    edge = topods.Edge(exp2.Current())
    adaptor = BRepAdaptor_Curve(edge)
    ct = adaptor.GetType()
    u1 = adaptor.FirstParameter()
    u2 = adaptor.LastParameter()
    p1 = adaptor.Value(u1)
    p2 = adaptor.Value(u2)
    print(f"  edge#{count}: type={ct} u=({u1:.2f},{u2:.2f}) "
          f"p1=({p1.X():.2f},{p1.Y():.2f},{p1.Z():.2f}) "
          f"p2=({p2.X():.2f},{p2.Y():.2f},{p2.Z():.2f})")
    count += 1
    exp2.Next()
