// 标注几何与边线识别工具（纯函数，无 Vue 依赖）
// 从 App.vue 抽离：toLineSeg / toCircle / 圆拟合 / 平行判断 / 点线运算 / 圆弧 path 等。

import styleConfig from '../../../cad_viewer_style.json'

/**
 * 将 line/polyline 规整为可标注的两点线段。
 * 后端对 BSpline 面的 HLR 剪影线会离散为 polyline(气缸等模型占大多数),
 * 视觉上近似直线;此处检测其是否近似直线:
 *   - 是 → 返回 {x1,y1,x2,y2,meta} 供几何计算与标注
 *   - 否(真曲线) → 返回 null，不做直线类标注
 */
export function toLineSeg(seg) {
  if (!seg) return null
  if (seg.type === 'line') {
    return { x1: seg.x1, y1: seg.y1, x2: seg.x2, y2: seg.y2, meta: seg.meta }
  }
  if (seg.type === 'polyline' && seg.points && seg.points.length >= 2) {
    const pts = seg.points
    const x1 = pts[0][0], y1 = pts[0][1]
    const x2 = pts[pts.length - 1][0], y2 = pts[pts.length - 1][1]
    const len = Math.hypot(x2 - x1, y2 - y1)
    if (len < 0.01) return null
    // 所有点到首尾连线的最大法向偏差
    let maxDev = 0
    for (let i = 1; i < pts.length - 1; i++) {
      const px = pts[i][0], py = pts[i][1]
      const cross = Math.abs((x2 - x1) * (y1 - py) - (x1 - px) * (y2 - y1))
      maxDev = Math.max(maxDev, cross / len)
    }
    // 偏差超过直线长度的 1.5% 视为曲线，不做直线标注
    if (maxDev > 0.015 * len) return null
    return { x1, y1, x2, y2, meta: seg.meta }
  }
  return null
}

/** 三点定圆：由 polyline 上三个采样点求圆心与半径（仅作为退化兜底） */
export function fitCircleFromPoints(pts) {
  if (!pts || pts.length < 3) return null
  const n = pts.length
  // 均匀取三个点，尽量分散
  const a = pts[0]
  const b = pts[Math.floor(n / 3)]
  const c = pts[Math.floor((2 * n) / 3)]
  const ax = a[0], ay = a[1]
  const bx = b[0], by = b[1]
  const cx = c[0], cy = c[1]
  const d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
  if (Math.abs(d) < 1e-6) return null
  const a2 = ax * ax + ay * ay
  const b2 = bx * bx + by * by
  const c2 = cx * cx + cy * cy
  const ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
  const uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
  const r = Math.hypot(ax - ux, ay - uy)
  if (r < 0.01) return null
  return { cx: ux, cy: uy, r }
}

/**
 * Kasa 最小二乘圆拟合：最小化各点到拟合圆半径差的平方和。
 * 用于后端未携带圆几何元数据时的工业级兜底（利用全部采样点而非三点）。
 * 返回 {cx, cy, r, maxDev}
 */
