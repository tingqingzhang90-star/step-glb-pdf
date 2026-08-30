# -*- coding: utf-8 -*-
"""临时: 端到端验证 — 用前端实例模板对目标型号出图(验证后删除)"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from drawing import frontend_template, anchor_resolver
from drawing.dim import dim_rebind, dim_pdf_sheet
from core import drawing_engine

TEMPLATE = os.path.join(_ROOT, "data", "templates", "engineering",
                        "250-E-H2K1-L200-D55.json")
MODEL = "250-E-H2K1-L100-D11"
OUT_DIR = os.path.join(_ROOT, "output")

td = frontend_template.load_frontend_template(TEMPLATE)
base_views = frontend_template.resolve_base_views(td, OUT_DIR)
base_refs = frontend_template.resolve_base_refs(td, base_views)
base_profile = anchor_resolver.resolve_anchors(td["model_id"])

shape_path = frontend_template.find_model_shape(OUT_DIR, MODEL)
palette = drawing_engine.generate_all_standard_views(shape_path)
target_profile = anchor_resolver.resolve_anchors(MODEL)
ctx = dim_rebind.compensation_ctx(base_profile, target_profile)

placements = {}
for v in td["views"]:
    pv = palette["views"][v["source_view"]]
    placements[v["id"]] = {
        "x": v["x"], "y": v["y"], "scale": 1.0,
        "source_view": v["source_view"],
        "segs": pv.get("edges", []),
        "hidden": pv.get("hidden_edges", []),
        "k": pv.get("bbox", {}).get("scale") or 1.0,
    }

rebound, cache = [], {}
for item in base_refs:
    r = dim_rebind.rebind_annotation(
        item["dim"], item["refs"], ctx, target_profile, placements, cache)
    r["annotation"] = item["dim"]
    rebound.append(r)

out_pdf = os.path.join(OUT_DIR, MODEL, "_refactor_verify.pdf")
dim_pdf_sheet.render_frontend_pdf(rebound, placements, td, MODEL, out_pdf)

print(f"PDF: {out_pdf}")
print(f"存在: {os.path.exists(out_pdf)}  大小: {os.path.getsize(out_pdf)} bytes")
for item in rebound:
    a = item["annotation"]
    print(f"  {a.get('id')} [{a.get('type')}/{a.get('mode')}] -> {item['status']}")
