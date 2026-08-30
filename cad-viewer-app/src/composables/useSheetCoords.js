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

  /** 视图内容在图纸坐标下的矩形。
   *  内容包围盒是视图局部坐标(= mm × bbox.scale),需再乘显示比例 view.scale,
   *  与视图 <g> 的 transform: translate(view.x, view.y) scale(view.scale) 一致。 */
  function viewSheetRect(view) {
    const s = view.scale ?? 1
    const cb = view.contentBBox
    const bx = cb ? cb.x : 0
    const by = cb ? cb.y : 0
    const bw = cb ? cb.width : (view.bbox?.orig_width ?? view.bbox?.width ?? 0) * (view.bbox?.scale ?? 1)
    const bh = cb ? cb.height : (view.bbox?.orig_height ?? view.bbox?.height ?? 0) * (view.bbox?.scale ?? 1)
    return { x: view.x + bx * s, y: view.y + by * s, width: bw * s, height: bh * s }
  }

  /** 图纸坐标 → 命中的视图(重叠时取最上层)。
   *  供电机包络等"视图级"工具使用:它们只关心落在哪个视图上,不依赖具体边线命中。 */
  function findViewAtPoint(point) {
    if (!point) return null
    const list = placedViews.value
    for (let i = list.length - 1; i >= 0; i--) {
      const r = viewSheetRect(list[i])
      if (r.width <= 0 || r.height <= 0) continue
      if (point.x >= r.x && point.x <= r.x + r.width
        && point.y >= r.y && point.y <= r.y + r.height) return list[i]
    }
    return null
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
    svgRef, eventToSheetPoint, isPointerOverSheet, findViewAtPoint, viewSheetRect,
    getEdgeByRef, getViewDisplayScale, getSheetPoint, getViewMmScale,
    edgeRefData, makeEdgeRef, resolveDimRef
  }
}
