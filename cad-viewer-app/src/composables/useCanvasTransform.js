// 图纸画布:整卡缩放/平移。
// SVG 内部图纸坐标固定,外层卡片位置尺寸统一变化
// (白卡/图框/标题栏/视图/标注始终作为同一整体移动)。
import { ref, computed } from 'vue'

const SHEET_ZOOM_MIN = 0.35
const SHEET_ZOOM_MAX = 4
const SHEET_ZOOM_STEP = 1.12

export function useCanvasTransform() {
  const sheetAreaRef = ref(null)
  const sheetWidth = ref(1189)
  const sheetHeight = ref(841)
  const sheetZoom = ref(1)
  const sheetPan = ref({ x: 0, y: 0 })
  const sheetPanning = ref(null)

  const sheetCardStyle = computed(() => ({
    left: `${sheetPan.value.x}px`,
    top: `${sheetPan.value.y}px`
  }))

  /** 首次挂载时把图纸卡在工作区内居中 */
  function centerSheet() {
    const area = sheetAreaRef.value
    if (!area) return
    sheetPan.value = {
      x: (area.clientWidth - sheetWidth.value) / 2,
      y: (area.clientHeight - sheetHeight.value) / 2
    }
  }

  /** 中键按下:开始整卡平移 */
  function startSheetPan(event) {
    sheetPanning.value = {
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: sheetPan.value.x,
      startY: sheetPan.value.y
    }
    document.body.classList.add('sheet-panning')
  }

  /** 平移进行中:卡片是 CSS 绝对定位,直接用屏幕像素差 */
  function updateSheetPan(event) {
    const drag = sheetPanning.value
    if (!drag) return
    sheetPan.value = {
      x: drag.startX + event.clientX - drag.startClientX,
      y: drag.startY + event.clientY - drag.startClientY
    }
  }

  function endSheetPan() {
    if (!sheetPanning.value) return
    sheetPanning.value = null
    document.body.classList.remove('sheet-panning')
  }

  /** 滚轮缩放:保持鼠标下的卡片点不动 */
  function onSheetWheel(event) {
    event.preventDefault()
    const direction = event.deltaY < 0 ? SHEET_ZOOM_STEP : 1 / SHEET_ZOOM_STEP
    const oldZoom = sheetZoom.value
    const newZoom = Math.max(SHEET_ZOOM_MIN, Math.min(SHEET_ZOOM_MAX, oldZoom * direction))
    if (newZoom === oldZoom) return

    // sheetPan 是 sheet-area 本地坐标,不能与 clientX/clientY(屏幕坐标)混算
    const areaRect = sheetAreaRef.value?.getBoundingClientRect()
    if (!areaRect) return
    const pointerX = event.clientX - areaRect.left
    const pointerY = event.clientY - areaRect.top
    const ratio = newZoom / oldZoom
    sheetZoom.value = newZoom
    sheetPan.value = {
      x: pointerX - (pointerX - sheetPan.value.x) * ratio,
      y: pointerY - (pointerY - sheetPan.value.y) * ratio
    }
  }

  return {
    sheetAreaRef, sheetWidth, sheetHeight,
    sheetZoom, sheetPan, sheetPanning, sheetCardStyle,
    centerSheet, startSheetPan, updateSheetPan, endSheetPan, onSheetWheel
  }
}
