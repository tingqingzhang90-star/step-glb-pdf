# -*- coding: utf-8 -*-
"""一次性脚本: 撤销 _fix_imports.py 误插入的 sys.path 行

上一版 ensure_syspath 逻辑有缺陷: 只认 _ROOT 变量,对已用 _PROJECT_ROOT /
os.path.dirname(__file__) 设过 sys.path 的脚本误判为"缺失",重复插入了
依赖未定义 _ROOT 的三行,运行时会 NameError。本脚本删除这些误插行。
"""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_ROOT, "tools")

# _fix_imports.py 插入的固定三行(末尾不带换行)
_INSERTED = [
    "",
    "_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))",
    "sys.path.insert(0, os.path.join(_ROOT, 'src'))",
]


def main():
    fixed = []
    for name in sorted(os.listdir(_TOOLS)):
        if not name.endswith(".py"):
            continue
        if name.startswith("_fix_imports"):
            continue
        path = os.path.join(_TOOLS, name)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.split("\n")

        # 统计该脚本里 sys.path.insert 出现次数
        n_insert = sum(1 for ln in lines if "sys.path.insert" in ln)
        if n_insert <= 1:
            continue  # 无重复,跳过

        # 删除所有形如 sys.path.insert(0, os.path.join(_ROOT, 'src')) 的行,
        # 以及紧邻其上的 _ROOT 定义行(若该 _ROOT 定义在文件里只出现这一次)
        n_root_def = sum(
            1 for ln in lines
            if "_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))" in ln)
        out = []
        i = 0
        removed = 0
        while i < len(lines):
            ln = lines[i]
            if "sys.path.insert(0, os.path.join(_ROOT, 'src'))" in ln:
                # 连带删掉紧邻上方的空行与 _ROOT 定义
                while out and out[-1].strip() == "":
                    out.pop()
                if (out and "_ROOT = os.path.dirname(os.path.dirname("
                        "os.path.abspath(__file__)))" in out[-1]
                        and n_root_def == 1):
                    out.pop()
                    while out and out[-1].strip() == "":
                        out.pop()
                removed += 1
                i += 1
                continue
            out.append(ln)
            i += 1
        if removed:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(out))
            fixed.append((name, removed))
    print(f"清理 {len(fixed)} 个脚本的重复 sys.path:")
    for n, c in fixed:
        print(f"  {n} (-{c} 行)")


if __name__ == "__main__":
    main()