export function fitCircleLeastSquares(pts) {
  if (!pts || pts.length < 4) return fitCircleFromPoints(pts)
  let u = 0, v = 0
  const n = pts.length
  for (const p of pts) {
    u += p[0]
    v += p[1]
  }
  u /= n
  v /= n
  // 中心化，构造线性方程组 Sum{ (ui*u + vi*v + w) * [ui, vi, 1] } = 0 (Kasa)
  let suu = 0, suv = 0, svv = 0, su = 0, sv = 0, sf = 0
  for (const p of pts) {
    const ui = p[0] - u
    const vi = p[1] - v
    const fi = ui * ui + vi * vi
    suu += ui * ui
    suv += ui * vi
    svv += vi * vi
    su += ui
    sv += vi
  }
  // 简化：中心化后 su/sv≈0，按 Kasa 直接解 2x2
  const denom = suu * svv - suv * suv
  if (Math.abs(denom) < 1e-9) return fitCircleFromPoints(pts)
  let sumUiF = 0, sumViF = 0
  for (const p of pts) {
    const ui = p[0] - u
    const vi = p[1] - v
    const fi = ui * ui + vi * vi
    sumUiF += ui * fi
    sumViF += vi * fi
  }
  const cu = (svv * sumUiF - suv * sumViF) / (2 * denom)
  const cv = (suu * sumViF - suv * sumUiF) / (2 * denom)
  const cx = cu + u
  const cy = cv + v
  let r2 = 0
  for (const p of pts) {
    r2 += (p[0] - cx) * (p[0] - cx) + (p[1] - cy) * (p[1] - cy)
  }
  const r = Math.sqrt(r2 / n)
  if (!isFinite(r) || r < 0.01) return null
  // 校验：所有点相对拟合圆的最大偏差（用于拒绝曲线边被误认成圆）
  let maxDev = 0
  for (const p of pts) {
    const dist = Math.abs(Math.hypot(p[0] - cx, p[1] - cy) - r)
    if (dist > maxDev) maxDev = dist
  }
  if (maxDev > Math.max(r * 0.10, 0.8)) return null
  return { cx, cy, r, maxDev }
}

/**
 * 将 circle/polyline 规整为可标注的圆（工业级精度）：
 *   - circle：直接使用其圆心/半径
 *   - polyline 且携带后端 CAD 元数据(curve='circle')：优先使用真实圆心/半径（mm）
 *   - 其余 polyline：Kasa 最小二乘拟合兜底
 * 返回 {cx, cy, r, meta}
 */
export function toCircle(seg) {
  if (!seg) return null
  if (seg.type === 'circle') {
    return { cx: seg.cx, cy: seg.cy, r: seg.r, meta: seg.meta }
  }
  if (seg.type === 'polyline' && seg.points && seg.points.length >= 3) {
    // 首选后端 CAD 元数据：真实圆心(像素)与半径(px/mm)
    const meta = seg.meta
    if (meta && meta.curve === 'circle' && Array.isArray(meta.center) && meta.center.length === 2) {
      if (typeof meta.radius_px === 'number' && meta.radius_px > 0) {
        return { cx: meta.center[0], cy: meta.center[1], r: meta.radius_px, meta }
      }
    }
    // 兜底：最小二乘拟合
    const fit = fitCircleLeastSquares(seg.points)
    if (!fit) return null
    return { cx: fit.cx, cy: fit.cy, r: fit.r, meta: seg.meta }
  }
  return null
}

/** 把角度差归一化到 [-π, π] */
function normAngleDelta(d) {
  while (d > Math.PI) d -= Math.PI * 2
  while (d < -Math.PI) d += Math.PI * 2
  return d
}

// 补齐弧越过箭头接触角的出头量(弧度,约 8°)
export const ARC_PATCH_OVERSHOOT = 0.14

/**
 * 计算圆边线在给定角度处的补齐弧范围(仅对后端标记的部分弧生效)。
 *   - 整圆(circle)/已有弧覆盖该角度/无弧元数据的拟合圆 → null(不补)
 *   - 部分弧且该角度缺失:补弧从"离箭头最近的已有弧端点"无缝接出,
 *     沿缺失段拉到箭头接触角,再向前出头 ARC_PATCH_OVERSHOOT
 * 返回 { start, span, dir }:start=起始角,span=弧长(弧度,含出头),
 * dir=拉伸方向(±1),终角 = start + dir*span;无需补时返回 null。
 */
