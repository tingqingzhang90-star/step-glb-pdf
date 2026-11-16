// 符号拖拽放置:复用 usePaletteDrag 的 pointer 事件 + rAF 节流范式,
// 但落点不是"放置视图",而是"写入命中的表格单元格的符号字段"。
// 依赖 coords.eventToSheetPoint / isPointerOverSheet 把屏幕坐标映射到图纸 mm,
// 再用 cellRCAtPoint 反查落点所在 (r,c)。
import { ref } from 'vue'
import { findCellAt, tableW, tableH, cellRCAtPoint } from '@/tables/tableGeometry'

const DRAG_THRESHOLD = 4 // 超阈值才算拖拽,否则视为点击(符号无点击放置,点击忽略)

export function useSymbolDrag({ coords, placedTables, setCellSymbol }) {
  const dragging = ref(false)
  const draggingFile = ref(null)
  const previewPos = ref(null) // 屏幕坐标 {x,y},供浮动预览

  let pointerStart = null
  let pendingEvent = null
  let animationFrame = 0

  function onSymbolPointerDown(file, event) {
    if (event.button !== 0) return
    event.preventDefault()
    draggingFile.value = file
    pointerStart = { x: event.clientX, y: event.clientY }
    pendingEvent = event
  }

  function updatePreview() {
    animationFrame = 0
    const event = pendingEvent
    pendingEvent = null
    if (!event || !draggingFile.value) return
    if (!dragging.value) {
      const dx = event.clientX - pointerStart.x
      const dy = event.clientY - pointerStart.y
      if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return
      dragging.value = true
    }
    previewPos.value = { x: event.clientX, y: event.clientY }
  }

  function onSymbolPointerMove(event) {
    if (!draggingFile.value || !pointerStart) return
    event.preventDefault()
    pendingEvent = event
    if (!animationFrame) animationFrame = requestAnimationFrame(updatePreview)
  }

  /** sheet 坐标点 → 命中的表格单元格(返回 {tableId, r, c} 或 null) */
  function cellAtSheetPoint(pt) {
    for (const t of placedTables.value) {
      if (pt.x < t.x || pt.x > t.x + tableW(t)) continue
      if (pt.y < t.y || pt.y > t.y + tableH(t)) continue
      const rc = cellRCAtPoint(t, pt)
      if (!rc) continue
      const cell = findCellAt(t, rc.r, rc.c)
      if (cell) return { tableId: t.id, r: cell.r, c: cell.c }
    }
    return null
  }

  function onSymbolPointerUp(event) {
    if (!draggingFile.value || !pointerStart) return
    const file = draggingFile.value
    const wasDragging = dragging.value
    if (wasDragging && coords.isPointerOverSheet(event)) {
      const pt = coords.eventToSheetPoint(event)
      if (pt) {
        const hit = cellAtSheetPoint(pt)
        if (hit) setCellSymbol(hit.tableId, hit.r, hit.c, file)
      }
    }
    reset()
  }

  function reset() {
    if (animationFrame) cancelAnimationFrame(animationFrame)
    animationFrame = 0
    pendingEvent = null
    pointerStart = null
    dragging.value = false
    draggingFile.value = null
    previewPos.value = null
  }

  return {
    dragging, draggingFile, previewPos,
    onSymbolPointerDown, onSymbolPointerMove, onSymbolPointerUp, reset
  }
}
