<template>
  <div class="sw-drawing-app">
    <!-- ============ 顶部工具栏 ============ -->
    <div class="top-toolbar">
      <div class="toolbar-left">
        <span class="app-title">工程图编辑器</span>
        <el-divider direction="vertical" />
        <el-select v-model="selectedModel" placeholder="选择型号" filterable size="small" style="width: 200px" @change="onModelChange">
          <el-option v-for="m in models" :key="m" :label="m" :value="m" />
        </el-select>
        <el-button type="primary" size="small" :loading="loadingViews" @click="loadViewPalette" :disabled="!selectedModel">
          <el-icon><Upload /></el-icon>
          导入模型
        </el-button>
      </div>
      <div class="toolbar-center">
        <el-button-group>
          <el-button size="small" :icon="ZoomIn" @click="zoomCanvas(1.2)" :disabled="!viewsLoaded">放大</el-button>
          <el-button size="small" :icon="ZoomOut" @click="zoomCanvas(0.8)" :disabled="!viewsLoaded">缩小</el-button>
          <el-button size="small" @click="resetCanvas" :disabled="!viewsLoaded">适应</el-button>
        </el-button-group>
        <el-divider direction="vertical" />
        <el-button size="small" :icon="Delete" @click="clearPlacedViews" :disabled="placedViews.length === 0">清空</el-button>
      </div>
      <div class="toolbar-right">
        <span v-if="loadingText" class="status-text">{{ loadingText }}</span>
        <span v-if="lastElapsed" class="status-ok">耗时 {{ lastElapsed }}s</span>
        <span v-if="error" class="status-err">{{ error }}</span>
      </div>
    </div>

    <div class="main-body">
      <!-- ============ 左侧:图纸画布 ============ -->
      <div class="sheet-area" ref="sheetAreaRef">
        <!-- 网格背景 -->
        <div class="sheet-grid"></div>
        <!-- SVG 画布 -->
        <svg
          ref="svgRef"
          class="drawing-sheet"
          :width="sheetWidth"
          :height="sheetHeight"
          :viewBox="`0 0 ${sheetWidth} ${sheetHeight}`"
          @dragover.prevent
          @drop="onSheetDrop"
          @mousedown="onSheetMouseDown"
        >
          <!-- 图纸边框 -->
          <rect x="20" y="20" :width="sheetWidth - 40" :height="sheetHeight - 40"
                fill="#ffffff" stroke="#999" stroke-width="1" />

          <!-- 已放置的视图 -->
          <g v-for="(pv, idx) in placedViews" :key="pv.id"
             :transform="`translate(${pv.x}, ${pv.y}) scale(${pv.scale})`"
             :class="['placed-view', { selected: selectedViewId === pv.id }]"
             @mousedown.stop="onViewMouseDown($event, pv)"
             @click.stop="selectView(pv.id)">
            <!-- 视图边框(选中时高亮) -->
            <rect
              :x="-4" :y="-4"
              :width="pv.bbox.width + 8"
              :height="pv.bbox.height + 8"
              fill="none"
              :stroke="selectedViewId === pv.id ? '#409eff' : 'transparent'"
              stroke-width="2"
              stroke-dasharray="4,2"
            />
            <!-- 视图图像(基于 HLRBRep 边线数据,支持关联式标注) -->
            <g class="visible-edges">
              <line v-for="(seg, i) in pv.edges" :key="'v'+i"
                    v-if="seg && seg.type === 'line'"
                    :x1="seg.x1" :y1="seg.y1" :x2="seg.x2" :y2="seg.y2"
                    stroke="#333" stroke-width="1" />
              <circle v-else-if="seg && seg.type === 'circle'"
                      :cx="seg.cx" :cy="seg.cy" :r="seg.r"
                      stroke="#333" stroke-width="1" fill="none" />
              <polyline v-else-if="seg && seg.type === 'polyline'"
                        :points="polylinePoints(seg.points)"
                        stroke="#333" stroke-width="1" fill="none" />
            </g>
            <!-- 隐藏边(虚线) -->
            <g class="hidden-edges">
              <line v-for="(seg, i) in pv.hiddenEdges" :key="'h'+i"
                    v-if="seg && seg.type === 'line'"
                    :x1="seg.x1" :y1="seg.y1" :x2="seg.x2" :y2="seg.y2"
                    stroke="#999" stroke-width="0.8" stroke-dasharray="3,2" />
            </g>
            <!-- 视图标签 -->
            <text :x="0" :y="pv.bbox.height + 16"
                  font-size="11" fill="#666">{{ pv.label }}</text>
          </g>

          <!-- 拖拽预览(跟随鼠标) -->
          <g v-if="draggingFromPalette && dragPreviewPos"
             :transform="`translate(${dragPreviewPos.x}, ${dragPreviewPos.y})`"
             opacity="0.5">
            <rect x="0" y="0" width="120" height="90" fill="#fff" stroke="#409eff" stroke-dasharray="3,3" />
            <text x="60" y="50" text-anchor="middle" font-size="11" fill="#409eff">{{ draggingView.label }}</text>
          </g>
        </svg>

        <!-- 空状态提示 -->
        <div v-if="!viewsLoaded && !loadingViews" class="empty-state">
          <el-icon :size="48"><DocumentAdd /></el-icon>
          <p>选择型号并导入模型以开始</p>
          <p class="sub">导入后可从右侧拖拽视图到图纸</p>
        </div>
      </div>

      <!-- ============ 右侧:视图调色板 ============ -->
      <div class="view-palette">
        <div class="palette-header">
          <span>视图调色板</span>
        </div>

        <!-- 加载状态 -->
        <div v-if="loadingViews" class="palette-loading">
          <el-icon class="is-loading"><Loading /></el-icon>
          <p>正在生成视图...</p>
          <p class="sub">STEP → HLR投影 → 9视图</p>
        </div>

        <!-- 模型未导入 -->
        <div v-else-if="!viewsLoaded" class="palette-empty">
          <p>请先导入模型</p>
        </div>

        <!-- 视图列表 -->
        <template v-else>
          <!-- 标准视图 -->
          <div class="palette-section">
            <div class="section-title">标准视图</div>
            <div class="view-grid">
              <div
                v-for="vw in standardViews"
                :key="vw.name"
                class="view-item"
                draggable="true"
                @dragstart="onPaletteDragStart($event, vw)"
                @click="onPaletteClick(vw)"
                :title="`点击或拖拽放置「${vw.label}」`"
              >
                <div class="view-thumbnail" v-html="vw.thumbnail"></div>
                <span class="view-label">{{ vw.label }}</span>
              </div>
            </div>
          </div>

          <!-- 轴测视图 -->
          <div class="palette-section">
            <div class="section-title">轴测视图</div>
            <div class="view-grid">
              <div
                v-for="vw in isometricViews"
                :key="vw.name"
                class="view-item"
                draggable="true"
                @dragstart="onPaletteDragStart($event, vw)"
                @click="onPaletteClick(vw)"
                :title="`点击或拖拽放置「${vw.label}」`"
              >
                <div class="view-thumbnail" v-html="vw.thumbnail"></div>
                <span class="view-label">{{ vw.label }}</span>
              </div>
            </div>
          </div>

          <!-- 选中视图属性 -->
          <div v-if="selectedView" class="palette-section">
            <div class="section-title">视图属性</div>
            <div class="view-props">
              <div class="prop-row">
                <span class="prop-label">名称</span>
                <span class="prop-value">{{ selectedView.label }}</span>
              </div>
              <div class="prop-row">
                <span class="prop-label">边数</span>
                <span class="prop-value">{{ selectedView.edges?.length || 0 }}</span>
              </div>
              <div class="prop-row">
                <span class="prop-label">比例</span>
                <el-input-number v-model="selectedView.scale" :min="0.1" :max="5" :step="0.1" size="small" style="width: 100px" />
              </div>
              <div class="prop-row">
                <span class="prop-label">位置</span>
                <span class="prop-value">{{ Math.round(selectedView.x) }}, {{ Math.round(selectedView.y) }}</span>
              </div>
              <el-button size="small" type="danger" plain @click="deleteSelectedView" style="width: 100%; margin-top: 8px">
                <el-icon><Delete /></el-icon>
                删除此视图
              </el-button>
            </div>
          </div>

          <!-- 统计 -->
          <div class="palette-section">
            <div class="section-title">图纸统计</div>
            <div class="stats">
              <div class="stat-row"><span>已放置视图</span><span class="num">{{ placedViews.length }}</span></div>
              <div class="stat-row"><span>模型尺寸</span><span class="num">{{ modelBbox.width }}×{{ modelBbox.height }}×{{ modelBbox.depth }}mm</span></div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Upload, ZoomIn, ZoomOut, Delete, DocumentAdd, Loading } from '@element-plus/icons-vue'

