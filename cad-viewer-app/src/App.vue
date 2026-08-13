<template>
  <div class="sw-drawing-app">
    <header class="top-toolbar">
      <div class="toolbar-left">
        <span class="app-title">工程图编辑器</span>
        <el-divider direction="vertical" />
        <el-select v-model="selectedModel" placeholder="选择型号" filterable size="small" class="model-select" @change="onModelChange">
          <el-option v-for="m in models" :key="m" :label="m" :value="m" />
        </el-select>
        <el-button type="primary" size="small" :loading="loadingViews" :disabled="!selectedModel" @click="loadViewPalette">
          <el-icon><Upload /></el-icon>
          导入模型
        </el-button>
      </div>

      <div class="toolbar-center">
        <el-button-group>
          <el-button size="small" :icon="ZoomIn" :disabled="!viewsLoaded" @click="zoomCanvas(1.2)">放大</el-button>
          <el-button size="small" :icon="ZoomOut" :disabled="!viewsLoaded" @click="zoomCanvas(0.8)">缩小</el-button>
          <el-button size="small" :disabled="!viewsLoaded" @click="resetCanvas">适应</el-button>
        </el-button-group>
        <el-divider direction="vertical" />
        <el-button-group>
          <el-button size="small" :type="activeTool === 'linear' ? 'primary' : ''" :disabled="!viewsLoaded" @click="toggleTool('linear')">线性</el-button>
          <el-button size="small" :type="activeTool === 'diameter' ? 'primary' : ''" :disabled="!viewsLoaded" @click="toggleTool('diameter')">直径</el-button>
          <el-button size="small" :type="activeTool === 'angle' ? 'primary' : ''" :disabled="!viewsLoaded" @click="toggleTool('angle')">角度</el-button>
        </el-button-group>
        <el-color-picker v-model="dimensionColor" size="small" :predefine="dimensionColorPresets" aria-label="标注颜色" />
        <el-divider direction="vertical" />
        <el-button size="small" :icon="Delete" :disabled="placedViews.length === 0" @click="clearPlacedViews">清空</el-button>
      </div>

      <div class="toolbar-right">
        <span v-if="loadingText" class="status-text">{{ loadingText }}</span>
        <span v-if="lastElapsed" class="status-ok">耗时 {{ lastElapsed }}s</span>
        <span v-if="error" class="status-err">{{ error }}</span>
      </div>
    </header>

    <main class="editor-shell">
      <aside class="view-palette">
        <div class="panel-header">视图调色板</div>

        <div v-if="loadingViews" class="panel-empty">
          <el-icon class="is-loading"><Loading /></el-icon>
          <p>正在生成视图...</p>
          <p class="sub">STEP → HLR 投影 → 标准视图</p>
        </div>

        <div v-else-if="!viewsLoaded" class="panel-empty">
          <p>请先导入模型</p>
        </div>

        <template v-else>
          <section class="palette-section">
            <div class="section-title">标准视图</div>
            <div class="view-grid">
              <div
                v-for="vw in standardViews"
                :key="vw.name"
                :class="['view-item', { 'is-placed': placedViewNames.has(vw.name) }]"
                :title="placedViewNames.has(vw.name) ? `「${vw.label}」已放置` : `点击或拖拽放置「${vw.label}」`"
                @pointerdown="!placedViewNames.has(vw.name) && onPalettePointerDown($event, vw)"
              >
                <div class="view-thumbnail" v-html="vw.thumbnail"></div>
                <span class="view-label">{{ vw.label }}</span>
              </div>
            </div>
          </section>

          <section class="palette-section">
            <div class="section-title">轴测视图</div>
            <div class="view-grid">
              <div
                v-for="vw in isometricViews"
                :key="vw.name"
                :class="['view-item', { 'is-placed': placedViewNames.has(vw.name) }]"
                :title="placedViewNames.has(vw.name) ? `「${vw.label}」已放置` : `点击或拖拽放置「${vw.label}」`"
                @pointerdown="!placedViewNames.has(vw.name) && onPalettePointerDown($event, vw)"
              >
                <div class="view-thumbnail" v-html="vw.thumbnail"></div>
                <span class="view-label">{{ vw.label }}</span>
              </div>
            </div>
          </section>
        </template>
      </aside>

      <section class="canvas-region">
        <div class="sheet-area" ref="sheetAreaRef">
          <div class="sheet-grid"></div>
          <svg
            ref="svgRef"
            :class="['drawing-sheet', { 'dim-active': activeTool }]"
            :width="sheetWidth"
            :height="sheetHeight"
            :viewBox="`0 0 ${sheetWidth} ${sheetHeight}`"
            @mousedown="onSvgMouseDown"
            @mousemove="onSvgMouseMove"
          >
            <rect x="20" y="20" :width="sheetWidth - 40" :height="sheetHeight - 40" fill="#ffffff" stroke="#999" stroke-width="1" />
            <rect x="920" y="690" width="240" height="120" fill="none" stroke="#555" stroke-width="1" />
            <line x1="920" y1="730" x2="1160" y2="730" stroke="#555" stroke-width="1" />
            <line x1="1000" y1="690" x2="1000" y2="810" stroke="#555" stroke-width="1" />
            <text x="1040" y="715" font-size="18" fill="#303133">产品工程图</text>
            <text x="936" y="755" font-size="12" fill="#606266">型号</text>
            <text x="1016" y="755" font-size="12" fill="#303133">{{ selectedModel || '-' }}</text>

            <!-- 对齐引导线（仅拖拽时显示） -->
            <g v-if="alignmentGuides.length > 0" class="alignment-guides" pointer-events="none">
              <template v-for="(guide, i) in alignmentGuides" :key="`guide-${i}`">
                <line
                  v-if="guide.type === 'vertical'"
                  :x1="guide.pos" y1="20" :x2="guide.pos" :y2="sheetHeight - 20"
                  stroke="#409eff" stroke-width="1" stroke-dasharray="6,3"
                  vector-effect="non-scaling-stroke" opacity="0.7"
                />
                <line
                  v-else
                  x1="20" :y1="guide.pos" :x2="sheetWidth - 20" :y2="guide.pos"
                  stroke="#409eff" stroke-width="1" stroke-dasharray="6,3"
                  vector-effect="non-scaling-stroke" opacity="0.7"
                />
              </template>
            </g>

            <g
              v-for="pv in placedViews"
              :key="pv.id"
              :transform="`translate(${pv.x}, ${pv.y}) scale(${pv.scale})`"
              :class="['placed-view', { selected: selectedViewId === pv.id }]"
              @mousedown.stop="onViewMouseDown($event, pv)"
              @click.stop="selectView(pv.id)"
            >
              <rect
                :x="pv.contentBBox.x - 4"
                :y="pv.contentBBox.y - 4"
                :width="pv.contentBBox.width + 8"
                :height="pv.contentBBox.height + 8"
                fill="none"
                :stroke="selectedViewId === pv.id ? '#409eff' : 'transparent'"
                stroke-width="2"
                stroke-dasharray="4,2"
                vector-effect="non-scaling-stroke"
              />
              <g class="visible-edges" vector-effect="non-scaling-stroke">
                <template v-for="(seg, i) in pv.edges" :key="`v${i}`">
                  <line
                    v-if="seg && seg.type === 'line'"
                    :x1="seg.x1"
                    :y1="seg.y1"
                    :x2="seg.x2"
                    :y2="seg.y2"
                    stroke="#333"
                    stroke-width="1"
                    vector-effect="non-scaling-stroke"
                  />
                  <circle
                    v-else-if="seg && seg.type === 'circle'"
                    :cx="seg.cx"
                    :cy="seg.cy"
                    :r="seg.r"
                    stroke="#333"
                    stroke-width="1"
                    fill="none"
                    vector-effect="non-scaling-stroke"
                  />
                  <polyline
                    v-else-if="seg && seg.type === 'polyline'"
                    :points="polylinePoints(seg.points)"
                    stroke="#333"
                    stroke-width="1"
                    fill="none"
                    vector-effect="non-scaling-stroke"
                  />
                </template>
              </g>
              <g class="hidden-edges" vector-effect="non-scaling-stroke">
                <template v-for="(seg, i) in pv.hiddenEdges" :key="`h${i}`">
                  <line
                    v-if="seg && seg.type === 'line'"
                    :x1="seg.x1"
                    :y1="seg.y1"
                    :x2="seg.x2"
                    :y2="seg.y2"
                    stroke="#999"
                    stroke-width="0.8"
                    stroke-dasharray="3,2"
                    vector-effect="non-scaling-stroke"
                  />
                </template>
              </g>
            </g>

            <!-- 标注命中层（仅标注工具激活时） -->
            <g v-if="activeTool" class="dim-hit-layer" pointer-events="stroke">
              <g v-for="pv in placedViews" :key="'hit-'+pv.id" :transform="`translate(${pv.x}, ${pv.y}) scale(${pv.scale})`">
                <template v-for="(seg, i) in pv.edges" :key="`dvh-${i}`">
                  <line v-if="seg.type === 'line' && activeTool !== 'diameter'" :x1="seg.x1" :y1="seg.y1" :x2="seg.x2" :y2="seg.y2" fill="none" vector-effect="non-scaling-stroke" class="dim-hit-line" :data-dim-view="pv.id" :data-dim-idx="i" :data-dim-type="'edges'" />
                  <polyline v-else-if="seg.type === 'polyline' && activeTool !== 'diameter'" :points="polylinePoints(seg.points)" fill="none" vector-effect="non-scaling-stroke" class="dim-hit-line" :data-dim-view="pv.id" :data-dim-idx="i" :data-dim-type="'edges'" />
                  <circle v-else-if="seg.type === 'circle' && activeTool === 'diameter'" :cx="seg.cx" :cy="seg.cy" :r="seg.r" fill="none" vector-effect="non-scaling-stroke" class="dim-hit-circle" :data-dim-view="pv.id" :data-dim-idx="i" :data-dim-type="'edges'" />
                </template>
                <template v-for="(seg, i) in pv.hiddenEdges" :key="`dvh-h-${i}`">
                  <line v-if="seg.type === 'line' && activeTool !== 'diameter'" :x1="seg.x1" :y1="seg.y1" :x2="seg.x2" :y2="seg.y2" fill="none" vector-effect="non-scaling-stroke" class="dim-hit-line" :data-dim-view="pv.id" :data-dim-idx="i" :data-dim-type="'hiddenEdges'" />
                  <polyline v-else-if="seg.type === 'polyline' && activeTool !== 'diameter'" :points="polylinePoints(seg.points)" fill="none" vector-effect="non-scaling-stroke" class="dim-hit-line" :data-dim-view="pv.id" :data-dim-idx="i" :data-dim-type="'hiddenEdges'" />
                  <circle v-else-if="seg.type === 'circle' && activeTool === 'diameter'" :cx="seg.cx" :cy="seg.cy" :r="seg.r" fill="none" vector-effect="non-scaling-stroke" class="dim-hit-circle" :data-dim-view="pv.id" :data-dim-idx="i" :data-dim-type="'hiddenEdges'" />
                </template>
              </g>
            </g>

            <!-- 标注高亮层（hover/选中边线） -->
            <g v-if="activeTool && dimHoveredEdge" class="dim-highlight" pointer-events="none">
              <g :transform="dimHoveredEdge.transform">
                <line v-if="dimHoveredEdge.seg.type === 'line'" :x1="dimHoveredEdge.seg.x1" :y1="dimHoveredEdge.seg.y1" :x2="dimHoveredEdge.seg.x2" :y2="dimHoveredEdge.seg.y2" class="dim-highlight-hover" />
                <circle v-else-if="dimHoveredEdge.seg.type === 'circle'" :cx="dimHoveredEdge.seg.cx" :cy="dimHoveredEdge.seg.cy" :r="dimHoveredEdge.seg.r" class="dim-highlight-hover" />
                <polyline v-else-if="dimHoveredEdge.seg.type === 'polyline'" :points="polylinePoints(dimHoveredEdge.seg.points)" class="dim-highlight-hover" />
              </g>
            </g>
            <g v-if="activeTool && dimFirstEdge" class="dim-highlight" pointer-events="none">
              <g :transform="dimFirstEdge.transform">
                <line v-if="dimFirstEdge.seg.type === 'line'" :x1="dimFirstEdge.seg.x1" :y1="dimFirstEdge.seg.y1" :x2="dimFirstEdge.seg.x2" :y2="dimFirstEdge.seg.y2" class="dim-highlight-selected" />
                <circle v-else-if="dimFirstEdge.seg.type === 'circle'" :cx="dimFirstEdge.seg.cx" :cy="dimFirstEdge.seg.cy" :r="dimFirstEdge.seg.r" class="dim-highlight-selected" />
                <polyline v-else-if="dimFirstEdge.seg.type === 'polyline'" :points="polylinePoints(dimFirstEdge.seg.points)" class="dim-highlight-selected" />
              </g>
            </g>

            <!-- 标注预览 -->
            <g v-if="dimPreview" class="dim-preview" :style="{ '--dimension-color': dimensionColor }" pointer-events="none">
              <template v-if="dimPreview.type === 'linear'">
                <line :x1="dimPreview.ext1.x" :y1="dimPreview.ext1.y" :x2="dimPreview.ext1End.x" :y2="dimPreview.ext1End.y" class="dim-ext-line" />
                <line :x1="dimPreview.ext2.x" :y1="dimPreview.ext2.y" :x2="dimPreview.ext2End.x" :y2="dimPreview.ext2End.y" class="dim-ext-line" />
                <line :x1="dimPreview.dimStart.x" :y1="dimPreview.dimStart.y" :x2="dimPreview.dimEnd.x" :y2="dimPreview.dimEnd.y" class="dim-line" />
                <polygon v-if="dimPreview.arrow1" :points="dimPreview.arrow1" class="dim-arrow" />
                <polygon v-if="dimPreview.arrow2" :points="dimPreview.arrow2" class="dim-arrow" />
                <text :x="dimPreview.textPos.x" :y="dimPreview.textPos.y" class="dim-text" text-anchor="middle" dominant-baseline="auto">{{ dimPreview.text }}</text>
              </template>
              <template v-if="dimPreview.type === 'diameter'">
                <line :x1="dimPreview.leaderStart.x" :y1="dimPreview.leaderStart.y" :x2="dimPreview.leaderEnd.x" :y2="dimPreview.leaderEnd.y" class="dim-line" />
                <polygon v-if="dimPreview.arrow" :points="dimPreview.arrow" class="dim-arrow" />
                <text :x="dimPreview.textPos.x" :y="dimPreview.textPos.y" class="dim-text" text-anchor="start" dominant-baseline="auto">{{ dimPreview.text }}</text>
              </template>
              <template v-if="dimPreview.type === 'angle'">
                <path :d="dimPreview.arcPath" class="dim-line" fill="none" />
                <polygon v-if="dimPreview.arrow1" :points="dimPreview.arrow1" class="dim-arrow" />
                <polygon v-if="dimPreview.arrow2" :points="dimPreview.arrow2" class="dim-arrow" />
                <text :x="dimPreview.textPos.x" :y="dimPreview.textPos.y" class="dim-text" text-anchor="middle" dominant-baseline="auto">{{ dimPreview.text }}</text>
              </template>
            </g>

            <!-- 已放置标注 -->
            <g class="dimensions-layer" pointer-events="stroke">
              <g v-for="dim in renderedDimensions" :key="dim.id" :class="['dimension-group', { 'dimension-selected': selectedDimId === dim.id }]" :style="{ '--dimension-color': dim.color }" @mousedown.stop="onDimMouseDown($event, dim)" @click.stop="selectDim(dim.id)">
                <!-- 线性标注 -->
                <template v-if="dim.type === 'linear'">
                  <line :x1="dim.ext1.x" :y1="dim.ext1.y" :x2="dim.ext1End.x" :y2="dim.ext1End.y" class="dim-ext-line" />
                  <line :x1="dim.ext2.x" :y1="dim.ext2.y" :x2="dim.ext2End.x" :y2="dim.ext2End.y" class="dim-ext-line" />
                  <line :x1="dim.dimStart.x" :y1="dim.dimStart.y" :x2="dim.dimEnd.x" :y2="dim.dimEnd.y" class="dim-line" />
                  <polygon v-if="dim.arrow1" :points="dim.arrow1" class="dim-arrow" />
                  <polygon v-if="dim.arrow2" :points="dim.arrow2" class="dim-arrow" />
                  <text :x="dim.textPos.x" :y="dim.textPos.y" class="dim-text" text-anchor="middle" dominant-baseline="auto">{{ dim.text }}</text>
                </template>
                <!-- 直径标注 -->
                <template v-if="dim.type === 'diameter'">
                  <line :x1="dim.leaderStart.x" :y1="dim.leaderStart.y" :x2="dim.leaderEnd.x" :y2="dim.leaderEnd.y" class="dim-line" />
                  <polygon v-if="dim.arrow" :points="dim.arrow" class="dim-arrow" />
                  <text :x="dim.textPos.x" :y="dim.textPos.y" class="dim-text" text-anchor="start" dominant-baseline="auto">{{ dim.text }}</text>
                </template>
                <!-- 角度标注 -->
                <template v-if="dim.type === 'angle'">
                  <path :d="dim.arcPath" class="dim-line" fill="none" />
                  <polygon v-if="dim.arrow1" :points="dim.arrow1" class="dim-arrow" />
                  <polygon v-if="dim.arrow2" :points="dim.arrow2" class="dim-arrow" />
                  <text :x="dim.textPos.x" :y="dim.textPos.y" class="dim-text" text-anchor="middle" dominant-baseline="auto">{{ dim.text }}</text>
                </template>
              </g>
            </g>

            <g
              v-if="draggingFromPalette && draggingView && dragPreviewPos"
              :transform="`translate(${dragPreviewPos.x}, ${dragPreviewPos.y}) scale(${dragPreviewPos.scale})`"
              class="palette-drag-preview"
            >
              <rect
                :x="dragPreviewPos.bbox.x - 4"
                :y="dragPreviewPos.bbox.y - 4"
                :width="dragPreviewPos.bbox.width + 8"
                :height="dragPreviewPos.bbox.height + 8"
                fill="rgba(64, 158, 255, 0.06)"
                stroke="#409eff"
                stroke-width="2"
                stroke-dasharray="4,2"
                vector-effect="non-scaling-stroke"
              />
              <template v-for="(seg, i) in draggingView.edges || []" :key="`preview-${i}`">
                <line
                  v-if="seg && seg.type === 'line'"
                  :x1="seg.x1"
                  :y1="seg.y1"
                  :x2="seg.x2"
                  :y2="seg.y2"
                  stroke="#409eff"
                  stroke-width="1"
                  vector-effect="non-scaling-stroke"
                />
                <circle
                  v-else-if="seg && seg.type === 'circle'"
                  :cx="seg.cx"
                  :cy="seg.cy"
                  :r="seg.r"
                  fill="none"
                  stroke="#409eff"
                  stroke-width="1"
                  vector-effect="non-scaling-stroke"
                />
                <polyline
                  v-else-if="seg && seg.type === 'polyline'"
                  :points="polylinePoints(seg.points)"
                  fill="none"
                  stroke="#409eff"
                  stroke-width="1"
                  vector-effect="non-scaling-stroke"
                />
              </template>
            </g>
          </svg>

          <div v-if="!viewsLoaded && !loadingViews" class="empty-state">
            <el-icon :size="48"><DocumentAdd /></el-icon>
            <p>选择型号并导入模型以开始</p>
            <p class="sub">导入后可从左侧拖拽视图到图纸</p>
          </div>
        </div>
      </section>

      <aside class="property-panel">
        <div class="panel-header">属性面板</div>

        <section v-if="selectedView" class="property-section">
          <div class="section-title">视图属性</div>
          <div class="prop-row">
            <span class="prop-label">名称</span>
            <span class="prop-value">{{ selectedView.label }}</span>
          </div>
          <div class="prop-row">
            <span class="prop-label">边数</span>
            <span class="prop-value">{{ selectedView.edges?.length || 0 }}</span>
          </div>
          <div class="prop-row stacked">
            <span class="prop-label">全局比例</span>
            <el-input-number :model-value="selectedView.scale" :min="0.1" :max="5" :step="0.1" size="small" class="prop-input" @update:model-value="onViewScaleChange" />
          </div>
          <div class="prop-row">
            <span class="prop-label">位置</span>
            <span class="prop-value">{{ Math.round(selectedView.x) }}, {{ Math.round(selectedView.y) }}</span>
          </div>
          <el-button size="small" type="danger" plain class="full-button" @click="deleteSelectedView">
            <el-icon><Delete /></el-icon>
            删除此视图
          </el-button>
        </section>

        <section v-else class="property-section muted-section">
          <div class="section-title">当前选择</div>
          <p>未选择对象</p>
        </section>

        <section class="property-section">
          <div class="section-title">图纸统计</div>
          <div class="stat-row"><span>已放置视图</span><span class="num">{{ placedViews.length }}</span></div>
          <div class="stat-row"><span>图纸尺寸</span><span class="num">{{ sheetWidth }}×{{ sheetHeight }}</span></div>
          <div class="stat-row"><span>模型尺寸</span><span class="num">{{ modelBbox.width }}×{{ modelBbox.height }}×{{ modelBbox.depth }}mm</span></div>
        </section>

        <section class="property-section document-json">
          <div class="section-title">工程图状态</div>
          <pre>{{ drawingDocumentPreview }}</pre>
        </section>
      </aside>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Upload, ZoomIn, ZoomOut, Delete, DocumentAdd, Loading } from '@element-plus/icons-vue'

