# -*- coding: utf-8 -*-
"""临时调试: 走完一次 generate_one_frontend 流水线,打印中间状态(验证后删除)"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from core import drawing_engine
from drawing import anchor_resolver
from drawing import frontend_template
from drawing.dim import dim_rebind
from drawing.dim import dim_render

TPL = os.path.join(_ROOT, "data", "templates", "engineering", "250-E-H2K1-L100-D11.json")
MODEL = "250-E-H2K1-L100-D11"
OUT_DIR = os.path.join(_ROOT, "output")

doc = frontend_template.load_frontend_template(TPL)
print("template identity:", doc.get("template_identity"))
print("views:", [(v["id"], v["source_view"], v.get("px_per_mm")) for v in doc["views"]])
print("annotations count:", len(doc["annotations"]))

base_views = frontend_template.resolve_base_views(doc, OUT_DIR)
base_refs = frontend_template.resolve_base_refs(doc, base_views)
base_profile = anchor_resolver.resolve_anchors(doc["model_id"])
print("\nbase_views:", {k: {"src": v["source_view"],
                              "edges": len(v["edges"]),
                              "k": v["bbox"].get("scale")} for k, v in base_views.items()})
print("base_refs count:", len(base_refs))

# 模拟重绑一个 dim
shape = frontend_template.find_model_shape(OUT_DIR, MODEL)
palette = drawing_engine.generate_all_standard_views(shape)
target_profile = anchor_resolver.resolve_anchors(MODEL)
ctx = dim_rebind.compensation_ctx(base_profile, target_profile)
print(f"\nctx: {ctx}")

placements = {}
for v in doc["views"]:
    src = v["source_view"]
    pv = palette["views"][src]
    k_base = v.get("px_per_mm") or base_views[v["id"]]["bbox"].get("scale") or 1.0
    k_target = pv["bbox"].get("scale") or k_base
    placements[v["id"]] = {
        "x": v["x"], "y": v["y"],
        "scale": v["scale"] * (k_base / k_target),
        "source_view": src,
        "segs": pv.get("edges", []),
        "hidden": pv.get("hidden_edges", []),
        "k": k_target,
    }
print(f"\nplacements:")
for k, p in placements.items():
    print(f"  {k}: scale={p['scale']:.3f}, k={p['k']:.4f}, "
          f"segs={len(p['segs'])}, first_segs={[(s['type'],s.get('x1')) for s in p['segs'][:3]]}")

# 重绑 dim_1
item = next(b for b in base_refs if b["dim"]["id"] == "dim_1")
print(f"\ndim_1 refs:")
for e in item["refs"]:
    if "error" in e:
        print(f"  ERROR: {e['error']}")
    else:
        seg = e["seg"]
        m = (seg.get("meta") or {}).get("mm_coords")
        print(f"  seg idx={e['ref']['idx']} type={seg.get('type')} "
              f"meta.mm={m} orient={seg.get('meta',{}).get('orientation')}")

r = dim_rebind.rebind_annotation(item["dim"], item["refs"], ctx, target_profile,
                                  placements, {})
print(f"\nrebind status: {r['status']}, reason: {r['reason']}")
print(f"segs[0]: type={r['segs'][0].get('type') if r['segs'] else 'none'}")
if r['segs']:
    s0 = r['segs'][0]
    print(f"  x1={s0.get('x1')}, y1={s0.get('y1')}, x2={s0.get('x2')}, y2={s0.get('y2')}")
    m = (s0.get('meta') or {}).get('mm_coords')
    print(f"  meta.mm_coords={m}")

# build_dim_primitives
prims = dim_render.build_dim_primitives(item["dim"], r["segs"], r["views"])
print(f"\nprims: {prims}")
