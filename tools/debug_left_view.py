# -*- coding: utf-8 -*-
"""
调试左视图坐标范围，找出长轴垂直的原因
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import drawing_engine
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib

STEP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'output', '250-E-H3K2-L100-D11', 'assembly.step')

def main():
    if not os.path.exists(STEP_PATH):
        print(f"STEP 文件不存在：{STEP_PATH}")
        return

    print(f"读取 STEP: {STEP_PATH}")
    shape = drawing_engine.read_shape_cached(STEP_PATH)

    # 打印 BBox
    bbox = Bnd_Box()
    brepbndlib.Add(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    print(f"\n模型 BBox:")
    print(f"  X: {xmin:.1f} ~ {xmax:.1f} (范围 {xmax-xmin:.1f})")
    print(f"  Y: {ymin:.1f} ~ {ymax:.1f} (范围 {ymax-ymin:.1f})")
    print(f"  Z: {zmin:.1f} ~ {zmax:.1f} (范围 {zmax-zmin:.1f})")
    print(f"  长轴：{'X' if xmax-xmin > max(ymax-ymin, zmax-zmin) else 'Y' if ymax-ymin > zmax-zmin else 'Z'}")

    # 测试左视图配置
    from OCC.Core.gp import gp_Dir
    from drawing_engine import STANDARD_VIEW_CONFIGS

    left_cfg = STANDARD_VIEW_CONFIGS['left']
    print(f"\n左视图配置:")
    print(f"  dir (N): ({left_cfg['dir'].X()}, {left_cfg['dir'].Y()}, {left_cfg['dir'].Z()})")
    print(f"  up (V):  ({left_cfg['up'].X()}, {left_cfg['up'].Y()}, {left_cfg['up'].Z()})")

    # 计算 U = V × N
    v = left_cfg['up']
    n = left_cfg['dir']
    u_x = v.Y() * n.Z() - v.Z() * n.Y()
    u_y = v.Z() * n.X() - v.X() * n.Z()
    u_z = v.X() * n.Y() - v.Y() * n.X()
    print(f"  U = V×N: ({u_x}, {u_y}, {u_z})")

    print(f"\n屏幕坐标系:")
    print(f"  screen_X (U): ({u_x}, {u_y}, {u_z}) - 水平方向")
    print(f"  screen_Y (V): ({v.X()}, {v.Y()}, {v.Z()}) - 垂直方向")

    # 计算模型在屏幕上的投影范围
    # screen_X = 点 · U
    # screen_Y = 点 · V
    # 模型角点：(xmin,ymin,zmin), (xmax,ymax,zmax) 等 8 个角

    corners = [
        (xmin, ymin, zmin), (xmax, ymin, zmin), (xmin, ymax, zmin), (xmax, ymax, zmin),
        (xmin, ymin, zmax), (xmax, ymin, zmax), (xmin, ymax, zmax), (xmax, ymax, zmax)
    ]

    screen_x_vals = [c[0]*u_x + c[1]*u_y + c[2]*u_z for c in corners]
    screen_y_vals = [c[0]*v.X() + c[1]*v.Y() + c[2]*v.Z() for c in corners]

    print(f"\n模型角点在屏幕上的投影:")
    print(f"  screen_X 范围：{min(screen_x_vals):.1f} ~ {max(screen_x_vals):.1f} (宽度 {max(screen_x_vals)-min(screen_x_vals):.1f})")
    print(f"  screen_Y 范围：{min(screen_y_vals):.1f} ~ {max(screen_y_vals):.1f} (高度 {max(screen_y_vals)-min(screen_y_vals):.1f})")

    if max(screen_x_vals)-min(screen_x_vals) > max(screen_y_vals)-min(screen_y_vals):
        print(f"\n✓ 长轴水平显示（宽度 > 高度）")
    else:
        print(f"\n✗ 长轴垂直显示（高度 > 宽度）- 这是问题！")

    # 实际投影测试
    print(f"\n{'='*60}")
    print(f"实际 HLR 投影测试...")
    visible, hidden = drawing_engine._project_shape(
        shape, left_cfg['dir'], left_cfg['up'], show_hidden=False
    )

    if visible:
        all_x = [s.get('x1', 0) for s in visible if s.get('type') == 'line'] + \
                [s.get('x2', 0) for s in visible if s.get('type') == 'line'] + \
                [s.get('cx', 0) for s in visible if s.get('type') == 'circle']
        all_y = [s.get('y1', 0) for s in visible if s.get('type') == 'line'] + \
                [s.get('y2', 0) for s in visible if s.get('type') == 'line'] + \
                [s.get('cy', 0) for s in visible if s.get('type') == 'circle']

        if all_x and all_y:
            width = max(all_x) - min(all_x)
            height = max(all_y) - min(all_y)
            print(f"\n实际投影边线范围:")
            print(f"  X (水平): {min(all_x):.1f} ~ {max(all_x):.1f} (宽度 {width:.1f})")
            print(f"  Y (垂直): {min(all_y):.1f} ~ {max(all_y):.1f} (高度 {height:.1f})")

            if width > height:
                print(f"\n✓ 实际投影：长轴水平")
            else:
                print(f"\n✗ 实际投影：长轴垂直 - 需要修复！")

            # 计算宽高比
            ratio = width / height if height > 0 else 0
            print(f"\n宽高比：{ratio:.2f}")
            print(f"  如果 > 1：长轴水平")
            print(f"  如果 < 1：长轴垂直")


if __name__ == '__main__':
    main()
