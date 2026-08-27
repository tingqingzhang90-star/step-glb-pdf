// 已放置视图管理:放置/删除/选择、全局比例缩放
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  normalizeViewBBox,
  computeContentBBox,
  getInitialViewScale
} from '@/views/viewGeometry.js'

export function usePlacedViews({ sheetWidth, sheetHeight }) {
  const placedViews = ref([])
  const selectedViewId = ref(null)
  const globalScale = ref(null)
  let viewIdCounter = 0

  const selectedView = computed(() =>
    placedViews.value.find(v => v.id === selectedViewId.value)
  )

  const placedViewNames = computed(() =>
    new Set(placedViews.value.map(v => v.name))
  )

  /** 放置视图(同名视图唯一);比例始终取全局值 */
  function placeView(view, x, y) {
    if (placedViews.value.some(pv => pv.name === view.name)) {
      ElMessage.warning(`「${view.label}」已存在于图纸中`)
      return
    }
    if (globalScale.value == null) {
      globalScale.value = getInitialViewScale(view)
    }
    const scale = globalScale.value
    const bbox = normalizeViewBBox(view)
    // 透传后端归一化比例，使 mm 换算使用真实 px/mm 比例
    if (view.bbox && typeof view.bbox.scale === 'number' && !('scale' in bbox)) {
      bbox.scale = view.bbox.scale
    }
    const edges = (view.edges || []).filter(s => s && s.type)
    const hiddenEdges = (view.hidden_edges || []).filter(s => s && s.type)
    const contentBBox = computeContentBBox({ ...view, edges, hidden_edges: hiddenEdges })
    placedViews.value.push({
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
    })
    selectedViewId.value = placedViews.value[placedViews.value.length - 1].id
  }

  function selectView(id) {
    selectedViewId.value = id
  }

  /** 删除选中视图,返回被删 id(供上层同步清理引用它的标注) */
  function deleteSelectedView() {
    const deletedViewId = selectedViewId.value
    if (!deletedViewId) return null
    placedViews.value = placedViews.value.filter(v => v.id !== deletedViewId)
    selectedViewId.value = null
    return deletedViewId
  }

  /** 清空已放置视图(不动全局比例) */
  function clearViews() {
    placedViews.value = []
    selectedViewId.value = null
  }

  /** 重置全局比例 */
  function resetScale() {
    globalScale.value = null
  }

  /** 视图绕内容中心缩放(位置补偿,视觉上原地缩放) */
  function zoomViewAroundCenter(view, newScale) {
    const bbox = view.contentBBox
    const cx = bbox.x + bbox.width / 2
    const cy = bbox.y + bbox.height / 2
    const oldScale = view.scale
    view.x = view.x + cx * (oldScale - newScale)
    view.y = view.y + cy * (oldScale - newScale)
    view.scale = newScale
  }

  function applyGlobalScale(newScale) {
    globalScale.value = newScale
    for (const v of placedViews.value) {
      zoomViewAroundCenter(v, newScale)
    }
  }

  /** 属性面板修改全局比例 */
  function onViewScaleChange(newScale) {
    applyGlobalScale(Math.max(0.1, Math.min(5, newScale)))
  }

  /** 工具栏放大/缩小 */
  function zoomCanvas(factor) {
    applyGlobalScale(Math.max(0.1, Math.min(5, (globalScale.value || 1) * factor)))
  }

  /** 工具栏"适应":按所有视图最大长边统一缩放 */
  function resetCanvas() {
    if (placedViews.value.length === 0) return
    let maxExtent = 0
    for (const v of placedViews.value) {
      maxExtent = Math.max(maxExtent, v.contentBBox.width, v.contentBBox.height)
    }
    if (maxExtent < 0.01) return
    const targetLongEdge = Math.min(sheetWidth.value * 0.6, sheetHeight.value * 0.6)
    applyGlobalScale(Math.max(0.1, Math.min(5, targetLongEdge / maxExtent)))
  }

  return {
    placedViews, selectedViewId, globalScale,
    selectedView, placedViewNames,
    placeView, selectView, deleteSelectedView, clearViews, resetScale,
    onViewScaleChange, zoomCanvas, resetCanvas
  }
}