const models = ref([])
const selectedModel = ref('')
const loadingViews = ref(false)
const viewsLoaded = ref(false)
const loadingText = ref('')
const error = ref('')
const lastElapsed = ref(null)
const modelBbox = ref({ width: 0, height: 0, depth: 0 })

const paletteViews = ref({})
const placedViews = ref([])
let viewIdCounter = 0
const selectedViewId = ref(null)

const sheetAreaRef = ref(null)
const svgRef = ref(null)
const sheetWidth = ref(1189)
const sheetHeight = ref(841)

const draggingFromPalette = ref(false)
const draggingView = ref(null)
const dragPreviewPos = ref(null)

let palettePointerStart = null
let pendingPalettePointer = null
let paletteAnimationFrame = 0
let movingView = null
let moveStartPos = null

// ===== 对齐分组（基于投影轴平行关系） =====
// 垂直对齐组：水平轴平行于 X 轴 → 拖拽时 X 中心对齐
const VERTICAL_ALIGN_GROUP_X = new Set(['front', 'back', 'top', 'bottom'])
// 垂直对齐组：水平轴平行于 Z 轴 → 拖拽时 X 中心对齐（缸体长轴方向）
const VERTICAL_ALIGN_GROUP_Z = new Set(['left', 'right', 'left_top'])
// 水平对齐组：垂直轴平行于 Y 轴 → 拖拽时 Y 中心对齐
const HORIZONTAL_ALIGN_GROUP_Y = new Set(['front', 'back', 'left', 'right'])

