// 图纸坐标换算与边线引用(依赖 svgRef 与已放置视图)
import { ref } from 'vue'

export function useSheetCoords({ placedViews }) {
  const svgRef = ref(null)

  /** 鼠标事件 → 图纸坐标(含 viewBox 逆变换) */
  function eventToSheetPoint(event) {
    const svg = svgRef.value
    if (!svg) return null
    const ctm = svg.getScreenCTM()
    if (!ctm) return null
    const pt = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm.inverse())
    return { x: pt.x, y: pt.y }
  }

  /** 指针是否落在图纸卡范围内 */
  function isPointerOverSheet(event) {
    const svg = svgRef.value
    if (!svg) return false
    const rect = svg.getBoundingClientRect()
    return event.clientX >= rect.left && event.clientX <= rect.right
      && event.clientY >= rect.top && event.clientY <= rect.bottom
  }

  /** 根据引用取边线数据 */
  function getEdgeByRef(viewId, idx, type) {
    const view = placedViews.value.find(v => v.id === viewId)
    if (!view) return null
    const list = type === 'hiddenEdges' ? view.hiddenEdges : view.edges
    return list && list[idx] ? list[idx] : null
  }

  /** 视图显示比例:整卡缩放由 SVG 根节点完成,视图内部只用基础比例,避免双重缩放 */
  function getViewDisplayScale(view) {
    return view.scale
  }

  /** 视图局部坐标 → 图纸坐标 */
  function getSheetPoint(view, lx, ly) {
    const displayScale = getViewDisplayScale(view)
    return { x: view.x + lx * displayScale, y: view.y + ly * displayScale }
  }

  /** 视图 px → mm 换算比例 */
  function getViewMmScale(view) {
    return view.bbox && view.bbox.scale ? view.bbox.scale : 1
  }

  /** edgeRef → 持久化引用 {viewId, idx, type} */
  function edgeRefData(edgeRef) {
    return { viewId: edgeRef.viewId, idx: edgeRef.idx, type: edgeRef.type }
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
      transform: `translate(${view.x}, ${view.y}) scale(${getViewDisplayScale(view)})`
    }
  }

  function resolveDimRef(ref) {
    if (!ref) return null
    const view = placedViews.value.find(v => v.id === ref.viewId)
    if (!view) return null
    return makeEdgeRef(view, ref.idx, ref.type)
  }

  return {
    svgRef, eventToSheetPoint, isPointerOverSheet,
    getEdgeByRef, getViewDisplayScale, getSheetPoint, getViewMmScale,
    edgeRefData, makeEdgeRef, resolveDimRef
  }
}