export function arcPatchRange(seg, circ, angle) {
  if (!seg || !circ) return null
  if (seg.type === 'circle') return null
  if (seg.type !== 'polyline' || !Array.isArray(seg.points)) return null
  const meta = seg.meta
  if (!meta || meta.curve !== 'circle') return null
  if (typeof meta.arc_span === 'number' && meta.arc_span >= Math.PI * 2 - 0.15) return null
  const pts = seg.points
  if (pts.length < 2) return null
  const angles = pts.map(p => Math.atan2(p[1] - circ.cy, p[0] - circ.cx))
  let maxStep = 0
  for (let i = 1; i < angles.length; i++) {
    const d = Math.abs(normAngleDelta(angles[i] - angles[i - 1]))
    if (d > maxStep) maxStep = d
  }
  const tol = maxStep / 2 + 0.02
  for (const a of angles) {
    if (Math.abs(normAngleDelta(angle - a)) <= tol) return null
  }
  // 从较近的弧端点出发,朝箭头方向拉弧
  const a0 = angles[0]
  const a1 = angles[angles.length - 1]
  const d0 = Math.abs(normAngleDelta(angle - a0))
  const d1 = Math.abs(normAngleDelta(angle - a1))
  const start = d0 <= d1 ? a0 : a1
  const dir = normAngleDelta(angle - start) >= 0 ? 1 : -1
  const span = Math.abs(normAngleDelta(angle - start)) + ARC_PATCH_OVERSHOOT
  return { start, span, dir }
}

/** 判断两条线段是否平行（角度差 < 5°），line/polyline 视为直线 */
export function isParallel(seg1, seg2) {
  const l1 = toLineSeg(seg1)
  const l2 = toLineSeg(seg2)
  if (!l1 || !l2) return false
  const dx1 = l1.x2 - l1.x1, dy1 = l1.y2 - l1.y1
  const dx2 = l2.x2 - l2.x1, dy2 = l2.y2 - l2.y1
  const len1 = Math.hypot(dx1, dy1), len2 = Math.hypot(dx2, dy2)
  if (len1 < 0.01 || len2 < 0.01) return false
  const dot = (dx1 * dx2 + dy1 * dy2) / (len1 * len2)
  return Math.abs(dot) > 0.996  // ≈ 5°
}

/** 点到线段的最近点 */
export function closestPointOnLine(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1
  const lenSq = dx * dx + dy * dy
  if (lenSq < 0.01) return { x: x1, y: y1, t: 0 }
  let t = ((px - x1) * dx + (py - y1) * dy) / lenSq
  t = Math.max(0, Math.min(1, t))
  return { x: x1 + t * dx, y: y1 + t * dy, t }
}

/** 线段基：单位方向 / 法向 / 长度 */
export function lineBasis(p1, p2) {
  const dx = p2.x - p1.x
  const dy = p2.y - p1.y
  const len = Math.hypot(dx, dy)
  if (len < 0.5) return null
  const unit = { x: dx / len, y: dy / len }
  return { unit, perp: { x: -unit.y, y: unit.x }, len }
}

/** 点沿方向偏移指定距离 */
export function offsetPoint(point, dir, distance) {
  return { x: point.x + dir.x * distance, y: point.y + dir.y * distance }
}

/** 点到过某点沿法向直线的有符号距离 */
export function signedDistanceToLine(point, linePoint, normal) {
  return (point.x - linePoint.x) * normal.x + (point.y - linePoint.y) * normal.y
}

/** 点向直线的投影 */
export function projectPointToLine(point, linePoint, dir) {
  const t = (point.x - linePoint.x) * dir.x + (point.y - linePoint.y) * dir.y
  return { x: linePoint.x + dir.x * t, y: linePoint.y + dir.y * t }
}

/** 两条直线交点（由各自两个端点定义）；平行/重合返回 null */
export function lineIntersection(p1, p2, q1, q2) {
  const d1x = p2.x - p1.x, d1y = p2.y - p1.y
  const d2x = q2.x - q1.x, d2y = q2.y - q1.y
  const cross = d1x * d2y - d1y * d2x
  if (Math.abs(cross) < 0.001) return null
  const t = ((q1.x - p1.x) * d2y - (q1.y - p1.y) * d2x) / cross
  return { x: p1.x + t * d1x, y: p1.y + t * d1y }
}

