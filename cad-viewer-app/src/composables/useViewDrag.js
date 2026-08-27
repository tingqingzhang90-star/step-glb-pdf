// 视图拖拽移动:按住已放置视图拖动,带投影对齐吸附与引导线
import { ref } from 'vue'
import { detectAlignment } from '@/views/viewGeometry.js'

export function useViewDrag({ placedViews, selectedViewId, toSheetPoint }) {
  const alignmentGuides = ref([])
  let movingView = null
  let moveStartPos = null

  function startMoveView(event, view) {
    selectedViewId.value = view.id
    movingView = view
    const startPoint = toSheetPoint(event)
    moveStartPos = {
      x: startPoint?.x ?? event.clientX,
      y: startPoint?.y ?? event.clientY,
      vx: view.x,
      vy: view.y
    }
  }

  function moveViewTo(event) {
    if (!movingView) return
    const point = toSheetPoint(event)
    const dx = (point?.x ?? event.clientX) - moveStartPos.x
    const dy = (point?.y ?? event.clientY) - moveStartPos.y
    let newX = moveStartPos.vx + dx
    let newY = moveStartPos.vy + dy

    // 当前视图中心 → 投影对齐吸附
    const center = {
      x: newX + (movingView.contentBBox.x + movingView.contentBBox.width / 2) * movingView.scale,
      y: newY + (movingView.contentBBox.y + movingView.contentBBox.height / 2) * movingView.scale
    }
    const alignment = detectAlignment(center.x, center.y, movingView.id, placedViews.value, pv => pv.scale)
    newX += alignment.snapDx
    newY += alignment.snapDy
    alignmentGuides.value = alignment.guides

    movingView.x = newX
    movingView.y = newY
  }

  function endMoveView() {
    movingView = null
    moveStartPos = null
    alignmentGuides.value = []
  }

  function clearGuides() {
    alignmentGuides.value = []
  }

  return { alignmentGuides, startMoveView, moveViewTo, endMoveView, clearGuides }
}
