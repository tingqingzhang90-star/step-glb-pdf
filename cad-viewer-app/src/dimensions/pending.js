// 线性标注"待固定"阶段：选完被测对象后预览跟随鼠标，再点一次左键才落位。
// 单独成文件，避免交互状态机（index.js）膨胀。

import { toLineSeg, toCircle, isParallel } from './geometry.js'

/**
 * 判定两个选中对象能构成的线性标注模式，不成立返回 null。
 * second 为 null 表示只选了一根边线（单边对齐标注）。
 * circle-edge 模式约定 first 为圆、second 为线。
 */
export function resolveLinearMode(first, second) {
  if (!first) return null
  if (!second) {
    return toLineSeg(first.seg) ? { mode: 'single', first, second: null } : null
  }
  const firstIsCircle = !!toCircle(first.seg)
  const secondIsCircle = !!toCircle(second.seg)
  if (firstIsCircle && secondIsCircle) return { mode: 'center', first, second }
  if (firstIsCircle && toLineSeg(second.seg)) return { mode: 'circle-edge', first, second }
  if (toLineSeg(first.seg) && secondIsCircle) return { mode: 'circle-edge', first: second, second: first }
  if (isParallel(first.seg, second.seg)) return { mode: 'parallel', first, second }
  return null
}

/** 待固定态预览：模式已定，只让偏移跟随鼠标 */
export function buildPendingPreview(core, pending, mousePos) {
  const P = core.previewBuilders
  const { mode, first, second } = pending
  if (mode === 'parallel') return P.linearParallel(first, second, mousePos)
  if (mode === 'center') return P.linearCenter(first, second, mousePos)
  if (mode === 'circle-edge') return P.linearCircleEdge(first, second, mousePos)
  return P.linearSingle(first, mousePos)
}

/** 落位：按当前偏移写入标注列表，返回新标注 id */
export function commitPending(core, pending, offset) {
  const { mode, first, second } = pending
  if (mode === 'parallel') return core.placeLinearDimParallel(first, second, offset)
  if (mode === 'center') return core.placeLinearCenterDim(first, second, offset)
  if (mode === 'circle-edge') return core.placeLinearCircleEdgeDim(first, second, offset)
  return core.placeLinearDimSingle(first, offset)
}
