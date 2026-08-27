// 标注箭头几何：长尖实心箭头，支持沿尺寸线向外(常态)与向内(小尺寸)
// 返回 SVG <polygon> 的 points 字符串，图纸坐标。

const ARROW_LEN = 14 // 箭头长度(图纸像素)
const ARROW_HALF = 1.6 // 箭头底部半宽，越小越尖锐

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

// 线性标注两端箭头：start→end 为尺寸线方向。
// outward=true：箭头尖端在端点，方向朝外(指向延伸线/被测边)；
// 空间不足(小尺寸)翻转：箭头尖端相对，文字放到外侧。
export function buildLinearArrows(start, end, unit, text) {
  const { outward } = linearArrowDirs(start, end, text)
  const dir1 = outward ? invert(unit) : unit
  const dir2 = outward ? unit : invert(unit)
  return {
    outward,
    arrow1: buildArrowPoints(start, dir1, true),
    arrow2: buildArrowPoints(end, dir2, true)
  }
}
