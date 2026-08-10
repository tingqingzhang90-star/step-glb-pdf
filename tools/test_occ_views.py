# -*- coding: utf-8 -*-
"""
测试 OCC OffscreenRenderer 内置视图方法
使用 View_Front/Left/Top 等内置方法生成视图 PNG，验证方向是否正确。
参考: https://blog.csdn.net/qq_43184070/article/details/151617543
"""
import os
import sys
import base64
import tempfile
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.AIS import AIS_Shape
from OCC.Core.Quantity import Quantity_Color, Quantity_NOC_BLACK
from OCC.Core.Aspect import Aspect_GFM_NONE
from OCC.Display.OCCViewer import OffscreenRenderer

STEP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'output', '250-E-H3K2-L100-D11', 'assembly.step')
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'output', '250-E-H3K2-L100-D11', 'test_views')

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # 读取 STEP
    reader = STEPControl_Reader()
    status = reader.ReadFile(STEP_PATH)
    if status != IFSelect_RetDone:
        print(f"无法读取: {STEP_PATH}")
        return
    reader.TransferRoots()
    shape = reader.OneShape()

    # 打印包围盒
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    bbox = Bnd_Box()
    brepbndlib.Add(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    print(f"BBox: X={xmax-xmin:.1f}, Y={ymax-ymin:.1f}, Z={zmax-zmin:.1f}")

    # 使用 OCC 内置视图方法
    views = [
        ("front",  "View_Front"),
        ("back",   "View_Rear"),
        ("left",   "View_Left"),
        ("right",  "View_Right"),
        ("top",    "View_Top"),
        ("bottom", "View_Bottom"),
    ]

    for view_name, method_name in views:
        renderer = OffscreenRenderer(screen_size=(400, 400))
        renderer.hide_triedron()

        ais_shape = AIS_Shape(shape)
        white = Quantity_Color(1.0, 1.0, 1.0, 0)
        renderer.set_bg_gradient_color(white, white)
        renderer.SetModeHLR()
        renderer.View.SetShadingModel(0)
        renderer.View.Camera().SetProjectionType(0)
        renderer.Context.Display(ais_shape, True)
        ais_shape.SetColor(Quantity_Color(Quantity_NOC_BLACK))

        # 调用内置视图方法
        view_method = getattr(renderer, method_name)
        view_method()

        renderer.FitAll()
        renderer.Context.UpdateCurrentViewer()
        renderer.Repaint()

        # 保存 PNG
        png_path = os.path.join(OUT_DIR, f"{view_name}.png")
        renderer.View.Dump(png_path)
        print(f"  {view_name}: {png_path}")

        # 清理
        renderer.Context.Remove(ais_shape, True)
        renderer.EraseAll()

    print(f"\n所有视图已保存到: {OUT_DIR}")
    print("请用图片查看器打开 PNG 文件检查方向是否正确")


if __name__ == '__main__':
    main()
