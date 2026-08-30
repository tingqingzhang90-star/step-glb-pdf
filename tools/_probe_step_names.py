# -*- coding: utf-8 -*-
"""临时探针: 验证 assembly.step 是否带零件名 + 提取缸体/电机 bbox(验证后删除)

若 STEP 由 step3_export_assembly_step_xcaf 导出,则可用 XCAF 按名称提取
各零件 bbox,锚点(缸体端面/电机包络)可从当前型号直接实测,无需硬编码。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(_ROOT, "output")

from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
from OCC.Core.TDocStd import TDocStd_Document
from OCC.Core.TCollection import TCollection_ExtendedString
from OCC.Core.XCAFApp import XCAFApp_Application
from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool
from OCC.Core.TDF import TDF_LabelSequence
from OCC.Core.TDataStd import TDataStd_Name
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.TopAbs import TopAbs_SOLID


def get_shape(shape_tool, label):
    try:
        return shape_tool.GetShape_s(label)
    except Exception:
        return None


def walk(labels, shape_tool, log, depth=0, out=None):
    out = out if out is not None else []
    for i in range(1, labels.Length() + 1):
        lab = labels.Value(i)
        name = ""
        from OCC.Core.TDataStd import TDataStd_Name as N
        attr = N()
        if lab.FindAttribute(N.GetID_s(), attr):
            try:
                name = attr.Get().ToExtString()
            except Exception:
                name = "(decode-fail)"
        is_asm = shape_tool.IsAssembly(lab)
        is_ref = shape_tool.IsReference(lab)
        is_simple = shape_tool.IsSimpleShape(lab)
        entry = {"name": name, "depth": depth,
                 "is_asm": is_asm, "is_ref": is_ref, "is_simple": is_simple}
        if is_ref:
            ref_lab = shape_tool.GetReferredShape_s(lab)
            if not ref_lab.IsNull():
                attr2 = N()
                if ref_lab.FindAttribute(N.GetID_s(), attr2):
                    try:
                        entry["ref_name"] = attr2.Get().ToExtString()
                    except Exception:
                        entry["ref_name"] = "(decode-fail)"
        # 提取 bbox(仅简单形状)
        if is_simple:
            shape = get_shape(shape_tool, lab)
            if shape is not None and not shape.IsNull():
                bb = Bnd_Box()
                brepbndlib.Add(shape, bb)
                if bb.IsVoid() is False:
                    xmin, ymin, zmin, xmax, ymax, zmax = bb.Get()
                    entry["bbox"] = {
                        "min": [round(xmin, 2), round(ymin, 2), round(zmin, 2)],
                        "max": [round(xmax, 2), round(ymax, 2), round(zmax, 2)],
                    }
        out.append(entry)
        if is_asm:
            children = TDF_LabelSequence()
            shape_tool.GetComponents_s(lab, children)
            walk(children, shape_tool, log, depth + 1, out)
    return out


def probe(model_code, log):
    log(f"\n{'='*70}\nmodel: {model_code}\n")
    step = os.path.join(OUT_DIR, model_code, "assembly.step")
    if not os.path.isfile(step):
        log(f"  STEP not found: {step}\n")
        return

    log("  [1] TDocStd_Document...\n")
    doc = TDocStd_Document(TCollection_ExtendedString("doc"))
    log("  [1a] ctor ok\n")
    app = XCAFApp_Application.GetApplication()
    log("  [1b] getapp ok\n")
    app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)
    log("  [1c] newdoc ok\n")
    log("  [2] STEPCAFControl_Reader...\n")
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    log("  [3] ReadFile...\n")
    status = reader.ReadFile(step)
    log(f"  [4] ReadFile done, status={status}\n")
    reader.Transfer(doc)
    log("  [5] Transfer done\n")

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    free = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free)
    log(f"  [6] free shapes: {free.Length()}\n")

    entries = walk(free, shape_tool, log)
    log(f"  [7] labels: {len(entries)}\n")
    for e in entries:
        bbox = e.get("bbox")
        line = f"  {'  '*e['depth']}- {e['name'] or e.get('ref_name') or '(unnamed)'}"
        if e.get("ref_name") and e["ref_name"] != e["name"]:
            line += f"  [ref: {e['ref_name']}]"
        if bbox:
            bmin, bmax = bbox["min"], bbox["max"]
            size = [round(bmax[i]-bmin[i], 1) for i in range(3)]
            line += f"  bbox_min={bmin} bbox_max={bmax} size={size}"
        log(line + "\n")


if __name__ == "__main__":
    out_path = os.path.join(_ROOT, "tools", "_probe_step_names.out.txt")
    f = open(out_path, "w", encoding="utf-8")
    def log(s):
        f.write(s)
        f.flush()
    for m in ["250-E-H2K1-L100-D55", "250-E-H2K1-L100-D11"]:
        try:
            probe(m, log)
        except Exception as e:
            import traceback
            log(f"  ERROR: {e}\n{traceback.format_exc()}\n")
    f.close()
    print("done")