const ALIGN_SNAP_THRESHOLD = 8  // 吸附阈值（SVG 坐标 px）

const alignmentGuides = ref([])
const globalScale = ref(null)

// ===== 标注工具状态 =====
const activeTool = ref(null)  // null | 'linear' | 'diameter' | 'angle'
const dimHoveredEdge = ref(null)  // { seg, transform, viewId, idx, type }
const dimFirstEdge = ref(null)    // 第一选中边线
const dimPreview = ref(null)      // 当前预览标注
const dimensionColor = ref('#303133')
const dimensionColorPresets = ['#303133', '#409eff', '#67c23a', '#e6a23c', '#f56c6c']
const dimensions = ref([])        // 已放置标注
const selectedDimId = ref(null)   // 选中标注 id
const dimDragging = ref(null)     // { dim, offset, ... } 拖拽调整中
let dimIdCounter = 0

const standardViews = computed(() =>
  Object.entries(paletteViews.value)
    .filter(([_, v]) => v.group === 'standard')
    .map(([name, v]) => ({ name, ...v }))
)

const isometricViews = computed(() =>
  Object.entries(paletteViews.value)
    .filter(([_, v]) => v.group === 'isometric')
    .map(([name, v]) => ({ name, ...v }))
)

const selectedView = computed(() =>
  placedViews.value.find(v => v.id === selectedViewId.value)
)

const placedViewNames = computed(() =>
  new Set(placedViews.value.map(v => v.name))
)

const renderedDimensions = computed(() => dimensions.value
  .map(renderDimension)
  .filter(Boolean)
)

const drawingDocumentPreview = computed(() => JSON.stringify({
  sheet: {
    size: 'A0',
    width: sheetWidth.value,
    height: sheetHeight.value
  },
  model_id: selectedModel.value || null,
  views: placedViews.value.map(v => ({
    id: v.id,
    source_view: v.name,
    label: v.label,
    x: Math.round(v.x),
    y: Math.round(v.y),
    scale: Number(v.scale.toFixed(2))
  })),
  annotations: dimensions.value.map(dim => ({
    id: dim.id,
    type: dim.type,
    text: dim.text,
    refs: dim.refs,
    offset: dim.offset ?? null,
    radius: dim.radius ?? null,
    side: dim.side ?? null,
    leaderAngle: dim.leaderAngle ?? null
  }))
}, null, 2))

onMounted(async () => {
  await loadModelList()
  window.addEventListener('mousemove', onGlobalMouseMove)
  window.addEventListener('mouseup', onGlobalMouseUp)
  window.addEventListener('pointermove', onPalettePointerMove)
  window.addEventListener('pointerup', onPalettePointerUp)
  window.addEventListener('pointercancel', resetPaletteDrag)
  window.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onGlobalMouseMove)
  window.removeEventListener('mouseup', onGlobalMouseUp)
  window.removeEventListener('pointermove', onPalettePointerMove)
  window.removeEventListener('pointerup', onPalettePointerUp)
  window.removeEventListener('pointercancel', resetPaletteDrag)
  window.removeEventListener('keydown', onKeyDown)
  if (paletteAnimationFrame) cancelAnimationFrame(paletteAnimationFrame)
})

async function loadModelList() {
  try {
    const res = await fetch('/api/files')
    const data = await res.json()
    if (data.groups) {
      const all = []
      for (const g of data.groups) {
        const names = (g.files || []).map(f => f.name)
        if (names.includes('assembly.step') || names.includes('assembly.brep')) {
          all.push(g.model)
        }
      }
      models.value = all
    }
  } catch (e) {
    error.value = '获取型号列表失败'
  }
}

function onModelChange() {
  paletteViews.value = {}
  placedViews.value = []
  selectedViewId.value = null
  viewsLoaded.value = false
  error.value = ''
  lastElapsed.value = null
}

async function loadViewPalette() {
  if (!selectedModel.value) return
  loadingViews.value = true
  loadingText.value = '正在生成标准视图...'
  error.value = ''

  try {
    const res = await fetch(`/api/drawing-view-palette/${selectedModel.value}`)
    const data = await res.json()
    if (!data.ok) {
      error.value = data.error || '生成视图失败'
      return
    }
    paletteViews.value = data.views
    modelBbox.value = data.model_bbox
    viewsLoaded.value = true
    lastElapsed.value = data.elapsed
    loadingText.value = ''
    ElMessage.success(`已生成 ${Object.keys(data.views).length} 个视图, 耗时 ${data.elapsed}s`)
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loadingViews.value = false
    loadingText.value = ''
  }
}

