# Linux 云服务器部署适配清单

> **状态: §1（COM 启动阻断）已落实；其余为部署期配置项。**
> 现状:生产环境跑在 Windows(conda 环境 `pdf1`),入口 `src/web/app.py`(5001)。
> 本文来自一次**代码走查 + 本机实测**(实测数据见文末附录),用于迁移到 Linux 时按序处理。
> 选型决策:**零件库改为 Windows 预导出**,Linux 运行时彻底不依赖 SolidWorks——
> 因此"穿透/隧道暴露 SW"的方案不再需要。SW 相关接口在 Linux 上返回 501。

---

## 1. 阻断项:不改就起不来

### 1.1 SolidWorks COM 依赖被模块级导入  ✅ 已落实

| 位置 | 内容 |
|---|---|
| `src/core/part_exporter.py:18-19` | `import pythoncom` / `import win32com.client`(模块顶层) |
| `src/web/blueprints/part_export.py:21` | `from core import part_exporter as pe`(模块顶层) |
| `src/web/app.py:50,59` | 注册 `part_export_bp` 蓝图 |

**现象**:Linux 上 `python app.py` 在 import 阶段直接 `ModuleNotFoundError: No module named 'pythoncom'`,
**整个 5001 服务起不来** —— 连带装配体生成、出图等与 SolidWorks 无关的功能一起不可用。

**已改**:
- `part_exporter.py`:顶层两行 COM 导入删除,改到 `_int_ref` / `_nothing` /
  `preview_components` / `export_series` 函数体内延迟 import(与 `sw_compare_ops.py` 同款做法)。
- `part_export.py`:删除顶层 `from core import part_exporter as pe`;新增 `_sw_only()` 守卫,
  `api_series` / `api_preview` / `_run_export` 内延迟 import `pe`;非 Windows 直接返回 501。
- `sw_compare.py`:`api_sw_apply` 加非 Windows 返回 501(`sw_compare_ops` 本就延迟 import,模块可安全导入)。

**验证**:
```
# ① 导入不再报错(关键:不再依赖 pythoncom)
python -c "import web.app"
# ② 主链路可用
curl -s http://127.0.0.1:5001/api/options | head -c 120
# ③ 仅零件导出/SW 对比返回"仅 Windows 支持"(HTTP 501)
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:5001/api/sw-apply -H 'Content-Type: application/json' -d '{}'
```

---

## 2. 多进程语义:Windows `spawn` → Linux `fork`

代码里多处阈值与注释都是按 **Windows spawn**(每个 worker 重新导入 pythonOCC ≈2s)标定的。

| 维度 | Windows `spawn` | Linux `fork` | 影响 |
|---|---|---|---|
| worker 启动开销 | 重新导入主模块 + pythonOCC(≈2s/worker) | 几乎为 0 | 现有"少视图串行"的阈值偏保守 |
| 内存 | 各自独立 | 写时复制继承父进程(fork 时父进程已 import OCC) | 需确认继承 OCC 状态是否安全 |
| 主模块重复执行 | 会(spawn 重导) | 不会 | `task_pool` 的"懒建池"注释只针对 spawn |

**受影响的阈值/注释**:

| 位置 | 现状 | 迁移后待办 |
|---|---|---|
| `src/drawing/hlr_poly.py:209` | `len(view_names) <= 4` → 强制串行 | Linux 上重测 3 视图串行 vs 并行,再调 |
| `src/core/drawing_engine.py:1413` | `_MIN_PARALLEL_VIEWS = 2` | 同上(并行收益变大) |
| `src/web/task_pool.py:231-235` | "必须懒创建(防 spawn 重导主模块而无限派生)" | fork 下无此问题,但改为 spawn/forkserver context 时注释依然成立 |

**已改(启动上下文)**:`src/web/task_pool.py` 已显式 `multiprocessing.get_context("spawn")`
并作为 `mp_context` 传给 `ProcessPoolExecutor`,跨平台统一用 spawn,避免 fork 继承 OCC 全局状态。
`spawn` 在 Windows 本就是默认(无差别);Linux/macOS 也可用。`server.py` 已有
`if __name__ == "__main__"` 守卫,spawn 子进程重导 `__main__` 时不会重复起服务。

**待办**:
1. (无需再改代码)在 Linux 上重测视图并行阈值(`hlr_poly.py:209` 的 `len(view_names)<=4`、
   `drawing_engine.py:1413` 的 `_MIN_PARALLEL_VIEWS`)。