// ============ 状态 ============
const models = ref([])
const selectedModel = ref('')
const loadingViews = ref(false)
const viewsLoaded = ref(false)
const loadingText = ref('')
const error = ref('')
const lastElapsed = ref(null)
const modelBbox = ref({ width: 0, height: 0, depth: 0 })

// 视图调色板数据(9个标准视图)
const paletteViews = ref({})

// 已放置到画布的视图
const placedViews = ref([])
let viewIdCounter = 0
const selectedViewId = ref(null)

// 画布
const sheetAreaRef = ref(null)
const svgRef = ref(null)
const sheetWidth = ref(1189)  // A0 横向
const sheetHeight = ref(841)

// 拖拽状态
const draggingFromPalette = ref(false)
const draggingView = ref(null)
const dragPreviewPos = ref(null)

// 视图移动状态
let movingView = null
let moveStartPos = null

// ============ 计算属性 ============
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

// ============ 生命周期 ============
onMounted(async () => {
  await loadModelList()
  // 全局鼠标事件(用于拖动视图)
  window.addEventListener('mousemove', onGlobalMouseMove)
  window.addEventListener('mouseup', onGlobalMouseUp)
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onGlobalMouseMove)
  window.removeEventListener('mouseup', onGlobalMouseUp)
})

// ============ 方法 ============