function isPointerOverSheet(event) {
  const svg = svgRef.value
  if (!svg) return false
  const rect = svg.getBoundingClientRect()
  return event.clientX >= rect.left && event.clientX <= rect.right
    && event.clientY >= rect.top && event.clientY <= rect.bottom
}

function onPalettePointerDown(event, view) {
  if (event.button !== 0) return
  event.preventDefault()
  draggingView.value = view
  palettePointerStart = { x: event.clientX, y: event.clientY }
  pendingPalettePointer = event
}

function updatePalettePreview() {
  paletteAnimationFrame = 0
  const event = pendingPalettePointer
  pendingPalettePointer = null
  if (!event || !draggingView.value) return

  if (!draggingFromPalette.value) {
    const dx = event.clientX - palettePointerStart.x
    const dy = event.clientY - palettePointerStart.y
    if (Math.hypot(dx, dy) < 4) return
    draggingFromPalette.value = true
    document.body.classList.add('palette-pointer-dragging')
  }

  if (!isPointerOverSheet(event)) {
    dragPreviewPos.value = null
    return
  }
  const point = getSvgPoint(event)
  if (point) dragPreviewPos.value = getCenteredViewPlacement(draggingView.value, point, globalScale.value ?? getInitialViewScale(draggingView.value))
}

function onPalettePointerMove(event) {
  if (!draggingView.value || !palettePointerStart) return
  event.preventDefault()
  pendingPalettePointer = event
  if (!paletteAnimationFrame) {
    paletteAnimationFrame = requestAnimationFrame(updatePalettePreview)
  }
}

function onPalettePointerUp(event) {
  if (!draggingView.value || !palettePointerStart) return
  const view = draggingView.value
  const wasDragging = draggingFromPalette.value

  if (wasDragging && isPointerOverSheet(event)) {
    // 唯一性检查：拖拽放置前
    if (!placedViews.value.some(pv => pv.name === view.name)) {
      const point = getSvgPoint(event)
      if (point) {
        const placement = getCenteredViewPlacement(view, point, globalScale.value ?? getInitialViewScale(view))
        placeView(view, placement.x, placement.y, placement.scale)
      }
    } else {
      ElMessage.warning(`「${view.label}」已存在于图纸中`)
    }
  } else if (!wasDragging) {
    onPaletteClick(view)
  }
  resetPaletteDrag()
}

function getSvgPoint(event) {
  const svg = svgRef.value
  if (!svg) return null
  const ctm = svg.getScreenCTM()
  if (!ctm) return null
  const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm.inverse())
  return { x: point.x, y: point.y }
}

function getCenteredViewPlacement(view, point, scale = getInitialViewScale(view)) {
  const bbox = computeContentBBox(view)
  return {
    x: point.x - (bbox.x + bbox.width / 2) * scale,
    y: point.y - (bbox.y + bbox.height / 2) * scale,
    scale,
    bbox
  }
}

function onPaletteClick(view) {
  // 首次放置时初始化全局缩放
  if (globalScale.value == null) {
    globalScale.value = getInitialViewScale(view)
  }
  const placement = getCenteredViewPlacement(view, {
    x: sheetWidth.value / 2,
    y: sheetHeight.value / 2
  }, globalScale.value)
  placeView(view, placement.x, placement.y, placement.scale)
}

function resetPaletteDrag() {
  if (paletteAnimationFrame) cancelAnimationFrame(paletteAnimationFrame)
  paletteAnimationFrame = 0
  pendingPalettePointer = null
  palettePointerStart = null
  draggingFromPalette.value = false
  draggingView.value = null
  dragPreviewPos.value = null
  document.body.classList.remove('palette-pointer-dragging')
}

function normalizeViewBBox(view) {
  return view.bbox || { x: 0, y: 0, width: 400, height: 300 }
}

function getInitialViewScale(view) {
  const bbox = computeContentBBox(view)
  const targetLongEdge = 260
  const longEdge = Math.max(bbox.width || 1, bbox.height || 1)
  return Math.max(0.35, Math.min(2.4, targetLongEdge / longEdge))
}

function computeContentBBox(view) {
  const points = []
  const collectPoint = (x, y) => {
    if (Number.isFinite(x) && Number.isFinite(y)) {
      points.push([x, y])
    }
  }

  for (const seg of [...(view.edges || []), ...(view.hidden_edges || [])]) {
    if (!seg || !seg.type) continue
    if (seg.type === 'line') {
      collectPoint(seg.x1, seg.y1)
      collectPoint(seg.x2, seg.y2)
    } else if (seg.type === 'circle') {
      collectPoint(seg.cx - seg.r, seg.cy - seg.r)
      collectPoint(seg.cx + seg.r, seg.cy + seg.r)
    } else if (seg.type === 'polyline') {
      for (const p of seg.points || []) {
        collectPoint(p[0], p[1])
      }
    }
  }

  if (points.length === 0) {
    return normalizeViewBBox(view)
  }

  const xs = points.map(p => p[0])
  const ys = points.map(p => p[1])
  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  const maxX = Math.max(...xs)
  const maxY = Math.max(...ys)
  return {
    x: minX,
    y: minY,
    width: Math.max(1, maxX - minX),
    height: Math.max(1, maxY - minY)
  }
}

// ===== 对齐检测辅助函数 =====
function getViewCenterInSheet(pv) {
  return {
    x: pv.x + (pv.contentBBox.x + pv.contentBBox.width / 2) * pv.scale,
    y: pv.y + (pv.contentBBox.y + pv.contentBBox.height / 2) * pv.scale
  }
}

function detectAlignment(centerX, centerY, skipId) {
  const guides = []
  let snapDx = 0, snapDy = 0
  let bestDistX = Infinity, bestDistY = Infinity

  for (const pv of placedViews.value) {
    if (pv.id === skipId) continue
    const otherCenter = getViewCenterInSheet(pv)

    // 垂直对齐线（X 中心对齐）— 同属垂直对齐组的视图
    if (VERTICAL_ALIGN_GROUP_X.has(pv.name) || VERTICAL_ALIGN_GROUP_Z.has(pv.name)) {
      const dist = Math.abs(centerX - otherCenter.x)
      if (dist < ALIGN_SNAP_THRESHOLD && dist < bestDistX) {
        bestDistX = dist
        snapDx = otherCenter.x - centerX
        guides.push({ type: 'vertical', pos: otherCenter.x })
      }
    }

    // 水平对齐线（Y 中心对齐）— 同属水平对齐组的视图
    if (HORIZONTAL_ALIGN_GROUP_Y.has(pv.name)) {
      const dist = Math.abs(centerY - otherCenter.y)
      if (dist < ALIGN_SNAP_THRESHOLD && dist < bestDistY) {
        bestDistY = dist
        snapDy = otherCenter.y - centerY
        guides.push({ type: 'horizontal', pos: otherCenter.y })
      }
    }
  }

  return { guides, snapDx, snapDy }
}

function placeView(view, x, y, scale) {
  // 唯一性约束：同一视图只能放置一次
  if (placedViews.value.some(pv => pv.name === view.name)) {
    ElMessage.warning(`「${view.label}」已存在于图纸中`)
    return
  }
  // 始终使用全局缩放比例（首次放置时自动计算）
  if (globalScale.value == null) {
    globalScale.value = getInitialViewScale(view)
  }
  scale = globalScale.value
  const bbox = normalizeViewBBox(view)
  const edges = (view.edges || []).filter(s => s && s.type)
  const hiddenEdges = (view.hidden_edges || []).filter(s => s && s.type)
  const contentBBox = computeContentBBox({ ...view, edges, hidden_edges: hiddenEdges })
  const newView = {
    id: `view_${++viewIdCounter}`,
    name: view.name,
    label: view.label,
    group: view.group,
    edges,
    hiddenEdges,
    bbox,
    contentBBox,
    x,
    y,
    scale
  }
  placedViews.value.push(newView)
  selectedViewId.value = newView.id
}

function selectView(id) {
  selectedViewId.value = id
}

function onViewMouseDown(event, view) {
  // 标注工具激活时禁止拖动视图
  if (activeTool.value) return
  selectedViewId.value = view.id
  movingView = view
  moveStartPos = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y }
}

function onSvgMouseDown(event) {
  // 标注工具激活：优先处理边线选择
  if (activeTool.value) {
    const target = event.target
    const hit = target && target.closest ? target.closest('[data-dim-view]') : null
    if (hit) {
      onDimEdgeSelect(hit)
      return
    }
    // 点击空白区域：取消当前选择
    dimFirstEdge.value = null
    dimPreview.value = null
    selectedDimId.value = null
    return
  }
  // 普通模式：点击空白处取消选中
  if (event.target.tagName === 'rect' || event.target.tagName === 'svg') {
    selectedViewId.value = null
    selectedDimId.value = null
  }
}

