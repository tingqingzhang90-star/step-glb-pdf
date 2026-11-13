# STEP / GLB 工程图服务

面向液压缸系列产品的参数化装配体生成与工程图出图服务。输入型号与选型参数，服务按系列零件库重建装配体，产出 STEP / GLB 模型以及 PDF、SVG、DXF 工程图；浏览器端提供 3D 查看、标注编辑和系列模板覆盖度看板。

几何链基于 pythonOCC：HLR 把 B-Rep 投影成 2D 线段与圆/弧，再结合语义锚点、同系列模板复用和标注重绑生成图纸。标注与型号解耦，一份模板可以覆盖同系列不同行程、不同安装方式的型号；精确圆的圆心与半径取自 B-Rep 圆边，可见性与边线几何交给离散投影，兼顾精度和速度。

## 环境准备

后端使用 Python 3.10，conda 环境名 `pdf1`。`pythonocc-core` 只提供 OCC 的 import，没有 pip 元数据，必须走 conda-forge 安装，不能用 venv 代替：

```bash
conda create -n pdf1 python=3.10
conda activate pdf1
conda install -c conda-forge pythonocc-core
pip install -r requirements.txt
```

`requirements.txt` 里是 Flask 3、reportlab、ezdxf、PyMuPDF、trimesh、numpy、openpyxl、svglib、pytest、boto3；其中 boto3 只在启用对象存储后端时才需要，代码里延迟导入。Linux 上还需要系统的 OpenGL / X11 共享库，参见 `docs/Linux 部署适配清单.md`。

## 启动后端

```bash
conda activate pdf1
python src/web/server.py
```

服务默认监听 `0.0.0.0:5001`，端口固定，绑定地址由 `STEP_HOST` 控制（设 `127.0.0.1` 则只在本机开放）。入口 `src/web/server.py` 转到 `src/web/app.py` 的 `main()`，`create_app()` 负责加载 `.env`、初始化 OCC 任务池并注册 11 个蓝图。生产部署用 WSGI 入口 `web.app:app` 搭配 gunicorn 与 Nginx，步骤见 `docs/DEPLOY_BAOTA.md`。

启动后的主要页面：

| 路径 | 用途 |
| --- | --- |
| `/` | 装配选型与构建面板 |
| `/viewer` | 装配体 3D 查看器 |
| `/drawing`、`/editor` | 工程图页面与 Vue 标注编辑器 |
| `/series` | 系列模板覆盖度看板 |
| `/part-export` | 零件导出 |
| `/sw-compare` | SolidWorks 选型对比（依赖 Windows COM） |

API 按蓝图分组：装配构建 `/api/build`、`/api/task/<id>`、`/api/options`；工程图 `/api/drawing-views/<型号>`、`/api/drawing-pdf`、`/api/drawing-dxf/<型号>`；模板出图 `/api/template-drawing/*`；另有视图调色板、符号库、表格预设、图纸源、服务端渲染与系列看板等接口。完整清单见 `docs/关键接口说明.md`。

## 前端编辑器

`cad-viewer-app/` 是独立的 Vue 3 + Vite + TypeScript 应用，基于 `@mlightcad/cad-viewer` 实现工程图标注编辑，样式配置与后端共用根目录的 `cad_viewer_style.json`。开发服务器跑在 5174，并把 `/api`、`/static` 代理到后端 5001；构建产物在 `cad-viewer-app/dist`，由 `/editor` 直接托管，dist 缺失时该路径返回 503。

```bash
cd cad-viewer-app
npm install
npm run dev          # 开发调试
npm run build        # 构建到 dist，/editor 依赖此步骤
npm run type-check
```

## 配置

复制 `.env.example` 为 `.env`（`.env` 不入库）。项目自己解析根目录的 `.env`，不依赖 python-dotenv，且已存在的环境变量优先。

| 键 | 说明 |
| --- | --- |
| `STORAGE_BACKEND` | `local`（默认）或 `oss`，决定结果写本地还是镜像到对象存储 |
| `OSS_ENDPOINT` / `OSS_REGION` / `OSS_BUCKET` | S3 兼容对象存储的接入信息 |
| `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` | 对象存储密钥，只放在本地 `.env` |
| `OSS_PREFIX` / `OSS_PUBLIC_BASE` / `OSS_PRESIGN_EXPIRE` | key 前缀、公开基址、签名 URL 有效期 |
| `BUILD_POOL_WORKERS` | OCC 任务池 worker 数，默认 `min(4, CPU 核数)` |
| `STEP_HOST` | Flask 绑定地址 |
| `OCC_POOL_INLINE` / `BUILD_POOL_MAX_TASKS_PER_CHILD` | 任务池调试与 worker 回收参数 |
| `DRAWING_ALGO` | 切换 HLR 精确算法与离散投影算法 |
| `DRAWING_POLY_DEFLECTION` / `DRAWING_POLY_DO_FIT` | 离散投影的精度与拟合开关 |

保持 `STORAGE_BACKEND=local` 就是纯本地运行，所有结果落在 `output/`。单个跑过投影的 worker 常驻 290–480 MB，`BUILD_POOL_WORKERS` 按可用内存调整。

## 目录

```
src/core/     装配体重建、HLR 投影、路径与存储
src/drawing/  图纸模板、标注重绑、PDF / SVG / DXF 渲染
src/batch/    批量出图 CLI
src/web/      Flask 应用、蓝图、任务池、静态资源
cad-viewer-app/  Vue 标注编辑器
tests/        pytest 用例
docs/         设计与部署文档
tools/        开发期一次性探针和调试脚本
tools/ 下的脚本不属于正式产线，也不由 pytest 管理，用途见 `docs/tools 临时脚本说明.md`。
```

代码分层依赖为 `web → batch → drawing → core`，路径常量集中在 `src/core/paths.py` 与 `src/web/common.py`。

## 测试

```bash
conda run -n pdf1 python -m pytest tests/ -v
```

24 个测试文件覆盖 API、路径、配置、模板出图、标注与 HLR 拟合；依赖 OCC 或真实模型的用例用 `importorskip`、`monkeypatch`、`tmp_path` 打桩或跳过。

## 运行数据不入库

系列零件库、模板与结果文件不纳入版本控制：`图库项目/`、`library/`、`parts_step/`、`reference/`、`output/`、`logs/`、`data/`、`verify/`，以及 `*.step`、`*.glb`、`*.SLD*`、`*.xlsx` 等大二进制。按这份清单配置本地忽略规则，避免把客户资料和生成产物误提交。克隆后需要自行准备系列零件库与模板数据；服务会在 `data/configs`、`data/templates`、`data/symbols` 等路径读写，约定见 `docs/目录结构与模板出图流程.md` 和 `docs/关键接口说明.md`。

## 文档索引

`docs/目录结构与模板出图流程.md` 记录分层与模板流程，`docs/关键接口说明.md` 说明接口与并发模型，`docs/同系列模板复用规则.md` 定义模板复用的身份判定，`docs/标注样式配置说明.md` 说明前后端共用样式字段。部署相关有 `docs/DEPLOY_BAOTA.md` 与 `docs/Linux 部署适配清单.md`，几何与编辑器设计另有若干方案文档。