/** 两点中距给定点更远的一个 */
export function farthestEndpointFrom(point, a, b) {
  const distanceA = Math.hypot(a.x - point.x, a.y - point.y)
  const distanceB = Math.hypot(b.x - point.x, b.y - point.y)
  return distanceA >= distanceB ? a : b
}

/** 构建圆弧 SVG path（折线近似） */
export function buildArcPath(cx, cy, r, startAngle, endAngle) {
  const steps = 20
  const pts = []
  for (let i = 0; i <= steps; i++) {
    const t = startAngle + (endAngle - startAngle) * (i / steps)
    pts.push(`${cx + Math.cos(t) * r},${cy + Math.sin(t) * r}`)
  }
  return `M${pts[0]} L${pts.slice(1).join(' L')}`
}

/**
 * 角度标注弧 path：两端各接一段直线延长线（tail1/tail2 为延长向量）。
 *
 * 延长段必须沿切线走直线，而不能继续沿圆弧延伸：箭头轴线就是弧端点的切线，
 * 只有直线延长才与之严格共线，才能从箭头尾部底中心穿出；继续沿圆弧会因
 * 曲率在尾部附近偏离箭头轴线（放大后看就是从尾部底一角冒出来）。
 */
export function buildAngleArcPath(cx, cy, r, startAngle, endAngle, tail1, tail2) {
  const steps = 20
  const x0 = cx + Math.cos(startAngle) * r
  const y0 = cy + Math.sin(startAngle) * r
  const xn = cx + Math.cos(endAngle) * r
  const yn = cy + Math.sin(endAngle) * r
  const pts = [`${x0 + tail1.x},${y0 + tail1.y}`, `${x0},${y0}`]
  for (let i = 1; i <= steps; i++) {
    const t = startAngle + (endAngle - startAngle) * (i / steps)
    pts.push(`${cx + Math.cos(t) * r},${cy + Math.sin(t) * r}`)
  }
  pts.push(`${xn + tail2.x},${yn + tail2.y}`)
  return `M${pts[0]} L${pts.slice(1).join(' L')}`
}

/** polyline 点数组 → SVG points 字符串 */
export function polylinePoints(points) {
  return points.map(p => `${p[0]},${p[1]}`).join(' ')
}

// ===== 尺寸标注外观(与后端 drawing/dim/dim_render.py 保持一致) =====

/** 尺寸界线越过尺寸线的长度(图纸 mm,取自共用样式配置) */
export const EXT_OVERSHOOT = styleConfig.dim.ext.overshoot_mm ?? 2.5

/** 延伸线终点越过尺寸线一小段 */
export function extendExtEnd(p, e) {
  const dx = e.x - p.x
  const dy = e.y - p.y
  const len = Math.hypot(dx, dy)
  if (len < 1e-6) return { ...e }
  return { x: e.x + (dx / len) * EXT_OVERSHOOT, y: e.y + (dy / len) * EXT_OVERSHOOT }
}

/** linear 文字旋转角(SVG 屏幕坐标):跟随尺寸线方向且不倒置,竖直统一字头朝左 */
export function linearTextAngle(unit) {
  let a = Math.atan2(unit.y, unit.x)
  if (Math.cos(a) < -1e-9) a += Math.PI
  if (Math.abs(Math.abs(a) - Math.PI / 2) < 1e-9) a = -Math.PI / 2
  return a
}

/** 文字与尺寸线的间距(图纸 mm,取自共用样式配置) */
export const DIM_TEXT_GAP = styleConfig.dim.text.gap_mm ?? 4

/** linear 文字位置:沿线滑动 slide,法向偏移 gap;水平在线上方,竖直在左侧 */
export function linearTextPos(unit, mid, gap = DIM_TEXT_GAP, slide = 0) {
  let nx = -unit.y, ny = unit.x
  if (Math.abs(unit.x) < 1e-9) { nx = -1; ny = 0 }
  else if (ny > 0) { nx = -nx; ny = -ny }
  return { x: mid.x + unit.x * slide + nx * gap, y: mid.y + unit.y * slide + ny * gap }
}
