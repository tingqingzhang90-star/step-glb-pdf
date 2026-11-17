// 断裂视图几何,镜像 src/drawing/break_view.py。
// 断裂只改渲染坐标:边线按双段裁剪 + 右段平移绘制,edges 数组与下标不动,
// 标注端点走 projectPoint 后自动贴到切口,尺寸数值仍取 spanMm 的真实 mm。

export const DEFAULT_WAVE_AMP = 3
export const DEFAULT_WAVE_CYCLES = 3
export const DEFAULT_VISUAL_GAP = 6

/**
 * @typedef {object} BreakSpec
 * @property {'x'|'y'} axis
 * @property {number} cutA
 * @property {number} cutB
 * @property {number} pxPerMm
 * @property {number} waveAmp
 * @property {number} waveCycles
 * @property {number} visualGap
 */

export function breakShift(spec) {
  return spec ? (spec.cutB - spec.cutA) - spec.visualGap : 0
}

export function rightCut(spec) {
  return spec.cutA + spec.visualGap
}

/** 落盘字段缺失或几何无效时按无断裂处理,兼容旧源文件 */
export function parseBreakSpec(raw) {
  if (!raw || typeof raw !== 'object' || (raw.axis !== 'x' && raw.axis !== 'y')) return null
  const spec = {
    axis: raw.axis,
    cutA: Number(raw.cutA),
    cutB: Number(raw.cutB),
    pxPerMm: Number(raw.pxPerMm),
    waveAmp: Number(raw.waveAmp ?? DEFAULT_WAVE_AMP),
    waveCycles: Number(raw.waveCycles ?? DEFAULT_WAVE_CYCLES),
    visualGap: Number(raw.visualGap ?? DEFAULT_VISUAL_GAP)
  }
  const valid = [spec.cutA, spec.cutB, spec.pxPerMm, spec.waveAmp,
    spec.waveCycles, spec.visualGap].every(Number.isFinite)
  if (!valid || breakShift(spec) < spec.visualGap || spec.pxPerMm <= 0 || spec.waveCycles < 1) return null
  return spec
}

/** 轴向画布坐标投影;落在断裂带内返回 null(该点被裁掉) */
export function projectCoord(valuePx, spec) {
  if (!spec) return valuePx
  if (valuePx <= spec.cutA) return valuePx
  if (valuePx >= spec.cutB) return valuePx - breakShift(spec)
  return null
}

/** 带内点钳到最近切口,供标注端点使用(永不返回 null) */
export function clampCoord(valuePx, spec) {
  const v = projectCoord(valuePx, spec)
  if (v !== null) return v
  const mid = (spec.cutA + spec.cutB) / 2
  return valuePx < mid ? spec.cutA : rightCut(spec)
}

export function projectPoint(x, y, spec) {
  if (!spec) return { x, y }
  const v = clampCoord(spec.axis === 'x' ? x : y, spec)
  return spec.axis === 'x' ? { x: v, y } : { x, y: v }
}

/** 双段裁剪范围 [[lo, hi, shift], ...],坐标是裁剪前的画布 px */
export function clipRanges(spec, canvasSize) {
  if (!spec) return [[0, canvasSize, 0]]
  return [
    [0, spec.cutA, 0],
    [spec.cutB, canvasSize, -breakShift(spec)]
  ]
}

/** 断裂后视图实际占位,供命中底板与 viewSheetRect 使用 */
export function effectiveContentBox(contentBBox, spec) {
  if (!contentBBox) return null
  const box = { ...contentBBox }
  if (!spec) return box
  const d = breakShift(spec)
  if (spec.axis === 'x') box.width = Math.max(1, box.width - d)
  else box.height = Math.max(1, box.height - d)
  return box
}

/** 两条折断波浪线点列(画布 px) */
export function wavePoints(spec, crossLo, crossHi) {
  if (!spec || crossHi <= crossLo) return [[], []]
  const n = Math.max(12, spec.waveCycles * 12)
  const span = crossHi - crossLo
  const left = []
  const right = []
  for (let i = 0; i <= n; i++) {
    const t = i / n
    const c = crossLo + span * t
    const d = spec.waveAmp * Math.sin(2 * Math.PI * spec.waveCycles * t)
    const a = spec.cutA + d
    const b = rightCut(spec) + d
    left.push(spec.axis === 'x' ? [a, c] : [c, a])
    right.push(spec.axis === 'x' ? [b, c] : [c, b])
  }
  return [left, right]
}

export function pointsToPath(points) {
  if (!points || !points.length) return ''
  return points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`).join(' ')
}

/** 从视图 contentBBox 推导两条波浪线的 SVG path */
export function wavePaths(view) {
  const spec = parseBreakSpec(view?.break)
  if (!spec || !view.contentBBox) return []
  const cb = view.contentBBox
  const crossLo = spec.axis === 'x' ? cb.y : cb.x
  const crossHi = crossLo + (spec.axis === 'x' ? cb.height : cb.width)
  const [left, right] = wavePoints(spec, crossLo, crossHi)
  return [pointsToPath(left), pointsToPath(right)]
}
