// 图纸坐标换算与边线引用(依赖 svgRef 与已放置视图)
import { ref } from 'vue'
import { viewSheetRect as calcViewSheetRect } from '@/views/viewGeometry.js'
import { parseBreakSpec, projectPoint } from '@/views/breakView.js'

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

  /** 1 屏幕 px = 多少图纸单位(sheet mm):由 SVG CTM 实时反推。
   *  供"屏幕 px 语义"的 UI 常量(引线预览偏移 -60px、引线限位 120px 等)
   *  换算到图纸坐标——这些常量原先直接当 sheet 单位用,在 ~3px/mm 的画布上
   *  会被放大 3 倍,导致折线直径的文字/引线被甩到几十毫米外。 */
  function screenPxToSheet() {
    const svg = svgRef.value
    if (!svg) return 1
    const ctm = svg.getScreenCTM()
    if (!ctm || !ctm.a || !isFinite(ctm.a) || ctm.a <= 0) return 1
    return 1 / ctm.a
  }

  /** 指针是否落在图纸卡范围内 */
  function isPointerOverSheet(event) {
    const svg = svgRef.value
    if (!svg) return false
    const rect = svg.getBoundingClientRect()
    return event.clientX >= rect.left && event.clientX <= rect.right
      && event.clientY >= rect.top && event.clientY <= rect.bottom
  }

  /** 视图内容在图纸坐标下的矩形(断裂后按有效占位计算) */
  function viewSheetRect(view) {
    return calcViewSheetRect(view)
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

  /** 视图局部坐标 → 图纸坐标;断裂时带内点贴到切口,标注几何自动跟随 */
  function getSheetPoint(view, lx, ly) {
    const displayScale = getViewDisplayScale(view)
    const p = projectPoint(lx, ly, parseBreakSpec(view?.break))
    return { x: view.x + p.x * displayScale, y: view.y + p.y * displayScale }
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
    edgeRefData, makeEdgeRef, resolveDimRef, screenPxToSheet
  }
}
