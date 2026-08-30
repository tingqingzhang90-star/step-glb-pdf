# -*- coding: utf-8 -*-
"""临时: 验证 src 分层重构后所有模块可导入且管线可跑通(验证后删除)"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

MODULES = [
    ("core.rebuild_assembly", "装配体重建"),
    ("core.build_config", "系列配置构建"),
    ("core.export_parts", "零件导出"),
    ("drawing.anchor_resolver", "锚点解析"),
    ("drawing.frontend_template", "实例模板装载"),
    ("drawing.drawing_pdf", "规则式 PDF 渲染"),
    ("drawing.dxf_exporter", "DXF 导出"),
    ("drawing.rule_template.drawing_template", "规则式模板引擎"),
    ("drawing.dim.dim_geometry", "标注几何"),
    ("drawing.dim.dim_render", "标注图元"),
    ("drawing.dim.dim_rebind", "几何指纹重绑"),
    ("drawing.dim.dim_pdf_sheet", "图纸 PDF 渲染"),
]

ok, fail = [], []
for mod, desc in MODULES:
    try:
        __import__(mod)
        ok.append((mod, desc))
    except Exception as e:
        fail.append((mod, desc, f"{type(e).__name__}: {e}"))

print(f"=== 模块导入验证 ({len(ok)}/{len(MODULES)} 通过) ===")
for m, d in ok:
    print(f"  [OK]   {m:<42} {d}")
for m, d, e in fail:
    print(f"  [FAIL] {m:<42} {d}\n        {e}")

# rule_template 的两个 JSON 是否随模块同目录
try:
    from drawing.rule_template import drawing_template as dt
    tpl_dir = os.path.dirname(dt.__file__)
    for j in ("drawing_template.json", "drawing_anchors.json"):
        p = os.path.join(tpl_dir, j)
        print(f"  [{'OK' if os.path.exists(p) else 'FAIL'}] JSON 同目录: {p}")
    tpl = dt.load_default_template()
    print(f"  [OK]   load_default_template() -> {len(tpl.get('items', []))} 条标注规则")
except Exception as e:
    print(f"  [FAIL] 规则式模板加载: {type(e).__name__}: {e}")

# 分层依赖方向检查: core 不应 import drawing/web
print("\n=== 分层依赖方向检查 ===")
import re
VIOLATION = re.compile(
    r"^\s*(?:from|import)\s+(drawing|batch|web)\b", re.M)
CORE_DIR = os.path.join(_ROOT, "src", "core")
bad = []
for name in os.listdir(CORE_DIR):
    if not name.endswith(".py"):
        continue
    with open(os.path.join(CORE_DIR, name), "r", encoding="utf-8") as f:
        for i, ln in enumerate(f.read().split("\n"), 1):
            if VIOLATION.match(ln):
                bad.append(f"core/{name}:{i} {ln.strip()}")
if bad:
    for b in bad:
        print(f"  [VIOLATION] {b}")
else:
    print("  [OK] core/ 无反向依赖(drawing/batch/web)")

sys.exit(1 if fail or bad else 0)