// 加载型号列表(接受 assembly.step 或 assembly.brep)
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
  // 切换型号时清空画布和调色板
  paletteViews.value = {}
  placedViews.value = []
  selectedViewId.value = null
  viewsLoaded.value = false
  error.value = ''
  lastElapsed.value = null
}

// 导入模型,生成视图调色板
async function loadViewPalette() {
  if (!selectedModel.value) return
  loadingViews.value = true
  loadingText.value = '正在生成 9 个标准视图...'
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
    ElMessage.success(`已生成 ${Object.keys(data.views).length} 个视图,耗时 ${data.elapsed}s`)
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loadingViews.value = false
    loadingText.value = ''
  }
}

// ============ 调色板拖拽 ============

function onPaletteDragStart(event, view) {
  draggingFromPalette.value = true
  draggingView.value = view
  // 设置拖拽数据(必须,否则 Firefox 不触发 drag)
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData('text/plain', view.name)
}

// 调色板点击放置(放到画布中心)
function onPaletteClick(view) {
  placeView(view, sheetWidth.value / 2 - 60, sheetHeight.value / 2 - 45)
}

// 拖拽放到画布
function onSheetDrop(event) {
  event.preventDefault()
  if (!draggingFromPalette.value || !draggingView.value) return

  const svg = svgRef.value
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  // 将屏幕坐标转换为 SVG 坐标
  const x = (event.clientX - rect.left) / rect.width * sheetWidth.value
  const y = (event.clientY - rect.top) / rect.height * sheetHeight.value

  placeView(draggingView.value, x - 60, y - 45)
  draggingFromPalette.value = false
  draggingView.value = null
  dragPreviewPos.value = null
}

