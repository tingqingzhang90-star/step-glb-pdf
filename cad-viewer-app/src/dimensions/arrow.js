import styleConfig from '../../../cad_viewer_style.json'

// 标注箭头几何：长尖实心箭头，支持沿尺寸线向外(常态)与向内(小尺寸)
// 返回 SVG <polygon> 的 points 字符串，图纸坐标。

// 箭头尺寸由 cad_viewer_style.json 的 dim.arrow 控制(与后端共用)
const ARROW_LEN = styleConfig.dim.arrow.len_px
const ARROW_HALF = styleConfig.dim.arrow.half_px

// 线性标注尺寸线两端向外延长量：箭头由外向内(inward)时，
// 尺寸线穿过箭头再向两侧延伸，工程图常见画法(标准 ISO/GB 也有类似习惯)。
// 放到 cad_viewer_style.json 的 dim.arrow.extension_px，前后端共用同一值。
const LINE_EXTENSION_PX = styleConfig.dim.arrow.extension_px ?? ARROW_LEN * 2

function invert(dir) {
  return { x: -dir.x, y: -dir.y }
}

// end: 箭头尖端落点；dir: 单位向量，指向箭头尖端方向；outward: true 从尺寸线指向被测边
export function buildArrowPoints(end, dir, outward = true) {
  const tip = outward ? dir : invert(dir)
  const back = invert(tip)
  const perp = { x: -tip.y, y: tip.x }
  const baseX = end.x + back.x * ARROW_LEN
  const baseY = end.y + back.y * ARROW_LEN
  const w = ARROW_HALF
  return [
    `${end.x},${end.y}`,
    `${baseX + perp.x * w},${baseY + perp.y * w}`,
    `${baseX - perp.x * w},${baseY - perp.y * w}`
  ].join(' ')
}

// 估计标注文字宽度(图纸像素)，用于小尺寸时翻转箭头方向
export function estimateTextWidth(text) {
  return String(text || '').length * 7 + 8
}

// 两端箭头方向决策：尺寸线两端各一个长尖箭头。
// 空间足够 → 向外(尖端指向尺寸界线)；空间不足 → 向内(尖端相对，文字移到外侧)
export function linearArrowDirs(start, end, text) {
  const dx = end.x - start.x
  const dy = end.y - start.y
  const len = Math.hypot(dx, dy) || 1
  const unit = { x: dx / len, y: dy / len }
  const arrowSpan = ARROW_LEN * 2 + estimateTextWidth(text) + 12
  if (len >= arrowSpan) {
    return { outward: true, unit }
  }
  return { outward: false, unit }
}

function resolveOutward(start, end, text, mode) {
  if (mode === 'outward') return true
  if (mode === 'inward') return false
  const { outward } = linearArrowDirs(start, end, text)
  return outward
}

// 线性标注两端箭头：start→end 为尺寸线方向。
// mode='auto' 按空间自动；'outward' 强制尖端朝外(由中间指向两边)；
// 'inward' 强制尖端相对(由两边指向中间)，尾部自然出头尺寸线。
export function buildLinearArrows(start, end, unit, text, mode = 'auto') {
  const outward = resolveOutward(start, end, text, mode)
  const dir1 = outward ? invert(unit) : unit
  const dir2 = outward ? unit : invert(unit)
  return {
    outward,
    arrow1: buildArrowPoints(start, dir1, true),
    arrow2: buildArrowPoints(end, dir2, true)
  }
}

// 尺寸线两端实际起止：outward 时等于箭头尖端；inward 时穿过箭头向外延伸。
// extStartPx / extEndPx: 可选，分别覆盖全局 LINE_EXTENSION_PX（单侧独立调整延长量）。
export function extendLinearLine(start, end, outward, unit, extStartPx, extEndPx) {
  const extS = extStartPx ?? LINE_EXTENSION_PX
  const extE = extEndPx ?? LINE_EXTENSION_PX
  if (outward) {
    return { lineStart: start, lineEnd: end }
  }
  return {
    lineStart: { x: start.x - unit.x * extS, y: start.y - unit.y * extS },
    lineEnd:   { x: end.x   + unit.x * extE, y: end.y   + unit.y * extE }
  }
}

export { LINE_EXTENSION_PX }