function onSvgMouseMove(event) {
  if (!activeTool.value) return
  // 命中检测：通过透明粗描边命中层
  const target = document.elementFromPoint(event.clientX, event.clientY)
  const hit = target && target.closest ? target.closest('[data-dim-view]') : null
  if (hit) {
    const viewId = hit.dataset.dimView
    const idx = parseInt(hit.dataset.dimIdx, 10)
    const type = hit.dataset.dimType
    const seg = getEdgeByRef(viewId, idx, type)
    const view = placedViews.value.find(v => v.id === viewId)
    if (seg && view) {
      const hover = makeEdgeRef(view, idx, type, seg)
      // 引用不同则更新（避免重复 set）
      const cur = dimHoveredEdge.value
      if (!cur || cur.viewId !== viewId || cur.idx !== idx || cur.type !== type) {
        dimHoveredEdge.value = hover
      }
      // 更新预览位置（用于线性/直径定位）
      updateDimPreviewAt(event)
      return
    }
  }
  if (dimHoveredEdge.value) dimHoveredEdge.value = null
  updateDimPreviewAt(event)
}

function onGlobalMouseMove(event) {
  if (dimDragging.value) {
    updateDimDrag(event)
    return
  }
  if (!movingView) return
  const dx = event.clientX - moveStartPos.x
  const dy = event.clientY - moveStartPos.y
  let newX = moveStartPos.vx + dx
  let newY = moveStartPos.vy + dy

  // 计算当前视图中心并检测对齐
  const center = {
    x: newX + (movingView.contentBBox.x + movingView.contentBBox.width / 2) * movingView.scale,
    y: newY + (movingView.contentBBox.y + movingView.contentBBox.height / 2) * movingView.scale
  }
  const alignment = detectAlignment(center.x, center.y, movingView.id)
  newX += alignment.snapDx
  newY += alignment.snapDy
  alignmentGuides.value = alignment.guides

  movingView.x = newX
  movingView.y = newY
}

function deleteSelectedView() {
  if (!selectedViewId.value) return
  const deletedViewId = selectedViewId.value
  placedViews.value = placedViews.value.filter(v => v.id !== deletedViewId)
  dimensions.value = dimensions.value.filter(dim => !dimensionUsesView(dim, deletedViewId))
  selectedViewId.value = null
  selectedDimId.value = null
  dimHoveredEdge.value = null
  dimFirstEdge.value = null
  dimPreview.value = null
}

function clearPlacedViews() {
  placedViews.value = []
  dimensions.value = []
  selectedViewId.value = null
  selectedDimId.value = null
  globalScale.value = null
  alignmentGuides.value = []
  dimHoveredEdge.value = null
  dimFirstEdge.value = null
  dimPreview.value = null
}

function zoomViewAroundCenter(view, newScale) {
  const bbox = view.contentBBox
  const cx = bbox.x + bbox.width / 2
  const cy = bbox.y + bbox.height / 2
  const oldScale = view.scale
  view.x = view.x + cx * (oldScale - newScale)
  view.y = view.y + cy * (oldScale - newScale)
  view.scale = newScale
}

function onViewScaleChange(newScale) {
  // 全局缩放：修改所有视图的比例
  const clamped = Math.max(0.1, Math.min(5, newScale))
  globalScale.value = clamped
  for (const v of placedViews.value) {
    zoomViewAroundCenter(v, clamped)
  }
}

function zoomCanvas(factor) {
  const newScale = Math.max(0.1, Math.min(5, (globalScale.value || 1) * factor))
  globalScale.value = newScale
  for (const v of placedViews.value) {
    zoomViewAroundCenter(v, newScale)
  }
}

function resetCanvas() {
  // 计算适应所有已放置视图的统一缩放
  if (placedViews.value.length === 0) return
  let maxExtent = 0
  for (const v of placedViews.value) {
    const extent = Math.max(v.contentBBox.width, v.contentBBox.height)
    maxExtent = Math.max(maxExtent, extent)
  }
  if (maxExtent < 0.01) return
  const targetLongEdge = Math.min(sheetWidth.value * 0.6, sheetHeight.value * 0.6)
  const newScale = Math.max(0.1, Math.min(5, targetLongEdge / maxExtent))
  globalScale.value = newScale
  for (const v of placedViews.value) {
    zoomViewAroundCenter(v, newScale)
  }
}

function polylinePoints(points) {
  return points.map(p => `${p[0]},${p[1]}`).join(' ')
}

/**
 * 将 line/polyline 规整为可标注的两点线段。
 * 后端对 BSpline 面的 HLR 剪影线会离散为 polyline(气缸等模型占大多数),
 * 视觉上近似直线;此处检测其是否近似直线:
 *   - 是 → 返回 {x1,y1,x2,y2,meta} 供几何计算与标注
 *   - 否(真曲线) → 返回 null，不做直线类标注
 */
function toLineSeg(seg) {
  if (!seg) return null
  if (seg.type === 'line') {
    return { x1: seg.x1, y1: seg.y1, x2: seg.x2, y2: seg.y2, meta: seg.meta }
  }
  if (seg.type === 'polyline' && seg.points && seg.points.length >= 2) {
    const pts = seg.points
    const x1 = pts[0][0], y1 = pts[0][1]
    const x2 = pts[pts.length - 1][0], y2 = pts[pts.length - 1][1]
    const len = Math.hypot(x2 - x1, y2 - y1)
    if (len < 0.01) return null
    // 所有点到首尾连线的最大法向偏差
    let maxDev = 0
    for (let i = 1; i < pts.length - 1; i++) {
      const px = pts[i][0], py = pts[i][1]
      const cross = Math.abs((x2 - x1) * (y1 - py) - (x1 - px) * (y2 - y1))
      maxDev = Math.max(maxDev, cross / len)
    }
    // 偏差超过直线长度的 1.5% 视为曲线，不做直线标注
    if (maxDev > 0.015 * len) return null
    return { x1, y1, x2, y2, meta: seg.meta }
  }
  return null
}

// ===== 标注工具核心函数 =====

/** 工具切换 */
function toggleTool(tool) {
  if (activeTool.value === tool) {
    activeTool.value = null
    dimHoveredEdge.value = null
    dimFirstEdge.value = null
    dimPreview.value = null
  } else {
    activeTool.value = tool
    dimHoveredEdge.value = null
    dimFirstEdge.value = null
    dimPreview.value = null
    selectedDimId.value = null
  }
}

/** 根据引用获取边线数据 */
function getEdgeByRef(viewId, idx, type) {
  const view = placedViews.value.find(v => v.id === viewId)
  if (!view) return null
  const list = type === 'hiddenEdges' ? view.hiddenEdges : view.edges
  return list && list[idx] ? list[idx] : null
}

/** 视图局部坐标 → 图纸坐标 */
function getSheetPoint(view, lx, ly) {
  return { x: view.x + lx * view.scale, y: view.y + ly * view.scale }
}

function getSvgMousePoint(event) {
  const svg = svgRef.value
  if (!svg) return null
  const ctm = svg.getScreenCTM()
  if (!ctm) return null
  const pt = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm.inverse())
  return { x: pt.x, y: pt.y }
}

function makeEdgeRef(view, idx, type, seg = null) {
  if (!view) return null
  const edge = seg || getEdgeByRef(view.id, idx, type)
  if (!edge) return null
  return {
    seg: edge,
    view,
    viewId: view.id,
    idx,
    type,
    transform: `translate(${view.x}, ${view.y}) scale(${view.scale})`
  }
}

function resolveDimRef(ref) {
  if (!ref) return null
  const view = placedViews.value.find(v => v.id === ref.viewId)
  if (!view) return null
  return makeEdgeRef(view, ref.idx, ref.type)
}

function dimensionUsesView(dim, viewId) {
  return (dim.refs || []).some(ref => ref.viewId === viewId)
}

/** 箭头三角形（图纸坐标） */
function computeArrowTip(end, dir, size) {
  const perp = { x: -dir.y, y: dir.x }
  const pt = size || 8
  const w = pt * 0.4
  return [
    `${end.x},${end.y}`,
    `${end.x - dir.x * pt + perp.x * w},${end.y - dir.y * pt + perp.y * w}`,
    `${end.x - dir.x * pt - perp.x * w},${end.y - dir.y * pt - perp.y * w}`
  ].join(' ')
}

/** 边线选择处理 */
function onDimEdgeSelect(hitEl) {
  const viewId = hitEl.dataset.dimView
  const idx = parseInt(hitEl.dataset.dimIdx, 10)
  const type = hitEl.dataset.dimType
  const seg = getEdgeByRef(viewId, idx, type)
  if (!seg) return
  const view = placedViews.value.find(v => v.id === viewId)
  if (!view) return
  const edgeRef = makeEdgeRef(view, idx, type, seg)
  if (!edgeRef) return

  if (activeTool.value === 'diameter') {
    // 直径：点击即放置（圆边线）
    if (seg.type === 'circle') {
      placeDiameterDim(edgeRef, dimPreview.value?.leaderAngle)
    }
    return
  }

  if (activeTool.value === 'linear') {
    // 线性：点击边线1 → 点击边线2（平行）或再点击同一位置放置
    if (!dimFirstEdge.value) {
      dimFirstEdge.value = edgeRef
      return
    }
    // 已有第一边线
    const first = dimFirstEdge.value
    if (first.viewId === viewId && first.idx === idx && first.type === type) {
      // 同一根边线 → 单边对齐标注
      const offset = dimPreview.value?.offset ?? getLinearOffsetFromMouse(first, getSvgMousePoint(event))
      placeLinearDimSingle(first, offset)
      dimFirstEdge.value = null
      dimHoveredEdge.value = null
      dimPreview.value = null
      activeTool.value = null
      return
    }
    // 平行检测
    if (isParallel(first.seg, seg)) {
      placeLinearDimParallel(first, edgeRef, dimPreview.value?.offset)
      dimFirstEdge.value = null
      dimPreview.value = null
      return
    }
    // 不平行：提示
    ElMessage.warning('线性标注需要选择平行边线')
    return
  }

  if (activeTool.value === 'angle') {
    // 角度：点击边线1 → 点击边线2（不平行）
    if (!dimFirstEdge.value) {
      dimFirstEdge.value = edgeRef
      return
    }
    const first = dimFirstEdge.value
    if (first.viewId === viewId && first.idx === idx && first.type === type) {
      return // 同一根边线，忽略
    }
    if (isParallel(first.seg, seg)) {
      ElMessage.warning('角度标注需要选择不平行边线')
      return
    }
    // 放置角度
    placeAngleDim(first, edgeRef, dimPreview.value?.radius)
    dimFirstEdge.value = null
    dimPreview.value = null
  }
}

