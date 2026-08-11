# -*- coding: utf-8 -*-
"""定位 top 视图离群长线的来源:
1. 判断异常边来自哪个 HLR 输出类别(OutLineV / V / Rg1)
2. 逐 solid 单独做 HLR, 定位是哪个零件产生的
3. 打印异常边的曲线类型、参数范围、采样点分布
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
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib

STEP = os.path.join(os.path.dirname(__file__), "..", "output",
                    "250-E-H3K2-L100-D11", "assembly.step")

CURVE_TYPES = {0: "Line", 1: "Circle", 2: "Ellipse", 3: "Hyperbola",
               4: "Parabola", 5: "Bezier", 6: "BSpline", 7: "Offset", 8: "Other"}


def load_shape():
    reader = STEPControl_Reader()
    reader.ReadFile(STEP)
    reader.TransferRoots()
    return reader.OneShape()


def hlr_project(shape, view_dir, up_dir):
    x_dir = gp_Dir(
        view_dir.Y() * up_dir.Z() - view_dir.Z() * up_dir.Y(),
        view_dir.Z() * up_dir.X() - view_dir.X() * up_dir.Z(),
        view_dir.X() * up_dir.Y() - view_dir.Y() * up_dir.X(),
    )
    ax2 = gp_Ax2(gp_Pnt(0, 0, 0), view_dir, x_dir)
    hlr = HLRBRep_Algo()
    hlr.Add(shape)
    hlr.Projector(HLRAlgo_Projector(ax2))
    hlr.Update()
    hlr.Hide()
    return HLRBRep_HLRToShape(hlr)


def edge_span_info(edge):
    adaptor = BRepAdaptor_Curve(edge)
    ctype = adaptor.GetType()
    try:
        sampler = GCPnts_QuasiUniformDeflection(adaptor, 0.1)
        if not sampler.IsDone():
            return ctype, None, None, []
        pts = [(sampler.Value(i).X(), sampler.Value(i).Y())
               for i in range(1, sampler.NbPoints() + 1)]
    except Exception:
        return ctype, None, None, []
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    return ctype, span, (min(xs), min(ys), max(xs), max(ys)), pts


def scan_compound(comp, label, threshold=500.0):
    """扫描 HLR 输出 compound, 打印跨度超过阈值的边"""
    if comp is None or comp.IsNull():
        return []
    found = []
    exp = TopExp_Explorer(comp, TopAbs_EDGE)
    idx = 0
    while exp.More():
        edge = topods.Edge(exp.Current())
        ctype, span, bbox, pts = edge_span_info(edge)
        if span is not None and span > threshold:
            adaptor = BRepAdaptor_Curve(edge)
            print(f"  [{label}] edge#{idx} type={CURVE_TYPES.get(ctype, ctype)} "
                  f"span={span:.1f} npts={len(pts)}")
            print(f"    param: [{adaptor.FirstParameter():.3f}, {adaptor.LastParameter():.3f}]")
            print(f"    bbox2d: ({bbox[0]:.1f},{bbox[1]:.1f})-({bbox[2]:.1f},{bbox[3]:.1f})")
            print(f"    first={pts[0][0]:.1f},{pts[0][1]:.1f} last={pts[-1][0]:.1f},{pts[-1][1]:.1f}")
            # 打印采样点里 x 的分布(每隔 n 个)
            step = max(1, len(pts) // 10)
            sample = [f"({p[0]:.0f},{p[1]:.0f})" for p in pts[::step]]
            print(f"    samples: {' '.join(sample)}")
            found.append((label, idx, ctype, span))
        idx += 1
        exp.Next()
    return found


def main():
    shape = load_shape()
    view_dir = gp_Dir(0, -1, 0)   # top
    up_dir = gp_Dir(0, 0, -1)

    print("========== 整体 HLR (top 视图) ==========")
    hs = hlr_project(shape, view_dir, up_dir)
    all_found = []
    all_found += scan_compound(hs.OutLineVCompound(), "OutLineV")
    all_found += scan_compound(hs.VCompound(), "V")
    all_found += scan_compound(hs.Rg1LineVCompound(), "Rg1")
    if not all_found:
        print("  (无跨度>500 的边)")

    print()
    print("========== 逐 solid HLR, 定位产生异常的零件 ==========")
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    sidx = 0
    while exp.More():
        solid = exp.Current()
        box = Bnd_Box()
        brepbndlib.Add(solid, box)
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
        hs2 = hlr_project(solid, view_dir, up_dir)
        found = []
        found += scan_compound(hs2.OutLineVCompound(), f"solid{sidx}/OutLineV")
        found += scan_compound(hs2.VCompound(), f"solid{sidx}/V")
        found += scan_compound(hs2.Rg1LineVCompound(), f"solid{sidx}/Rg1")
        if found:
            print(f"  >>> solid#{sidx} 产生异常边, 3D bbox: "
                  f"({xmin:.1f},{ymin:.1f},{zmin:.1f})-({xmax:.1f},{ymax:.1f},{zmax:.1f})")
        sidx += 1
        exp.Next()
    print(f"  共 {sidx} 个 solid 扫描完成")


if __name__ == "__main__":
    main()
