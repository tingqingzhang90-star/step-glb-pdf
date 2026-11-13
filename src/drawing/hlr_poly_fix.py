# -*- coding: utf-8 -*-
"""PolyAlgo 数组越界的拓扑修复：反转平面 face 上边数 > 3 的复杂内环。

HLRBRep_PolyAlgo::Update 对个别 STEP 装配体的平面内环方向组合会抛
Standard_OutOfRange(NCollection_Array1::ChangeValue)。BRepCheck_Analyzer 判定
这类拓扑合法，ShapeFix_Face.FixOrientation 也修不好，只有反转内环方向能避开。
修复只作用于副本：进程内 shape 缓存、精确 HLR 降级与 B-Rep 圆语义共用原
shape，不能被改动。
"""
import logging

from OCC.Core.BRep import BRep_Builder
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.BRepTools import breptools
from OCC.Core.GeomAbs import GeomAbs_Plane
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_WIRE, TopAbs_EDGE
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopoDS import topods

logger = logging.getLogger(__name__)

# id(shape) -> (原 shape 引用, 修复副本或 None)。保留原引用防止 id 被复用后误命中。
_FIXED = {}


def _edge_count(wire):
    n = 0
    ex = TopExp_Explorer(wire, TopAbs_EDGE)
    while ex.More():
        n += 1
        ex.Next()
    return n


def _plane_faces(shape):
    faces = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        face = topods.Face(ex.Current())
        if BRepAdaptor_Surface(face).GetType() == GeomAbs_Plane:
            faces.append(face)
        ex.Next()
    return faces


def _reverse_complex_inners(shape):
    builder = BRep_Builder()
    changed = 0
    for face in _plane_faces(shape):
        outer = breptools.OuterWire(face)
        targets = []
        ex = TopExp_Explorer(face, TopAbs_WIRE)
        while ex.More():
            wire = topods.Wire(ex.Current())
            if not wire.IsSame(outer) and _edge_count(wire) > 3:
                targets.append(wire)
            ex.Next()
        if not targets:
            continue
        # 缓存里的 face 是 frozen，不 Free 就地 Remove 会抛 TopoDS_FrozenShape
        face.Free(True)
        for wire in targets:
            builder.Remove(face, wire)
            rev = topods.Wire(BRepBuilderAPI_Copy(wire).Shape())
            rev.Reverse()
            builder.Add(face, rev)
            changed += 1
    return changed


def get_fixed_shape(shape, deflection):
    """返回可用于 PolyAlgo 重试的修复副本；无需修复时返回 None。

    结果按 shape 对象缓存，同一 worker 处理多视图时只做一次深拷贝与重新网格化。
    """
    hit = _FIXED.get(id(shape))
    if hit is not None and hit[0] is shape:
        return hit[1]
    fixed = BRepBuilderAPI_Copy(shape).Shape()
    changed = _reverse_complex_inners(fixed)
    if changed:
        # 改了拓扑，旧三角网格必须作废后按同一 deflection 重建
        breptools.Clean(fixed)
        BRepMesh_IncrementalMesh(fixed, deflection, False, 0.5, True)
        logger.warning("poly 拓扑修复: 反转 %d 个复杂内环并重建网格", changed)
        _FIXED[id(shape)] = (shape, fixed)
        return fixed
    _FIXED[id(shape)] = (shape, None)
    return None
