# -*- coding: utf-8 -*-
"""基础能力层 — 无本包内部依赖,可被任意上层引用

    rebuild_assembly    装配体重建(型号解析/显隐/变换/STEP+GLB 导出)
    drawing_engine      pythonOCC HLRBRep 隐藏线消除 2D 投影引擎
    build_config        系列装配表 → data/configs/<系列>.json
    part_exporter       SW 装配体 → 系列零件库(参数化,CLI 与面板共用)
    paths               项目路径唯一真源
"""
