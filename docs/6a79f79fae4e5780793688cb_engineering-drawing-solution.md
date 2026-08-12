# 产品参数驱动自动工程图系统 — 可行性方案文档

> 基于 pythonocc-core + 语义锚点的自动化工程图生成方案，面向微信小程序 WebView 展示场景

| 版本 | 日期 | 状态 |
|------|------|------|
| v1.0 | 2026-08-10 | 方案讨论阶段 |

---

## 目录

1. [系统目标与设计原则](#1-系统目标与设计原则)
2. [技术选型与方案评估](#2-技术选型与方案评估)
3. [系统架构设计](#3-系统架构设计)
4. [HLR 视图生成方案](#4-hlr-视图生成方案)
5. [语义锚点绑定系统](#5-语义锚点绑定系统)
6. [多用户并发架构](#6-多用户并发架构)
7. [微信小程序 WebView 集成](#7-微信小程序-webview-集成)
8. [性能预算与时间分析](#8-性能预算与时间分析)
9. [分阶段实施路线](#9-分阶段实施路线)
10. [自研工程图编辑器方案](#10-自研工程图编辑器方案)

---

## 1 系统目标与设计原则

### 1.1 核心目标

构建一套**产品参数驱动的自动工程图系统**，以型号规则（如 `250-E-H3K2-L100-D11`）为输入，自动生成包含多视图、尺寸标注、技术要求的完整工程图，替代 SolidWorks 工程图模板的部分能力。

系统输入输出：

- **输入**：产品型号 + 参数（行程 L、缸径 D、安装方式等）
- **输出**：6 视图 SVG 工程图（含标注、标题栏），通过微信小程序 WebView 展示

### 1.2 设计原则

> **核心设计原则**
>
> **视图线条用于显示，标注锚点用于计算。** 标注值不依赖 SVG 边线长度，而是来自产品参数和 BRep 几何锚点。这是整个系统能够稳定运作的基石。

#### 关键设计决策

- **标注与视图解耦**：标注值来自参数或锚点测量，不依赖 SVG path
- **模板驱动**：JSON 模板定义视图布局、标注位置、锚点绑定关系
- **语义锚点**：标注绑定语义名（如 `cylinder.front_end`），不绑定拓扑 ID
- **两阶段分离**：3D 模型生成与工程图生成分阶段独立执行
- **全后端计算**：因微信小程序 WebView 限制，所有计算在后端完成

---

## 2 技术选型与方案评估

### 2.1 方案评估总览

经过全网调研和多维度对比，评估了以下方案：

| 方案 | 类型 | HLR 性能 | 30秒可行性 | 并发友好度 | 结论 |
|------|------|----------|------------|------------|------|
| **pythonocc-core (OCCT PolyAlgo)** | 开源 | 中等 (3-8秒/6视图) | ✅ 可行 | 高 | ✅ 采用 |
| FreeCAD TechDraw | 开源 | 极慢 (数分钟) | ❌ 不可行 | 低 | ❌ 否决 |
| CGM HLR (Spatial) | 商业 | 极快 | ✅ 可行 | 高 | ⚠️ 备选 |
| C3D Modeler | 商业 | 快 (3-8秒) | ✅ 可行 | 高 | ⚠️ 备选 |
| three-edge-projection (GPU) | 开源 | 极快 (1-3秒) | ❌ 不可行 | 极高(前端) | ❌ 否决 |
| OCCT WASM (浏览器) | 开源 | 慢于原生 | ⚠️ 勉强 | 极高(前端) | ❌ 否决 |

### 2.2 否决方案及原因

#### FreeCAD TechDraw — 否决

> **否决原因：性能不满足 30 秒约束**
>
> FreeCAD TechDraw 在 OCCT HLR 基础上增加了显著额外开销，出图速度比同类最差的 Rhino 7 还要慢数倍 [^1]。TechDraw 导出 20 页工程图在 RTX 3060 上需要 2 分 18 秒 [^2]。单任务耗时数分钟，完全无法满足 30 秒约束。
>
> 此外，FreeCAD 的无界面（headless）模式存在严重限制：PDF/DXF 导出不支持、标注导出 SVG 有缺陷 [^3]。多进程内存占用高（500MB-1GB/Worker），同样硬件下可运行的 Worker 数量仅为 pythonocc 方案的一半。

#### three-edge-projection (GPU) — 否决

> **否决原因：微信小程序 WebView 不支持 WebGPU**
>
> three-edge-projection 使用 GPU compute shader + BVH 空间加速结构实现 HLR，在浏览器中性能极佳（复杂模型 13 秒）[^4]。但其 GPU 加速模式依赖 WebGPU，而微信小程序 WebView 环境中 WebGPU 支持不可靠：Android XWeb 内核（Chromium 142）部分支持，iOS WKWebView 不支持 [^5]。无法作为生产环境依赖。

#### 商业方案（CGM HLR / C3D）— 备选

> **备选原因：性能优异但成本高**
>
> CGM HLR（Dassault Systèmes）在所有 HLR 测试中性能排名第一 [^6]，C3D Modeler 速度也远超 OCCT（568 零件模型：OCCT 需 3 分 25 秒，C3D 仅需 6 秒 [^1]）。但年费约 $15,000-$50,000+，当前阶段暂不采用，作为未来质量升级的备选方案保留。

### 2.3 最终选定方案：pythonocc-core

> **选定理由**
>
> - **免费开源**（LGPL 协议），无授权费用
> - **轻量级**：纯 Python + OCCT C++ 库，无 GUI 依赖，单 Worker 内存约 200MB
> - **并发友好**：多进程隔离，OCCT C++ 调用释放 GIL，单进程内可多线程并行
> - **性能满足**：PolyAlgo 离散算法 + 并行 6 视图，预计 3-8 秒完成
> - **功能完整**：STEP 读取、BRep 遍历、HLR 消隐、SVG 导出，全链路覆盖

---

## 3 系统架构设计

### 3.1 两阶段分离架构

3D 模型生成与工程图生成分阶段独立执行。用户选型完成后先生成 3D 模型并展示预览，用户再点击"查看工程图"时才触发生成。这一设计大幅释放了工程图生成的时间预算。

```
阶段1: 模型生成                      阶段2: 工程图生成
┌─────────────────────┐             ┌─────────────────────┐
│ 用户选型             │             │ 用户点击查看工程图   │
│   ↓                  │             │   ↓                  │
│ 参数 → STEP/GLB      │             │ 加载已缓存 STEP      │
│   ↓                  │             │   ↓                  │
│ 缓存模型             │ ─────────→  │ HLR 6视图            │
│   ↓                  │  用户决定    │   ↓                  │
│ 展示 3D 预览         │             │ 锚点 + 标注          │
└─────────────────────┘             │   ↓                  │
                                    │ SVG 合成             │
                                    │   ↓                  │
                                    │ WebView 展示         │
                                    └─────────────────────┘
```

*图 1：两阶段分离架构流程*

### 3.2 系统组件架构

```
┌─────────────────────────────────────────────────────────────────┐
│  前端: 微信小程序                                                 │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ 选型页面  │  │ 3D预览WebView │  │ 工程图WebView │              │
│  └────┬─────┘  └──────────────┘  └──────┬───────┘              │
└───────┼─────────────────────────────────┼──────────────────────┘
        │                                 │
┌───────┼─────────────────────────────────┼──────────────────────┐
│       ▼          后端服务               ▼                      │
│  ┌─────────────────────────┐  ┌─────────────────────────┐      │
│  │    模型生成服务          │  │    工程图生成服务        │      │
│  │  ┌─────┐ ┌─────┐ ┌────┐ │  │  ┌────┐ ┌────┐ ┌────┐  │      │
│  │  │参数  │→│STEP │→│GLB │ │  │  │STEP│→│HLR │→│锚点│  │      │
│  │  │解析  │ │生成  │ │生成 │ │  │  │加载│ │视图│ │计算│  │      │
│  │  └─────┘ └─────┘ └────┘ │  │  └────┘ └────┘ └────┘  │      │
│  │       ┌─────┐           │  │       ┌────┐ ┌────┐    │      │
│  │       │模型  │           │  │       │标注│ │SVG │    │      │
│  │       │缓存  │           │  │       │生成│ │合成│    │      │
│  │       └─────┘           │  │       └────┘ └────┘    │      │
│  └─────────────────────────┘  │       ┌────────┐       │      │
│           │                   │       │工程图   │       │      │
│  ┌────────▼────────┐          │       │缓存     │       │      │
│  │  预生成调度       │          │       └────────┘       │      │
│  │  ┌──────────┐   │          └─────────────────────────┘      │
│  │  │后台任务   │   │                    ▲                      │
│  │  │队列       │   │────────────────────┘                      │
│  │  ┌──────────┐   │                                           │
│  │  │低优先级   │   │                                           │
│  │  │Worker     │   │                                           │
│  └────────────────┘                                           │
└─────────────────────────────────────────────────────────────────┘
```

*图 2：系统组件架构图*

### 3.3 数据流设计

| 阶段 | 输入 | 处理 | 输出 | 缓存产物 |
|------|------|------|------|----------|
| 阶段1 | 产品参数 JSON | 参数驱动建模 | STEP + GLB 文件 | `/cache/models/{型号}/model.step` |
| 阶段2 | STEP 文件 + 参数 | HLR + 锚点 + 标注 | drawing.json (SVG + 标注) | `/cache/drawings/{型号}/drawing.json` |

### 3.4 预生成策略

用户生成 3D 模型后，系统后台静默预生成工程图。当用户点击"查看工程图"时：

| 场景 | 耗时 | 说明 |
|------|------|------|
| 预生成已完成 | **< 0.5秒** | 缓存命中，秒开返回 |
| 预生成进行中 | **~3-5秒** | 等待预生成完成 |
| 预生成未启动 | **~6-10秒** | 实时生成 |

---

## 4 HLR 视图生成方案

### 4.1 算法选择

OCCT 提供两种 HLR 算法 [^7]：

| 算法 | 原理 | 速度 | 精度 | 适用场景 |
|------|------|------|------|----------|
| `HLRBRep_PolyAlgo` | 基于离散网格 | ✅ 快 | 圆弧变多段线 | 实时生成（默认） |
| `HLRBRep_Algo` | 基于精确 BRep | ⚠️ 慢 | 精确圆弧/样条 | 高质量导出 |

由于两阶段分离后工程图生成有 6-10 秒预算，**两种算法均可使用**。默认使用 PolyAlgo（快），质量要求高时切换到 Algo（精确）。

### 4.2 性能基准数据

OCCT HLR 性能对比研究数据 [^1]：

| 模型 | 零件数 | 文件大小 | OCCT 标准版 | OCCT 优化版(CR28991) |
|------|--------|----------|-------------|----------------------|
| Ass1.stp | 124 | 28 MiB | 18秒 | 16秒 |
| LEGO Fire Plane | 568 | 28 MiB | 3分25秒 | 2分11秒 |
| LEGO Corvette | 582 | 40 MiB | 3分53秒 | 2分50秒 |

> **预估分析**
>
> 本系统产品（如 250-E-H3K2 气缸+电机装配体）零件数预计在 10-50 个级别，远少于上述测试模型。使用 PolyAlgo + 并行 6 视图，预计单次生成时间在 **3-8 秒**范围内。

### 4.3 六大优化策略

#### 策略 1：模型预处理

HLR 前先根据显示/隐藏规则移除不可见零件，移除小特征（倒角、圆角、螺纹等不影响轮廓的特征），只保留外表面。可节省 30-50% 计算时间。

#### 策略 2：并行生成 6 个视图

6 个投影方向相互独立，利用 OCCT C++ 调用释放 GIL 的特性，在同一 Worker 进程内用 `ThreadPoolExecutor` 并行计算。单视图 1-2 秒，6 视图并行后仍只需 1-2 秒。

#### 策略 3：调整离散精度

`BRepMesh_IncrementalMesh(shape, linDeflection)` 的 `linDeflection` 参数控制精度。工程图推荐 `0.3-0.8`，速度可提升数倍 [^7]。对标注精度无影响，因为标注值来自参数和锚点。

#### 策略 4：三级缓存

- **L1 内存缓存**：Worker 进程内 LRU，命中 < 1ms
- **L2 文件缓存**：所有生成过的型号，命中 < 10ms
- **L3 Redis（可选）**：多服务器共享，命中 < 5ms

#### 策略 5：PolyAlgo + 后处理修线

PolyAlgo 输出的圆弧为多段线，可在后处理中用 Douglas-Peucker 算法简化，再用圆弧拟合合并为圆弧。

#### 策略 6：增量更新

参数变化时只重新计算受影响的视图（如行程 L 变化只影响左视图的总长标注）。

### 4.4 核心代码结构

```python
# HLR 视图生成核心逻辑
from OCC.Core.HLRBRep import HLRBRep_PolyAlgo
from OCC.Core.HLRAlgo import HLRAlgo_Projector
from OCC.Core.HLRBRep import HLRBRep_PolyHLRToShape
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from concurrent.futures import ThreadPoolExecutor

def generate_views_parallel(shape, view_directions):
    """并行生成6个视图"""
    # 1. 网格化（控制精度是提速关键）
    BRepMesh_IncrementalMesh(shape, 0.5)

    # 2. OCCT C++调用释放GIL，线程可真正并行
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [
            pool.submit(_generate_single_view, shape, name, ax2)
            for name, ax2 in view_directions
        ]
        views = [f.result() for f in futures]
    return views

def _generate_single_view(shape, view_name, projector_ax2):
    """生成单个视图的 HLR + SVG"""
    hlr = HLRBRep_PolyAlgo()
    hlr.Load(shape)
    hlr.Projector(HLRAlgo_Projector(projector_ax2))
    hlr.Update()

    hlr_to_shape = HLRBRep_PolyHLRToShape()
    hlr_to_shape.Update(hlr)

    visible = hlr_to_shape.VCompound()        # 可见锐边
    outline = hlr_to_shape.OutLineVCompound() # 可见轮廓线

    svg = shapes_to_svg(visible, outline)
    return {"name": view_name, "svg": svg}
```

---

## 5 语义锚点绑定系统

### 5.1 核心问题：拓扑命名问题（TNP）

当模型参数变化时，BRep 拓扑结构会发生变化：面的编号可能改变，边可能消失或新增 [^8]。如果标注绑定的是拓扑 ID（如 `Edge12`），参数变化后会失效。

> **不能这样做**
>
> 绑定 `Edge12` 这种拓扑 ID → 参数变化后 Edge12 可能消失或变成 Edge15+Edge16 → 标注失效。

### 5.2 锚点绑定三种方式

#### 方式一：参数驱动锚点（首选，微秒级）

不查询 BRep 拓扑，直接从产品参数计算锚点的 3D 坐标。因为模型本身就是参数驱动的，所有关键几何位置都可以从参数推导。

```python
class AnchorCalculator:
    def __init__(self, params: dict):
        self.stroke = params.get("L", 100)    # 行程
        self.bore = params.get("D", 11)       # 缸径

    def get_anchor(self, anchor_name: str) -> dict:
        anchors = {
            "cylinder.front_end": {
                "point3d": (0, 0, self.stroke / 2),
                "axis": (0, 0, 1),
                "type": "plane_face"
            },
            "cylinder.outer_diameter": {
                "point3d": (self.bore / 2, 0, 0),
                "radius": self.bore / 2,
                "type": "cylinder_face"
            },
            "shaft.axis": {
                "point3d": (0, 0, 0),
                "direction": (0, 0, 1),
                "type": "axis"
            }
        }
        return anchors.get(anchor_name)
```

#### 方式二：BRep 几何查询锚点（补充，毫秒级）

当锚点位置无法从参数直接推导时，在 BRep 模型上通过几何特征（面类型、法向量、位置、尺寸）搜索匹配的拓扑实体。查询时用几何特征而非拓扑 ID。

```python
class BRepAnchorFinder:
    def find_face_by_normal(self, target_normal, tolerance=5.0):
        """根据法向量查找平面"""
        results = []
        explorer = TopExp_Explorer(self.shape, TopAbs_FACE)
        while explorer.More():
            face = explorer.Current()
            adaptor = BRepAdaptor_Surface(face)
            if adaptor.GetType() == 1:  # GeomAbs_Plane
                plane = adaptor.Plane()
                normal = plane.Axis().Direction()
                dot = (normal.X() * target_normal[0] +
                       normal.Y() * target_normal[1] +
                       normal.Z() * target_normal[2])
                if dot > 1.0 - tolerance / 100.0:
                    results.append(face)
            explorer.Next()
        return results

    def find_cylinder_by_radius(self, target_radius, tolerance=0.1):
        """根据半径查找圆柱面"""
        # 遍历所有面，匹配圆柱面类型和半径
        ...
```

#### 方式三：OCCT OCAF 拓扑命名（不推荐）

OCCT 的 OCAF 框架内置拓扑命名机制 [^9]，通过记录建模历史中拓扑实体的演化来追踪。但本系统每次从参数重新生成 STEP 模型，没有建模历史可追踪，不适用。

### 5.3 混合实现架构

采用参数驱动 + BRep 查询的混合模式：能从参数直接算的优先用参数，无法推导时回退到 BRep 查询。

```
锚点解析请求
    │
    ▼
参数可推导? ──是──→ 参数驱动计算 ──┐
    │                              │
    否                              ├──→ 3D锚点数据
    │                              │         │
    └──→ BRep几何查询 ─────────────┘         ▼
                                    投影到2D视图坐标
                                          │
                                          ▼
                                    返回: 3D + 2D 数据

标注值来源:
    A类: 参数值 ─────────────┐
    B类: 几何测量值 ─────────┤
    C类: 固定文本 ───────────┘
```

*图 3：锚点解析与标注值生成流程*

### 5.4 标注值三类来源

| 类型 | 来源 | 示例 | 速度 |
|------|------|------|------|
| **A. 参数驱动** | 直接从产品参数取值 | 行程 L=100、缸径 D=11 | ~0ms |
| **B. 几何测量** | 从 BRep 锚点计算距离/直径 | 两安装孔中心距、外圆直径 | ~1ms |
| **C. 固定文本** | 模板中预定义的文字 | 电机型号说明、技术要求 | ~0ms |

### 5.5 模板 JSON 结构

```json
{
  "template_id": "250-E-H3K2",
  "paper": { "size": "A3", "orientation": "landscape" },
  "views": [
    { "name": "front", "position": [0, 0], "scale": 1.0 },
    { "name": "top",   "position": [1, 0], "scale": 1.0 },
    { "name": "left",  "position": [0, 1], "scale": 1.0 }
  ],
  "dimensions": [
    {
      "id": "dim_total_length",
      "type": "linear_horizontal",
      "anchor_from": "cylinder.front_end",
      "anchor_to": "cylinder.back_end",
      "view": "left",
      "value_source": "param:L",
      "offset": 30
    },
    {
      "id": "dim_bore_diameter",
      "type": "diameter",
      "anchor": "cylinder.outer_diameter",
      "view": "front",
      "value_source": "param:D",
      "offset": 20
    },
    {
      "id": "dim_hole_distance",
      "type": "linear_horizontal",
      "anchor_from": "mounting.hole_1",
      "anchor_to": "mounting.hole_2",
      "view": "top",
      "value_source": "measure",
      "offset": 25
    }
  ]
}
```

---

## 6 多用户并发架构

### 6.1 并发模型选择

Python GIL 限制同一进程内同一时刻只有一个线程执行 Python 字节码 [^10]，且 OCCT HLR 算法本身是单线程计算 [^1]。因此多线程对 HLR 计算无效，**必须用多进程**。

pythonocc-core 方案的多进程并发优势：

| 维度 | FreeCAD 方案 | pythonocc-core 方案 |
|------|-------------|-------------------|
| 单 Worker 内存 | ~500MB-1GB | **~200MB** |
| 8核可跑 Worker | 3-4 个 | **6-7 个** |
| 进程启动时间 | ~3-5秒 | **~1秒** |
| 单任务耗时 | 2-5分钟 | **~6-10秒** |
| 吞吐量(8核) | ~2-3 任务/分钟 | **~36-70 任务/分钟** |
| 崩溃恢复 | 慢 | **快（进程池自动重启）** |

### 6.2 Worker 进程池架构

```
┌─────────────────────────────────────────────────────┐
│  API层                                                │
│  ┌──────────────────────┐                            │
│  │  FastAPI 异步接入     │                            │
│  └──────────┬───────────┘                            │
├─────────────┼────────────────────────────────────────┤
│  任务调度   │                                         │
│  ┌──────────▼───────────┐                            │
│  │  任务队列 → Redis/内存队列 │                        │
│  └──┬─────┬─────┬─────┬──┘                           │
├─────┼─────┼─────┼─────┼──────────────────────────────┤
│  Worker进程池                                         │
│  ┌──▼──┐ ┌──▼──┐ ┌──▼──┐ ┌──▼──┐                   │
│  │W0   │ │W1   │ │W2   │ │WN   │                    │
│  │~200MB│ │~200MB│ │~200MB│ │~200MB│                  │
│  └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘                   │
├─────┼──────┼──────┼──────┼──────────────────────────┤
│  缓存层                                              │
│  ┌──▼──────────────────────────┐                      │
│  │ L1 内存缓存 (<1ms)           │                      │
│  │ L2 文件缓存 (<10ms)          │                      │
│  │ L3 Redis    (<5ms)           │                      │
│  └──────────────────────────────┘                      │
└─────────────────────────────────────────────────────┘
```

*图 4：Worker 进程池并发架构*

### 6.3 并发设计要点

#### Worker 进程复用

进程池常驻，每个 Worker 启动时预导入 OCCT 模块（`initializer=_init_worker`），避免每次任务重复加载。OCCT 模块导入约需 2-3 秒，复用后每任务节省此开销。

#### GIL 释放的关键利用

OCCT 的 HLR 计算是 C++ 代码，在执行期间会释放 Python GIL [^11]。这意味着同一个 Worker 进程内，可以用多线程并行生成 6 个视图：**进程级并行（多用户）+ 线程级并行（单用户 6 视图）**。

#### 超时与熔断

每个 Worker 任务设置 30 秒超时，Worker 崩溃后 ProcessPoolExecutor 自动重启子进程，不影响其他 Worker。

### 6.4 并发性能估算（8核 16GB 服务器）

| 指标 | 数值 | 说明 |
|------|------|------|
| 可用 Worker 数 | **6-7** | CPU核数 - 1（留1核给主进程） |
| 总内存占用 | **~1.4GB** | 7 Workers × 200MB |
| 单任务耗时 | **~8秒** | 含模型加载+HLR+标注 |
| 吞吐量 | **~50/分钟** | 缓存未命中时 |
| 缓存命中速度 | **<100ms** | 同型号重复请求 |

---

## 7 微信小程序 WebView 集成

### 7.1 环境约束分析

微信小程序 WebView 环境的能力边界决定了**所有计算必须在后端完成** [^5][^12]：

| 能力 | 原生小程序 | WebView 内 H5 | 影响 |
|------|-----------|---------------|------|
| WebGL | 残缺 | 可用（完整浏览器引擎） | Three.js 可跑但性能不稳 |
| WebGPU | 不支持 | Android 部分支持，iOS 不支持 | 不可靠，不能依赖 |
| SVG | 部分支持（无法动态修改） | 完整支持 | H5 内 SVG 没问题 |
| WASM | 受限 | 可用但性能不如原生 | OCCT WASM 不值得 |
| compute shader | 不支持 | 不稳定 | three-edge-projection 不可用 |

### 7.2 前端展示方案

后端生成完整 SVG（含标注），前端 WebView 内 H5 页面只需做纯展示：

```html
<!-- drawing-viewer.html (部署在业务域名下) -->
<body>
  <div id="loading">生成中...</div>
  <div id="drawing" style="display:none;"></div>

  <script>
  // 从小程序接收参数
  const params = new URLSearchParams(location.search);
  const model = params.get('model');

  // 请求后端生成工程图
  fetch('https://api.example.com/api/drawing/generate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ model, params: {} })
  })
  .then(r => r.json())
  .then(data => {
    document.getElementById('loading').style.display = 'none';
    const container = document.getElementById('drawing');
    // 直接渲染SVG（标注已嵌入）
    data.views.forEach(view => {
      const div = document.createElement('div');
      div.innerHTML = view.svg;
      container.appendChild(div);
    });
  });
  </script>
</body>
```

### 7.3 SVG 标注后端合成

为减少前端复杂度和数据传输量，标注在后端直接合成到 SVG 中。后端将 HLR 视图线条 + 标注层合成为完整 SVG，前端只需 `innerHTML = svg` 即可显示。

### 7.4 进度体验优化

首次生成需 6-10 秒，前端通过轮询展示阶段进度：

```javascript
// 前端轮询 + 进度展示
async function generateDrawing(params) {
  const task = await submitTask(params);
  while (true) {
    const status = await checkStatus(task.id);
    updateProgress(status.progress, status.stage);
    // "正在生成3D模型... 45%"
    // "正在生成工程图视图... 70%"
    // "正在添加标注... 95%"
    if (status.status === 'done') {
      renderDrawing(status.result);
      break;
    }
    await sleep(1000);
  }
}
```

### 7.5 WebView 业务域名配置

> **部署要求**
>
> - 所有通过 `<web-view>` 加载的网页必须使用 **HTTPS** 协议 [^13]
> - 域名必须在小程序后台**业务域名白名单**中配置 [^13]
> - 需上传验证文件到服务器根目录
> - 个人类型小程序不可使用 web-view 组件

---

## 8 性能预算与时间分析

### 8.1 两阶段时间预算

#### 阶段 1：模型生成（用户选型后触发）

| 环节 | 预估耗时 | 说明 |
|------|----------|------|
| 参数解析与验证 | ~0.1秒 | 型号规则解析 |
| STEP 模型生成 | ~10-15秒 | 已实现 |
| GLB 转换 | ~1-2秒 | 用于前端 3D 预览 |
| 模型缓存写入 | ~0.3秒 | 文件系统 |
| **合计** | **~12-17秒** | |

#### 阶段 2：工程图生成（用户点击查看时触发）

| 环节 | 预估耗时 | 说明 |
|------|----------|------|
| 加载已缓存 STEP | ~0.5-1秒 | 从文件系统读取 |
| 模型预处理 | ~0.3秒 | 移除隐藏零件、简化特征 |
| HLR 6视图（并行） | ~3-6秒 | PolyAlgo + 多线程 |
| 锚点计算 | ~0.01秒 | 参数驱动 |
| 标注生成 | ~0.01秒 | 模板驱动 |
| SVG 合成 | ~0.3秒 | 视图+标注嵌入 |
| 网络传输 | ~1-2秒 | SVG 数据 |
| 前端渲染 | ~0.5秒 | 纯 SVG 展示 |
| **合计** | **~6-10秒** | 远低于 30 秒 |

### 8.2 缓存命中场景

| 场景 | 耗时 | 触发条件 |
|------|------|----------|
| 工程图缓存命中 | **< 0.5秒** | 同型号已生成过（预生成完成） |
| 模型缓存命中 | **~6-10秒** | 模型已生成，工程图首次生成 |
| 全量实时生成 | **~18-27秒** | 模型和工程图均未缓存 |

### 8.3 对比：合并方案 vs 分离方案

| 维度 | 合并方案（一阶段） | 分离方案（两阶段） |
|------|-------------------|-------------------|
| 工程图生成耗时 | 18-27秒 | **6-10秒** |
| 30秒压力 | 紧张 | **轻松** |
| HLR 质量 | 只能用 PolyAlgo | **可用精确 Algo** |
| 预生成能力 | 无 | **有（用户看模型时后台生成）** |
| 缓存命中后 | 无 | **<0.5秒秒开** |
| 服务扩展性 | 耦合 | **独立扩容** |
| 用户体验 | 一次长等待 | **两次短等待** |

---

## 9 分阶段实施路线

### 第一阶段：HLR 视图生成原型

| 维度 | 内容 |
|------|------|
| **目标** | 用 pythonocc-core 从 STEP 生成 6 个视图 SVG |
| **验收标准** | 视图方向正确；视图不残缺、不杂糅；6 视图并行 < 8 秒 |

### 第二阶段：锚点系统

| 维度 | 内容 |
|------|------|
| **目标** | 实现参数驱动锚点 + BRep 查询锚点 |
| **关键锚点** | 缸体左端/右端、轴线、外径圆、电机包络、安装孔中心 |
| **验收标准** | L100/L200 切换后锚点更新；端点距离正确；视图上锚点位置正确 |

### 第三阶段：标注系统

| 维度 | 内容 |
|------|------|
| **目标** | 实现模板驱动的标注生成 + SVG 合成 |
| **标注类型** | 线性标注（水平/垂直）、直径标注、角度标注、固定文本 |
| **验收标准** | 标注值不受视图缩放影响；模型变化后标注跟着变；标注位置由模板控制 |

### 第四阶段：并发与缓存

| 维度 | 内容 |
|------|------|
| **目标** | Worker 进程池 + 三级缓存 + 预生成 |
| **实现内容** | ProcessPoolExecutor Worker 池；内存/文件/Redis 三级缓存；后台预生成调度器；任务状态查询 API；超时与熔断机制 |

### 第五阶段：小程序集成

| 维度 | 内容 |
|------|------|
| **目标** | 微信小程序 WebView 展示工程图 |
| **实现内容** | H5 工程图查看页面；业务域名配置；进度展示与轮询；SVG 交互（缩放/平移） |

### 第六阶段：导出与完善

| 维度 | 内容 |
|------|------|
| **目标** | 支持多种导出格式和完整工程图功能 |
| **实现内容** | PDF 导出（SVG → PDF 转换）；DXF 导出；标题栏和明细栏；条件标注（零件显示/隐藏联动） |

---

> **下一步行动建议**
>
> 不要再继续在当前 HLR 上反复修补，直接进入第一阶段：搭建 pythonocc-core Worker 原型，输入 STEP 文件输出 6 个 SVG 视图，验证视图质量和生成速度。这是整个方案的可行性验证基础。

---

## 10 自研工程图编辑器方案

### 10.1 方案定位

本项目后续不再以 SolidWorks `.SLDDRW` 标注提取作为主线。`.SLDDRW` 仅保留为模板参考样本，不作为工程图能力的核心数据源。

主线改为：

- 模型参数驱动视图生成
- 语义锚点驱动标注绑定
- 自研工程图文档驱动前端编辑
- 模型变化后自动重建视图并重绑标注

### 10.2 目标

构建一套自研工程图编辑器，达到以下效果：

- 自动生成标准视图
- 在图纸上拖拽、摆放、缩放视图
- 手工添加线性、直径、半径、角度标注
- 支持文字、中心线、标题栏、表格
- 模型系列变化后自动更新视图
- 标注尽量保持语义关联，不随视图漂移

### 10.3 核心原则

1. 视图只负责显示，不负责标注求值。
2. 标注不绑定屏幕坐标，绑定语义锚点与几何指纹。
3. 同系列产品优先复用模板，不依赖外部工程图反向提取。
4. 标注失配时可提示用户修复，不做静默错误映射。

### 10.4 数据结构

#### DrawingTemplate

描述某一系列图纸的布局规则、默认视图、默认标注和适用条件。

```json
{
  "template_id": "250-E-H3K2",
  "name": "250系列液压缸模板",
  "sheet": { "size": "A3", "width": 420, "height": 297 },
  "apply_rules": { "series": "250", "mount": "H3K2" },
  "views": [],
  "annotations": [],
  "title_block": {}
}
```

#### DrawingDocument

描述当前用户正在编辑的工程图实例。

```json
{
  "document_id": "doc_001",
  "template_id": "250-E-H3K2",
  "model_id": "250-E-H3K2-L100-D11",
  "sheet": {},
  "views": [],
  "annotations": [],
  "revision": 1
}
```

#### AnnotationBinding

描述标注如何绑定到模型几何或语义锚点。

```json
{
  "id": "dim_total_length",
  "type": "linear",
  "view_id": "front",
  "binding": {
    "from_anchor": "cylinder.front_end",
    "to_anchor": "cylinder.back_end",
    "geometry_fingerprint": {}
  },
  "presentation": {
    "offset": 30,
    "text_pos": [120, 240]
  }
}
```

### 10.5 前后端模块划分

#### 后端

- 模型参数解析
- 视图生成
- 语义锚点计算
- 几何指纹匹配
- 标注重绑定
- SVG / JSON 导出

#### 前端

- 图纸画布
- 视图调色板
- 标注工具栏
- 属性面板
- 文档保存与加载

### 10.6 与现有代码的关系

可复用的内容：

- [drawing_engine.py](file:///e:/分享代码/step__glb_pdf/src/drawing_engine.py)
- [drawing_template.py](file:///e:/分享代码/step__glb_pdf/src/drawing_template.py)
- [App.vue](file:///e:/分享代码/step__glb_pdf/cad-viewer-app/src/App.vue)
- [server.py](file:///e:/分享代码/step__glb_pdf/src/server.py#L755-L785)

不再作为主线的内容：

- SolidWorks `.SLDDRW` 标注提取
- COM 逆向工程图数据

### 10.7 实施顺序

1. 固化工程图 JSON 数据结构
2. 在 `cad-viewer-app` 中拆分工程图编辑器组件
3. 接入模型视图生成与图纸画布
4. 接入标注创建与保存
5. 接入锚点绑定与重绑定
6. 支持系列模板复用

### 10.8 近期决策

- `.SLDDRW` 标注提取停止投入
- 仅保留模板参考样本
- 主线全部转向自研工程图编辑器

---

## 参考资料

[^1]: Sergey Slyadnev, *Hidden Line Removal Comparative Study*. OCCT HLR 与商业 CAD 软件的性能对比研究。 https://quaoar.su/files/papers/cascade/HLR_ComparativeStudy_2021-02-28.pdf

[^2]: CSDN, *FreeCAD性能基准测试:不同硬件配置下的建模效率对比*。TechDraw 导出 20 页工程图的渲染耗时数据。 https://blog.csdn.net/gitblog_00710/article/details/153853861

[^3]: GitHub/FreeCAD, *TechDraw: Ability to Headless export of SVG and PDF*. 无界面模式导出限制的开放功能请求。 https://github.com/FreeCAD/FreeCAD/issues/5710

[^4]: gkjohnson, *Three-Edge-Projection: Generating Vector Drawings from Models*. 基于 three-mesh-bvh 和 GPU compute shader 的 HLR 方案。 https://discourse.threejs.org/t/three-edge-projection-generating-vector-drawings-from-models/92165

[^5]: 腾讯云, *为什么 Perfect HandAR 在微信小程序中必须用 WebView*。微信小程序原生环境与浏览器环境的能力差异分析。 https://cloud.tencent.com/developer/article/2596281

[^6]: Spatial, *CGM HLR Hidden Line Removal*. Dassault Systèmes 旗下商业 HLR 解决方案。 https://www.spatial.com/solutions/3d-modeling/cgm-hlr-hidden-line-removal

[^7]: 卡核, *OpenCASCADE Hidden Line Removal*. OCCT HLR 算法原理与 HLRBRep_PolyAlgo 性能分析。 https://www.caxkernel.com/2052.html

[^8]: 博客园, *几何建模引擎中的TNP稳定命名机制*。拓扑命名问题（Topological Naming Problem）的关键技术分析。 https://www.cnblogs.com/chanyuantiandao/p/20376088

[^9]: OpenCASCADE, *OCAF User Guide*. reference-key 模型与拓扑命名机制文档。 https://www.opencascade.com/doc/occt-7.5.0/overview/html/occt_user_guides__ocaf.html

[^10]: CSDN, *深入理解Python的GIL锁:从原理到实战*。CPython 全局解释器锁的原理与影响。 https://blog.csdn.net/m0_51069462/article/details/159856227

[^11]: CodingPancake, *How to Bypass the Python GIL from Scratch*. C 扩展调用释放 GIL 的多核并行模式。 https://www.codingpancake.com/2026/07/how-to-bypass-python-gil-from-scratch.html

[^12]: 微信开放社区, *小程序通过加载WebGPU或WebGL网页可以支持吗*。微信小程序 WebGL/WebGPU 支持情况官方回复。 https://developers.weixin.qq.com/community/develop/doc/00080a234a86103d1be37a6546bc00

[^13]: CSDN, *微信小程序开发实战指南: Webview访问总结*。web-view 组件业务域名配置与限制条件。 https://blog.csdn.net/dazhong2012/article/details/153327373
