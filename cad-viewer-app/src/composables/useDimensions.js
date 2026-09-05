// 标注工具:状态声明 + 引擎装配(dimCore 几何构建 / dimEngine 交互状态机)
import { ref, computed } from 'vue'
import { createDimEngine, coreFactory } from '@/dimensions/index.js'
import { toCircle, toLineSeg } from '@/dimensions/geometry.js'

export function useDimensions({ placedViews, selectedViewId, coords, getMotorEnvelope }) {
  const activeTool = ref(null)       // null | 'linear' | 'diameter' | 'angle' | 'center-mark' | 'motor-envelope'
  const dimHoveredEdge = ref(null)   // { seg, transform, viewId, idx, type }
  const dimFirstEdge = ref(null)     // 第一选中边线
  const dimPending = ref(null)       // { mode, first, second } 已选齐对象，等点击固定
  const dimPreview = ref(null)       // 当前预览标注
  const dimensionColor = ref('#303133')
  const dimensionColorPresets = ['#303133', '#409eff', '#67c23a', '#e6a23c', '#f56c6c']
  const dimensions = ref([])         // 已放置标注
  const selectedDimId = ref(null)    // 选中标注 id
  const dimHoveredId = ref(null)     // 悬浮中的已放置标注 id(字符串,来自 data-dim-id)
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
    resolveDimRef: coords.resolveDimRef,
    getMotorEnvelope
  }, {
    dimensions,
    dimensionColor,
    idCounter: dimIdCounter
  })

  const {
    toggleTool, onDimEdgeSelect, onMotorEnvelopePick, updateDimPreviewAt, commitPendingLinear,
    onDimMouseDown, onDimTextMouseDown, onDimDragMove,     onGlobalDimMouseUp, onKeyDown, clearDimState: clearDimToolState
  } = createDimEngine({
    activeTool,
    dimHoveredEdge,
    dimFirstEdge,
    dimPending,
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
    getMotorEnvelope,
    selectDim,
    selectView: (id) => { selectedViewId.value = id },
    core: dimCore
  })

  const renderedDimensions = computed(() => dimensions.value
    .map(dim => dimCore.renderDimension(dim))
    .filter(Boolean)
  )

  const selectedDim = computed(() =>
    dimensions.value.find(d => d.id === selectedDimId.value) || null
  )

  /** 属性面板编辑标注字段(customText/bind_motor),直接改对象触发重渲染 */
  function setDimField(id, field, value) {
    const dim = dimensions.value.find(d => d.id === id)
    if (dim) dim[field] = value
  }

  /** 标注右键菜单 */
  const dimContextMenu = ref(null)

  function openDimContextMenu(event, dim) {
    event.preventDefault()
    event.stopPropagation()
    selectDim(dim.id)
    dimContextMenu.value = {
      x: event.clientX,
      y: event.clientY,
      dimId: dim.id,
      currentMode: dim.arrowMode || 'auto'
    }
  }

  function closeDimContextMenu() {
    dimContextMenu.value = null
  }

  function setDimArrowMode(mode) {
    const m = dimContextMenu.value
    if (!m) return
    const dim = dimensions.value.find(d => d.id === m.dimId)
    if (dim) dim.arrowMode = mode
    closeDimContextMenu()
  }

  /** 待高亮的选中对象：第一边 + 待固定态的第二边，附带圆拟合与图纸坐标半径 */
  const dimHighlightEdges = computed(() => {
    const list = []
    if (dimFirstEdge.value) list.push(dimFirstEdge.value)
    if (dimPending.value?.second) list.push(dimPending.value.second)
    return list.map(edge => {
      const circle = toCircle(edge.seg)
      const r = circle ? circle.r * coords.getViewDisplayScale(edge.view) : null
      return { edge, circle, r }
    })
  })

  /** 点击图纸空白:清除临时选择(保留已放置标注) */
  function clearTransientSelection() {
    dimFirstEdge.value = null
    dimPending.value = null
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
    // 点击空白处：已选齐对象的预览就地落位
    if (activeTool.value === 'linear' && dimPending.value) {
      commitPendingLinear()
      return
    }
    // 只选了一根边线：单边标注按当前偏移直接放置
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

  /** 鼠标移出图纸:清掉 hover 高亮,避免残留 */
  function onSvgMouseLeave() {
    dimHoveredId.value = null
    if (dimHoveredEdge.value) dimHoveredEdge.value = null
  }

  /** 点击已放置标注:选中它;标注工具激活时同步退出其临时选择态(第一边/待固定预览) */
  function onDimClick(dim) {
    selectDim(dim.id)
    if (activeTool.value) clearDimToolState()
  }

  /** SVG mousemove:先看是否悬浮在已放置标注上,否则走透明命中层的边线 hover + 预览更新 */
  function onSvgMouseMove(event) {
    // 已放置标注优先：无论是普通模式还是标注工具激活时,都要能悬浮高亮并点击选中。
    // 命中时冻结预览(不跟随鼠标),否则待固定态的预览会在用户去点标注时乱跳。
    const target = document.elementFromPoint(event.clientX, event.clientY)
    const hitDimEl = target?.closest('[data-dim-id]')
    if (hitDimEl) {
      dimHoveredId.value = hitDimEl.dataset.dimId
      if (dimHoveredEdge.value) dimHoveredEdge.value = null
      return
    }
    if (dimHoveredId.value) dimHoveredId.value = null

    if (!activeTool.value) return

    // 电机包络:与具体边线无关,鼠标进入视图范围即按该视图的包络出预览
    if (activeTool.value === 'motor-envelope') {
      const pt = coords.eventToSheetPoint(event)
      const v = pt ? coords.findViewAtPoint(pt) : null
      const env = v && getMotorEnvelope ? getMotorEnvelope(v) : null
      if (v && env) {
        if (dimHoveredEdge.value?.viewId !== v.id) {
          dimHoveredEdge.value = { view: v, viewId: v.id, motorEnvelope: true }
        }
        updateDimPreviewAt(event)
      } else {
        if (dimHoveredEdge.value) dimHoveredEdge.value = null
        if (dimPreview.value) dimPreview.value = null
      }
      return
    }

    const hit = target?.closest('[data-dim-view]') ?? null
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
    dimHoveredId.value = null
    dimHoveredEdge.value = null
    dimFirstEdge.value = null
    dimPending.value = null
    dimPreview.value = null
  }

  return {
    activeTool, dimHoveredEdge, dimFirstEdge, dimPending, dimPreview,
    dimensionColor, dimensionColorPresets, dimensions, selectedDimId, dimDragging,
    renderedDimensions, dimHighlightEdges, dimHoveredId, selectedDim, setDimField,
    dimContextMenu, openDimContextMenu, closeDimContextMenu, setDimArrowMode,
    toggleTool, onDimEdgeSelect, onMotorEnvelopePick, onDimMouseDown, onDimTextMouseDown, onDimDragMove,
    onGlobalDimMouseUp, onKeyDown, selectDim, onDimClick,
    onSvgMouseDown, onSvgMouseMove, onSvgMouseLeave,
    clearTransientSelection, removeByView, resetAll
  }
}
