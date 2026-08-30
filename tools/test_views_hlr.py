# -*- coding: utf-8 -*-
"""
测试 generate_all_standard_views 生成的视图方向是否正确
直接调用 drawing_engine 生成 SVG,保存为 HTML 文件在浏览器中打开
"""
import os
import sys

# 添加 src 到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from core import drawing_engine

STEP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'output', '250-E-H3K2-L100-D11', 'assembly.step')
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'output', '250-E-H3K2-L100-D11', 'test_views_hlr')


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    if not os.path.exists(STEP_PATH):
        print(f"STEP 文件不存在: {STEP_PATH}")
        return

    print(f"正在生成视图: {STEP_PATH}")
    result = drawing_engine.generate_all_standard_views(STEP_PATH)
    print(f"耗时: {result['elapsed']}s")
    print(f"模型 BBox: {result['model_bbox']}")
    print(f"视图数量: {len(result['views'])}")

    # 生成 HTML 文件展示所有视图
    html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>HLR 视图测试 - 与 viewer.html 对比</title>
<style>
  body { font-family: 'Microsoft YaHei', sans-serif; background: #1a1a1a; color: #e0e0e0; margin: 20px; }
  h1 { font-size: 18px; }
  .info { background: #212121; padding: 12px; border-radius: 8px; margin-bottom: 16px; font-size: 13px; }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
  .card { background: #212121; border: 1px solid #333; border-radius: 8px; padding: 12px; }
  .card h3 { font-size: 14px; margin: 0 0 8px 0; }
  .card .meta { font-size: 11px; color: #9e9e9e; margin-bottom: 8px; }
  .card svg { background: #fff; border-radius: 4px; display: block; }
  .group-title { font-size: 14px; color: #2196f3; margin: 20px 0 10px 0; font-weight: 600; }
</style>
</head>
<body>
<h1>HLR 视图测试 (STANDARD_VIEW_CONFIGS 修正后)</h1>
<div class="info">
  模型 BBox: {{width}} × {{height}} × {{depth}} mm |
  耗时: {{elapsed}}s |
  <span style="color:#4caf50">前视=圆形端面, 左视=侧面长轴水平, 与 viewer.html 一致</span>
</div>
'''

    html += f'''<div class="info">
  模型 BBox: {result['model_bbox']['width']} × {result['model_bbox']['height']} × {result['model_bbox']['depth']} mm |
  耗时: {result['elapsed']}s
</div>
'''

    # 基本视图
    html += '<div class="group-title">基本视图 (6个)</div><div class="grid">'
    for name in ['front', 'back', 'left', 'right', 'top', 'bottom']:
        v = result['views'].get(name)
        if v:
            html += f'''<div class="card">
  <h3>{v['label']} ({name})</h3>
  <div class="meta">边线: {v['seg_count']} | 隐藏: {v['hidden_count']} | 投影: {v['project_time']}s</div>
  {v['thumbnail']}
</div>
'''
    html += '</div>'

    # 轴测视图
    html += '<div class="group-title">轴测视图 (3个)</div><div class="grid">'
    for name in ['isometric', 'dimetric_left', 'dimetric_right']:
        v = result['views'].get(name)
        if v:
            html += f'''<div class="card">
  <h3>{v['label']} ({name})</h3>
  <div class="meta">边线: {v['seg_count']} | 隐藏: {v['hidden_count']}</div>
  {v['thumbnail']}
</div>
'''
    html += '</div>'

    html += '</body></html>'

    html_path = os.path.join(OUT_DIR, 'views_test.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"\nHTML 报告已保存: {html_path}")

    # 在浏览器中打开
    import webbrowser
    webbrowser.open(f'file:///{html_path.replace(os.sep, "/")}')
    print("已在浏览器中打开")


if __name__ == '__main__':
    main()
