#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SLDDRW 模板文件结构分析
尝试提取 SolidWorks 工程图模板的布局信息
"""

import os
import re
import zipfile
from pathlib import Path


def analyze_slddrw(slddrw_path: str):
    """
    分析 SLDDRW 文件结构
    
    SLDDRW 是 SolidWorks 的二进制格式，但可能包含一些可读的文本信息
    """
    print(f"\n{'='*80}")
    print(f"分析 SLDDRW: {slddrw_path}")
    print(f"{'='*80}\n")
    
    if not os.path.exists(slddrw_path):
        print(f"文件不存在: {slddrw_path}")
        return
    
    file_size = os.path.getsize(slddrw_path)
    print(f"文件大小: {file_size:,} 字节 ({file_size/1024/1024:.2f} MB)\n")
    
    # 1. 尝试作为 ZIP 打开（某些 SolidWorks 文件可能是复合文档）
    print("1. 尝试作为 ZIP 打开...")
    try:
        with zipfile.ZipFile(slddrw_path, 'r') as zf:
            print(f"  ✓ 是 ZIP 格式，包含 {len(zf.namelist())} 个文件:")
            for name in zf.namelist()[:20]:
                info = zf.getinfo(name)
                print(f"    - {name} ({info.file_size:,} 字节)")
    except zipfile.BadZipFile:
        print("  ✗ 不是 ZIP 格式")
    
    # 2. 提取可读文本
    print("\n2. 提取可读文本内容...")
    text_patterns = []
    
    with open(slddrw_path, 'rb') as f:
        content = f.read()
        
        # 查找 UTF-8 编码的文本
        try:
            text = content.decode('utf-8', errors='ignore')
            # 提取中文字符和英文单词
            chinese_chars = re.findall(r'[\u4e00-\u9fff]+', text)
            english_words = re.findall(r'[A-Za-z_][A-Za-z0-9_]{2,}', text)
            
            print(f"  找到 {len(chinese_chars)} 个中文字符串")
            print(f"  找到 {len(english_words)} 个英文单词")
            
            # 显示前 20 个有意义的文本
            print("\n  中文字符串示例:")
            for i, char in enumerate(chinese_chars[:20]):
                if len(char) > 1:
                    print(f"    {i+1}. {char}")
            
            print("\n  英文单词示例:")
            for i, word in enumerate(english_words[:20]):
                if len(word) > 3:
                    print(f"    {i+1}. {word}")
        except Exception as e:
            print(f"  提取失败: {e}")
    
    # 3. 查找关键标记
    print("\n3. 查找关键标记...")
    keywords = [
        'VIEW', 'SHEET', 'TITLE', 'DIMENSION', 'ANNOTATION',
        'TABLE', 'BOM', 'FORMAT', 'TEMPLATE',
        '主视图', '俯视图', '左视图', '标题栏', '明细表'
    ]
    
    for keyword in keywords:
        count = content.count(keyword.encode('utf-8', errors='ignore'))
        if count > 0:
            print(f"  ✓ '{keyword}' 出现 {count} 次")
    
    # 4. 查找坐标和尺寸信息
    print("\n4. 查找可能的坐标数据...")
    # 查找浮点数模式
    float_pattern = rb'[\x00-\xff]{4}[\x00-\xff]{4}[\x00-\xff]{4}[\x00-\xff]{4}'
    matches = re.findall(float_pattern, content[:10000])
    print(f"  前 10KB 中找到 {len(matches)} 个可能的浮点数序列")
    
    print(f"\n{'='*80}")
    print("分析完成")
    print(f"{'='*80}\n")


def main():
    """主函数"""
    slddrw_path = r"e:\分享代码\step__glb_pdf\图库项目\250直连\YRJ250-H2K2-E.SLDDRW"
    analyze_slddrw(slddrw_path)


if __name__ == "__main__":
    main()
