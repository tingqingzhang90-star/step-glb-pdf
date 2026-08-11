# -*- coding: utf-8 -*-
"""验证方案: 用模型 3D bbox 的 8 个角点投影到视图平面, 得到该视图
合法的 2D 范围, 再判断哪些 HLR 输出边越界。
同时统计装配体拓扑构成, 解释逐 solid Add 为什么丢边。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import (TopAbs_EDGE, TopAbs_SOLID, TopAbs_SHELL,
                             TopAbs_FACE, TopAbs_COMPOUND, TopAbs_COMPSOLID)
from OCC.Core.TopoDS import topods
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
from OCC.Core.GCPnts import GCPnts_QuasiUniformDeflection
from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Trsf, gp_Ax3
from OCC.Core.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCC.Core.HLRAlgo import HLRAlgo_Projector
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib

STEP = os.path.join(os.path.dirname(__file__), "..", "output",
                    "250-E-H3K2-L100-D11", "assembly.step")


def load_shape():
    reader = STEPControl_Reader()
    reader.ReadFile(STEP)
    reader.TransferRoots()
    return reader.OneShape()


def count_type(shape, t):
    c = 0
    e = TopExp_Explorer(shape, t)
    while e.More():
        c += 1
        e.Next()
    return c


def view_axes(view_dir, up_dir):
    x_dir = gp_Dir(
        view_dir.Y() * up_dir.Z() - view_dir.Z() * up_dir.Y(),
        view_dir.Z() * up_dir.X() - view_dir.X() * up_dir.Z(),
        view_dir.X() * up_dir.Y() - view_dir.Y() * up_dir.X(),
    )
    return gp_Ax2(gp_Pnt(0, 0, 0), view_dir, x_dir)


def bbox_2d_range(shape, ax2):
    """把 3D bbox 8 角点用与 HLR 相同的变换投影到 2D, 求合法范围"""
    box = Bnd_Box()
    brepbndlib.Add(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()

    # HLR Projector 的变换: 世界坐标 -> ax2 局部坐标系
    trsf = gp_Trsf()
    trsf.SetTransformation(gp_Ax3(ax2))

    xs, ys = [], []
    for cx in (xmin, xmax):
        for cy in (ymin, ymax):
            for cz in (zmin, zmax):
                p = gp_Pnt(cx, cy, cz)
                p.Transform(trsf)
                xs.append(p.X())
                ys.append(p.Y())
    return (min(xs), min(ys), max(xs), max(ys)), (xmin, ymin, zmin, xmax, ymax, zmax)


def scan(comp, label, legal, results):
    if comp is None or comp.IsNull():
        return
    lx0, ly0, lx1, ly1 = legal
    exp = TopExp_Explorer(comp, TopAbs_EDGE)
    idx = 0
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
                out = (min(xs) < lx0 - 1.0 or max(xs) > lx1 + 1.0 or
                       min(ys) < ly0 - 1.0 or max(ys) > ly1 + 1.0)
                if out:
                    over_x = max(0.0, max(xs) - lx1) + max(0.0, lx0 - min(xs))
                    over_y = max(0.0, max(ys) - ly1) + max(0.0, ly0 - min(ys))
                    results.append((label, idx, adaptor.GetType(), len(pts),
                                    max(max(xs) - min(xs), max(ys) - min(ys)),
                                    over_x, over_y))
        except Exception:
            pass
        idx += 1
        exp.Next()


def main():
    shape = load_shape()
    print("===== 装配体拓扑构成 =====")
    print(f"  COMPOUND={count_type(shape, TopAbs_COMPOUND)} "
          f"COMPSOLID={count_type(shape, TopAbs_COMPSOLID)} "
          f"SOLID={count_type(shape, TopAbs_SOLID)} "
          f"SHELL={count_type(shape, TopAbs_SHELL)} "
          f"FACE={count_type(shape, TopAbs_FACE)}")
    print()

    views = {
        "front": (gp_Dir(0, 0, 1), gp_Dir(0, 1, 0)),
        "back": (gp_Dir(0, 0, -1), gp_Dir(0, 1, 0)),
        "left": (gp_Dir(-1, 0, 0), gp_Dir(0, 1, 0)),
        "right": (gp_Dir(1, 0, 0), gp_Dir(0, 1, 0)),
        "top": (gp_Dir(0, -1, 0), gp_Dir(0, 0, -1)),
        "bottom": (gp_Dir(0, 1, 0), gp_Dir(0, 0, 1)),
    }

    for name, (vd, ud) in views.items():
        ax2 = view_axes(vd, ud)
        legal, bb3d = bbox_2d_range(shape, ax2)
        hlr = HLRBRep_Algo()
        hlr.Add(shape)
        hlr.Projector(HLRAlgo_Projector(ax2))
        hlr.Update()
        hlr.Hide()
        hs = HLRBRep_HLRToShape(hlr)

        results = []
        scan(hs.OutLineVCompound(), "OutLineV", legal, results)
        scan(hs.VCompound(), "V", legal, results)
        scan(hs.Rg1LineVCompound(), "Rg1", legal, results)

        print(f"===== {name} =====")
        print(f"  合法 2D 范围: ({legal[0]:.1f},{legal[1]:.1f})-({legal[2]:.1f},{legal[3]:.1f})"
              f"  尺寸={legal[2]-legal[0]:.1f}x{legal[3]-legal[1]:.1f}")
        if results:
            for r in results:
                print(f"  越界: {r[0]}#{r[1]} type={r[2]} npts={r[3]} "
                      f"span={r[4]:.1f} overX={r[5]:.1f} overY={r[6]:.1f}")
        else:
            print("  无越界边")
        print()


if __name__ == "__main__":
    main()
