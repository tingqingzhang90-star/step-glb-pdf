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

## 五、标注命中算法设计

标注拾取同时面临两类命中：**DOM 命中**（透明加宽命中带，`elementFromPoint` 取最顶层元素）与**几何命中**（按数学距离判定）。两者分工与配套如下。

### 5.1 几何命中：孔 / 分度圆择近分派

**问题背景**：孔组的分度圆（虚线圆，`pitchCircle`）在标注工具（如 `center-mark`）下，其 DOM 命中带 `.dim-bolt-hit` 刻意让路给孔/边线（避免挡住点孔），而虚线本身仅 1px，几乎点不中。在分度圆附近用「点中心十字」功能极难命中。

**算法骨架**（`dimensions/index.js` 的 `pickCircleNear` 与 `pickBoltCircleNear` 同构）：

- 容差（屏幕 ≈12px，随视图缩放补偿）：`tolerance = max(6, 12 / scale)`，其中 `scale = view.scale`。
- 坐标统一换算到图纸坐标：`getSheetPoint(view, cx, cy)`（局部 → 图纸）。
- 判定量：**点到圆周的有符号距离** `d = |dist(鼠标, 圆心) − r|`，`d ≤ tolerance` 即命中；多候选取 `d` 最小者。
- `pickCircleNear`：遍历视图的 `edges` / `hiddenEdges`，`toCircle(seg)` 还原圆，`r < 3` 跳过噪声小圆，返回命中的 `edgeRef`（携带 `d`）。
- `pickBoltCircleNear`：遍历 `dimensions` 中 `type==='center-mark' && (group||groupCenter)` 的标注，经 `core.buildBoltCircleRef(refs)`（由孔组引用实时最小二乘还原分度圆，已从 core 导出复用）得到 `{ seg(局部坐标), view }`，换算后判定，返回 `{ dim, circle, d }`。

**择近分派**（避免孔与分度圆相交区域打架）：

> 孔都长在分度圆上，孔心恰在分度圆周上。鼠标同时靠近两者时，取 `d` 更小的：
> `if (bolt && (!hole || bolt.d <= hole.d))` → 命中分度圆；否则命中孔。

适用工具：`diameter`（直径）与 `center-mark`（中心标记，单孔/孔组两子模式同）。

- **mousedown**（`onSvgMouseDown` 开头、DOM 命中**之前**——否则"预览按分度圆、点击落在孔"行为分裂）：分度圆命中 → 直径工具走 `core.placeDiameterOnBoltCircleDim(bolt.dim.refs, opts)`（贯穿直线用预览角度；引线折线用预览 textLeft，均所见即所得），中心标记走 `core.placeCenterMarkAtGroupCenter(bolt.dim.refs)`（孔组中心打十字）；孔命中 → 按 `centerSubMode` 走单孔十字 / 加入孔组。放置后 `suppressPreviewAfterPlace` 防预览与标注自身重叠。点孔组标注的 DOM 命中副本（`onDimMouseDown`）有对称分支兜底。
- **hover 预览**（`updateDimPreviewAt` 内同择近判定，`dimPending` 时不干扰选孔预览）：分度圆更近时出**与放置一致的预览**——直径：贯穿线/引线跟随鼠标（`buildDiameterPreview` / `buildDiameterLeaderPreview` 直接吃分度圆合成 edgeRef）；中心标记：`buildCenterMarkGroupGeometry(refs, true)` 孔组中心十字。同时清 `dimHoveredEdge`（避免孔高亮与分度圆预览分裂）、`onSvgMouseMove` 设 `dimHoveredId` 高亮孔组虚线圆（变蓝瞄准反馈）；更靠近孔时让位给孔的既有 DOM hover/预览通道。
- **圆引用统一收口**：`core.diameterRefOf(dim)`——分度圆标注（数据带 `groupRefs`）由孔组各孔实时还原合成圆（换型号自动跟随），其余取单边线。渲染、拖拽（`updateDimDrag`/`updateDimTextDrag`）、快照（`diameterTextLeftSheetClamped`）全走它，组引用兼容不再散落判断。分度圆直径标注两形态：`diameterMode: 'bolt-circle'`（贯穿直线）与 `'leader' + groupRefs`（引线折线）。

**复用点**：几何命中零 DOM、天然不挡任何东西，契合「标注工具下让路」的设计意图；`hover` 与 `mousedown` 共用同一判定；还原分度圆复用 `buildBoltCircleRef`。若日后直径工具也想去掉 `.dim-bolt-hit` DOM 命中带，可直接复用 `pickBoltCircleNear`。

### 5.2 命中层 z-order 策略（DOM 命中）

标注工具激活时，已放置标注的命中副本（`.dim-hit-dims`，10px 透明命中带）与视图边线命中带同处 `dim-hit-layer`。

- **原则**：副本**永远位于边线命中层之下**（DOM 中先渲染 = 下层）。重叠处 `elementFromPoint` 命中上层边线 → 拾取边线/点孔优先，任何已放置标注（直径贯穿线、引线、十字、线性、角度）都不挡拾取。
- 鼠标只在纯标注带上（附近无边线）才落到副本 → 仍可悬浮高亮/点选/拖拽已放置标注。
- 「等第二边」状态（`dimFirstEdge` 已选、待固定态未建立）时副本整体不渲染：点击落到 svg 根，保持「单边标注按当前偏移直接放置」原语义。
- 十字命中带的孔心处挖空（`Math.min(6, max(2, cm.r−4))`），点孔心可穿透到 `pickCircleNear` 几何兜底，已放置十字不挡对同孔的再次拾取。
- 角度标注的延长线（`extLines`）补了命中副本，工具激活时真实层 `.dim-hit-stroke` 让路后仍能点中。

### 5.3 直径引线长度限位（关联设计）

直径「引线折线」模式的文字/折点若离圆太远，会拖出横跨半张图的超长折线。统一收口于 `core.js` 的 `clampDiameterLeaderTextLeft`：

- 折点（文字搁置线右端）距圆心超过 `r + LEADER_MAX_LENGTH`（120px）时，沿「折点→圆心」方向把整个标注（文字 + 折点 + 引线）自动拉近圆。
- 在 `buildDiameterLeaderGeometry` 内先限位、再按「折点→圆心」重算瞄准角（引线方向始终与圆相交），故**预览/放置/拖拽/渲染四个入口自动全部生效**；已放好的超长标注刷新后也会收紧。
- 拖拽快照取限位后的坐标（`diameterTextLeftSheetClamped`），保证旧数据（限位外远点）与显示一致，避免拖拽卡顿。
- 引线模式不支持文字单独拖动（文字按下走整体拖拽 `onDimMouseDown`），行为统一。
