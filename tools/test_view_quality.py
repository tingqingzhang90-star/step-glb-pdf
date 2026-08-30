# -*- coding: utf-8 -*-
"""测试视图质量:生成6个标准视图的SVG文件,在浏览器中打开查看

验证:
  1. 视图方向是否正确(前/后/左/右/上/下)
  2. 是否存在断裂/空白
  3. 线条杂糅程度
  4. 生成耗时
"""
import os
import sys
import time
import json
import webbrowser

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_PROJECT_ROOT, "src")
sys.path.insert(0, _SRC)

from core import drawing_engine


def generate_test_views():
    """生成6个标准视图并保存为HTML"""
    model_code = "250-E-H3K2-L100-D11"
    step_path = os.path.join(_PROJECT_ROOT, "output", model_code, "assembly.step")

    if not os.path.exists(step_path):
        print(f"✗ STEP 文件不存在: {step_path}")
        return

    print(f"模型: {model_code}")
    print(f"STEP: {step_path}")
    print(f"文件大小: {os.path.getsize(step_path) / 1024 / 1024:.2f} MB")

    # 生成9个标准视图(6基本+3轴测)
    print("\n--- 生成视图 ---")
    t0 = time.time()
    result = drawing_engine.generate_all_standard_views(
        step_path,
        include_hidden=False,
        thumb_width=420,
        thumb_height=280,
        canvas_width=500,
        canvas_height=380
    )
    elapsed = time.time() - t0

    print(f"总耗时: {elapsed:.2f}秒")
    print(f"  读取: {result['timing']['read']}秒")
    print(f"  投影: {result['timing']['project']}秒")
    print(f"模型包围盒: {result['model_bbox']}")
    print(f"统一缩放: {result['scale_info']}")

    views = result.get("views", {})
    print(f"\n视图数量: {len(views)}")
    for name, view in views.items():
        print(f"  {name}({view['label']}): "
              f"边线数={view['seg_count']}, 隐藏={view['hidden_count']}, "
              f"投影={view['project_time']}秒")

    def render_svg(segments, hidden_segments, width=500, height=380):
        def seg_to_svg(seg, hidden=False):
            stroke = "#999999" if hidden else "#333333"
            dash = ' stroke-dasharray="2,2"' if hidden else ''
            if seg["type"] == "line":
                return f'<line x1="{seg["x1"]}" y1="{seg["y1"]}" x2="{seg["x2"]}" y2="{seg["y2"]}" stroke="{stroke}" stroke-width="0.8"{dash}/>'
            if seg["type"] == "circle":
                return f'<circle cx="{seg["cx"]}" cy="{seg["cy"]}" r="{seg["r"]}" stroke="{stroke}" stroke-width="0.8" fill="none"{dash}/>'
            if seg["type"] == "polyline":
                pts = " ".join(f"{x},{y}" for x, y in seg["points"])
                return f'<polyline points="{pts}" stroke="{stroke}" stroke-width="0.8" fill="none"{dash}/>'
            return ""

        parts = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">',
                 f'<rect width="{width}" height="{height}" fill="#fafafa"/>']
        for seg in hidden_segments:
            parts.append(seg_to_svg(seg, hidden=True))
        for seg in segments:
            parts.append(seg_to_svg(seg, hidden=False))
        parts.append('</svg>')
        return "".join(parts)

    # 生成HTML展示
    html_path = os.path.join(_PROJECT_ROOT, "tools", "view_quality_test.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write("""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>视图质量测试 - """ + model_code + """</title>
<style>
body { font-family: 'Microsoft YaHei', sans-serif; margin: 20px; background: #f5f5f5; }
h1 { color: #333; }
.info { background: #fff; padding: 12px; border-radius: 6px; margin-bottom: 16px; }
.grid { display: grid; grid-template-columns: repeat(3, minmax(520px, 1fr)); gap: 16px; align-items: start; }
.view-card { background: #fff; padding: 12px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }
.view-card h3 { margin: 0 0 8px 0; font-size: 14px; color: #666; }
.view-card .thumb { background: #fafafa; border: 1px solid #eee; display: flex; justify-content: center; align-items: center; min-height: 300px; overflow: auto; }
.view-card .thumb svg { width: 100%; height: auto; min-width: 500px; }
.view-card .stats { font-size: 12px; color: #999; margin-top: 6px; }
</style></head><body>
<h1>视图质量测试</h1>
<div class="info">
  <b>型号:</b> """ + model_code + """<br>
  <b>总耗时:</b> """ + f"{elapsed:.2f}" + """秒 |
  <b>读取:</b> """ + f"{result['timing']['read']}" + """秒 |
  <b>投影:</b> """ + f"{result['timing']['project']}" + """秒<br>
  <b>模型包围盒:</b> X=""" + f"{result['model_bbox']['width']}" + """ Y=""" + f"{result['model_bbox']['height']}" + """ Z=""" + f"{result['model_bbox']['depth']}" + """mm<br>
  <b>统一缩放:</b> """ + f"{result['scale_info']['uniform_scale']}" + """ (""" + f"{result['scale_info']['mm_per_pixel']}" + """ mm/px)
</div>
<div class="grid">
""")

        # 先放6个基本视图
        standard_order = ["front", "back", "left", "right", "top", "bottom"]
        iso_order = ["isometric", "dimetric_left", "dimetric_right"]

        for name in standard_order + iso_order:
            if name not in views:
                continue
            view = views[name]
            canvas_svg = render_svg(view["edges"], view["hidden_edges"])
            f.write(f"""<div class="view-card">
<h3>{view['label']} ({name})</h3>
<div class="thumb">{canvas_svg}</div>
<div class="stats">边线: {view['seg_count']} | 隐藏: {view['hidden_count']} | {view['project_time']}s</div>
</div>
""")

        f.write("</div></body></html>")

    print(f"\n✓ HTML 已生成: {html_path}")

    # 自动打开浏览器
    webbrowser.open(f"file:///{html_path.replace(os.sep, '/')}")
    print("✓ 已在浏览器中打开")


if __name__ == "__main__":
    generate_test_views()
