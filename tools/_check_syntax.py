# -*- coding: utf-8 -*-
"""临时: 批量语法检查 src/ 与 tools/ 下所有 .py(验证后删除)"""
import os
import py_compile
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

bad = []
count = 0
for base in (os.path.join(_ROOT, "src"), os.path.join(_ROOT, "tools")):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            count += 1
            path = os.path.join(dirpath, fn)
            try:
                py_compile.compile(path, doraise=True, cfile=path + "c")
            except py_compile.PyCompileError as e:
                bad.append((os.path.relpath(path, _ROOT), str(e).strip()))
            finally:
                if os.path.exists(path + "c"):
                    os.remove(path + "c")

print(f"=== 语法检查 ({count} 个文件) ===")
if bad:
    for rel, err in bad:
        print(f"  [FAIL] {rel}")
        print(f"         {err}")
else:
    print("  [OK] 全部通过")
sys.exit(1 if bad else 0)
