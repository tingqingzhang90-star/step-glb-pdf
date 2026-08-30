# -*- coding: utf-8 -*-
"""
纯 Python 工程图生成器（不使用 SolidWorks COM）

方案：
1. 使用参考 PDF 作为模板基础
2. 使用 pythonOCC 从 STEP 生成 2D 视图投影
3. 使用 PyMuPDF (fitz) 渲染视图并添加尺寸标注
4. 更新技术参数表

依赖：
    conda run -n pdf1 python ...
"""
import os
import io
import json
import time
import math
import shutil
from typing import Dict, List, Optional, Tuple, Any

import fitz  # PyMuPDF

from OCC.Core.gp import gp_Dir, gp_Ax2, gp_Pnt
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib

from core import drawing_engine


# 250 直连系列参考 PDF 模板路径
TEMPLATE_PDF = r"e:\分享代码\step__glb_pdf\图库项目\250直连\250-E-H2K1-L104\pdf\250-E-H2K1-L104.source.pdf"

# 250 系列固定尺寸参数（不随行程变化的尺寸）
FIXED_DIMENSIONS = {
    "A": 250,    # 缸径
    "B": 350,    # 安装孔距
    "C": 165,    # 前法兰厚度
    "D": 290,    # 总宽
    "E": 40,     # 鱼眼轴承孔径
    "F": 90,     # 底部安装孔距
    "G": 137,    # 底部安装孔径
    "H": 50,     # 底部安装孔径
    "I": 300,    # 电机减速机长度
    "J": 137,    # 减速机安装孔径
    "K": 444,    # 电机总长
    "L": 50,     # 联轴器孔径
    "M": 110,    # 电机安装孔径
    "N": 5,      # 键槽
    "O": 200,    # 电机法兰宽度
    "P": 145,    # 电机法兰高度
}

# 技术参数表字段映射
PARAM_TABLE_FIELDS = {
    "产品型号": "model_code",
    "缸径（mm）": "bore_diameter",
    "有效行程（mm）": "stroke",
    "电机功率（KW）": "motor_power",
    "额定转速（rpm）": "rated_speed",
    "额定扭矩（N.M）": "rated_torque",
    "最高转速（rpm）": "max_speed",
    "丝杆型号": "screw_model",
    "丝杆导程（mm）": "screw_lead",
    "减速比": "reduction_ratio",
    "重复定位精度（mm）": "positioning_accuracy",
}


