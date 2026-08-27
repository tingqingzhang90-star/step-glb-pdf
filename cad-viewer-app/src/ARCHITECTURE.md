# CAD 工程图查看器 — 前端目录结构与功能模块说明

> 适用目录：`cad-viewer-app/src/`
> 技术栈：Vue 3（Composition API + `<script setup>`）+ Vite + Element Plus
> 设计原则：纯函数/纯工具抽离到无依赖模块，有状态逻辑用「工厂 + 依赖注入」封装成 composable，App.vue 只保留模板、事件总控与状态声明。

## 一、目录总览

```
src/
├── App.vue                      # 根组件：模板 + 事件总控 + 引擎装配
├── main.js                      # 应用入口（挂载 App、引入样式/Element Plus）
├── style.css                    # 全局样式
├── data-model-shim.js           # 后端数据模型兜底/兼容层（AcDbFontNameCollector 等）
├── api/                         # 后端接口请求封装（无 UI 状态）
├── composables/                 # 有状态逻辑：Vue 组合式函数（工厂 + 依赖注入）
├── dimensions/                  # 标注子系统：几何纯函数 + 构建引擎 + 交互状态机
├── views/                       # 视图几何与对齐纯函数（零 Vue 依赖）
├── utils/                       # 通用纯函数工具（文档序列化等）
├── components/                  # 复用型 UI 组件（当前含示例组件 HelloWorld.vue）
└── assets/                      # 静态资源（图片、svg 等）
```

## 二、各模块职责说明

### 1. `App.vue`（根组件）

职责边界：模板渲染、全局事件总控、各 composable 实例化与装配。

- 通过 `useCanvasTransform` / `useModelPalette` / `usePlacedViews` / `useSheetCoords` / `usePaletteDrag` / `useViewDrag` / `useDimensions` 装配子系统，并以依赖注入方式串接。
- 保留跨子系统的事件总控函数（如 `onSvgMouseDown`、`onGlobalMouseMove`），内部业务逻辑委托给对应引擎模块。
- 保留 App 级坐标 helper（如 `getSheetPoint` / `makeEdgeRef` / `resolveDimRef`），因其直接依赖 `placedViews` 与 `svgRef`。

### 2. `api/drawingApi.js` — 接口封装

仅做请求与数据规整，不持有 UI 状态：

- `fetchModelList()`：拉取可选型号列表（过滤含 `assembly.step`/`assembly.brep` 的模型组）。
- `fetchViewPalette(modelId)`：按型号拉取视图调色板（标准视图/轴测视图及边线数据）。

### 3. `composables/` — 组合式逻辑层

| 模块 | 导出 | 职责 |
|------|------|------|
| `useCanvasTransform.js` | `useCanvasTransform()` | 图纸画布整体缩放/平移（白卡/图框/视图/标注作为同一整体移动），含缩放上下限 `SHEET_ZOOM_MIN/MAX`。 |
| `useModelPalette.js` | `useModelPalette()` | 型号选择与视图调色板数据加载（models、selectedModel、standardViews、isometricViews 等状态）。 |
| `usePlacedViews.js` | `usePlacedViews({ sheetWidth, sheetHeight })` | 已放置视图管理：放置/删除/选择、全局比例 `globalScale`、同名视图唯一约束。依赖 `views/viewGeometry.js` 计算包围盒与初始比例。 |
| `useSheetCoords.js` | `useSheetCoords({ placedViews })` | 图纸坐标换算与边线引用：鼠标事件→图纸坐标（`eventToSheetPoint`）、`getEdgeByRef`/`makeEdgeRef`/`resolveDimRef`/`edgeRefData`/`getViewDisplayScale`/`getViewMmScale` 等。依赖 `svgRef`。 |
| `usePaletteDrag.js` | `usePaletteDrag({ coords, views, sheetWidth, sheetHeight })` | 调色板拖拽放置：pointer 事件 + rAF 节流预览 + 点击放置，依赖 `views/viewGeometry.js` 计算居中放置与初始比例。 |
| `useViewDrag.js` | `useViewDrag({ placedViews, selectedViewId, toSheetPoint })` | 已放置视图拖动移动，带投影对齐吸附与引导线（`alignmentGuides`），依赖 `views/viewGeometry.js` 的 `detectAlignment`。 |
| `useDimensions.js` | `useDimensions({ placedViews, selectedViewId, coords })` | 标注工具状态声明 + 引擎装配：装配 `dimCore`（几何构建）与 `dimEngine`（交互状态机），对外暴露 `toggleTool`/`onDimEdgeSelect`/`renderedDimensions` 等。 |