/** 预览更新（跟随鼠标） */
function updateDimPreviewAt(event) {
  if (!activeTool.value) return
  const mousePos = getSvgMousePoint(event)
  if (!mousePos) return

  if (activeTool.value === 'linear') {
    // 如果有第一边线，边线类型需要按鼠标位置预览
    if (dimFirstEdge.value) {
      const first = dimFirstEdge.value
      // 检测鼠标是否在另一条平行边线上
      const hit = dimHoveredEdge.value
      if (hit && (hit.viewId !== first.viewId || hit.idx !== first.idx)) {
        const seg2 = getEdgeByRef(hit.viewId, hit.idx, hit.type)
        if (seg2 && isParallel(first.seg, seg2)) {
          dimPreview.value = buildLinearParallelPreview(first, hit, mousePos)
          return
        }
      }
      // 默认：单边对齐标注
      dimPreview.value = buildLinearSinglePreview(first, mousePos)
      return
    }
    // 无第一边线：跟随光标预览最近边线
    if (dimHoveredEdge.value) {
      const seg = dimHoveredEdge.value.seg
      if (toLineSeg(seg)) {
        dimPreview.value = buildLinearSinglePreview(dimHoveredEdge.value, mousePos)
      }
    }
    return
  }

  if (activeTool.value === 'diameter') {
    // 直径预览：跟随光标
    if (dimHoveredEdge.value && dimHoveredEdge.value.seg.type === 'circle') {
      dimPreview.value = buildDiameterPreview(dimHoveredEdge.value, mousePos)
    }
    return
  }

  if (activeTool.value === 'angle') {
    if (dimFirstEdge.value) {
      const first = dimFirstEdge.value
      if (dimHoveredEdge.value) {
        const seg2 = getEdgeByRef(dimHoveredEdge.value.viewId, dimHoveredEdge.value.idx, dimHoveredEdge.value.type)
        if (seg2 && !isParallel(first.seg, seg2)) {
          dimPreview.value = buildAnglePreview(first, dimHoveredEdge.value, mousePos)
          return
        }
      }
    }
    if (dimHoveredEdge.value && toLineSeg(dimHoveredEdge.value.seg)) {
      // 单选线预览：显示角度候选
      dimPreview.value = null
    }
  }
}

// ===== 几何工具 =====

/** 判断两条线段是否平行（角度差 < 5°），line/polyline 视为直线 */
function isParallel(seg1, seg2) {
  const l1 = toLineSeg(seg1)
  const l2 = toLineSeg(seg2)
  if (!l1 || !l2) return false
  const dx1 = l1.x2 - l1.x1, dy1 = l1.y2 - l1.y1
  const dx2 = l2.x2 - l2.x1, dy2 = l2.y2 - l2.y1
  const len1 = Math.hypot(dx1, dy1), len2 = Math.hypot(dx2, dy2)
  if (len1 < 0.01 || len2 < 0.01) return false
  const dot = (dx1 * dx2 + dy1 * dy2) / (len1 * len2)
  return Math.abs(dot) > 0.996  // ≈ 5°
}

/** 点到线段的最近点 */
function closestPointOnLine(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1
  const lenSq = dx * dx + dy * dy
  if (lenSq < 0.01) return { x: x1, y: y1, t: 0 }
  let t = ((px - x1) * dx + (py - y1) * dy) / lenSq
  t = Math.max(0, Math.min(1, t))
  return { x: x1 + t * dx, y: y1 + t * dy, t }
}

function lineBasis(p1, p2) {
  const dx = p2.x - p1.x
  const dy = p2.y - p1.y
  const len = Math.hypot(dx, dy)
  if (len < 0.5) return null
  const unit = { x: dx / len, y: dy / len }
  return { unit, perp: { x: -unit.y, y: unit.x }, len }
}

function offsetPoint(point, dir, distance) {
  return { x: point.x + dir.x * distance, y: point.y + dir.y * distance }
}

function signedDistanceToLine(point, linePoint, normal) {
  return (point.x - linePoint.x) * normal.x + (point.y - linePoint.y) * normal.y
}

// ===== 线性标注构建 =====

function edgeRefData(edgeRef) {
  return { viewId: edgeRef.viewId, idx: edgeRef.idx, type: edgeRef.type }
}

function formatMm(value) {
  return `${Number(value || 0).toFixed(1).replace(/\.0$/, '')}mm`
}

function formatDeg(value) {
  return `${Number(value || 0).toFixed(1).replace(/\.0$/, '')}°`
}

function getViewMmScale(view) {
  return view.bbox && view.bbox.scale ? view.bbox.scale : 1
}

function buildLinearSinglePreview(edgeRef, mousePos) {
  const offset = getLinearOffsetFromMouse(edgeRef, mousePos)
  return buildLinearSingleGeometry(edgeRef, offset)
}

function getLinearOffsetFromMouse(edgeRef, mousePos) {
  if (!edgeRef) return 50
  const { seg, view } = edgeRef
  const line = toLineSeg(seg)
  if (!line || !view || !mousePos) return 50
  const p1 = getSheetPoint(view, line.x1, line.y1)
  const p2 = getSheetPoint(view, line.x2, line.y2)
  const dir = lineBasis(p1, p2)
  if (!dir) return 50
  const mid = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 }
  const raw = (mousePos.x - mid.x) * dir.perp.x + (mousePos.y - mid.y) * dir.perp.y
  return Math.max(20, Math.abs(raw)) * (raw >= 0 ? 1 : -1)
}

function buildLinearSingleGeometry(edgeRef, offset = 50) {
  if (!edgeRef) return null
  const { seg, view } = edgeRef
  const line = toLineSeg(seg)
  if (!line || !view) return null
  const p1 = getSheetPoint(view, line.x1, line.y1)
  const p2 = getSheetPoint(view, line.x2, line.y2)
  const dir = lineBasis(p1, p2)
  if (!dir) return null
  const extEnd1 = offsetPoint(p1, dir.perp, offset)
  const extEnd2 = offsetPoint(p2, dir.perp, offset)
  const mmVal = line.meta && line.meta.length ? line.meta.length : Math.hypot(p2.x - p1.x, p2.y - p1.y) / (view.scale * getViewMmScale(view))
  return {
    type: 'linear',
    mode: 'single',
    refs: [edgeRefData(edgeRef)],
    offset,
    ext1: p1,
    ext1End: extEnd1,
    ext2: p2,
    ext2End: extEnd2,
    dimStart: extEnd1,
    dimEnd: extEnd2,
    arrow1: computeArrowTip(extEnd1, dir.unit),
    arrow2: computeArrowTip(extEnd2, { x: -dir.unit.x, y: -dir.unit.y }),
    textPos: { x: (extEnd1.x + extEnd2.x) / 2, y: (extEnd1.y + extEnd2.y) / 2 - 10 },
    text: formatMm(mmVal)
  }
}

function buildLinearParallelPreview(edgeRef1, edgeRef2, mousePos) {
  const offset = getParallelOffsetFromMouse(edgeRef1, mousePos)
  return buildLinearParallelGeometry(edgeRef1, edgeRef2, offset)
}

function getParallelOffsetFromMouse(edgeRef, mousePos) {
  if (!edgeRef) return 50
  const { seg, view } = edgeRef
  const line = toLineSeg(seg)
  if (!line || !view || !mousePos) return 50
  const p1 = getSheetPoint(view, line.x1, line.y1)
  const p2 = getSheetPoint(view, line.x2, line.y2)
  const dir = lineBasis(p1, p2)
  if (!dir) return 50
  const raw = signedDistanceToLine(mousePos, p1, dir.unit)
  return Math.max(20, Math.abs(raw)) * (raw >= 0 ? 1 : -1)
}

