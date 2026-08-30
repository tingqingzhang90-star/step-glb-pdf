# -*- coding: utf-8 -*-
"""一次性脚本: src 目录分层重构后,批量更新 tools/ 下探针脚本的 import

映射:
    import rebuild_assembly   -> from core import rebuild_assembly
    import drawing_engine     -> from core import drawing_engine
    import drawing_template   -> from drawing.rule_template import drawing_template
    import anchor_resolver    -> from drawing import anchor_resolver
    import frontend_template  -> from drawing import frontend_template
    import dim_*              -> from drawing.dim import dim_*
    import dxf_exporter       -> from drawing import dxf_exporter
    import drawing_pdf        -> from drawing import drawing_pdf
    import drawing_generator  -> from drawing import drawing_generator
并统一把 src(而非 src/web)加入 sys.path。
"""
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_ROOT, "tools")

# 模块名 -> 新导入语句(保留 as 别名)
_MAPPING = {
    "rebuild_assembly": "from core import rebuild_assembly",
    "drawing_engine": "from core import drawing_engine",
    "drawing_template": "from drawing.rule_template import drawing_template",
    "anchor_resolver": "from drawing import anchor_resolver",
    "frontend_template": "from drawing import frontend_template",
    "dxf_exporter": "from drawing import dxf_exporter",
    "drawing_pdf": "from drawing import drawing_pdf",
    "drawing_generator": "from drawing import drawing_generator",
    "dim_geometry": "from drawing.dim import dim_geometry",
    "dim_render": "from drawing.dim import dim_render",
    "dim_rebind": "from drawing.dim import dim_rebind",
    "dim_pdf_sheet": "from drawing.dim import dim_pdf_sheet",
}

# 匹配 import xxx [as yyy] / import a, b
_IMPORT_RE = re.compile(
    r"^(\s*)import\s+([A-Za-z_][\w]*(?:\s*,\s*[A-Za-z_][\w]*)*)"
    r"(?:\s+as\s+([A-Za-z_][\w]*))?\s*$", re.M)
# 匹配 from xxx import ...
_FROM_RE = re.compile(
    r"^(\s*)from\s+([A-Za-z_][\w]*)\s+import\s+", re.M)


def fix_line(line):
    m = _IMPORT_RE.match(line)
    if m:
        indent, names, alias = m.group(1), m.group(2), m.group(3)
        parts = [n.strip() for n in names.split(",")]
        if len(parts) == 1 and parts[0] in _MAPPING:
            new = _MAPPING[parts[0]]
            return f"{indent}{new} as {alias}" if alias else f"{indent}{new}"
        return line
    m = _FROM_RE.match(line)
    if m and m.group(2) in _MAPPING:
        # 仅单行 from xxx import yyy 的简单形式
        indent, mod = m.group(1), m.group(2)
        rest = line[m.end():]
        return f"{indent}from {_MAPPING[mod].split() [1]} import {rest}"
    return line


def ensure_syspath(src_lines):
    """确保脚本把 src 加入 sys.path(重构后模块都在包里)"""
    joined = "\n".join(src_lines)
    if "sys.path" in joined and "_ROOT" in joined:
        return src_lines
    # 在最后一个 import os/sys 块后插入
    idx = 0
    for i, ln in enumerate(src_lines[:20]):
        if ln.startswith("import ") or ln.startswith("from "):
            idx = i + 1
    insert = [
        "",
        "_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))",
        "sys.path.insert(0, os.path.join(_ROOT, 'src'))",
    ]
    return src_lines[:idx] + insert + src_lines[idx:]


def main():
    changed = []
    for name in sorted(os.listdir(_TOOLS)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(_TOOLS, name)
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")
        new_lines = [fix_line(ln) for ln in lines]
        if new_lines != lines:
            new_lines = ensure_syspath(new_lines)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(new_lines))
            changed.append(name)
    print(f"已更新 {len(changed)} 个脚本:")
    for c in changed:
        print(f"  {c}")


if __name__ == "__main__":
    main()
