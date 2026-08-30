# -*- coding: utf-8 -*-
"""前端样式标注渲染链(与 cad-viewer-app/src/dimensions 算法同源)

    dim_geometry     基础几何(线段/圆/基准/偏移),移植自前端 dimensions/geometry.js
    dim_render       标注图元构建,移植自前端 dimensions/core.js
    dim_rebind       几何指纹重绑(基准型号边线 → 目标型号边线)
    dim_pdf_sheet    图纸 → PDF 渲染(视图边线 + 标注 + 图框)
"""
