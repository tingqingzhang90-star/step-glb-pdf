// 画布触控手势:单指平移、双指缩放(围绕双指中点)。
// 仅用于移动端查看浏览,不触发任何编辑逻辑;复用 useCanvasTransform 的
// sheetZoom / sheetPan 状态,缩放数学与 onSheetWheel 保持一致。
import { onMounted, onUnmounted } from 'vue'

const SHEET_ZOOM_MIN = 0.35
const SHEET_ZOOM_MAX = 4

export function useTouchCanvas({ areaRef, sheetZoom, sheetPan }) {
  let panStart = null
  let lastDist = 0

  const clampZoom = (z) => Math.max(SHEET_ZOOM_MIN, Math.min(SHEET_ZOOM_MAX, z))
  const dist = (a, b) => Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)
  const center = (a, b) => ({ x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2 })

  function onTouchStart(e) {
    if (e.touches.length === 1) {
      const t = e.touches[0]
      panStart = { x: t.clientX, y: t.clientY, px: sheetPan.value.x, py: sheetPan.value.y }
    } else if (e.touches.length === 2) {
      panStart = null
      lastDist = dist(e.touches[0], e.touches[1])
    }
  }

  function onTouchMove(e) {
    if (e.touches.length === 1 && panStart) {
      const t = e.touches[0]
      sheetPan.value = {
        x: panStart.px + (t.clientX - panStart.x),
        y: panStart.py + (t.clientY - panStart.y)
      }
      e.preventDefault()
    } else if (e.touches.length === 2 && lastDist > 0) {
      const area = areaRef.value?.getBoundingClientRect()
      if (!area) return
      const d = dist(e.touches[0], e.touches[1])
      const c = center(e.touches[0], e.touches[1])
      const oldZoom = sheetZoom.value
      const newZoom = clampZoom(oldZoom * (d / lastDist))
      if (newZoom !== oldZoom) {
        const px = c.x - area.left
        const py = c.y - area.top
        const ratio = newZoom / oldZoom
        sheetZoom.value = newZoom
        sheetPan.value = {
          x: px - (px - sheetPan.value.x) * ratio,
          y: py - (py - sheetPan.value.y) * ratio
        }
      }
      lastDist = d
      e.preventDefault()
    }
  }

  function onTouchEnd(e) {
    if (e.touches.length === 0) {
      panStart = null
      lastDist = 0
    } else if (e.touches.length === 1) {
      // 双指松开一根后回到单指:重置平移起点,避免跳变
      const t = e.touches[0]
      panStart = { x: t.clientX, y: t.clientY, px: sheetPan.value.x, py: sheetPan.value.y }
      lastDist = 0
    }
  }

  onMounted(() => {
    const el = areaRef.value
    if (!el) return
    el.addEventListener('touchstart', onTouchStart, { passive: false })
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    el.addEventListener('touchend', onTouchEnd)
    el.addEventListener('touchcancel', onTouchEnd)
  })

  onUnmounted(() => {
    const el = areaRef.value
    if (!el) return
    el.removeEventListener('touchstart', onTouchStart)
    el.removeEventListener('touchmove', onTouchMove)
    el.removeEventListener('touchend', onTouchEnd)
    el.removeEventListener('touchcancel', onTouchEnd)
  })
}
