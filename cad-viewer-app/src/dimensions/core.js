// 标注构建/放置/渲染/拖拽核心逻辑（依赖注入，无模板耦合）
// 从 App.vue 抽离：线性(单边/平行/中心距/圆心到边)、直径、角度标注的几何构建与放置。
//
// 依赖注入 deps：
//   getSheetPoint(view, lx, ly)      视图局部坐标 → 图纸坐标
//   getViewDisplayScale(view)        视图显示比例
//   getViewMmScale(view)             bbox.scale（px→mm 换算）
//   edgeRefData(edgeRef)             { viewId, idx, type }
//   getSvgMousePoint(event)          鼠标位置 → 图纸坐标
//   resolveDimRef(ref)               ref → edgeRef
// 可变状态 ctx（对象，跨函数共享）：
//   dimensions(ref)      已放置标注数组
//   dimensionColor(ref)  当前标注颜色
//   idCounter(number)    标注自增 id（按引用递增）

import {
  toLineSeg,
  toCircle,
  isParallel,
  closestPointOnLine,
  lineBasis,
  offsetPoint,
  signedDistanceToLine,
  projectPointToLine,
  lineIntersection,
  farthestEndpointFrom,
  buildArcPath
} from './geometry.js'
import { buildArrowPoints, buildLinearArrows } from './arrow.js'

