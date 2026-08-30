# -*- coding: utf-8 -*-
"""step__glb_pdf 后端源码包

分层结构:
    core/       基础能力层(装配体重建、HLR 投影引擎、配置、零件导出)
    drawing/    工程图领域(锚点解析、模板引擎、标注渲染链、PDF/DXF 导出)
    batch/      批量出图 CLI
    web/        Flask 服务层(HTTP API + 页面 + 静态资源)

依赖方向单向: web → batch → drawing → core,禁止反向依赖。
运行任何入口前需把本目录(src)加入 sys.path,各包内模块按包名导入,如::

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    from drawing.dim import dim_pdf_sheet
"""
