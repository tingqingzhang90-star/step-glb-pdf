# -*- coding: utf-8 -*-
"""统一 Web 应用入口

把原先分散在 server.py / sw_compare_server.py / part_export_server.py 的
三个 Flask 服务,合并到同一个 app,统一跑 5001 端口。各业务以蓝图挂载,
见 web/blueprints/。

旧启动命令仍可用(三个 *.py 都改成了本模块的壳):
    conda run -n pdf1 python src/server.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_HERE)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from flask import Flask

from web import env_settings, task_pool
from web import common


def create_app() -> Flask:
    """构建 Flask 应用并注册全部蓝图

    .env 必须在创建任务池之前读,否则 BUILD_POOL_WORKERS 不会被采纳;
    蓝图延迟到 load_env + 任务池初始化之后再导入,模块级的 pool 单例才能
    拿到正确配置。
    """
    env_settings.load_env(common.PROJECT_ROOT)
    app = Flask(__name__)

    # OCC 任务池懒创建于子进程;此处仅初始化单例(读 worker 数、建日志目录)
    task_pool.get_pool()

    from web.blueprints.assembly import bp as assembly_bp
    from web.blueprints.drawing import bp as drawing_bp
    from web.blueprints.template import bp as template_bp
    from web.blueprints.sw_view import bp as sw_view_bp
    from web.blueprints.part_export import bp as part_export_bp
    from web.blueprints.sw_compare import bp as sw_compare_bp
    from web.blueprints.symbols import bp as symbols_bp
    from web.blueprints.table_presets import bp as table_presets_bp
    from web.blueprints.drawing_sources import bp as drawing_sources_bp

    for bp in (assembly_bp, drawing_bp, template_bp,
               sw_view_bp, part_export_bp, sw_compare_bp,
               symbols_bp, table_presets_bp, drawing_sources_bp):
        app.register_blueprint(bp)
    return app


app = create_app()


def main() -> None:
    """启动统一服务(供各兼容壳的 __main__ 复用)"""
    os.makedirs(common.OUT_DIR, exist_ok=True)
    print("=" * 56)
    print("  装配体生成 / 工程图 / 视图调色板 / 模板 / SW 对比 / 零件导出")
    print("  统一服务已启动: http://127.0.0.1:5001")
    print("  装配面板:    http://127.0.0.1:5001/")
    print("  3D 查看器:    http://127.0.0.1:5001/viewer")
    print("  工程图编辑器:  http://127.0.0.1:5001/drawing")
    print("  零件导出:     http://127.0.0.1:5001/part-export")
    print("  SW 选型对比:   http://127.0.0.1:5001/sw-compare")
    print("-" * 56)
    print(f"  OCC 任务池: {task_pool.get_pool().max_workers} 个并行 worker"
          f" (环境变量 BUILD_POOL_WORKERS 可调)")
    print("=" * 56)
    try:
        app.run(host="127.0.0.1", port=5001, debug=False, threaded=True)
    finally:
        task_pool.get_pool().shutdown(wait=False)


if __name__ == "__main__":
    main()
