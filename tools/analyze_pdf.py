#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF结构分析脚本
使用PyMuPDF (fitz)提取PDF的详细信息
"""

import fitz  # PyMuPDF
import json
from pathlib import Path
from typing import Dict, List, Any


def analyze_pdf(pdf_path: str) -> Dict[str, Any]:
    """
    分析单个PDF文件的结构信息
    
    Args:
        pdf_path: PDF文件路径
        
    Returns:
        包含PDF结构信息的字典
    """
    print(f"\n{'='*80}")
    print(f"分析PDF: {pdf_path}")
    print(f"{'='*80}\n")
    
    # 打开PDF文档
    doc = fitz.open(pdf_path)
    
    result = {
        "file_path": pdf_path,
        "page_count": len(doc),
        "pages": []
    }
    
    # 遍历每一页
    for page_num in range(len(doc)):
        page = doc[page_num]
        print(f"\n处理第 {page_num + 1} 页...")
        
        page_info = {
            "page_number": page_num + 1,
            "page_size": {
                "width": page.rect.width,
                "height": page.rect.height,
                "x0": page.rect.x0,
                "y0": page.rect.y0,
                "x1": page.rect.x1,
                "y1": page.rect.y1
            },
            "text_blocks": [],
            "drawings": [],
            "images": [],
            "annotations": []
        }
        
        # 1. 提取文本内容及其位置
        print("  - 提取文本内容...")
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block["type"] == 0:  # 文本块
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text_info = {
                            "text": span["text"],
                            "bbox": span["bbox"],
                            "font": span["font"],
                            "size": span["size"],
                            "color": span["color"],
                            "flags": span["flags"]
                        }
                        page_info["text_blocks"].append(text_info)
        
        # 2. 提取线条/路径
        print("  - 提取线条/路径...")
        drawings = page.get_drawings()
        for drawing in drawings:
            drawing_info = {
                "rect": drawing["rect"],
                "items": []
            }
            for item in drawing.get("items", []):
                item_type = item[0]
                if item_type == "l":  # 线段
                    drawing_info["items"].append({
                        "type": "line",
                        "points": [item[1], item[2]]
                    })
                elif item_type == "re":  # 矩形
                    drawing_info["items"].append({
                        "type": "rectangle",
                        "rect": item[1]
                    })
                elif item_type == "c":  # 曲线
                    drawing_info["items"].append({
                        "type": "curve",
                        "points": item[1:]
                    })
            
            drawing_info["color"] = drawing.get("color")
            drawing_info["fill"] = drawing.get("fill")
            drawing_info["width"] = drawing.get("width")
            page_info["drawings"].append(drawing_info)
        
        # 3. 提取图片信息
        print("  - 提取图片信息...")
        image_list = page.get_images()
        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            if base_image:
                image_info = {
                    "index": img_index,
                    "xref": xref,
                    "width": base_image["width"],
                    "height": base_image["height"],
                    "ext": base_image["ext"],
                    "colorspace": base_image["colorspace"],
                    "bbox": None
                }
                
                # 尝试获取图片在页面上的位置
                try:
                    img_rects = page.get_image_rects(xref)
                    if img_rects:
                        image_info["bbox"] = img_rects[0]
                except:
                    pass
                
                page_info["images"].append(image_info)
        
        # 4. 提取标注信息
        print("  - 提取标注信息...")
        annots = page.annots()
        if annots:
            for annot in annots:
                annot_info = {
                    "type": annot.type[1],
                    "rect": annot.rect,
                    "content": annot.info.get("content", ""),
                    "title": annot.info.get("title", "")
                }
                page_info["annotations"].append(annot_info)
        
        result["pages"].append(page_info)
    
    doc.close()
    
    # 分析关键元素
    print("\n分析关键元素...")
    result["analysis"] = analyze_key_elements(result)
    
    return result


def analyze_key_elements(pdf_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    分析PDF中的关键元素：标题栏、视图、尺寸标注、参数表
    """
    analysis = {
        "title_block": None,
        "views": [],
        "dimensions": [],
        "parameter_tables": []
    }
    
    if not pdf_data["pages"]:
        return analysis
    
    page = pdf_data["pages"][0]
    page_width = page["page_size"]["width"]
    page_height = page["page_size"]["height"]
    
    # 1. 分析标题栏（通常在右下角）
    print("  - 分析标题栏...")
    title_block_texts = []
    for text in page["text_blocks"]:
        bbox = text["bbox"]
        # 标题栏通常在页面右下区域
        if bbox[0] > page_width * 0.6 and bbox[1] > page_height * 0.7:
            title_block_texts.append({
                "text": text["text"],
                "position": bbox,
                "size": text["size"]
            })
    
    if title_block_texts:
        analysis["title_block"] = {
            "location": "右下角",
            "texts": title_block_texts
        }
    
    # 2. 分析视图（通过文本内容识别）
    print("  - 分析视图...")
    view_keywords = ["主视图", "俯视图", "左视图", "右视图", "仰视图", "后视图", 
                     "Front", "Top", "Left", "Right", "Bottom", "Rear",
                     "A向", "B向", "C向", "D向"]
    
    for text in page["text_blocks"]:
        for keyword in view_keywords:
            if keyword in text["text"]:
                analysis["views"].append({
                    "name": text["text"],
                    "position": text["bbox"],
                    "size": text["size"]
                })
                break
    
    # 3. 分析尺寸标注
    print("  - 分析尺寸标注...")
    dimension_texts = []
    for text in page["text_blocks"]:
        # 尺寸通常包含数字和单位符号，或者带有φ、R等前缀
        text_content = text["text"]
        if any(c.isdigit() for c in text_content):
            if any(prefix in text_content for prefix in ["φ", "R", "M", "°", "×"]):
                dimension_texts.append({
                    "text": text_content,
                    "position": text["bbox"],
                    "size": text["size"]
                })
    
    analysis["dimensions"] = dimension_texts
    
    # 4. 分析参数表（通过线条和文本的组合识别）
    print("  - 分析参数表...")
    # 参数表通常由多个矩形线条组成，且包含文本
    if len(page["drawings"]) > 0 and len(page["text_blocks"]) > 0:
        # 查找表格区域（简化逻辑：查找包含密集线条和文本的区域）
        table_regions = []
        
        # 统计每个区域的线条密度
        for drawing in page["drawings"]:
            rect = drawing["rect"]
            if rect:
                # 检查该区域是否有文本
                text_count = 0
                for text in page["text_blocks"]:
                    text_bbox = text["bbox"]
                    if (rect[0] <= text_bbox[0] <= rect[2] and 
                        rect[1] <= text_bbox[1] <= rect[3]):
                        text_count += 1
                
                if text_count > 3:  # 如果区域内有多个文本，可能是表格
                    table_regions.append({
                        "rect": rect,
                        "text_count": text_count
                    })
        
        if table_regions:
            analysis["parameter_tables"] = table_regions
    
    return analysis