// 放置视图到画布
function placeView(view, x, y) {
  const newView = {
    id: `view_${++viewIdCounter}`,
    name: view.name,
    label: view.label,
    group: view.group,
    // 边线数据(含元数据,用于关联式标注)
    edges: (view.edges || []).filter(s => s && s.type),
    hiddenEdges: (view.hidden_edges || []).filter(s => s && s.type),
    bbox: view.bbox || { x: 0, y: 0, width: 400, height: 300 },
    x: Math.max(0, x),
    y: Math.max(0, y),
    scale: 1
  }
  placedViews.value.push(newView)
  selectedViewId.value = newView.id
}

// ============ 画布上视图操作 ============

function selectView(id) {
  selectedViewId.value = id
}

function onViewMouseDown(event, view) {
  selectedViewId.value = view.id
  movingView = view
  moveStartPos = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y }
}

function onSheetMouseDown(event) {
  // 点击空白处取消选中
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

// 删除选中视图
function deleteSelectedView() {
  if (!selectedViewId.value) return
  placedViews.value = placedViews.value.filter(v => v.id !== selectedViewId.value)
  selectedViewId.value = null
}

// 清空所有视图
function clearPlacedViews() {
  placedViews.value = []
  selectedViewId.value = null
}

// ============ 画布缩放 ============

function zoomCanvas(factor) {
  // 简单实现:调整所有视图的 scale
  for (const v of placedViews.value) {
    v.scale = Math.max(0.1, Math.min(5, v.scale * factor))
  }
}

function resetCanvas() {
  for (const v of placedViews.value) {
    v.scale = 1
  }
}

// ============ 工具函数 ============

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

/* ============ 顶部工具栏 ============ */
.top-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #fff;
  border-bottom: 1px solid #dcdfe6;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
  flex-shrink: 0;
}
.toolbar-left, .toolbar-center, .toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.app-title {
  font-weight: 600;
  font-size: 15px;
  color: #303133;
}
.status-text { color: #409eff; font-size: 12px; }
.status-ok { color: #67c23a; font-size: 12px; }
.status-err { color: #f56c6c; font-size: 12px; }

/* ============ 主区域 ============ */
.main-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ============ 图纸区域 ============ */
.sheet-area {
  flex: 1;
  position: relative;
  overflow: auto;
  background: #e8eaed;
  display: flex;
  align-items: center;
  justify-content: center;
}
.sheet-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(0,0,0,0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,0,0,0.04) 1px, transparent 1px);
  background-size: 20px 20px;
  pointer-events: none;
}
.drawing-sheet {
  background: #fff;
  box-shadow: 0 2px 12px rgba(0,0,0,0.15);
  flex-shrink: 0;
}
.placed-view {
  cursor: move;
}
.placed-view.selected {
  filter: drop-shadow(0 0 4px rgba(64,158,255,0.3));
}
.empty-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: #909399;
}
.empty-state .sub {
  font-size: 12px;
  color: #c0c4cc;
  margin-top: 4px;
}

/* ============ 视图调色板 ============ */
.view-palette {
  width: 240px;
  background: #fff;
  border-left: 1px solid #dcdfe6;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  flex-shrink: 0;
}
.palette-header {
  padding: 12px 16px;
  font-weight: 600;
  font-size: 14px;
  border-bottom: 1px solid #ebeef5;
  background: #fafafa;
}
.palette-loading, .palette-empty {
  padding: 40px 16px;
  text-align: center;
  color: #909399;
}
.palette-loading .sub, .palette-empty .sub {
  font-size: 12px;
  color: #c0c4cc;
  margin-top: 8px;
}
.palette-section {
  padding: 12px;
  border-bottom: 1px solid #f0f2f5;
}
.section-title {
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.view-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.view-item {
  cursor: grab;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 4px;
  text-align: center;
  transition: all 0.15s;
  background: #fff;
}
.view-item:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64,158,255,0.15);
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
  margin-top: 2px;
}

/* 视图属性 */
.view-props {
  font-size: 12px;
}
.prop-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
}
.prop-label {
  color: #909399;
}
.prop-value {
  color: #303133;
  font-weight: 500;
}

/* 统计 */
.stats {
  font-size: 12px;
}
.stat-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  color: #606266;
}
.stat-row .num {
  color: #303133;
  font-weight: 500;
}
</style>