function buildLinearParallelGeometry(edgeRef1, edgeRef2, offset = 50) {
  if (!edgeRef1 || !edgeRef2) return null
  const { seg: seg1, view: view1 } = edgeRef1
  const { seg: seg2, view: view2 } = edgeRef2
  const line1 = toLineSeg(seg1)
  const line2 = toLineSeg(seg2)
  if (!line1 || !line2) return null
  const p1 = getSheetPoint(view1, line1.x1, line1.y1)
  const p2 = getSheetPoint(view1, line1.x2, line1.y2)
  const q1 = getSheetPoint(view2, line2.x1, line2.y1)
  const q2 = getSheetPoint(view2, line2.x2, line2.y2)
  const basis = lineBasis(p1, p2)
  if (!basis) return null
  let normal = basis.perp
  let distance = signedDistanceToLine(q1, p1, normal)
  if (distance < 0) {
    normal = { x: -normal.x, y: -normal.y }
    distance = -distance
  }
  if (distance < 0.5) return null
  const start = closestPointOnLine(q1.x, q1.y, p1.x, p1.y, p2.x, p2.y)
  const end = offsetPoint(start, normal, distance)
  const dimBase = offsetPoint(start, basis.unit, offset)
  const dimEnd = offsetPoint(dimBase, normal, distance)
  const ext1End = dimBase
  const ext2End = dimEnd
  const mmVal = distance / (view1.scale * getViewMmScale(view1))
  return {
    type: 'linear',
    mode: 'parallel',
    refs: [edgeRefData(edgeRef1), edgeRefData(edgeRef2)],
    offset,
    ext1: start,
    ext1End,
    ext2: end,
    ext2End,
    dimStart: ext1End,
    dimEnd: ext2End,
    arrow1: computeArrowTip(ext1End, normal),
    arrow2: computeArrowTip(ext2End, { x: -normal.x, y: -normal.y }),
    textPos: { x: (ext1End.x + ext2End.x) / 2 + basis.unit.x * 10, y: (ext1End.y + ext2End.y) / 2 + basis.unit.y * 10 },
    text: formatMm(mmVal)
  }
}

/** 放置单边线性标注 */
function placeLinearDimSingle(edgeRef, offset = 50) {
  const geometry = buildLinearSingleGeometry(edgeRef, offset)
  if (!geometry) return
  const id = `dim_${++dimIdCounter}`
  dimensions.value.push({
    id,
    type: 'linear',
    mode: 'single',
    refs: [edgeRefData(edgeRef)],
    offset: geometry.offset,
    color: dimensionColor.value,
    text: geometry.text
  })
  selectedDimId.value = id
}

/** 放置平行线间距标注 */
function placeLinearDimParallel(edgeRef1, edgeRef2, offset = 50) {
  const geometry = buildLinearParallelGeometry(edgeRef1, edgeRef2, offset)
  if (!geometry) return
  const id = `dim_${++dimIdCounter}`
  dimensions.value.push({
    id,
    type: 'linear',
    mode: 'parallel',
    refs: [edgeRefData(edgeRef1), edgeRefData(edgeRef2)],
    offset: geometry.offset,
    color: dimensionColor.value,
    text: geometry.text
  })
  selectedDimId.value = id
}

// ===== 直径标注 =====

function buildDiameterPreview(edgeRef, mousePos) {
  const { seg, view } = edgeRef
  if (seg.type !== 'circle' || !view || !mousePos) return null
  const cx = view.x + seg.cx * view.scale
  const cy = view.y + seg.cy * view.scale
  const angle = Math.atan2(mousePos.y - cy, mousePos.x - cx)
  return buildDiameterGeometry(edgeRef, angle)
}

function placeDiameterDim(edgeRef, leaderAngle = -Math.PI / 4) {
  const geometry = buildDiameterGeometry(edgeRef, leaderAngle)
  if (!geometry) return
  const id = `dim_${++dimIdCounter}`
  dimensions.value.push({
    id,
    type: 'diameter',
    refs: [edgeRefData(edgeRef)],
    leaderAngle: geometry.leaderAngle,
    color: dimensionColor.value,
    text: geometry.text
  })
  selectedDimId.value = id
}

function buildDiameterGeometry(edgeRef, angle = -Math.PI / 4) {
  if (!edgeRef) return null
  const { seg, view } = edgeRef
  if (seg.type !== 'circle' || !view) return null
  const cx = view.x + seg.cx * view.scale
  const cy = view.y + seg.cy * view.scale
  const r = seg.r * view.scale
  const dir = { x: Math.cos(angle), y: Math.sin(angle) }
  const edgePt = { x: cx + dir.x * r, y: cy + dir.y * r }
  const textPos = { x: cx + dir.x * (r + 30), y: cy + dir.y * (r + 30) }
  const mmVal = seg.meta && seg.meta.radius ? seg.meta.radius * 2 : (seg.r * 2) / getViewMmScale(view)
  return {
    type: 'diameter',
    refs: [edgeRefData(edgeRef)],
    leaderAngle: angle,
    leaderStart: textPos,
    leaderEnd: edgePt,
    arrow: computeArrowTip(edgePt, dir),
    textPos,
    text: `ø${formatMm(mmVal)}`
  }
}

// ===== 角度标注 =====

function buildAnglePreview(edgeRef1, edgeRef2, mousePos) {
  const base = buildAngleGeometry(edgeRef1, edgeRef2, 40)
  if (!base || !mousePos) return base
  const radius = Math.max(15, Math.min(200, Math.hypot(mousePos.x - base.inter.x, mousePos.y - base.inter.y)))
  return buildAngleGeometry(edgeRef1, edgeRef2, radius)
}

function buildAngleGeometry(edgeRef1, edgeRef2, radius = 40) {
  if (!edgeRef1 || !edgeRef2) return null
  const { seg: seg1, view: view1 } = edgeRef1
  const { seg: seg2, view: view2 } = edgeRef2
  const line1 = toLineSeg(seg1)
  const line2 = toLineSeg(seg2)
  if (!line1 || !line2) return null
  const p1 = getSheetPoint(view1, line1.x1, line1.y1)
  const p2 = getSheetPoint(view1, line1.x2, line1.y2)
  const q1 = getSheetPoint(view2, line2.x1, line2.y1)
  const q2 = getSheetPoint(view2, line2.x2, line2.y2)
  const inter = lineIntersection(p1, p2, q1, q2)
  if (!inter) return null
  const dir1 = lineBasis(inter, farthestEndpointFrom(inter, p1, p2))
  const dir2 = lineBasis(inter, farthestEndpointFrom(inter, q1, q2))
  if (!dir1 || !dir2) return null
  let startAngle = Math.atan2(dir1.unit.y, dir1.unit.x)
  let endAngle = Math.atan2(dir2.unit.y, dir2.unit.x)
  while (endAngle < startAngle) endAngle += Math.PI * 2
  if (endAngle - startAngle > Math.PI) {
    const temp = startAngle
    startAngle = endAngle
    endAngle = temp + Math.PI * 2
  }
  const sweep = endAngle - startAngle
  const angle = Math.min(sweep, Math.PI * 2 - sweep)
  const arrowAng1 = startAngle + sweep * 0.05
  const arrowAng2 = endAngle - sweep * 0.05
  const arrowP1 = { x: inter.x + Math.cos(arrowAng1) * radius, y: inter.y + Math.sin(arrowAng1) * radius }
  const arrowP2 = { x: inter.x + Math.cos(arrowAng2) * radius, y: inter.y + Math.sin(arrowAng2) * radius }
  const tan1 = { x: -Math.sin(arrowAng1), y: Math.cos(arrowAng1) }
  const tan2 = { x: -Math.sin(arrowAng2), y: Math.cos(arrowAng2) }
  const midAngle = startAngle + sweep / 2
  return {
    type: 'angle',
    refs: [edgeRefData(edgeRef1), edgeRefData(edgeRef2)],
    inter,
    radius,
    startAngle,
    endAngle,
    arcPath: buildArcPath(inter.x, inter.y, radius, startAngle, endAngle),
    arrow1: computeArrowTip(arrowP1, tan1, 6),
    arrow2: computeArrowTip(arrowP2, { x: -tan2.x, y: -tan2.y }, 6),
    textPos: { x: inter.x + Math.cos(midAngle) * (radius + 18), y: inter.y + Math.sin(midAngle) * (radius + 18) },
    text: formatDeg(angle * 180 / Math.PI)
  }
}

function placeAngleDim(edgeRef1, edgeRef2, radius = 40) {
  const geometry = buildAngleGeometry(edgeRef1, edgeRef2, radius)
  if (!geometry) return
  const id = `dim_${++dimIdCounter}`
  dimensions.value.push({
    id,
    type: 'angle',
    refs: [edgeRefData(edgeRef1), edgeRefData(edgeRef2)],
    radius: geometry.radius,
    color: dimensionColor.value,
    text: geometry.text
  })
  selectedDimId.value = id
}

function farthestEndpointFrom(point, a, b) {
  const distanceA = Math.hypot(a.x - point.x, a.y - point.y)
  const distanceB = Math.hypot(b.x - point.x, b.y - point.y)
  return distanceA >= distanceB ? a : b
}

/** 两条直线交点 */
function lineIntersection(p1, p2, q1, q2) {
  const d1x = p2.x - p1.x, d1y = p2.y - p1.y
  const d2x = q2.x - q1.x, d2y = q2.y - q1.y
  const cross = d1x * d2y - d1y * d2x
  if (Math.abs(cross) < 0.001) return null
  const t = ((q1.x - p1.x) * d2y - (q1.y - p1.y) * d2x) / cross
  return { x: p1.x + t * d1x, y: p1.y + t * d1y }
}