export function createDimensionCore(deps, ctx) {
  const {
    getSheetPoint,
    getViewDisplayScale,
    getViewMmScale,
    edgeRefData,
    getSvgMousePoint,
    resolveDimRef
  } = deps

  const formatMm = (value) => `${Number(value || 0).toFixed(1).replace(/\.0$/, '')}mm`
  const formatDeg = (value) => `${Number(value || 0).toFixed(1).replace(/\.0$/, '')}°`

  // 从 CAD 原始 mm 坐标(后端 meta.mm_coords)直接计算线段真实长度,
  // 不经过归一化像素缩放,避免缩放/round 引入毫米级误差
  function lineSegMmLength(seg) {
    const m = seg && seg.meta && seg.meta.mm_coords
    if (!m || m.length < 4) return null
    const [x1, y1, x2, y2] = m
    return Math.hypot(x2 - x1, y2 - y1)
  }

  // 从两条线的 CAD 原始 mm 坐标直接算它们的最小垂直间距(平行标注真值),
  // 不经过归一化像素缩放,避免缩放/round 引入毫米级误差
  function parallelSegMmDistance(seg1, seg2) {
    const m1 = seg1 && seg1.meta && seg1.meta.mm_coords
    const m2 = seg2 && seg2.meta && seg2.meta.mm_coords
    if (!m1 || !m2 || m1.length < 4 || m2.length < 4) return null
    // 取两条线段在 mm 坐标系下的端点,求 seg1 上一点到 seg2 所在直线的最短距离
    const [ax1, ay1, ax2, ay2] = m1
    const [bx1, by1, bx2, by2] = m2
    const dx = bx2 - bx1
    const dy = by2 - by1
    const len2 = dx * dx + dy * dy
    if (len2 < 1e-9) return null
    // seg2 单位法向量
    const nx = -dy / Math.sqrt(len2)
    const ny = dx / Math.sqrt(len2)
    // seg1 两端点到 seg2 直线的有符号距离,取绝对值较小者(近似垂直间距)
    const d1 = Math.abs((ax1 - bx1) * nx + (ay1 - by1) * ny)
    const d2 = Math.abs((ax2 - bx1) * nx + (ay2 - by1) * ny)
    return Math.min(d1, d2)
  }

  const nextId = () => `dim_${++ctx.idCounter.value}`

  const pushDim = (data) => {
    ctx.dimensions.value.push(data)
    return data.id
  }

  /** 圆中心（图纸坐标），用于渲染/拖拽定位 */
  function getCircleCenterSheet(edgeRef) {
    if (!edgeRef) return null
    const circ = toCircle(edgeRef.seg)
    if (!circ) return null
    return getSheetPoint(edgeRef.view, circ.cx, circ.cy)
  }

  /**
   * 圆中心（CAD 真值 mm 坐标）。
   * 优先用后端返回的真实中心 mm（对称于 meta.radius 真值半径），
   * 后端需在 circle 元数据补充 center_mm: [x, y]（模型坐标系 mm）。
   * 回退：用归一化像素圆心 ÷ 后端精确比例 bbox.scale，
   * 不经过 displayScale 双重换算，避免缩放/round 引入毫米级误差。
   */
  function getCircleCenterMm(edgeRef) {
    if (!edgeRef) return null
    const circ = toCircle(edgeRef.seg)
    if (!circ) return null
    const meta = circ.meta || {}
    if (Array.isArray(meta.center_mm) && meta.center_mm.length === 2 &&
        typeof meta.center_mm[0] === 'number' && typeof meta.center_mm[1] === 'number') {
      return { x: meta.center_mm[0], y: meta.center_mm[1] }
    }
    const s = getViewMmScale(edgeRef.view)
    if (s) return { x: circ.cx / s, y: circ.cy / s }
    return null
  }

  /** 边线端点的 CAD 真值 mm 坐标（与 lineSegMmLength 同源），用于圆标注垂足投影 */
  function lineMmEndpoints(line) {
    const m = line && line.meta && line.meta.mm_coords
    if (!m || m.length < 4) return null
    return [{ x: m[0], y: m[1] }, { x: m[2], y: m[3] }]
  }

  /** 真值 mm 坐标系下：点 mmC 到边线(mm)所在直线的有符号距离 */
  function pointToLineMmDistance(mmC, mmLine) {
    if (!mmC || !mmLine) return null
    const [a, b] = mmLine
    const dx = b.x - a.x
    const dy = b.y - a.y
    const len2 = dx * dx + dy * dy
    if (len2 < 1e-9) return null
    const nx = -dy / Math.sqrt(len2)
    const ny = dx / Math.sqrt(len2)
    return Math.abs((mmC.x - a.x) * nx + (mmC.y - a.y) * ny)
  }

  // ===== 单边线性标注 =====

  function getLinearOffsetFromMouse(edgeRef, mousePos) {
    if (!edgeRef) return 50
    const { seg, view } = edgeRef
    const line = toLineSeg(seg)
    if (!line || !view || !mousePos) return 50
    const p1 = getSheetPoint(view, line.x1, line.y1)
    const p2 = getSheetPoint(view, line.x2, line.y2)
    const dir = lineBasis(p1, p2)
    if (!dir) return 50
    const mid = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 }
    const raw = (mousePos.x - mid.x) * dir.perp.x + (mousePos.y - mid.y) * dir.perp.y
//    钳位限制 保留4px安全距离
    return Math.max(2, Math.abs(raw)) * (raw >= 0 ? 1 : -1)

  }

  function buildLinearSingleGeometry(edgeRef, offset = 50) {
    if (!edgeRef) return null
    const { seg, view } = edgeRef
    const line = toLineSeg(seg)
    if (!line || !view) return null
    const p1 = getSheetPoint(view, line.x1, line.y1)
    const p2 = getSheetPoint(view, line.x2, line.y2)
    const dir = lineBasis(p1, p2)
    if (!dir) return null
    const extEnd1 = offsetPoint(p1, dir.perp, offset)
    const extEnd2 = offsetPoint(p2, dir.perp, offset)
    // 优先用 CAD 原始 mm 坐标直接计算真实长度(不经过像素缩放,无误差)
    const mmVal = lineSegMmLength(line) ?? Math.hypot(p2.x - p1.x, p2.y - p1.y) / (getViewDisplayScale(view) * getViewMmScale(view))
    return {
      type: 'linear',
      mode: 'single',
      refs: [edgeRefData(edgeRef)],
      offset,
      ext1: p1,
      ext1End: extEnd1,
      ext2: p2,
      ext2End: extEnd2,
      dimStart: extEnd1,
      dimEnd: extEnd2,
      ...(() => {
        const r = buildLinearArrows(extEnd1, extEnd2, dir.unit, formatMm(mmVal))
        return {
          ...r,
          textPos: { x: (extEnd1.x + extEnd2.x) / 2, y: (extEnd1.y + extEnd2.y) / 2 - 3 }
        }
      })(),
      text: formatMm(mmVal)
    }
  }

  function buildLinearSinglePreview(edgeRef, mousePos) {
    const offset = getLinearOffsetFromMouse(edgeRef, mousePos)
    return buildLinearSingleGeometry(edgeRef, offset)
  }

  // ===== 平行线间距 =====

  function getParallelOffsetFromMouse(edgeRef, mousePos) {
    if (!edgeRef) return 50
    const { seg, view } = edgeRef
    const line = toLineSeg(seg)
    if (!line || !view || !mousePos) return 50
    const p1 = getSheetPoint(view, line.x1, line.y1)
    const p2 = getSheetPoint(view, line.x2, line.y2)
    const dir = lineBasis(p1, p2)
    if (!dir) return 50
    const raw = signedDistanceToLine(mousePos, p1, dir.unit)
    return Math.max(2, Math.abs(raw)) * (raw >= 0 ? 1 : -1)
  }

  function buildLinearParallelGeometry(edgeRef1, edgeRef2, offset = 50) {
    if (!edgeRef1 || !edgeRef2) return null
    const { seg: seg1, view: view1 } = edgeRef1
    const { seg: seg2, view: view2 } = edgeRef2
    const line1 = toLineSeg(seg1)
    const line2 = toLineSeg(seg2)
    if (!line1 || !line2) return null
    const p1 = getSheetPoint(view1, line1.x1, line1.y1)
    const p2 = getSheetPoint(view1, line1.x2, line1.y2)
    const q1 = getSheetPoint(view2, line2.x1, line2.y1)
    const q2 = getSheetPoint(view2, line2.x2, line2.y2)
    const basis = lineBasis(p1, p2)
    if (!basis) return null
    let normal = basis.perp
    let distance = signedDistanceToLine(q1, p1, normal)
    if (distance < 0) {
      normal = { x: -normal.x, y: -normal.y }
      distance = -distance
    }
    if (distance < 0.5) return null
    const start = closestPointOnLine(q1.x, q1.y, p1.x, p1.y, p2.x, p2.y)
    const end = offsetPoint(start, normal, distance)
    const dimBase = offsetPoint(start, basis.unit, offset)
    const dimEnd = offsetPoint(dimBase, normal, distance)
    const ext1End = dimBase
    const ext2End = dimEnd
    // 优先用两条线的 CAD 原始 mm 坐标直接算平行间距真值(无像素缩放误差)
    const mmVal = parallelSegMmDistance(line1, line2) ?? distance / (view1.scale * getViewMmScale(view1))
    return {
      type: 'linear',
      mode: 'parallel',
      refs: [edgeRefData(edgeRef1), edgeRefData(edgeRef2)],
      offset,
      ext1: start,
      ext1End,
      ext2: end,
      ext2End,
      dimStart: ext1End,
      dimEnd: ext2End,
      ...(() => {
        const r = buildLinearArrows(ext1End, ext2End, normal, formatMm(mmVal))
        const shift = r.outward ? 10 : 14
        return {
          ...r,
          textPos: { x: (ext1End.x + ext2End.x) / 2 + basis.unit.x * shift, y: (ext1End.y + ext2End.y) / 2 + basis.unit.y * shift }
        }
      })(),
      text: formatMm(mmVal)
    }
  }

  function buildLinearParallelPreview(edgeRef1, edgeRef2, mousePos) {
    const offset = getParallelOffsetFromMouse(edgeRef1, mousePos)
    return buildLinearParallelGeometry(edgeRef1, edgeRef2, offset)
  }

  // ===== 两圆心中心距 =====

  function getCenterOffsetFromMouse(edgeRef1, edgeRef2, mousePos) {
    const c1 = getCircleCenterSheet(edgeRef1)
    const c2 = getCircleCenterSheet(edgeRef2)
    if (!c1 || !c2 || !mousePos) return 50
    const basis = lineBasis(c1, c2)
    if (!basis) return 50
    const mid = { x: (c1.x + c2.x) / 2, y: (c1.y + c2.y) / 2 }
    const raw = (mousePos.x - mid.x) * basis.perp.x + (mousePos.y - mid.y) * basis.perp.y
    return Math.max(20, Math.abs(raw)) * (raw >= 0 ? 1 : -1)
  }

  function buildLinearCenterGeometry(edgeRef1, edgeRef2, offset = 50) {
    if (!edgeRef1 || !edgeRef2) return null
    const { view: view1 } = edgeRef1
    const c1 = getCircleCenterSheet(edgeRef1)
    const c2 = getCircleCenterSheet(edgeRef2)
    if (!c1 || !c2) return null
    const basis = lineBasis(c1, c2)
    if (!basis) return null
    const extEnd1 = offsetPoint(c1, basis.perp, offset)
    const extEnd2 = offsetPoint(c2, basis.perp, offset)
    // 优先用两圆心 CAD 真值 mm 坐标直接算欧氏距离(不经过像素缩放,无 0.1mm 误差)
    const mmC1 = getCircleCenterMm(edgeRef1)
    const mmC2 = getCircleCenterMm(edgeRef2)
    const mmVal = (mmC1 && mmC2)
      ? Math.hypot(mmC1.x - mmC2.x, mmC1.y - mmC2.y)
      : basis.len / (view1.scale * getViewMmScale(view1))
    return {
      type: 'linear',
      mode: 'center',
      refs: [edgeRefData(edgeRef1), edgeRefData(edgeRef2)],
      offset,
      ext1: c1,
      ext1End: extEnd1,
      ext2: c2,
      ext2End: extEnd2,
      dimStart: extEnd1,
      dimEnd: extEnd2,
      ...(() => {
        const r = buildLinearArrows(extEnd1, extEnd2, basis.unit, formatMm(mmVal))
        return {
          ...r,
          textPos: { x: (extEnd1.x + extEnd2.x) / 2, y: (extEnd1.y + extEnd2.y) / 2 - 3 }
        }
      })(),
      text: formatMm(mmVal),
      // 中心十字按各自孔的半径贴合(不再固定 8px 短十字)
      centerMarks: [
        { x: c1.x, y: c1.y, r: centerMarkHalfPx(edgeRef1) },
        { x: c2.x, y: c2.y, r: centerMarkHalfPx(edgeRef2) }
      ]
    }
  }

  function buildCenterPreview(edgeRef1, edgeRef2, mousePos) {
    const offset = getCenterOffsetFromMouse(edgeRef1, edgeRef2, mousePos)
    return buildLinearCenterGeometry(edgeRef1, edgeRef2, offset)
  }

  // ===== 圆心到边线距离 =====

  function getCircleEdgeOffsetFromMouse(circleRef, edgeRef, mousePos) {
    const c = getCircleCenterSheet(circleRef)
    const line = toLineSeg(edgeRef?.seg)
    if (!c || !line || !mousePos) return 50
    const q1 = getSheetPoint(edgeRef.view, line.x1, line.y1)
    const q2 = getSheetPoint(edgeRef.view, line.x2, line.y2)
    const basis = lineBasis(q1, q2)
    if (!basis) return 50
    return (mousePos.x - c.x) * basis.unit.x + (mousePos.y - c.y) * basis.unit.y
  }

  /**
   * 圆心到边线距离标注几何：
   *  - 尺寸线方向 = 边线法线(basis.perp)，与被测方向一致；
   *  - 延伸线方向 = 边线方向(basis.unit)，从圆心和边线垂足沿 unit 走到尺寸线；
   *  - 尺寸线位置由鼠标沿 unit 方向的位移决定。
   */
  function buildLinearCircleEdgeGeometry(circleRef, edgeRef, offset = 50) {
    if (!circleRef || !edgeRef) return null
    const c = getCircleCenterSheet(circleRef)
    const line = toLineSeg(edgeRef.seg)
    if (!c || !line) return null
    const view = circleRef.view
    const q1 = getSheetPoint(edgeRef.view, line.x1, line.y1)
    const q2 = getSheetPoint(edgeRef.view, line.x2, line.y2)
    const basis = lineBasis(q1, q2)
    if (!basis) return null
    const u = basis.unit
    const dC = signedDistanceToLine(c, q1, basis.perp)
    const f = projectPointToLine(c, q1, u)
    const footC = { x: c.x + u.x * offset, y: c.y + u.y * offset }
    const footF = { x: f.x + u.x * offset, y: f.y + u.y * offset }
    // 优先用 CAD 真值 mm 直接算圆心到边线距离(不经过像素缩放,无 0.1mm 误差)
    const mmC = getCircleCenterMm(circleRef)
    const mmLine = lineMmEndpoints(line)
    const mmVal = (mmC && mmLine)
      ? pointToLineMmDistance(mmC, mmLine)
      : Math.abs(dC) / (view.scale * getViewMmScale(view))
    return {
      type: 'linear',
      mode: 'circle-edge',
      refs: [edgeRefData(circleRef), edgeRefData(edgeRef)],
      offset,
      ext1: c,
      ext1End: footC,
      ext2: f,
      ext2End: footF,
      dimStart: footC,
      dimEnd: footF,
      ...(() => {
        const r = buildLinearArrows(footC, footF, basis.perp, formatMm(mmVal))
        return {
          ...r,
          textPos: { x: (footC.x + footF.x) / 2, y: (footC.y + footF.y) / 2 - 3 }
        }
      })(),
      text: formatMm(mmVal),
      centerMarks: [{ x: c.x, y: c.y, r: centerMarkHalfPx(circleRef) }],
      centerMarkAngle: Math.atan2(u.y, u.x)
    }
  }

  function buildLinearCircleEdgePreview(circleRef, edgeRef, mousePos) {
    const offset = getCircleEdgeOffsetFromMouse(circleRef, edgeRef, mousePos)
    return buildLinearCircleEdgeGeometry(circleRef, edgeRef, offset)
  }

  /**
   * 中心十字半长(图纸坐标像素):与对应孔的半径一致,端点恰好落在圆周上。
   * 用于独立孔位中心标记、中心距/圆心到边线辅助十字、"已选第一对象"提示——
   * 任何"圆上画十字"的场景都按孔大小贴合,不再做 8px 短十字区分。
   */
  function centerMarkHalfPx(edgeRef) {
    const circ = toCircle(edgeRef?.seg)
    if (!circ) return 0
    return circ.r * getViewDisplayScale(edgeRef.view)
  }

  /** 用 edgeRef 直接生成中心标记点(模板用的 {x, y, r} 结构) */
  function buildCenterMarkPoints(edgeRef) {
    const c = getCircleCenterSheet(edgeRef)
    if (!c) return null
    return { x: c.x, y: c.y, r: centerMarkHalfPx(edgeRef) }
  }

  function buildCenterMarkGeometry(edgeRef) {
    const cm = buildCenterMarkPoints(edgeRef)
    if (!cm) return null
    return {
      type: 'center-mark',
      refs: [edgeRefData(edgeRef)],
      centerMarks: [cm],
      text: ''
    }
  }

  function placeCenterMarkDim(edgeRef) {
    const geometry = buildCenterMarkGeometry(edgeRef)
    if (!geometry) return
    const id = nextId()
    pushDim({
      id,
      type: 'center-mark',
      refs: geometry.refs,
      color: ctx.dimensionColor.value
    })
    return id
  }

  // ===== 放置 =====

  function placeLinearDimSingle(edgeRef, offset = 50) {
    const geometry = buildLinearSingleGeometry(edgeRef, offset)
    if (!geometry) return
    const id = nextId()
    pushDim({
      id,
      type: 'linear',
      mode: 'single',
      refs: [edgeRefData(edgeRef)],
      offset: geometry.offset,
      color: ctx.dimensionColor.value,
      text: geometry.text
    })
    return id
  }

  function placeLinearDimParallel(edgeRef1, edgeRef2, offset = 50) {
    const geometry = buildLinearParallelGeometry(edgeRef1, edgeRef2, offset)
    if (!geometry) return
    const id = nextId()
    pushDim({
      id,
      type: 'linear',
      mode: 'parallel',
      refs: [edgeRefData(edgeRef1), edgeRefData(edgeRef2)],
      offset: geometry.offset,
      color: ctx.dimensionColor.value,
      text: geometry.text
    })
    return id
  }

  function placeLinearCenterDim(edgeRef1, edgeRef2, offset = 50) {
    const geometry = buildLinearCenterGeometry(edgeRef1, edgeRef2, offset)
    if (!geometry) return
    const id = nextId()
    pushDim({
      id,
      type: 'linear',
      mode: 'center',
      refs: [edgeRefData(edgeRef1), edgeRefData(edgeRef2)],
      offset: geometry.offset,
      color: ctx.dimensionColor.value,
      text: geometry.text
    })
    return id
  }

  function placeLinearCircleEdgeDim(circleRef, edgeRef, offset = 50) {
    const geometry = buildLinearCircleEdgeGeometry(circleRef, edgeRef, offset)
    if (!geometry) return
    const id = nextId()
    pushDim({ id, ...geometry })
    return id
  }

  // ===== 直径标注 =====

  function buildDiameterGeometry(edgeRef, angle = -Math.PI / 4, leaderLength = 30) {
    if (!edgeRef) return null
    const { seg, view } = edgeRef
    const circ = toCircle(seg)
    if (!circ || !view) return null
    const cx = view.x + circ.cx * getViewDisplayScale(view)
    const cy = view.y + circ.cy * getViewDisplayScale(view)
    const r = circ.r * getViewDisplayScale(view)
    const dir = { x: Math.cos(angle), y: Math.sin(angle) }
    const edgePt = { x: cx + dir.x * r, y: cy + dir.y * r }
    const textPos = { x: cx + dir.x * (r + leaderLength), y: cy + dir.y * (r + leaderLength) }
    const mmVal = circ.meta && circ.meta.radius ? circ.meta.radius * 2 : (circ.r * 2) / getViewMmScale(view)
    // 让文字始终处于可读角度(不倒立)
    const textAngle = Math.abs(angle) > Math.PI / 2 ? angle + Math.PI : angle
    return {
      type: 'diameter',
      refs: [edgeRefData(edgeRef)],
      leaderAngle: angle,
      leaderLength,
      textAngle,
      leaderStart: { x: cx, y: cy },
      leaderEnd: textPos,
      arrow: buildArrowPoints(edgePt, dir, false),
      textPos,
      text: `ø${formatMm(mmVal)}`
    }
  }

  function buildDiameterPreview(edgeRef, mousePos) {
    const { seg, view } = edgeRef
    const circ = toCircle(seg)
    if (!circ || !view || !mousePos) return null
    const cx = view.x + circ.cx * getViewDisplayScale(view)
    const cy = view.y + circ.cy * getViewDisplayScale(view)
    const r = circ.r * getViewDisplayScale(view)
    const angle = Math.atan2(mousePos.y - cy, mousePos.x - cx)
    const dist = Math.hypot(mousePos.x - cx, mousePos.y - cy)
    const leaderLength = Math.max(15, dist - r)
    return buildDiameterGeometry(edgeRef, angle, leaderLength)
  }

  function placeDiameterDim(edgeRef, leaderAngle = -Math.PI / 4) {
    const geometry = buildDiameterGeometry(edgeRef, leaderAngle)
    if (!geometry) return
    const id = nextId()
    pushDim({
      id,
      type: 'diameter',
      refs: [edgeRefData(edgeRef)],
      leaderAngle: geometry.leaderAngle,
      leaderLength: geometry.leaderLength,
      color: ctx.dimensionColor.value,
      text: geometry.text
    })
    return id
  }

  // ===== 角度标注 =====

  function buildAngleGeometry(edgeRef1, edgeRef2, radius = 40) {
    if (!edgeRef1 || !edgeRef2) return null
    const { seg: seg1, view: view1 } = edgeRef1
    const { seg: seg2, view: view2 } = edgeRef2
    const line1 = toLineSeg(seg1)
    const line2 = toLineSeg(seg2)
    if (!line1 || !line2) return null
    const p1 = getSheetPoint(view1, line1.x1, line1.y1)
    const p2 = getSheetPoint(view1, line1.x2, line1.y2)
    const q1 = getSheetPoint(view2, line2.x1, line2.y1)
    const q2 = getSheetPoint(view2, line2.x2, line2.y2)
    const inter = lineIntersection(p1, p2, q1, q2)
    if (!inter) return null
    const dir1 = lineBasis(inter, farthestEndpointFrom(inter, p1, p2))
    const dir2 = lineBasis(inter, farthestEndpointFrom(inter, q1, q2))
    if (!dir1 || !dir2) return null
    let startAngle = Math.atan2(dir1.unit.y, dir1.unit.x)
    let endAngle = Math.atan2(dir2.unit.y, dir2.unit.x)
    while (endAngle < startAngle) endAngle += Math.PI * 2
    if (endAngle - startAngle > Math.PI) {
      const temp = startAngle
      startAngle = endAngle
      endAngle = temp + Math.PI * 2
    }
    const sweep = endAngle - startAngle
    const angle = Math.min(sweep, Math.PI * 2 - sweep)
    const arrowAng1 = startAngle + sweep * 0.05
    const arrowAng2 = endAngle - sweep * 0.05
    const arrowP1 = { x: inter.x + Math.cos(arrowAng1) * radius, y: inter.y + Math.sin(arrowAng1) * radius }
    const arrowP2 = { x: inter.x + Math.cos(arrowAng2) * radius, y: inter.y + Math.sin(arrowAng2) * radius }
    const tan1 = { x: -Math.sin(arrowAng1), y: Math.cos(arrowAng1) }
    const tan2 = { x: -Math.sin(arrowAng2), y: Math.cos(arrowAng2) }
    const midAngle = startAngle + sweep / 2
    return {
      type: 'angle',
      refs: [edgeRefData(edgeRef1), edgeRefData(edgeRef2)],
      inter,
      radius,
      startAngle,
      endAngle,
      arcPath: buildArcPath(inter.x, inter.y, radius, startAngle, endAngle),
      arrow1: buildArrowPoints(arrowP1, tan1, true),
      arrow2: buildArrowPoints(arrowP2, { x: -tan2.x, y: -tan2.y }, true),
      textPos: { x: inter.x + Math.cos(midAngle) * (radius + 18), y: inter.y + Math.sin(midAngle) * (radius + 18) },
      text: formatDeg(angle * 180 / Math.PI)
    }
  }

  function buildAnglePreview(edgeRef1, edgeRef2, mousePos) {
    const base = buildAngleGeometry(edgeRef1, edgeRef2, 40)
    if (!base || !mousePos) return base
    const radius = Math.max(15, Math.min(200, Math.hypot(mousePos.x - base.inter.x, mousePos.y - base.inter.y)))
    return buildAngleGeometry(edgeRef1, edgeRef2, radius)
  }

  function placeAngleDim(edgeRef1, edgeRef2, radius = 40) {
    const geometry = buildAngleGeometry(edgeRef1, edgeRef2, radius)
    if (!geometry) return
    const id = nextId()
    pushDim({
      id,
      type: 'angle',
      refs: [edgeRefData(edgeRef1), edgeRefData(edgeRef2)],
      radius: geometry.radius,
      color: ctx.dimensionColor.value,
      text: geometry.text
    })
    return id
  }

  // ===== 渲染 =====

  function renderDimension(dim) {
    if (!dim?.refs?.length) return null

    let geometry = null
    if (dim.type === 'linear') {
      const first = resolveDimRef(dim.refs[0])
      if (!first) return null
      if (dim.mode === 'center') {
        geometry = buildLinearCenterGeometry(first, resolveDimRef(dim.refs[1]), dim.offset)
      } else if (dim.mode === 'parallel') {
        geometry = buildLinearParallelGeometry(first, resolveDimRef(dim.refs[1]), dim.offset)
      } else if (dim.mode === 'circle-edge') {
        geometry = buildLinearCircleEdgeGeometry(first, resolveDimRef(dim.refs[1]), dim.offset)
      } else {
        geometry = buildLinearSingleGeometry(first, dim.offset)
      }
    } else if (dim.type === 'center-mark') {
      geometry = buildCenterMarkGeometry(resolveDimRef(dim.refs[0]))
    } else if (dim.type === 'diameter') {
      geometry = buildDiameterGeometry(resolveDimRef(dim.refs[0]), dim.leaderAngle, dim.leaderLength)
    } else if (dim.type === 'angle') {
      geometry = buildAngleGeometry(resolveDimRef(dim.refs[0]), resolveDimRef(dim.refs[1]), dim.radius)
    }

    return geometry ? { ...geometry, id: dim.id, color: dim.color || '#303133' } : null
  }

  // ===== 拖拽 =====

  function updateDimDrag(dim, mousePos) {
    if (!dim || !mousePos) return

    if (dim.type === 'linear') {
      const first = resolveDimRef(dim.refs[0])
      if (!first) return
      if (dim.mode === 'center') {
        const second = resolveDimRef(dim.refs[1])
        if (!second) return
        dim.offset = getCenterOffsetFromMouse(first, second, mousePos)
      } else if (dim.mode === 'parallel') {
        dim.offset = getParallelOffsetFromMouse(first, mousePos)
      } else if (dim.mode === 'circle-edge') {
        const second = resolveDimRef(dim.refs[1])
        if (!second) return
        dim.offset = getCircleEdgeOffsetFromMouse(first, second, mousePos)
      } else {
        dim.offset = getLinearOffsetFromMouse(first, mousePos)
      }
    } else if (dim.type === 'diameter') {
      const ref = resolveDimRef(dim.refs[0])
      if (!ref) return
      const circ = toCircle(ref.seg)
      if (!circ) return
      const center = getSheetPoint(ref.view, circ.cx, circ.cy)
      const r = circ.r * getViewDisplayScale(ref.view)
      const dist = Math.hypot(mousePos.x - center.x, mousePos.y - center.y)
      dim.leaderAngle = Math.atan2(mousePos.y - center.y, mousePos.x - center.x)
      dim.leaderLength = Math.max(15, dist - r)
    } else if (dim.type === 'angle') {
      const first = resolveDimRef(dim.refs[0])
      const second = resolveDimRef(dim.refs[1])
      if (!first || !second) return
      const geometry = buildAngleGeometry(first, second, 40)
      if (!geometry) return
      dim.radius = Math.max(15, Math.min(200, Math.hypot(mousePos.x - geometry.inter.x, mousePos.y - geometry.inter.y)))
    }
  }

  // 供引擎使用的预览构建集合
  const previewBuilders = {
    linearSingle: buildLinearSinglePreview,
    linearParallel: buildLinearParallelPreview,
    linearCenter: buildCenterPreview,
    linearCircleEdge: buildLinearCircleEdgePreview,
    centerMark: buildCenterMarkGeometry,
    diameter: buildDiameterPreview,
    angle: buildAnglePreview
  }

  return {
    // 几何构建
    getCircleCenterSheet,
    getLinearOffsetFromMouse,
    getParallelOffsetFromMouse,
    getCenterOffsetFromMouse,
    getCircleEdgeOffsetFromMouse,
    buildLinearSingleGeometry,
    buildLinearParallelGeometry,
    buildLinearCenterGeometry,
    buildLinearCircleEdgeGeometry,
    buildCenterMarkGeometry,
    buildDiameterGeometry,
    buildAngleGeometry,
    // 放置
    placeLinearDimSingle,
    placeLinearDimParallel,
    placeLinearCenterDim,
    placeLinearCircleEdgeDim,
    placeCenterMarkDim,
    placeDiameterDim,
    placeAngleDim,
    // 渲染与拖拽
    renderDimension,
    updateDimDrag,
    previewBuilders
  }
}
