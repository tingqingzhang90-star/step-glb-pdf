// 标注工具:状态声明 + 引擎装配(dimCore 几何构建 / dimEngine 交互状态机)
import { ref, computed } from 'vue'
import { createDimEngine, coreFactory } from '@/dimensions/index.js'
import { toCircle, toLineSeg } from '@/dimensions/geometry.js'

export function useDimensions({ placedViews, selectedViewId, coords }) {
  const activeTool = ref(null)       // null | 'linear' | 'diameter' | 'angle'
  const dimHoveredEdge = ref(null)   // { seg, transform, viewId, idx, type }
  const dimFirstEdge = ref(null)     // 第一选中边线
  const dimPreview = ref(null)       // 当前预览标注
  const dimensionColor = ref('#303133')
  const dimensionColorPresets = ['#303133', '#409eff', '#67c23a', '#e6a23c', '#f56c6c']
  const dimensions = ref([])         // 已放置标注
  const selectedDimId = ref(null)    // 选中标注 id
  const dimDragging = ref(null)      // 拖拽调整中
  const dimIdCounter = { value: 0 }  // 按引用传给 core 自增

  function selectDim(id) {
    selectedDimId.value = id
    selectedViewId.value = null
  }

  const dimCore = coreFactory({
    getSheetPoint: coords.getSheetPoint,
    getViewDisplayScale: coords.getViewDisplayScale,
    getViewMmScale: coords.getViewMmScale,
    edgeRefData: coords.edgeRefData,
    getSvgMousePoint: coords.eventToSheetPoint,
    resolveDimRef: coords.resolveDimRef
  }, {
    dimensions,
    dimensionColor,
    idCounter: dimIdCounter
  })

  const {
    toggleTool, onDimEdgeSelect, updateDimPreviewAt, onDimMouseDown,
    onDimDragMove, onGlobalDimMouseUp, onKeyDown
  } = createDimEngine({
    activeTool,
    dimHoveredEdge,
    dimFirstEdge,
    dimPreview,
    dimensions,
    selectedDimId,
    dimDragging,
    placedViews,
    getEdgeByRef: coords.getEdgeByRef,
    makeEdgeRef: coords.makeEdgeRef,
    resolveDimRef: coords.resolveDimRef,
    getSvgMousePoint: coords.eventToSheetPoint,
    getSheetPoint: coords.getSheetPoint,
    selectDim,
    selectView: (id) => { selectedViewId.value = id },
    core: dimCore
  })

  const renderedDimensions = computed(() => dimensions.value
    .map(dim => dimCore.renderDimension(dim))
    .filter(Boolean)
  )

  /** 第一选中边的圆心拟合(中心距标注高亮十字) */
  function getFirstDimCircle() {
    const first = dimFirstEdge.value
    if (!first) return null
    return toCircle(first.seg)
  }

  /** 点击图纸空白:清除临时选择(保留已放置标注) */
  function clearTransientSelection() {
    dimFirstEdge.value = null
    dimPreview.value = null
    selectedDimId.value = null
  }

  /** SVG mousedown:标注工具激活时的边线选择/放置/取消 */
  function onSvgMouseDown(event) {
    if (!activeTool.value) return
    const target = document.elementFromPoint(event.clientX, event.clientY)
    const hit = target && target.closest ? target.closest('[data-dim-view]') : null
    if (hit) {
      onDimEdgeSelect(hit, event)
      return
    }
    // 点击空白处：若当前是 single 线性预览，则在当前 offset 位置放置；否则取消
    const first = dimFirstEdge.value
    const preview = dimPreview.value
    if (activeTool.value === 'linear' && first && preview && toLineSeg(first.seg) && preview.type === 'linear' && preview.mode === 'single') {
      const offset = preview.offset ?? dimCore.getLinearOffsetFromMouse(first, coords.eventToSheetPoint(event))
      const id = dimCore.placeLinearDimSingle(first, offset)
      if (id) selectDim(id)
      dimFirstEdge.value = null
      dimPreview.value = null
      dimHoveredEdge.value = null
      activeTool.value = null
      return
    }
    clearTransientSelection()
  }

  /** SVG mousemove:通过透明命中层做边线 hover 检测 + 预览更新 */
  function onSvgMouseMove(event) {
    if (!activeTool.value) return
    const target = document.elementFromPoint(event.clientX, event.clientY)
    const hit = target && target.closest ? target.closest('[data-dim-view]') : null
    if (hit) {
      const viewId = hit.dataset.dimView
      const idx = parseInt(hit.dataset.dimIdx, 10)
      const type = hit.dataset.dimType
      const seg = coords.getEdgeByRef(viewId, idx, type)
      const view = placedViews.value.find(v => v.id === viewId)
      if (seg && view) {
        const hover = coords.makeEdgeRef(view, idx, type, seg)
        // 引用不同才更新(避免重复 set)
        const cur = dimHoveredEdge.value
        if (!cur || cur.viewId !== viewId || cur.idx !== idx || cur.type !== type) {
          dimHoveredEdge.value = hover
        }
        updateDimPreviewAt(event)
        return
      }
    }
    if (dimHoveredEdge.value) dimHoveredEdge.value = null
    updateDimPreviewAt(event)
  }

  /** 删除引用了指定视图的全部标注 */
  function removeByView(viewId) {
    dimensions.value = dimensions.value.filter(
      dim => !(dim.refs || []).some(ref => ref.viewId === viewId)
    )
  }

  /** 全量重置(清空图纸时) */
  function resetAll() {
    dimensions.value = []
    selectedDimId.value = null
    dimHoveredEdge.value = null
    dimFirstEdge.value = null
    dimPreview.value = null
  }

  return {
    activeTool, dimHoveredEdge, dimFirstEdge, dimPreview,
    dimensionColor, dimensionColorPresets, dimensions, selectedDimId, dimDragging,
    renderedDimensions,
    toggleTool, onDimEdgeSelect, onDimMouseDown, onDimDragMove,
    onGlobalDimMouseUp, onKeyDown, selectDim, getFirstDimCircle,
    onSvgMouseDown, onSvgMouseMove, clearTransientSelection, removeByView, resetAll
  }
}