2. `max_tasks_per_child` 已按 Python 版本条件传入(3.11+ 才传该 kwarg,3.10 不传),
   避免旧版本 `TypeError`;部署机 Python ≥3.11 时可在 `.env` 设
   `BUILD_POOL_MAX_TASKS_PER_CHILD=8` 回收常驻内存。

**验证**:同一型号 3 视图,分别用 `parallel=True/False` 跑,比较墙钟与 `timing.parallel`;
再连续跑 100 次出图,确认无崩溃(fork 继承 OCC 全局状态的隐患)。

---

## 3. 部署形态与并发参数

### 3.1 严禁多进程 WSGI(gunicorn 多 worker)

`task_pool` 是**进程内单例**(`src/web/task_pool.py` 的 `_POOL`),
用 `gunicorn -w 4` 会变成 4 个独立池 → `4 × BUILD_POOL_WORKERS` 个 OCC 进程。

**只允许**:`gunicorn -w 1 --threads N`(或把任务池拆成独立服务)。

### 3.2 `BUILD_POOL_WORKERS` 按云主机内存定

实测每个**跑过任务的** worker 常驻 **290–480MB**(5902 面装配体,含已加载 shape);
本机 32GB 配 `BUILD_POOL_WORKERS=20` 时峰值约 6–10GB。云主机按
`可用内存 ÷ 0.45GB` 估上限,并留出系统与主进程余量。

### 3.3 worker 常驻不回收 → 建议加 `max_tasks_per_child`

`src/web/task_pool.py:241,248` 两处 `ProcessPoolExecutor(max_workers=...)`,
可补 `max_tasks_per_child=8`(Python 3.11+):worker 跑满 8 个任务即退出重建,释放常驻内存。
代价仅是下个任务重新读 `.brep`(≈0.34s)。

### 3.4 已知未修的隐患:algo 路径会嵌套进程池

`poly` 路径在任务池子进程内会自动降级串行(实测 `parallel=False`,无嵌套);
但 `algo` 路径(`src/core/drawing_engine.py:1595`)只判断视图数,没有防嵌套判断,
在任务池子进程内会再起一个进程池(`4 × 3 = 12` 起步;调色板 9+3 视图时可达 `4 × 9 = 36`)。
当前 `.env` 是 `DRAWING_ALGO=poly` 故不触发,**切回 algo 前需补上同样的守卫**。

---

## 4. 环境依赖

- `pythonocc-core` **只能 conda 装**(见 `requirements.txt` 注释):
  `conda install -c conda-forge pythonocc-core`
- 其余按 `requirements.txt` pip 安装
- **[Linux 专属] OCC 系统级共享库必须预装**:conda 的 pythonocc-core 只带 Python 包,
  运行/导入时还依赖系统的 OpenGL/X11 库,缺了会 `ImportError: libGL.so.1` 之类。
  Debian/Ubuntu 系:
  `apt-get install -y libgl1-mesa-glx libglu1-mesa libxmu6 libxi6 libsm6 libice6
   libxcursor1 libxrandr2 libxinerama1 libgomp1`
  (容器镜像同理;Alpine 用 `mesa-gl glu libxmu libxi libsm libice` 等)。
  HLR/三角化走 CPU,一般不需 Xvfb,但上述 `.so` 必须存在。
- **中文字体不用额外准备**:PDF 用的是 reportlab 内置 CID 字体
  `STSong-Light`(`src/drawing/drawing_source_render.py:26`),与系统字体无关 ✅

### 4.1 前端编辑器必须单独构建

`/editor`(模板标注编辑器)托管的是 `cad-viewer-app/dist`,而 **`dist` 在
`cad-viewer-app/.gitignore` 里,不入库** —— 新机器上 clone 完直接启动会看不到编辑器。

部署前在该目录执行:

```
npm install && npm run build      # 实测 node v20.19 / npm 10.8,build 约 14s
```

- 未构建时 `/editor` 会给出明确提示(见 `src/web/blueprints/drawing.py:27-35`)
- 后端与 dist 无版本绑定:只要改过 `cad-viewer-app/src/**`,就必须重新 build 才生效
- 前端调用的接口全部在同源 5001 下,无需额外代理配置

---

## 5. 路径与编码