def convert_to_serializable(obj):
    """
    将PyMuPDF对象转换为可JSON序列化的类型
    """
    if isinstance(obj, dict):
        return {k: convert_to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_serializable(item) for item in obj]
    elif isinstance(obj, tuple):
        return [convert_to_serializable(item) for item in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    elif isinstance(obj, fitz.Rect):
        return {"x0": obj.x0, "y0": obj.y0, "x1": obj.x1, "y1": obj.y1}
    elif isinstance(obj, fitz.Point):
        return {"x": obj.x, "y": obj.y}
    elif hasattr(obj, 'x0') and hasattr(obj, 'y0'):
        # 其他类似Rect的对象
        return {"x0": obj.x0, "y0": obj.y0, "x1": obj.x1, "y1": obj.y1}
    else:
        return str(obj)


def save_to_json(data: Dict[str, Any], output_path: str):
    """
    将分析结果保存为JSON文件
    """
    # 转换所有对象为可序列化格式
    serializable_data = convert_to_serializable(data)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(serializable_data, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到: {output_path}")


def print_summary(pdf_data: Dict[str, Any]):
    """
    打印PDF分析的摘要信息
    """
    print(f"\n{'='*80}")
    print("PDF分析摘要")
    print(f"{'='*80}")
    print(f"文件路径: {pdf_data['file_path']}")
    print(f"页面数量: {pdf_data['page_count']}")
    
    if pdf_data['pages']:
        page = pdf_data['pages'][0]
        print(f"\n第1页信息:")
        print(f"  页面尺寸: {page['page_size']['width']:.2f} x {page['page_size']['height']:.2f}")
        print(f"  文本块数量: {len(page['text_blocks'])}")
        print(f"  线条/路径数量: {len(page['drawings'])}")
        print(f"  图片数量: {len(page['images'])}")
        print(f"  标注数量: {len(page['annotations'])}")
        
        # 打印关键元素分析
        analysis = pdf_data.get('analysis', {})
        
        if analysis.get('title_block'):
            print(f"\n标题栏分析:")
            print(f"  位置: {analysis['title_block']['location']}")
            print(f"  文本数量: {len(analysis['title_block']['texts'])}")
            for i, text in enumerate(analysis['title_block']['texts'][:5]):
                print(f"    {i+1}. '{text['text']}' (大小: {text['size']:.1f})")
        
        if analysis.get('views'):
            print(f"\n视图分析:")
            print(f"  发现 {len(analysis['views'])} 个视图标记")
            for view in analysis['views'][:5]:
                print(f"    - {view['name']} @ {view['position']}")
        
        if analysis.get('dimensions'):
            print(f"\n尺寸标注分析:")
            print(f"  发现 {len(analysis['dimensions'])} 个尺寸标注")
            for dim in analysis['dimensions'][:5]:
                print(f"    - {dim['text']} @ {dim['position']}")
        
        if analysis.get('parameter_tables'):
            print(f"\n参数表分析:")
            print(f"  发现 {len(analysis['parameter_tables'])} 个可能的表格区域")
            for i, table in enumerate(analysis['parameter_tables'][:3]):
                print(f"    {i+1}. 区域: {table['rect']}, 包含 {table['text_count']} 个文本")


def main():
    """
    主函数
    """
    # 定义要分析的PDF文件
    pdf_files = [
        r"e:\分享代码\step__glb_pdf\图库项目\250直连\250-E-H2K1-L104\pdf\250-E-H2K1-L104.source.pdf",
        r"e:\分享代码\step__glb_pdf\图库项目\250直连\250-E-H2K1-L104\pdf\250-E-H2K1-L104.pdf"
    ]
    
    # 分析每个PDF文件
    for pdf_path in pdf_files:
        if not Path(pdf_path).exists():
            print(f"警告: 文件不存在 - {pdf_path}")
            continue
        
        # 分析PDF
        pdf_data = analyze_pdf(pdf_path)
        
        # 打印摘要
        print_summary(pdf_data)
        
        # 保存详细结果到JSON
        output_filename = Path(pdf_path).stem + "_analysis.json"
        output_path = Path(pdf_path).parent / output_filename
        save_to_json(pdf_data, str(output_path))
    
    print(f"\n{'='*80}")
    print("分析完成!")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