/** 构建圆弧 SVG path */
function buildArcPath(cx, cy, r, startAngle, endAngle) {
  const steps = 20
  const pts = []
  for (let i = 0; i <= steps; i++) {
    const t = startAngle + (endAngle - startAngle) * (i / steps)
    pts.push(`${cx + Math.cos(t) * r},${cy + Math.sin(t) * r}`)
  }
  return `M${pts[0]} L${pts.slice(1).join(' L')}`
}

function renderDimension(dim) {
  if (!dim?.refs?.length) return null

  let geometry = null
  if (dim.type === 'linear') {
    const first = resolveDimRef(dim.refs[0])
    if (!first) return null
    geometry = dim.mode === 'parallel'
      ? buildLinearParallelGeometry(first, resolveDimRef(dim.refs[1]), dim.offset)
      : buildLinearSingleGeometry(first, dim.offset)
  } else if (dim.type === 'diameter') {
    geometry = buildDiameterGeometry(resolveDimRef(dim.refs[0]), dim.leaderAngle)
  } else if (dim.type === 'angle') {
    geometry = buildAngleGeometry(resolveDimRef(dim.refs[0]), resolveDimRef(dim.refs[1]), dim.radius)
  }

  return geometry ? { ...geometry, id: dim.id, color: dim.color || '#303133' } : null
}

function onDimMouseDown(event, dim) {
  if (activeTool.value) return
  const mousePos = getSvgMousePoint(event)
  if (!mousePos) return
  selectDim(dim.id)
  dimDragging.value = { id: dim.id, type: dim.type }
}

function updateDimDrag(event) {
  const drag = dimDragging.value
  const dim = dimensions.value.find(item => item.id === drag?.id)
  const mousePos = getSvgMousePoint(event)
  if (!drag || !dim || !mousePos) return

  if (dim.type === 'linear') {
    const first = resolveDimRef(dim.refs[0])
    if (!first) return
    dim.offset = dim.mode === 'parallel'
      ? getParallelOffsetFromMouse(first, mousePos)
      : getLinearOffsetFromMouse(first, mousePos)
  } else if (dim.type === 'diameter') {
    const ref = resolveDimRef(dim.refs[0])
    if (!ref) return
    const center = getSheetPoint(ref.view, ref.seg.cx, ref.seg.cy)
    dim.leaderAngle = Math.atan2(mousePos.y - center.y, mousePos.x - center.x)
  } else if (dim.type === 'angle') {
    const first = resolveDimRef(dim.refs[0])
    const second = resolveDimRef(dim.refs[1])
    if (!first || !second) return
    const geometry = buildAngleGeometry(first, second, 40)
    if (!geometry) return
    dim.radius = Math.max(15, Math.min(200, Math.hypot(mousePos.x - geometry.inter.x, mousePos.y - geometry.inter.y)))
  }
}

/** 标注选中/删除 */
function selectDim(id) {
  selectedDimId.value = id
  selectedViewId.value = null
}

function deleteSelectedDim() {
  if (!selectedDimId.value) return
  dimensions.value = dimensions.value.filter(d => d.id !== selectedDimId.value)
  selectedDimId.value = null
}

/** 键盘事件：Delete 删除选中标注 */
function onKeyDown(event) {
  if (event.key === 'Delete' || event.key === 'Del') {
    if (selectedDimId.value) {
      deleteSelectedDim()
    }
  }
}

/** 全局鼠标事件：标注拖拽调整 */
function onGlobalMouseUp() {
  movingView = null
  moveStartPos = null
  alignmentGuides.value = []
  // 标注拖拽结束
  dimDragging.value = null
}
</script>

<style scoped>
.sw-drawing-app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: #f0f2f5;
}

.top-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 48px;
  padding: 8px 14px;
  background: #fff;
  border-bottom: 1px solid #dcdfe6;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
  flex-shrink: 0;
}

.toolbar-left,
.toolbar-center,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.toolbar-center {
  flex: 1;
  justify-content: center;
}

.toolbar-right {
  justify-content: flex-end;
  min-width: 180px;
}

.app-title {
  font-weight: 600;
  font-size: 15px;
  color: #303133;
  white-space: nowrap;
}

.model-select {
  width: 220px;
}

.status-text { color: #409eff; font-size: 12px; }
.status-ok { color: #67c23a; font-size: 12px; }
.status-err { color: #f56c6c; font-size: 12px; }

.editor-shell {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr) 280px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.view-palette,
.property-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow-y: auto;
  background: #fff;
}

.view-palette {
  border-right: 1px solid #dcdfe6;
}

.property-panel {
  border-left: 1px solid #dcdfe6;
}

.panel-header {
  padding: 12px 16px;
  font-weight: 600;
  font-size: 14px;
  color: #303133;
  border-bottom: 1px solid #ebeef5;
  background: #fafafa;
  flex-shrink: 0;
}

.panel-empty {
  padding: 40px 16px;
  text-align: center;
  color: #909399;
}

.panel-empty .sub,
.empty-state .sub {
  font-size: 12px;
  color: #c0c4cc;
  margin-top: 6px;
}

.palette-section,
.property-section {
  padding: 12px;
  border-bottom: 1px solid #f0f2f5;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 8px;
  text-transform: uppercase;
}

.view-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.view-item {
  cursor: grab;
  touch-action: none;
  user-select: none;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 4px;
  text-align: center;
  transition: all 0.15s;
  background: #fff;
}

.view-item:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.15);
  transform: translateY(-1px);
}

.view-item:active {
  cursor: grabbing;
}

.view-item.is-placed {
  opacity: 0.35;
  cursor: not-allowed;
  pointer-events: none;
  border-color: #dcdfe6;
  background: #f5f7fa;
}

.view-item.is-placed .view-label {
  color: #c0c4cc;
}

.view-thumbnail {
  width: 100%;
  height: 70px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fafafa;
  border-radius: 2px;
  overflow: hidden;
}

.view-thumbnail :deep(svg) {
  max-width: 100%;
  max-height: 100%;
}

.view-label {
  display: block;
  font-size: 11px;
  color: #606266;
  margin-top: 3px;
}

.canvas-region {
  min-width: 0;
  min-height: 0;
  background: #e8eaed;
  overflow: hidden;
}

.sheet-area {
  width: 100%;
  height: 100%;
  position: relative;
  overflow: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.sheet-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(0, 0, 0, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 0, 0, 0.04) 1px, transparent 1px);
  background-size: 20px 20px;
  pointer-events: none;
}

.drawing-sheet {
  position: relative;
  z-index: 1;
  background: #fff;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.15);
  flex-shrink: 0;
  user-select: none;
  -webkit-user-select: none;
}

.placed-view {
  cursor: move;
}

.placed-view.selected {
  filter: drop-shadow(0 0 4px rgba(64, 158, 255, 0.3));
}

.palette-drag-preview {
  pointer-events: none;
  opacity: 0.58;
}

.empty-state {
  position: absolute;
  z-index: 2;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: #909399;
  pointer-events: none;
}

.prop-row,
.stat-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 5px 0;
  font-size: 12px;
  color: #606266;
}

.prop-row.stacked {
  align-items: flex-start;
  flex-direction: column;
}

.prop-label {
  color: #909399;
}

.prop-value,
.stat-row .num {
  color: #303133;
  font-weight: 500;
  text-align: right;
}

.prop-input,
.full-button {
  width: 100%;
}

.full-button {
  margin-top: 8px;
}

.muted-section {
  color: #909399;
  font-size: 12px;
}

.document-json pre {
  max-height: 260px;
  overflow: auto;
  padding: 8px;
  border-radius: 4px;
  background: #f6f8fa;
  color: #303133;
  font-size: 11px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ===== 标注工具样式 ===== */
.dim-hit-line,
.dim-hit-circle {
  stroke: transparent;
  stroke-width: 10;
  fill: none;
  cursor: crosshair;
}

.dim-hit-circle {
  fill: none;
}

.dim-highlight-hover {
  stroke: #409eff;
  stroke-width: 3;
  fill: none;
  vector-effect: non-scaling-stroke;
}

.dim-highlight-selected {
  stroke: #67c23a;
  stroke-width: 3;
  fill: none;
  vector-effect: non-scaling-stroke;
}

.dim-ext-line {
  stroke: var(--dimension-color, #606266);
  stroke-width: 0.8;
  stroke-dasharray: 3,2;
  vector-effect: non-scaling-stroke;
}

.dim-line {
  stroke: var(--dimension-color, #303133);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.dim-arrow {
  fill: var(--dimension-color, #303133);
  vector-effect: non-scaling-stroke;
}

.dim-text {
  font-size: 12px;
  fill: var(--dimension-color, #303133);
  font-family: 'Microsoft YaHei', sans-serif;
  user-select: none;
  -webkit-user-select: none;
}

.dimension-group {
  cursor: pointer;
}

.dimension-selected .dim-line {
  stroke-width: 1.5;
}

.dimension-selected .dim-text {
  font-weight: 600;
}

.drawing-sheet.dim-active {
  cursor: crosshair;
}

@media (max-width: 1080px) {
  .editor-shell {
    grid-template-columns: 220px minmax(0, 1fr) 240px;
  }

  .model-select {
    width: 180px;
  }
}
</style>
