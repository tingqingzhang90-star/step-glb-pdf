# -*- coding: utf-8 -*-
"""批量工程图生成 CLI — 标注模板 × 型号列表 → PDF/SVG

支持两种模板:
  --template          规则式模板(标注以 bbox_x_min 等规则描述)
  --frontend-template 前端编辑器标注保存的实例模板(几何指纹重绑)

同系列各型号共用一份模板,锚点按型号实时解析(缸长随行程、电机包络
随电机型号自动跟随),失配标注写入报告而非静默丢弃。

用法(在 src 目录或项目根均可):
    python batch_drawing.py --models 250-E-H2K1-L100-D11 250-E-H2K1-L200-D55
    python batch_drawing.py --all
    python batch_drawing.py --all --template src/drawing_template.json
    python batch_drawing.py --frontend-template data/templates/engineering/250-E-H2K1-L100-D11.json \
        --models 250-E-H2K1-L200-D55 250-E-H2K1-L100-D75
"""
import argparse
import json
import os
import sys
import time

# 本文件位于 src/batch/,需把 src 加入 sys.path 才能导入 core/drawing 包
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(_SRC_DIR)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from core import rebuild_assembly as rb
from core import drawing_engine
from drawing.rule_template import drawing_template
from drawing import anchor_resolver
from drawing import frontend_template
from drawing.dim import dim_rebind
from drawing.dim import dim_pdf_sheet
from drawing.drawing_pdf import render_drawing_pdf

DEFAULT_TEMPLATE = os.path.join(
    _SRC_DIR, "drawing", "rule_template", "drawing_template.json")


def discover_models(out_dir):
    """扫描 output 目录,返回含 assembly.step 的型号列表"""
    if not os.path.isdir(out_dir):
        return []
    return sorted(
        d for d in os.listdir(out_dir)
        if os.path.isfile(os.path.join(out_dir, d, "assembly.step"))
    )


def _dim_summary(template_result):
    return [
        {
            "id": d.get("id"),
            "type": d.get("type"),
            "text": d.get("text", ""),
            "value": d.get("value"),
        }
        for d in template_result.get("dimensions", [])
    ]


def generate_one(model_code, template, out_dir, write_svg=True):
    """生成单个型号的工程图,返回结果 dict(不含异常)"""
    t0 = time.time()
    model_dir = os.path.join(out_dir, model_code)
    step_path = os.path.join(model_dir, "assembly.step")
    if not os.path.isfile(step_path):
        raise FileNotFoundError(f"未找到 STEP: {step_path}")

    # 按型号解析锚点与模板参数
    anchors = anchor_resolver.resolve_anchors(model_code)
    params = anchor_resolver.build_model_params(model_code)

    # 视图按模板声明生成
    view_types = sorted({v["type"] for v in template.get("views", [])})
    views_raw = drawing_engine.generate_drawing_views_raw(step_path, views=view_types)
    views_data = dict(views_raw)
    views_data["anchors"] = anchors

    template_result = drawing_template.apply_template(views_data, template, params)

    pdf_path = render_drawing_pdf(
        template_result, os.path.join(model_dir, "drawing.pdf"), params)

    svg_path = None
    if write_svg:
        svg = drawing_template.render_engineering_svg(template_result, params)
        svg_path = os.path.join(model_dir, "drawing.svg")
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg)

    return {
        "model_code": model_code,
        "ok": True,
        "pdf": pdf_path,
        "svg": svg_path,
        "unmatched": template_result.get("unmatched", []),
        "dims": _dim_summary(template_result),
        "elapsed": round(time.time() - t0, 2),
    }


def _frontend_dim_summary(rebound):
    return [
        {
            "id": item["annotation"].get("id"),
            "type": item["annotation"].get("type"),
            "mode": item["annotation"].get("mode"),
            "status": item["status"],
            "reason": item.get("reason", ""),
        }
        for item in rebound
    ]


def generate_one_frontend(model_code, template_doc, base_views, base_refs,
                          base_profile, out_dir):
    """前端实例模板:重绑 + 渲染单型号,返回结果 dict"""
    t0 = time.time()
    model_dir = os.path.join(out_dir, model_code)
    pdf_path = os.path.join(model_dir, "drawing_frontend.pdf")
    identity = frontend_template.template_identity(model_code)
    tmpl_identity = template_doc.get("template_identity") or \
        frontend_template.template_identity(template_doc["model_id"])
    if identity != tmpl_identity:
        raise ValueError(
            f"型号 {model_code}(系列 {identity})与模板系列 {tmpl_identity} 不同,"
            "不能共用该模板")

    shape_path = frontend_template.find_model_shape(out_dir, model_code)
    palette = drawing_engine.generate_all_standard_views(shape_path)
    target_profile = anchor_resolver.resolve_anchors(model_code)
    ctx = dim_rebind.compensation_ctx(base_profile, target_profile)

    # 视图放置:模板里 v.scale 是前端 UI 缩放,与后端渲染无关;
    # segs 已经是画布 px 坐标(由 px_per_mm 归一化得到),直接用模板位置
    # placement.scale=1,placement.k 留给 _mark_half_px 等少量需要缩放的细节
    placements = {}
    for v in template_doc["views"]:
        src = v["source_view"]
        pv = palette["views"].get(src)
        if not pv:
            raise ValueError(f"目标型号不支持视图: {src}")
        k_target = pv.get("bbox", {}).get("scale") or 1.0
        placements[v["id"]] = {
            "x": v["x"], "y": v["y"],
            "scale": 1.0,  # segs 已是画布 px,不再二次缩放
            "source_view": src,
            "segs": pv.get("edges", []),
            "hidden": pv.get("hidden_edges", []),
            "k": k_target,
        }

    rebound = []
    match_cache = {}
    for item in base_refs:
        r = dim_rebind.rebind_annotation(
            item["dim"], item["refs"], ctx, target_profile,
            placements, match_cache)
        r["annotation"] = item["dim"]
        rebound.append(r)

    dim_pdf_sheet.render_frontend_pdf(
        rebound, placements, template_doc, model_code, pdf_path)

    unmatched = [f"{i['annotation'].get('id')}: {i['reason']}"
                 for i in rebound if i["status"] == "unmatched"]
    return {
        "model_code": model_code,
        "ok": True,
        "pdf": pdf_path,
        "svg": None,
        "unmatched": unmatched,
        "dims": _frontend_dim_summary(rebound),
        "elapsed": round(time.time() - t0, 2),
    }


