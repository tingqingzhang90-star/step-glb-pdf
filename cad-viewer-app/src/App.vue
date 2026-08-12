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
          <el-button size="small" :disabled="!viewsLoaded">线性</el-button>
          <el-button size="small" :disabled="!viewsLoaded">直径</el-button>
          <el-button size="small" :disabled="!viewsLoaded">角度</el-button>
          <el-button size="small" :disabled="!viewsLoaded">文字</el-button>
        </el-button-group>
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
                class="view-item"
                :title="`点击或拖拽放置「${vw.label}」`"
                @pointerdown="onPalettePointerDown($event, vw)"
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
                class="view-item"
                :title="`点击或拖拽放置「${vw.label}」`"
                @pointerdown="onPalettePointerDown($event, vw)"
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
            class="drawing-sheet"
            :width="sheetWidth"
            :height="sheetHeight"
            :viewBox="`0 0 ${sheetWidth} ${sheetHeight}`"
            @mousedown="onSheetMouseDown"
          >
            <rect x="20" y="20" :width="sheetWidth - 40" :height="sheetHeight - 40" fill="#ffffff" stroke="#999" stroke-width="1" />
            <rect x="920" y="690" width="240" height="120" fill="none" stroke="#555" stroke-width="1" />
            <line x1="920" y1="730" x2="1160" y2="730" stroke="#555" stroke-width="1" />
            <line x1="1000" y1="690" x2="1000" y2="810" stroke="#555" stroke-width="1" />
            <text x="1040" y="715" font-size="18" fill="#303133">产品工程图</text>
            <text x="936" y="755" font-size="12" fill="#606266">型号</text>
            <text x="1016" y="755" font-size="12" fill="#303133">{{ selectedModel || '-' }}</text>

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
            <span class="prop-label">比例</span>
            <el-input-number v-model="selectedView.scale" :min="0.1" :max="5" :step="0.1" size="small" class="prop-input" />
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
  annotations: []
}, null, 2))

onMounted(async () => {
  await loadModelList()
  window.addEventListener('mousemove', onGlobalMouseMove)
  window.addEventListener('mouseup', onGlobalMouseUp)
  window.addEventListener('pointermove', onPalettePointerMove)
  window.addEventListener('pointerup', onPalettePointerUp)
  window.addEventListener('pointercancel', resetPaletteDrag)
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onGlobalMouseMove)
  window.removeEventListener('mouseup', onGlobalMouseUp)
  window.removeEventListener('pointermove', onPalettePointerMove)
  window.removeEventListener('pointerup', onPalettePointerUp)
  window.removeEventListener('pointercancel', resetPaletteDrag)
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
  if (point) dragPreviewPos.value = getCenteredViewPlacement(draggingView.value, point)
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
    const point = getSvgPoint(event)
    if (point) {
      const placement = getCenteredViewPlacement(view, point)
      placeView(view, placement.x, placement.y, placement.scale)
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
  const placement = getCenteredViewPlacement(view, {
    x: sheetWidth.value / 2,
    y: sheetHeight.value / 2
  })
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

function placeView(view, x, y, scale = 1) {
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
  selectedViewId.value = view.id
  movingView = view
  moveStartPos = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y }
}

function onSheetMouseDown(event) {
  if (event.target.tagName === 'rect' || event.target.tagName === 'svg') {
    selectedViewId.value = null
  }
}

function onGlobalMouseMove(event) {
  if (!movingView) return
  const dx = event.clientX - moveStartPos.x
  const dy = event.clientY - moveStartPos.y
  movingView.x = moveStartPos.vx + dx
  movingView.y = moveStartPos.vy + dy
}

function onGlobalMouseUp() {
  movingView = null
  moveStartPos = null
}

function deleteSelectedView() {
  if (!selectedViewId.value) return
  placedViews.value = placedViews.value.filter(v => v.id !== selectedViewId.value)
  selectedViewId.value = null
}

function clearPlacedViews() {
  placedViews.value = []
  selectedViewId.value = null
}

function zoomCanvas(factor) {
  for (const v of placedViews.value) {
    v.scale = Math.max(0.1, Math.min(5, v.scale * factor))
  }
}

function resetCanvas() {
  for (const v of placedViews.value) {
    v.scale = 1
  }
}

function polylinePoints(points) {
  return points.map(p => `${p[0]},${p[1]}`).join(' ')
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

@media (max-width: 1080px) {
  .editor-shell {
    grid-template-columns: 220px minmax(0, 1fr) 240px;
  }

  .model-select {
    width: 180px;
  }
}
</style>