- 所有路径由 `src/core/paths.py` 从项目根推导,**无硬编码盘符** ✅
- 但目录/文件名含中文(`图库项目/`、系列名 `250直连`、`250缸体.step`、`11kw.step`):
  打包/解压/挂载需保证 UTF-8 不乱码
- Linux 区分大小写,Windows 不区分 —— 这类问题只在 Linux 暴露。
  当前仓库零件库扩展名已统一为小写 `.step`(312 个文件已核对),
  后续补零件/重新导出时保持大小写一致即可
- Windows 下 `conda run` 在中文路径会 gbk 崩溃(见 `docs/tools 临时脚本说明.md`),Linux 无此问题

---

## 5.1 结果存储(可选 OSS 对象存储)

默认纯本地(`output/`),无需任何改动。**可选**把结果(STEP/GLB/PDF/DXF/`drawing_source.json` 等)
镜像到对象存储,并让下载/预览路由 302 到外链(前端无需改动)。

- 后端抽象:`src/core/storage.py`,本地仍是工作存储,只在结果产出后镜像 + 对外 302
- 协议:**S3 兼容**,通吃阿里云 OSS / 腾讯云 COS / MinIO / AWS S3(统一用 `boto3`)
- 接入点:`.env`(示例见 `.env.example`),核心三项:
  - `STORAGE_BACKEND=oss`(不配=local,零行为变化)
  - `OSS_ENDPOINT` / `OSS_REGION` / `OSS_BUCKET` / `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET`
  - `OSS_PREFIX`(key 前缀,可空) + `OSS_PUBLIC_BASE`(留空=临时签名 URL;`填了`=公开 CDN 基址)
- 上传失败的容错:任何 OSS 异常都被吞掉并打到 stderr,**绝不阻断构建/出图主流程**
- `requirements.txt` 已加 `boto3==1.40.0`(仅 OSS 模式加载,本地部署不装也能跑)

> 验证:配好 OSS 后,跑一次构建/出图,确认对象存储桶里出现 `PREFIX/<型号>/...`;
> 再访问下载/预览接口,确认返回 302 且 Location 指向对象存储。

---

## 6. 迁移完成后建议复测的三项

1. **并发**:6~20 路混合(构建 + 出图),确认线性度与内存回落
2. **单用户基线**:`resources → build → render-drawing` 全链路(Windows 实测 15.9s,见附录)
3. **一致性**:同一型号在 Windows / Linux 各出一张图,比对 `drawing_source.json`
   (边线数量、几何指纹),确保 OCC 平台差异不改变输出

---

## 附录:本机实测数据(Windows,28 逻辑核 / 32GB)

**单用户完整链路**(型号 `YRJ250-E-H3K2-L85-D11`,全新未生成):

| 阶段 | 耗时 |
|---|---|
| `GET /api/resources/<model>` 未命中 | 0.03s |
| `POST /api/build` + 轮询(含构建期落 BREP 2.09s) | 11.76s |
| `POST /api/render-drawing`(自动重绑 4.03s + PDF 0.06s) | 4.14s |
| 合计 | **15.9s** |
| 二次进入(已生成) | `resources` 命中 **0.026s**,0 次 OCC |

**并发能力**(任务池 `BUILD_POOL_WORKERS=20`):

| 场景 | 结果 |
|---|---|
| 同型号 3 并发构建 | 同一 task_id,`dedup=[True,True,False]`,只真跑一次 |
| 3 个不同型号并发构建 | 3 个不同 pid,墙钟 13.0s(串行 38s)→ **2.93x** |
| 6 个不同型号并发构建 | 6 个不同 pid,墙钟 13.6s(串行 79s)→ **5.86x** |
| 3 个型号并发出图 | 墙钟 5.2s(串行 14.7s)→ **2.82x** |
| 同型号 3 并发出图 | 共用同一次自动重绑,各自仅做 PDF 渲染(0.14s) |
| 混合(3 构建 + 3 出图) | 构建 11.6–12.0s、出图 4.84–4.88s,**互不排队** |

**内存画像**:

- 6 个空闲 worker 常驻 **1.95GB**,任务结束后**不自动回收**(需重启服务才释放)
- 64 位 Windows 上 `Memory Compression` 达 4.76GB,是内存压力的表现,而非某个进程泄漏
- 单用户链路峰值主要集中在构建子进程(STEP 30MB 解析 + 三角化 + GLB 导出)