def run_frontend(models, template_doc, out_dir):
    """前端实例模板批量生成,返回结果列表"""
    base_model = template_doc["model_id"]
    base_views = frontend_template.resolve_base_views(template_doc, out_dir)
    base_refs = frontend_template.resolve_base_refs(template_doc, base_views)
    base_profile = anchor_resolver.resolve_anchors(base_model)

    results = []
    for i, model_code in enumerate(models, 1):
        print(f"[{i}/{len(models)}] {model_code} ...", flush=True)
        try:
            r = generate_one_frontend(model_code, template_doc, base_views,
                                      base_refs, base_profile, out_dir)
        except Exception as e:  # noqa: BLE001 - 单型号失败不中断批次
            import traceback
            r = {"model_code": model_code, "ok": False, "error": str(e),
                 "traceback": traceback.format_exc()}
        results.append(r)
        if r["ok"]:
            flag = f"  [WARN] 未匹配标注: {r['unmatched']}" if r["unmatched"] else ""
            print(f"  [OK] {r['pdf']} ({r['elapsed']}s){flag}", flush=True)
        else:
            print(f"  [FAIL] {r['error']}", flush=True)
            print(r.get("traceback", ""), flush=True)
    return results


def run(models, template, out_dir, write_svg=True):
    """批量生成,返回 (结果列表, 汇总 dict)"""
    results = []
    for i, model_code in enumerate(models, 1):
        print(f"[{i}/{len(models)}] {model_code} ...", flush=True)
        try:
            r = generate_one(model_code, template, out_dir, write_svg)
        except Exception as e:  # noqa: BLE001 - 单型号失败不中断批次
            import traceback
            r = {"model_code": model_code, "ok": False, "error": str(e),
                 "traceback": traceback.format_exc()}
        results.append(r)
        if r["ok"]:
            unmatched = r["unmatched"]
            flag = f"  [WARN] 未匹配标注: {unmatched}" if unmatched else ""
            print(f"  [OK] {r['pdf']} ({r['elapsed']}s){flag}", flush=True)
        else:
            print(f"  [FAIL] {r['error']}", flush=True)
            print(r.get("traceback", ""), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description="按模板批量生成工程图 PDF")
    parser.add_argument("--models", nargs="+", help="型号编码列表")
    parser.add_argument("--all", action="store_true",
                        help="扫描 output 目录处理全部型号")
    parser.add_argument("--template", default=DEFAULT_TEMPLATE,
                        help="规则式模板 JSON 路径")
    parser.add_argument("--frontend-template",
                        help="前端编辑器保存的实例模板 JSON 路径(优先于 --template)")
    parser.add_argument("--out-dir", default=rb.OUT_DIR,
                        help="模型输出根目录(默认 output/)")
    parser.add_argument("--no-svg", action="store_true",
                        help="不输出调试用 SVG")
    args = parser.parse_args()

    models = args.models or []
    if args.all:
        models = discover_models(args.out_dir)
    if not models:
        parser.error("请用 --models 指定型号,或用 --all 处理全部")

    if args.frontend_template:
        template_doc = frontend_template.load_frontend_template(args.frontend_template)
        identity = template_doc.get("template_identity") or \
            frontend_template.template_identity(template_doc["model_id"])
        print(f"模板(前端实例): {args.frontend_template}")
        print(f"基准型号: {template_doc['model_id']}, 系列: {identity}")
        print(f"型号数: {len(models)}\n")
        results = run_frontend(models, template_doc, args.out_dir)
    else:
        template = drawing_template.load_template(args.template)
        print(f"模板: {args.template} ({template.get('name')})")
        print(f"型号数: {len(models)}\n")
        results = run(models, template, args.out_dir,
                      write_svg=not args.no_svg)

    report_path = os.path.join(args.out_dir, "batch_report.json")
    os.makedirs(args.out_dir, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    ok_n = sum(1 for r in results if r["ok"])
    warn_n = sum(1 for r in results if r.get("ok") and r.get("unmatched"))
    print(f"\n完成: {ok_n}/{len(results)} 成功, {warn_n} 个存在未匹配标注")
    print(f"报告: {report_path}")
    sys.exit(0 if ok_n == len(results) else 1)


if __name__ == "__main__":
    main()