class DrawingGenerator:
    """纯 Python 工程图生成器"""
    
    def __init__(self, template_pdf: str = None):
        self.template_pdf = template_pdf or TEMPLATE_PDF
        if not os.path.exists(self.template_pdf):
            raise FileNotFoundError(f"模板 PDF 不存在: {self.template_pdf}")
    
    def generate(self, step_path: str, output_pdf: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成工程图 PDF
        
        Args:
            step_path: STEP 文件路径
            output_pdf: 输出 PDF 路径
            params: 型号参数，包含：
                - model_code: 型号编码（如 "250-E-H2K1-L100"）
                - stroke: 行程（mm）
                - bore_diameter: 缸径（mm）
                - motor_power: 电机功率（KW）
                - 等等...
        
        Returns:
            生成结果字典
        """
        t0 = time.time()
        result = {
            "success": False,
            "output_pdf": output_pdf,
            "elapsed": 0,
            "steps": []
        }
        
        try:
            # 1. 复制模板 PDF
            t1 = time.time()
            shutil.copy(self.template_pdf, output_pdf)
            result["steps"].append({"name": "复制模板", "time": round(time.time() - t1, 3)})
            
            # 2. 读取 STEP 并生成视图
            t2 = time.time()
            views_data = self._generate_views(step_path)
            result["steps"].append({"name": "生成视图", "time": round(time.time() - t2, 3)})
            
            # 3. 打开 PDF 并添加视图
            t3 = time.time()
            doc = fitz.open(output_pdf)
            page = doc[0]
            
            # 渲染视图到 PDF
            self._render_views(page, views_data)
            result["steps"].append({"name": "渲染视图", "time": round(time.time() - t3, 3)})
            
            # 4. 更新技术参数表
            t4 = time.time()
            self._update_parameter_table(page, params)
            result["steps"].append({"name": "更新参数表", "time": round(time.time() - t4, 3)})
            
            # 5. 添加尺寸标注
            t5 = time.time()
            self._add_dimensions(page, params)
            result["steps"].append({"name": "添加标注", "time": round(time.time() - t5, 3)})
            
            # 6. 保存 PDF
            t6 = time.time()
            doc.save(output_pdf, incremental=True, encryption=0)
            doc.close()
            result["steps"].append({"name": "保存PDF", "time": round(time.time() - t6, 3)})
            
            result["success"] = True
            result["elapsed"] = round(time.time() - t0, 3)
            
        except Exception as e:
            result["error"] = str(e)
            import traceback
            result["traceback"] = traceback.format_exc()
        
        return result
    
    def _generate_views(self, step_path: str) -> Dict[str, Any]:
        """从 STEP 生成视图投影数据"""
        # 使用现有的 drawing_engine
        result = drawing_engine.generate_drawing_views_fast(
            step_path,
            views=["front", "top"],
            target_width=400,
            target_height=300
        )
        return result
    
    def _render_views(self, page: fitz.Page, views_data: Dict[str, Any]):
        """将视图渲染到 PDF 页面"""
        # 视图在 PDF 中的位置（基于 A3 横向布局）
        view_positions = {
            "front": {"x": 500, "y": 200, "width": 350, "height": 260},  # 主视图
            "top": {"x": 500, "y": 500, "width": 350, "height": 200},    # 俯视图
        }
        
        for view_name, view_data in views_data.get("views", {}).items():
            if view_name not in view_positions:
                continue
            
            pos = view_positions[view_name]
            segments = view_data.get("visible", [])
            
            # 绘制视图边线
            for seg in segments:
                if seg["type"] == "line":
                    # 将归一化坐标转换为 PDF 坐标
                    x1 = pos["x"] + seg["x1"] * pos["width"] / 400
                    y1 = pos["y"] + seg["y1"] * pos["height"] / 300
                    x2 = pos["x"] + seg["x2"] * pos["width"] / 400
                    y2 = pos["y"] + seg["y2"] * pos["height"] / 300
                    
                    # 绘制线段
                    shape = page.new_shape()
                    shape.draw_line(fitz.Point(x1, y1), fitz.Point(x2, y2))
                    shape.finish(color=(0, 0, 0), width=0.5)
                    shape.commit()
    
    def _update_parameter_table(self, page: fitz.Page, params: Dict[str, Any]):
        """更新技术参数表"""
        # 参数表位置（基于参考 PDF 分析）
        table_x = 85
        table_y = 509
        row_height = 28.35  # 约 10mm
        col_widths = [215, 160, 215, 160]  # 标签列和值列宽度
        
        # 需要更新的字段
        fields_to_update = {
            "产品型号": params.get("model_code", ""),
            "有效行程（mm）": str(params.get("stroke", "")),
            "缸径（mm）": str(params.get("bore_diameter", "250")),
            "电机功率（KW）": params.get("motor_power", ""),
            "额定转速（rpm）": params.get("rated_speed", ""),
            "额定扭矩（N.M）": params.get("rated_torque", ""),
            "最高转速（rpm）": params.get("max_speed", ""),
            "丝杆型号": params.get("screw_model", ""),
            "丝杆导程（mm）": params.get("screw_lead", ""),
            "减速比": params.get("reduction_ratio", ""),
            "重复定位精度（mm）": params.get("positioning_accuracy", "±0.02"),
        }
        
        # 查找并更新文本（通过覆盖旧文本）
        for field_name, field_value in fields_to_update.items():
            if not field_value:
                continue
            
            # 查找字段在 PDF 中的位置
            text_instances = page.search_for(field_name)
            if text_instances:
                # 获取字段位置
                field_rect = text_instances[0]
                # 值在字段右侧约 215 像素处
                value_x = field_rect.x0 + 215
                value_y = field_rect.y0
                
                # 插入新值
                text_rect = fitz.Rect(value_x, value_y, value_x + 150, value_y + 16)
                page.insert_textbox(
                    text_rect,
                    field_value,
                    fontsize=12,
                    fontname="china-s",
                    color=(0, 0, 0),
                    align=fitz.TEXT_ALIGN_LEFT
                )
    
    def _add_dimensions(self, page: fitz.Page, params: Dict[str, Any]):
        """添加尺寸标注"""
        stroke = params.get("stroke", 100)
        
        # 计算随行程变化的尺寸
        # L1 = 行程 + 185
        # L2 = 行程 + 409
        L1 = stroke + 185
        L2 = stroke + 409
        
        # 尺寸标注位置和样式
        dim_style = {
            "color": (1, 0, 0),  # 红色
            "width": 0.8,
            "fontsize": 10,
            "arrow_size": 5,
        }
        
        # 添加 L1 尺寸（缸体总长）
        self._draw_dimension(
            page,
            start=(300, 350),
            end=(300 + L1 * 0.7, 350),  # 缩放比例 0.7
            text=f"{L1}",
            offset=30,
            style=dim_style
        )
        
        # 添加 L2 尺寸（总长）
        self._draw_dimension(
            page,
            start=(300, 400),
            end=(300 + L2 * 0.7, 400),
            text=f"{L2}",
            offset=30,
            style=dim_style
        )
        
        # 添加行程尺寸
        self._draw_dimension(
            page,
            start=(400, 300),
            end=(400 + stroke * 0.7, 300),
            text=f"{stroke}",
            offset=20,
            style=dim_style
        )
    
    def _draw_dimension(self, page: fitz.Page, start: Tuple[float, float], 
                        end: Tuple[float, float], text: str, offset: float,
                        style: Dict[str, Any]):
        """绘制单个尺寸标注"""
        x1, y1 = start
        x2, y2 = end
        
        # 尺寸线偏移
        if abs(y1 - y2) < 0.1:  # 水平尺寸
            x1_off, y1_off = x1, y1 + offset
            x2_off, y2_off = x2, y2 + offset
        else:  # 垂直尺寸
            x1_off, y1_off = x1 + offset, y1
            x2_off, y2_off = x2 + offset, y2
        
        shape = page.new_shape()
        
        # 绘制尺寸线
        shape.draw_line(fitz.Point(x1_off, y1_off), fitz.Point(x2_off, y2_off))
        shape.finish(color=style["color"], width=style["width"])
        
        # 绘制延伸线
        shape.draw_line(fitz.Point(x1, y1), fitz.Point(x1_off, y1_off))
        shape.draw_line(fitz.Point(x2, y2), fitz.Point(x2_off, y2_off))
        shape.finish(color=style["color"], width=style["width"] * 0.6)
        
        # 绘制箭头
        arrow_size = style["arrow_size"]
        # 起点箭头
        shape.draw_line(fitz.Point(x1_off - arrow_size, y1_off - arrow_size/2), 
                       fitz.Point(x1_off, y1_off))
        shape.draw_line(fitz.Point(x1_off - arrow_size, y1_off + arrow_size/2), 
                       fitz.Point(x1_off, y1_off))
        # 终点箭头
        shape.draw_line(fitz.Point(x2_off + arrow_size, y2_off - arrow_size/2), 
                       fitz.Point(x2_off, y2_off))
        shape.draw_line(fitz.Point(x2_off + arrow_size, y2_off + arrow_size/2), 
                       fitz.Point(x2_off, y2_off))
        shape.finish(color=style["color"], width=style["width"])
        
        shape.commit()
        
        # 添加尺寸文本
        text_x = (x1_off + x2_off) / 2
        text_y = (y1_off + y2_off) / 2 - 10
        text_rect = fitz.Rect(text_x - 30, text_y, text_x + 30, text_y + 14)
        page.insert_textbox(
            text_rect,
            text,
            fontsize=style["fontsize"],
            fontname="china-s",
            color=style["color"],
            align=fitz.TEXT_ALIGN_CENTER
        )


def generate_drawing_pdf(step_path: str, output_pdf: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    生成工程图 PDF 的便捷函数
    
    Args:
        step_path: STEP 文件路径
        output_pdf: 输出 PDF 路径
        params: 型号参数
    
    Returns:
        生成结果字典
    """
    generator = DrawingGenerator()
    return generator.generate(step_path, output_pdf, params)


# 测试入口
if __name__ == "__main__":
    import sys
    
    # 测试参数
    test_params = {
        "model_code": "250-E-H2K1-L100-D11",
        "stroke": 100,
        "bore_diameter": "250",
        "motor_power": "0.75",
        "rated_speed": "3000",
        "rated_torque": "2.4",
        "max_speed": "5000",
        "screw_model": "SFU1605",
        "screw_lead": "5",
        "reduction_ratio": "1:5",
        "positioning_accuracy": "±0.02",
    }
    
    step_path = r"e:\分享代码\step__glb_pdf\output\250-E-H2K1-L100-D11\assembly.step"
    output_pdf = r"e:\分享代码\step__glb_pdf\output\250-E-H2K1-L100-D11\drawing.pdf"
    
    if not os.path.exists(step_path):
        print(f"STEP 文件不存在: {step_path}")
        sys.exit(1)
    
    print(f"生成工程图: {step_path} -> {output_pdf}")
    result = generate_drawing_pdf(step_path, output_pdf, test_params)
    
    print(f"\n生成结果:")
    print(f"  成功: {result['success']}")
    print(f"  耗时: {result['elapsed']}s")
    print(f"  输出: {result['output_pdf']}")
    
    if result.get("error"):
        print(f"  错误: {result['error']}")
        if result.get("traceback"):
            print(f"\n{result['traceback']}")
    
    for step in result.get("steps", []):
        print(f"  - {step['name']}: {step['time']}s")
