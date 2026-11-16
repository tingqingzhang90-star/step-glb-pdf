# -*- coding: utf-8 -*-
"""工程图领域

    anchor_resolver      按型号实时解析语义锚点(缸体端面/电机包络)
    frontend_template    前端实例模板装载与基准边线还原
    rule_template/       规则式模板引擎(含同目录 JSON 配置)
    dim/                 前端样式标注渲染链(几何/图元/重绑/PDF)
    drawing_pdf          规则式管线的 reportlab PDF 渲染
    drawing_generator    早期 PyMuPDF + 参考 PDF 模板生成器(遗留)
    dxf_exporter         DXF 导出
    hlr_poly / hlr_arcfit  B 层可选离散投影链路(PolyAlgo + 圆弧拟合 + 进程池并行),
                          独立于 core.drawing_engine 的 Algo 路径, 接口可平替
"""
