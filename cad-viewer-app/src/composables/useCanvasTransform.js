// 图纸画布:整卡缩放/平移。
// SVG 内部图纸坐标固定,外层卡片位置尺寸统一变化
// (白卡/图框/标题栏/视图/标注始终作为同一整体移动)。
// sheet 尺寸即图纸毫米尺寸(A3=420x297, A4=297x210, A0=1189x841),
// 后端 PDF 直接以此尺寸渲染,不再做映射转换。
import { ref, computed } from 'vue'

const SHEET_ZOOM_MIN = 0.35
const SHEET_ZOOM_MAX = 4
const SHEET_ZOOM_STEP = 1.12

// 标准图纸毫米尺寸(横向,长边为 width)
export const SHEET_SIZES = {
  A0: { size: 'A0', width: 1189, height: 841 },
  A1: { size: 'A1', width: 841, height: 594 },
  A2: { size: 'A2', width: 594, height: 420 },
  A3: { size: 'A3', width: 420, height: 297 },
  A4: { size: 'A4', width: 297, height: 210 }
}

export function useCanvasTransform() {
  const sheetAreaRef = ref(null)
  const sheetSize = ref('A3')  // 默认 A3(与后端 PDF 输出尺寸一致)
  const sheetWidth = ref(SHEET_SIZES.A3.width)
  const sheetHeight = ref(SHEET_SIZES.A3.height)
  const sheetZoom = ref(1)
  const sheetPan = ref({ x: 0, y: 0 })
  const sheetPanning = ref(null)

  const sheetCardStyle = computed(() => ({
    left: `${sheetPan.value.x}px`,
    top: `${sheetPan.value.y}px`
  }))

  /** 切换图纸尺寸,触发居中重排 */
  function setSheetSize(name) {
    const cfg = SHEET_SIZES[name]
    if (!cfg) return
    sheetSize.value = cfg.size
    sheetWidth.value = cfg.width
    sheetHeight.value = cfg.height
    centerSheet()
  }

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
    sheetAreaRef, sheetSize, sheetWidth, sheetHeight,
    sheetZoom, sheetPan, sheetPanning, sheetCardStyle,
    setSheetSize,
    centerSheet, startSheetPan, updateSheetPan, endSheetPan, onSheetWheel
  }
}
