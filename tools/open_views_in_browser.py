# -*- coding: utf-8 -*-
"""
在浏览器中打开生成的6个标准视图PNG文件
"""
import webbrowser
import os
import time

# 视图文件目录
VIEW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'output', '250-E-H3K2-L100-D11', 'test_views')

# 6个标准视图文件
VIEW_FILES = [
    'front.png',   # 前视图
    'back.png',    # 后视图
    'left.png',    # 左视图
    'right.png',   # 右视图
    'top.png',     # 上视图
    'bottom.png',  # 下视图
]

def main():
    print(f"视图文件目录: {VIEW_DIR}")
    print(f"正在打开 {len(VIEW_FILES)} 个视图文件...\n")
    
    for view_file in VIEW_FILES:
        file_path = os.path.join(VIEW_DIR, view_file)
        if os.path.exists(file_path):
            print(f"  打开: {view_file}")
            # 使用file://协议打开本地文件
            file_url = f"file:///{file_path.replace(os.sep, '/')}"
            webbrowser.open(file_url)
            time.sleep(0.3)  # 短暂延迟,避免浏览器打开过多标签页
        else:
            print(f"  文件不存在: {file_path}")
    
    print(f"\n已在浏览器中打开所有视图文件")
    print("请检查视图方向是否正确:")
    print("  - 前视图(front): 应显示圆形端面")
    print("  - 左视图(left): 应显示侧面轮廓(长轴水平)")
    print("  - 上视图(top): 应显示俯视图(长轴水平)")

if __name__ == '__main__':
    main()