### 4. `dimensions/` — 标注子系统

标注逻辑从 App.vue 完整抽离，按「纯几何 → 构建引擎 → 交互状态机」分层：

| 模块 | 导出 | 职责 |
|------|------|------|
| `geometry.js` | `toLineSeg`、`fitCircleFromPoints`、`fitCircleLeastSquares`、`toCircle`、`isParallel`、`closestPointOnLine`、`lineBasis`、`offsetPoint`、`signedDistanceToLine`、`projectPointToLine`、`lineIntersection`、`farthestEndpointFrom`、`buildArcPath`、`polylinePoints` | 标注几何纯函数（线段/圆拟合、平行判断、投影、交点、弧路径），零 Vue 依赖。 |
| `arrow.js` | `buildArrowPoints`、`estimateTextWidth`、`linearArrowDirs`、`buildLinearArrows` | 标注箭头与文本宽度估算纯函数。 |
| `core.js` | `createDimensionCore(deps, ctx)` | 标注构建引擎：根据边线引用与几何纯函数生成标注数据，并负责 `renderDimension` 渲染产出。 |
| `index.js` | `createDimEngine(deps)`、`createDimensionCore`（别名 `coreFactory`） | 标注交互状态机：工具切换/边线选择/预览/拖拽；通过依赖注入共享 state 与 helper，配合 core 完成放置与渲染。 |

依赖方向：`index.js` → `core.js` / `geometry.js` / `arrow.js`；App.vue 经 `useDimensions` 间接消费 `dimensions/index.js`。

### 5. `views/viewGeometry.js` — 视图几何与对齐

零 Vue 依赖的纯函数，供 `usePlacedViews` / `usePaletteDrag` / `useViewDrag` 复用：

- 对齐分组常量：`VERTICAL_ALIGN_GROUP_X`、`VERTICAL_ALIGN_GROUP_Z`、`HORIZONTAL_ALIGN_GROUP_Y`。
- 几何计算：`normalizeViewBBox`、`computeContentBBox`、`getInitialViewScale`、`getCenteredViewPlacement`、`getViewCenterInSheet`。
- 投影对齐：`detectAlignment(centerX, centerY, skipId, placedViews, getScale)`。

### 6. `utils/drawingDocument.js` — 工程图文档序列化

- `buildDrawingDocument({ sheetWidth, sheetHeight, modelId, placedViews, dimensions })`：将当前图纸（图幅、视图、标注）序列化为 JSON，供属性面板预览及后续导出复用。纯函数，无副作用。

### 7. 其他

- `data-model-shim.js`：后端数据模型兼容/兜底层（如 `AcDbFontNameCollector`），用于前端数据形态适配。
- `components/`：可复用 UI 组件目录（当前含 `HelloWorld.vue` 示例）。
- `assets/`：静态资源。
- `main.js` / `style.css`：入口与全局样式。

## 三、数据流与依赖关系

```
App.vue
  ├─ useCanvasTransform      → 画布缩放/平移状态
  ├─ useModelPalette         → api/drawingApi.js（型号、调色板数据）
  ├─ usePlacedViews          → views/viewGeometry.js（包围盒/比例）
  │     └─ useSheetCoords    → 坐标换算 + 边线引用（持有 svgRef）
  ├─ usePaletteDrag          → views/viewGeometry.js（居中放置）
  ├─ useViewDrag             → views/viewGeometry.js（detectAlignment）
  └─ useDimensions
        └─ dimensions/index.js（createDimEngine）
              └─ dimensions/core.js（createDimensionCore）
                    └─ dimensions/geometry.js + arrow.js
```

关键约束：

- 纯函数模块（`dimensions/geometry.js`、`arrow.js`、`views/viewGeometry.js`、`utils/drawingDocument.js`）不依赖 Vue，可被任意 composable 复用与单测。
- composable 通过「工厂 + 依赖注入」解耦（如 `createDimEngine(deps)`、`usePaletteDrag({ coords, views, ... })`），App.vue 只负责装配，不直接编排内部状态。
- `.vue` 单文件严格控制在 300 行内；超过则按「职责边界 + 依赖注入」拆分到上述目录。

## 四、命名与规范约定

- 目录 kebab-case；组件 PascalCase；函数/变量 camelCase；常量 UPPER_SNAKE_CASE。
- 前端接口消费遵循 `request` 拦截器解包约定（成功只返回内层 `data`）。
- 标注/视图相关新增模块统一落在 `dimensions/`、`views/`，通用工具落在 `utils/`，禁止把业务塞进 App.vue。
