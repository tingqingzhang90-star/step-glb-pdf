# -*- coding: utf-8 -*-
"""端到端联调测试: STEP → HLR 视图 → 锚点投影 → 标注 → SVG 工程图"""
import sys
import os
import webbrowser
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from drawing_template import generate_drawing

STEP = os.path.join(os.path.dirname(__file__), "..", "output",
                    "250-E-H3K2-L100-D11", "assembly.step")

OUT_HTML = os.path.join(os.path.dirname(__file__), "drawing_test.html")


def main():
    params = {
        "model_code": "250-E-H3K2-L100-D11",
        "series": "250",
        "date": date.today().isoformat(),
        "scale": 5,
        "has_motor": True,
        "motor_code": "YE3-132M-4",
    }

    print("正在生成工程图...")
    result = generate_drawing(
        STEP,
        views=["front", "top", "left"],
        params=params
    )

    tr = result["template_result"]
    print(f"\n耗时: {result['elapsed']}s")
    print(f"视图数: {len(tr.get('views', {}))}")
    print(f"标注数: {len(tr.get('dimensions', []))}")
    print(f"未匹配: {tr.get('unmatched', [])}")

    for vid, vdata in tr.get("views", {}).items():
        print(f"  视图 {vid}: scale={vdata['scale']} offset={vdata['offset']} "
              f"visible={len(vdata['visible'])} hidden={len(vdata['hidden'])}")

    print("\n标注详情:")
    for dim in tr.get("dimensions", []):
        print(f"  {dim.get('id')}: type={dim.get('type')} "
              f"text={dim.get('text', '')} value={dim.get('value', '')}")
        if dim.get("p1_screen"):
            print(f"    p1_screen={dim['p1_screen']} p2_screen={dim['p2_screen']}")

    # 写入 HTML 预览
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>工程图联调测试</title>
<style>
body {{ margin: 20px; background: #f5f5f5; }}
h2 {{ font-family: sans-serif; color: #333; }}
.svg-container {{ background: white; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
.info {{ font-family: monospace; font-size: 13px; margin: 10px 0; color: #666; }}
</style>
</head>
<body>
<h2>250-E-H3K2-L100-D11 工程图</h2>
<div class="info">耗时: {result['elapsed']}s | 标注: {len(tr.get('dimensions', []))} | 未匹配: {tr.get('unmatched', [])}</div>
<div class="svg-container">{result['svg']}</div>
</body>
</html>"""

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nHTML 已保存到: {OUT_HTML}")
    webbrowser.open(f"file:///{OUT_HTML.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
