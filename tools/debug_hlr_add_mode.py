# -*- coding: utf-8 -*-
"""验证: 把每个 solid 分别 Add 进同一个 HLRBRep_Algo,
是否能消除整体 compound 模式下的退化外轮廓线。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_SOLID
from OCC.Core.TopoDS import topods
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
from OCC.Core.GCPnts import GCPnts_QuasiUniformDeflection
from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Ax2
from OCC.Core.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCC.Core.HLRAlgo import HLRAlgo_Projector

STEP = os.path.join(os.path.dirname(__file__), "..", "output",
                    "250-E-H3K2-L100-D11", "assembly.step")


def load_shape():
    reader = STEPControl_Reader()
    reader.ReadFile(STEP)
    reader.TransferRoots()
    return reader.OneShape()


def make_projector(view_dir, up_dir):
    x_dir = gp_Dir(
        view_dir.Y() * up_dir.Z() - view_dir.Z() * up_dir.Y(),
        view_dir.Z() * up_dir.X() - view_dir.X() * up_dir.Z(),
        view_dir.X() * up_dir.Y() - view_dir.Y() * up_dir.X(),
    )
    return HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), view_dir, x_dir))


def max_span(comp, threshold=500.0):
    if comp is None or comp.IsNull():
        return []
    found = []
    exp = TopExp_Explorer(comp, TopAbs_EDGE)
    while exp.More():
        edge = topods.Edge(exp.Current())
        adaptor = BRepAdaptor_Curve(edge)
        try:
            sampler = GCPnts_QuasiUniformDeflection(adaptor, 0.1)
            if sampler.IsDone():
                pts = [(sampler.Value(i).X(), sampler.Value(i).Y())
                       for i in range(1, sampler.NbPoints() + 1)]
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                span = max(max(xs) - min(xs), max(ys) - min(ys))
                if span > threshold:
                    found.append((span, adaptor.GetType(), len(pts)))
        except Exception:
            pass
        exp.Next()
    return found


def run(label, add_mode, view_dir, up_dir):
    shape = load_shape()
    hlr = HLRBRep_Algo()
    if add_mode == "compound":
        hlr.Add(shape)
    else:
        exp = TopExp_Explorer(shape, TopAbs_SOLID)
        n = 0
        while exp.More():
            hlr.Add(exp.Current())
            n += 1
            exp.Next()
    hlr.Projector(make_projector(view_dir, up_dir))
    hlr.Update()
    hlr.Hide()
    hs = HLRBRep_HLRToShape(hlr)

    # 统计各 compound 边数
    def count(comp):
        if comp is None or comp.IsNull():
            return 0
        c = 0
        e = TopExp_Explorer(comp, TopAbs_EDGE)
        while e.More():
            c += 1
            e.Next()
        return c

    anomalies = []
    anomalies += [("OutLineV",) + a for a in max_span(hs.OutLineVCompound())]
    anomalies += [("V",) + a for a in max_span(hs.VCompound())]
    anomalies += [("Rg1",) + a for a in max_span(hs.Rg1LineVCompound())]

    print(f"--- {label} ---")
    print(f"  edges: OutLineV={count(hs.OutLineVCompound())} "
          f"V={count(hs.VCompound())} Rg1={count(hs.Rg1LineVCompound())}")
    if anomalies:
        for a in anomalies:
            print(f"  异常: {a[0]} span={a[1]:.1f} type={a[2]} npts={a[3]}")
    else:
        print("  无跨度>500 异常边")


def main():
    views = {
        "top": (gp_Dir(0, -1, 0), gp_Dir(0, 0, -1)),
        "bottom": (gp_Dir(0, 1, 0), gp_Dir(0, 0, 1)),
        "front": (gp_Dir(0, 0, 1), gp_Dir(0, 1, 0)),
        "left": (gp_Dir(-1, 0, 0), gp_Dir(0, 1, 0)),
    }
    for name, (vd, ud) in views.items():
        print(f"===== {name} =====")
        run("整体 compound 一次 Add", "compound", vd, ud)
        run("逐 solid 分别 Add", "per_solid", vd, ud)
        print()


if __name__ == "__main__":
    main()
