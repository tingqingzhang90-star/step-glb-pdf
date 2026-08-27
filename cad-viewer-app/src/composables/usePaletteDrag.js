// 调色板拖拽放置:pointer 事件 + rAF 节流预览 + 点击放置
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getCenteredViewPlacement, getInitialViewScale } from '@/views/viewGeometry.js'

const DRAG_THRESHOLD = 4 // 位移超过该值才算拖拽,否则视为点击

export function usePaletteDrag({ coords, views, sheetWidth, sheetHeight }) {
  const draggingFromPalette = ref(false)
  const draggingView = ref(null)
  const dragPreviewPos = ref(null)

  let pointerStart = null
  let pendingPointer = null
  let animationFrame = 0

  function onPalettePointerDown(event, view) {
    if (event.button !== 0) return
    event.preventDefault()
    draggingView.value = view
    pointerStart = { x: event.clientX, y: event.clientY }
    pendingPointer = event
  }

  function updatePreview() {
    animationFrame = 0
    const event = pendingPointer
    pendingPointer = null
    if (!event || !draggingView.value) return

    if (!draggingFromPalette.value) {
      const dx = event.clientX - pointerStart.x
      const dy = event.clientY - pointerStart.y
      if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return
      draggingFromPalette.value = true
      document.body.classList.add('palette-pointer-dragging')
    }

    if (!coords.isPointerOverSheet(event)) {
      dragPreviewPos.value = null
      return
    }
    const point = coords.eventToSheetPoint(event)
    if (point) {
      dragPreviewPos.value = getCenteredViewPlacement(
        draggingView.value, point,
        views.globalScale.value ?? getInitialViewScale(draggingView.value)
      )
    }
  }

  function onPalettePointerMove(event) {
    if (!draggingView.value || !pointerStart) return
    event.preventDefault()
    pendingPointer = event
    if (!animationFrame) {
      animationFrame = requestAnimationFrame(updatePreview)
    }
  }

  function onPalettePointerUp(event) {
    if (!draggingView.value || !pointerStart) return
    const view = draggingView.value
    const wasDragging = draggingFromPalette.value

    if (wasDragging && coords.isPointerOverSheet(event)) {
      // 唯一性检查:拖拽放置前
      if (!views.placedViews.value.some(pv => pv.name === view.name)) {
        const point = coords.eventToSheetPoint(event)
        if (point) {
          const placement = getCenteredViewPlacement(
            view, point,
            views.globalScale.value ?? getInitialViewScale(view)
          )
          views.placeView(view, placement.x, placement.y)
        }
      } else {
        ElMessage.warning(`「${view.label}」已存在于图纸中`)
      }
    } else if (!wasDragging) {
      onPaletteClick(view)
    }
    resetPaletteDrag()
  }

  /** 点击调色板项:以图纸中心为落点直接放置 */
  function onPaletteClick(view) {
    if (views.globalScale.value == null) {
      views.globalScale.value = getInitialViewScale(view)
    }
    const placement = getCenteredViewPlacement(view, {
      x: sheetWidth.value / 2,
      y: sheetHeight.value / 2
    }, views.globalScale.value)
    views.placeView(view, placement.x, placement.y)
  }

  function resetPaletteDrag() {
    if (animationFrame) cancelAnimationFrame(animationFrame)
    animationFrame = 0
    pendingPointer = null
    pointerStart = null
    draggingFromPalette.value = false
    draggingView.value = null
    dragPreviewPos.value = null
    document.body.classList.remove('palette-pointer-dragging')
  }

  /** 组件卸载时清理 rAF */
  function dispose() {
    if (animationFrame) cancelAnimationFrame(animationFrame)
  }

  return {
    draggingFromPalette, draggingView, dragPreviewPos,
    onPalettePointerDown, onPalettePointerMove, onPalettePointerUp,
    resetPaletteDrag, dispose
  }
}
