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
  buildArcPath,
  extendExtEnd,
  linearTextAngle,
  linearTextPos,
  DIM_TEXT_GAP
} from './geometry.js'
import { buildArrowPoints, buildLinearArrows, extendLinearLine } from './arrow.js'
import {
  buildMotorEnvelopeGeometry,
  getMotorEnvelopeOffsetFromMouse
} from './motorEnvelope.js'
import config from '../../../cad_viewer_style.json'

export function createDimensionCore(deps, ctx) {
  const {
    getSheetPoint,
    getViewDisplayScale,
    getViewMmScale,
    edgeRefData,
    getSvgMousePoint,
    resolveDimRef,
    getMotorEnvelope
  } = deps

  const formatMm = (value) => Number(value || 0).toFixed(1).replace(/\.0$/, '')
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

  function buildLinearSingleGeometry(edgeRef, offset = 50, arrowMode = 'auto', extStartPx, extEndPx) {
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
      ext1End: extendExtEnd(p1, extEnd1),
      ext2: p2,
      ext2End: extendExtEnd(p2, extEnd2),
      dimStart: extEnd1,
      dimEnd: extEnd2,
      ...(() => {
        const r = buildLinearArrows(extEnd1, extEnd2, dir.unit, formatMm(mmVal), arrowMode)
        const mid = { x: (extEnd1.x + extEnd2.x) / 2, y: (extEnd1.y + extEnd2.y) / 2 }
        const ext = extendLinearLine(extEnd1, extEnd2, r.outward, dir.unit, extStartPx, extEndPx)
        return {
          ...r,
          dimLineStart: ext.lineStart,
          dimLineEnd: ext.lineEnd,
          textPos: linearTextPos(dir.unit, mid),
          textAngle: linearTextAngle(dir.unit)
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

  function getParallelOffsetFromMouse(edgeRef1, edgeRef2, mousePos) {
    if (!edgeRef1 || !edgeRef2 || !mousePos) return 50
    const { seg: seg1, view: view1 } = edgeRef1
    const { seg: seg2, view: view2 } = edgeRef2
    const line1 = toLineSeg(seg1)
    const line2 = toLineSeg(seg2)
    if (!line1 || !line2 || !view1 || !view2) return 50
    const p1 = getSheetPoint(view1, line1.x1, line1.y1)
    const p2 = getSheetPoint(view1, line1.x2, line1.y2)
    const q1 = getSheetPoint(view2, line2.x1, line2.y1)
    const dir = lineBasis(p1, p2)
    if (!dir) return 50
    // offset 是尺寸线沿被测边方向的滑动量；以第二条边在第一条边上的垂足为原点，
    // 才能让尺寸线精确跟随鼠标，而不是被第一条边的端点位置带偏。
    const start = closestPointOnLine(q1.x, q1.y, p1.x, p1.y, p2.x, p2.y)
    const raw = (mousePos.x - start.x) * dir.unit.x + (mousePos.y - start.y) * dir.unit.y
    return raw
  }

  function buildLinearParallelGeometry(edgeRef1, edgeRef2, offset = 50, arrowMode = 'auto', extStartPx, extEndPx) {
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
    const extTip1 = extendExtEnd(start, dimBase)
    const extTip2 = extendExtEnd(end, dimEnd)
    // 优先用两条线的 CAD 原始 mm 坐标直接算平行间距真值(无像素缩放误差)
    const mmVal = parallelSegMmDistance(line1, line2) ?? distance / (view1.scale * getViewMmScale(view1))
    return {
      type: 'linear',
      mode: 'parallel',
      refs: [edgeRefData(edgeRef1), edgeRefData(edgeRef2)],
      offset,
      ext1: start,
      ext1End: extTip1,
      ext2: end,
      ext2End: extTip2,
      dimStart: dimBase,
      dimEnd,
      ...(() => {
        const r = buildLinearArrows(dimBase, dimEnd, normal, formatMm(mmVal), arrowMode)
        const mid = { x: (dimBase.x + dimEnd.x) / 2, y: (dimBase.y + dimEnd.y) / 2 }
        const ext = extendLinearLine(dimBase, dimEnd, r.outward, normal, extStartPx, extEndPx)
        return {
          ...r,
          dimLineStart: ext.lineStart,
          dimLineEnd: ext.lineEnd,
          textPos: linearTextPos(normal, mid),
          textAngle: linearTextAngle(normal)
        }
      })(),
      text: formatMm(mmVal)
    }
  }

  function buildLinearParallelPreview(edgeRef1, edgeRef2, mousePos) {
    const offset = getParallelOffsetFromMouse(edgeRef1, edgeRef2, mousePos)
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

  function buildLinearCenterGeometry(edgeRef1, edgeRef2, offset = 50, arrowMode = 'auto', extStartPx, extEndPx) {
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
      ext1End: extendExtEnd(c1, extEnd1),
      ext2: c2,
      ext2End: extendExtEnd(c2, extEnd2),
      dimStart: extEnd1,
      dimEnd: extEnd2,
      ...(() => {
        const r = buildLinearArrows(extEnd1, extEnd2, basis.unit, formatMm(mmVal), arrowMode)
        const mid = { x: (extEnd1.x + extEnd2.x) / 2, y: (extEnd1.y + extEnd2.y) / 2 }
        const ext = extendLinearLine(extEnd1, extEnd2, r.outward, basis.unit, extStartPx, extEndPx)
        return {
          ...r,
          dimLineStart: ext.lineStart,
          dimLineEnd: ext.lineEnd,
          textPos: linearTextPos(basis.unit, mid),
          textAngle: linearTextAngle(basis.unit)
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
  function buildLinearCircleEdgeGeometry(circleRef, edgeRef, offset = 50, arrowMode = 'auto', extStartPx, extEndPx) {
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
      ext1End: extendExtEnd(c, footC),
      ext2: f,
      ext2End: extendExtEnd(f, footF),
      dimStart: footC,
      dimEnd: footF,
      ...(() => {
        const r = buildLinearArrows(footC, footF, basis.perp, formatMm(mmVal), arrowMode)
        const mid = { x: (footC.x + footF.x) / 2, y: (footC.y + footF.y) / 2 }
        const ext = extendLinearLine(footC, footF, r.outward, basis.perp, extStartPx, extEndPx)
        return {
          ...r,
          dimLineStart: ext.lineStart,
          dimLineEnd: ext.lineEnd,
          textPos: linearTextPos(basis.perp, mid),
          textAngle: linearTextAngle(basis.perp)
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
   * 中心十字半长(图纸坐标像素):等于对应孔的半径再略超出 1mm,端点落在
   * 圆周外一点,与工程图中心标记习惯一致、更醒目。1mm 的超出量按视图缩放
   * 折回图纸坐标,使不同比例下视觉超出量稳定。
   * 用于独立孔位中心标记、中心距/圆心到边线辅助十字、"已选第一对象"提示——
   * 任何"圆上画十字"的场景都按孔大小贴合,不再做 8px 短十字区分。
   */
  function centerMarkHalfPx(edgeRef) {
    const circ = toCircle(edgeRef?.seg)
    if (!circ) return 0
    const r = circ.r * getViewDisplayScale(edgeRef.view)
    const extra = 0.2 / (getViewMmScale(edgeRef.view) || 1) // 0.5mm 超出圆周，轻微探出
    return r + extra
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

  // ===== 电机包络尺寸 =====

  function placeMotorEnvelopeDim(view, envelope, edgeRef, offset = 50, customText = '') {
    const geometry = buildMotorEnvelopeGeometry(
      view, envelope, getSheetPoint, offset, customText)
    if (!geometry) return
    const id = nextId()
    pushDim({
      id,
      type: 'linear',
      mode: 'motor-envelope',
      refs: [edgeRefData(edgeRef)],
      bind_motor: true,
      customText: customText || null,
      text: geometry.text,
      spanMm: envelope.span_mm,
      offset: geometry.offset ?? offset,
      color: ctx.dimensionColor.value
    })
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
    // 直径线贯穿整个圆:起点 = 对侧圆周,终点 = 圆心正方向 r+leaderLength 处
    // 这样 leader 长度 = 2r + leaderLength,贯穿整个圆,箭头仍画在正侧圆周
    const leaderStart = { x: cx - dir.x * r, y: cy - dir.y * r }
    const edgePt = { x: cx + dir.x * r, y: cy + dir.y * r }
    const leaderEnd = { x: cx + dir.x * (r + leaderLength), y: cy + dir.y * (r + leaderLength) }
    // 文字完全位于 leader 线段上:
    //   1) 沿 -dir 方向从 leaderEnd 退回,把文字落在 leader 末端的内侧(不超出箭头)
    //   2) 再沿屏幕"上方"法向微调 4px,与线分离避免压线
    // 取两个候选法向中 y 更小者作为屏幕上方方向,保证任意 leader 朝向都靠上
    const perpUp1 = { x: -dir.y, y: dir.x }
    const perpUp2 = { x: dir.y, y: -dir.x }
    const perp = perpUp1.y <= perpUp2.y ? perpUp1 : perpUp2
    const textAlongBack = 20   // 沿 -dir 退回距离,让文字落回 leader 末端内侧
    const textPerpGap = 4      // 垂直于 leader 的上方微调
    const textPos = {
      x: leaderEnd.x - dir.x * textAlongBack + perp.x * textPerpGap,
      y: leaderEnd.y - dir.y * textAlongBack + perp.y * textPerpGap
    }
    const mmVal = circ.meta && circ.meta.radius ? circ.meta.radius * 2 : (circ.r * 2) / getViewMmScale(view)
    // 让文字始终处于可读角度(不倒立)
    const textAngle = Math.abs(angle) > Math.PI / 2 ? angle + Math.PI : angle
    return {
      type: 'diameter',
      refs: [edgeRefData(edgeRef)],
      leaderAngle: angle,
      leaderLength,
      textAngle,
      leaderStart,
      leaderEnd,
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
    // leader 长度按鼠标在圆外超出圆周的距离算;
    // 起点在 buildDiameterGeometry 中固定为对侧圆周,线自然贯穿整个圆
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

  // ===== 引线直径标注(Leader Diameter) =====
  // 文字在水平线上,引线从文字末端折向圆周,箭头指向圆。
  // 常用于孔位标注如 "6x Ø22 贯穿"。

  const LEADER_SHOULDER = 10   // 水平肩部长度(px)
  const LEADER_TEXT_GAP = 4    // 文字与水平线垂直间距(px)

  function buildDiameterLeaderGeometry(edgeRef, textLeft, leaderAngle = -Math.PI / 4) {
    if (!edgeRef) return null
    const { seg, view } = edgeRef
    const circ = toCircle(seg)
    if (!circ || !view) return null
    const cx = view.x + circ.cx * getViewDisplayScale(view)
    const cy = view.y + circ.cy * getViewDisplayScale(view)
    const r = circ.r * getViewDisplayScale(view)
    const dir = { x: Math.cos(leaderAngle), y: Math.sin(leaderAngle) }

    // 文字左端(用户拖拽/鼠标位置),水平向右延伸
    const textX = textLeft.x
    const textY = textLeft.y

    // 估算文字宽度,确定肩部起点
    const mmVal = circ.meta && circ.meta.radius ? circ.meta.radius * 2 : (circ.r * 2) / getViewMmScale(view)
    const label = `ø${formatMm(mmVal)}`
    const textW = estimateTextWidth(label) + 8   // 预留余量

    // 水平线: 文字下方
    const textLineStart = { x: textX, y: textY + LEADER_TEXT_GAP }
    const textLineEnd = { x: textX + textW + LEADER_SHOULDER, y: textY + LEADER_TEXT_GAP }

    // 肩部终点(折点): 从这里沿 leaderAngle 方向向圆引线
    const bendPt = { x: textLineEnd.x, y: textLineEnd.y }

    // 计算折点到圆的射线与圆的交点(取离折点近的那个交点)
    // 射线参数方程: P = bendPt + t * dir, t > 0
    // 圆方程: |P - C|^2 = r^2
    const dx = bendPt.x - cx
    const dy = bendPt.y - cy
    const a = dir.x * dir.x + dir.y * dir.y  // = 1
    const b = 2 * (dx * dir.x + dy * dir.y)
    const c = dx * dx + dy * dy - r * r
    const disc = b * b - 4 * a * c
    if (disc < 0) return null
    const sqrtDisc = Math.sqrt(disc)
    const t1 = (-b - sqrtDisc) / (2 * a)
    const t2 = (-b + sqrtDisc) / (2 * a)
    // 取正的较小 t(最近的交点)
    let t = (t1 > 0 ? t1 : (t2 > 0 ? t2 : 0))
    if (t < 1) t = 1  // 至少走 1px,避免箭头压到折点
    const edgePt = { x: bendPt.x + dir.x * t, y: bendPt.y + dir.y * t }

    return {
      type: 'diameter',
      diameterMode: 'leader',
      refs: [edgeRefData(edgeRef)],
      leaderAngle,
      // 水平文字线段
      textLineStart,
      textLineEnd,
      // 折线引线: 折点 → 圆周
      leaderBend: bendPt,
      leaderEnd: edgePt,
      // 箭头在圆周,方向沿 dir 向外
      arrow: buildArrowPoints(edgePt, dir, false),
      // 文字:水平,左对齐
      textPos: { x: textX, y: textY },
      textAngle: 0,
      text: label
    }
  }

  function buildDiameterLeaderPreview(edgeRef, mousePos) {
    if (!edgeRef || !mousePos) return null
    // 引线角度:从圆心到鼠标方向的反方向(让引线从文字折向圆)
    const { seg, view } = edgeRef
    const circ = toCircle(seg)
    if (!circ || !view) return null
    const cx = view.x + circ.cx * getViewDisplayScale(view)
    const cy = view.y + circ.cy * getViewDisplayScale(view)
    // 文字左端放在鼠标位置左侧一点,引线向右下折向圆
    const textLeft = { x: mousePos.x - 60, y: mousePos.y }
    // 引线角度:指向圆的大致方向
    const angle = Math.atan2(cy - mousePos.y, cx - mousePos.x)
    return buildDiameterLeaderGeometry(edgeRef, textLeft, angle)
  }

  function placeDiameterLeaderDim(edgeRef, textLeft, leaderAngle) {
    const geometry = buildDiameterLeaderGeometry(edgeRef, textLeft, leaderAngle)
    if (!geometry) return
    const id = nextId()
    pushDim({
      id,
      type: 'diameter',
      diameterMode: 'leader',
      refs: [edgeRefData(edgeRef)],
      leaderAngle: geometry.leaderAngle,
      textLeft: geometry.textPos,
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
    if (!dim) return null

    const extS = dim.extensionStartPx ?? undefined
    const extE = dim.extensionEndPx ?? undefined
    let geometry = null
    if (dim.type === 'linear' && dim.mode === 'motor-envelope') {
      const ref = resolveDimRef(dim.refs?.[0])
      if (!ref) return null
      const envelope = getMotorEnvelope ? getMotorEnvelope(ref.view) : null
      if (!envelope) return null
      geometry = buildMotorEnvelopeGeometry(
        ref.view, envelope, getSheetPoint, dim.offset, dim.customText || '', dim.arrowMode || 'auto', extS, extE)
      if (geometry) {
        geometry.text = dim.customText || geometry.text
      }
    } else if (dim.type === 'linear') {
      const first = resolveDimRef(dim.refs[0])
      if (!first) return null
      if (dim.mode === 'center') {
        geometry = buildLinearCenterGeometry(first, resolveDimRef(dim.refs[1]), dim.offset, dim.arrowMode || 'auto', extS, extE)
      } else if (dim.mode === 'parallel') {
        geometry = buildLinearParallelGeometry(first, resolveDimRef(dim.refs[1]), dim.offset, dim.arrowMode || 'auto', extS, extE)
      } else if (dim.mode === 'circle-edge') {
        geometry = buildLinearCircleEdgeGeometry(first, resolveDimRef(dim.refs[1]), dim.offset, dim.arrowMode || 'auto', extS, extE)
      } else {
        geometry = buildLinearSingleGeometry(first, dim.offset, dim.arrowMode || 'auto', extS, extE)
      }
    } else if (dim.type === 'center-mark') {
      geometry = buildCenterMarkGeometry(resolveDimRef(dim.refs[0]))
    } else if (dim.type === 'diameter') {
      if (dim.diameterMode === 'leader' && dim.textLeft) {
        geometry = buildDiameterLeaderGeometry(resolveDimRef(dim.refs[0]), dim.textLeft, dim.leaderAngle)
      } else {
        geometry = buildDiameterGeometry(resolveDimRef(dim.refs[0]), dim.leaderAngle, dim.leaderLength)
      }
    } else if (dim.type === 'angle') {
      geometry = buildAngleGeometry(resolveDimRef(dim.refs[0]), resolveDimRef(dim.refs[1]), dim.radius)
    }

    if (dim.customText != null && dim.customText !== '') {
      geometry.text = dim.customText
    }
    // 拖动过的文字按 textSlide 沿尺寸线滑动(存于标注数据,随模板持久化)
    // 注意:与 updateDimTextDrag 共用同一基准(dimLineStart/dimLineEnd,含延长线),
    // 否则延长线拉伸后两处中点错开,文字不跟鼠标
    if (geometry && dim.type === 'linear' && dim.textSlide) {
      const a = geometry.dimLineStart ?? geometry.dimStart
      const b = geometry.dimLineEnd ?? geometry.dimEnd
      const dx = b.x - a.x
      const dy = b.y - a.y
      const len = Math.hypot(dx, dy)
      if (len > 1e-6) {
        const unit = { x: dx / len, y: dy / len }
        const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
        geometry.textPos = linearTextPos(unit, mid, DIM_TEXT_GAP, dim.textSlide)
        geometry.textAngle = linearTextAngle(unit)
      }
    }
    // 伴随文字标签(label):位置相对数值文字固定偏移(沿尺寸线反方向),
    // 保证前后端渲染时 label 与 value 的相对位置一致。
    if (geometry && geometry.textPos && dim.label) {
      const tp = geometry.textPos
      const ta = geometry.textAngle || 0
      // 沿文字基线反方向偏移:水平尺寸线label在左,竖直在上方
      const ux = Math.cos(ta), uy = Math.sin(ta)
      // 间距随字号成比例(= font_px * PX2MM * label_gap_factor,单位mm),
      // 与后端 dim_label_gap_mm() 公式完全一致
      const labelGapFactor = config.dim.text.label_gap_factor ?? 0.55
      const LABEL_GAP = config.dim.text.font_px * config._px_to_mm_at_96dpi * labelGapFactor
      geometry.labelText = dim.label
      // 标签与数值共用同一基线 y(保证等高);仅 x 沿反方向偏移间距
      geometry.labelPos = { x: tp.x - ux * LABEL_GAP, y: tp.y }
      geometry.labelAngle = ta
    }

    return geometry ? { ...geometry, id: dim.id, color: dim.color || '#303133', arrowMode: dim.arrowMode || 'auto', offset: dim.offset } : null
  }

  // ===== 拖拽 =====

  function updateDimDrag(dim, mousePos) {
    if (!dim || !mousePos) return

    if (dim.type === 'linear') {
      const first = resolveDimRef(dim.refs[0])
      if (!first) return
      if (dim.mode === 'motor-envelope') {
        const envelope = getMotorEnvelope ? getMotorEnvelope(first.view) : null
        if (!envelope) return
        dim.offset = getMotorEnvelopeOffsetFromMouse(
          first.view, envelope, getSheetPoint, mousePos)
      } else if (dim.mode === 'center') {
        const second = resolveDimRef(dim.refs[1])
        if (!second) return
        dim.offset = getCenterOffsetFromMouse(first, second, mousePos)
      } else if (dim.mode === 'parallel') {
        const second = resolveDimRef(dim.refs[1])
        if (!second) return
        dim.offset = getParallelOffsetFromMouse(first, second, mousePos)
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
      if (dim.diameterMode === 'leader') {
        // 引线模式:拖拽更新文字位置和引线角度
        dim.textLeft = { x: mousePos.x - 60, y: mousePos.y }
        const center = getSheetPoint(ref.view, circ.cx, circ.cy)
        dim.leaderAngle = Math.atan2(center.y - mousePos.y, center.x - mousePos.x)
      } else {
        const center = getSheetPoint(ref.view, circ.cx, circ.cy)
        const r = circ.r * getViewDisplayScale(ref.view)
        const dist = Math.hypot(mousePos.x - center.x, mousePos.y - center.y)
        dim.leaderAngle = Math.atan2(mousePos.y - center.y, mousePos.x - center.x)
        dim.leaderLength = Math.max(15, dist - r)
      }
    } else if (dim.type === 'angle') {
      const first = resolveDimRef(dim.refs[0])
      const second = resolveDimRef(dim.refs[1])
      if (!first || !second) return
      const geometry = buildAngleGeometry(first, second, 40)
      if (!geometry) return
      dim.radius = Math.max(15, Math.min(200, Math.hypot(mousePos.x - geometry.inter.x, mousePos.y - geometry.inter.y)))
    }
  }

  /** 拖动文字标签:鼠标位置投影到尺寸线方向,更新 textSlide(相对中点,允许稍出界)
   *  使用 dimLineStart/dimLineEnd(含延长线的全长)而非 dimStart/dimEnd(仅箭头间),
   *  确保文字可沿整个尺寸线(含延长线)拖动。*/
  function updateDimTextDrag(dim, mousePos) {
    if (!dim || dim.type !== 'linear' || !mousePos) return
    const geometry = renderDimension({ ...dim, textSlide: 0 })
    if (!geometry) return
    // 优先使用含延长线的全长端点,确保拖动范围覆盖整条尺寸线
    const a = geometry.dimLineStart ?? geometry.dimStart
    const b = geometry.dimLineEnd ?? geometry.dimEnd
    const dx = b.x - a.x
    const dy = b.y - a.y
    const len = Math.hypot(dx, dy)
    if (len < 1e-6) return
    const t = (mousePos.x - a.x) * (dx / len) + (mousePos.y - a.y) * (dy / len) - len / 2
    dim.textSlide = Math.max(-(len / 2 + 15), Math.min(len / 2 + 15, t))
  }

  /** 拖动延长线手柄:鼠标沿尺寸线方向投影,计算超出箭头尖端的距离,更新对应侧的 extensionPx。
   *  endSide: 'start' | 'end', 表示拖的是哪一端。*/
  function updateDimExtensionDrag(dim, mousePos, endSide) {
    if (!dim || dim.type !== 'linear' || !mousePos) return
    // 不传 extension 用默认值构建基底几何,拿到箭头尖端位置
    const geometry = renderDimension({ ...dim, extensionStartPx: undefined, extensionEndPx: undefined })
    if (!geometry) return
    const a = geometry.dimStart
    const b = geometry.dimEnd
    const dx = b.x - a.x
    const dy = b.y - a.y
    const len = Math.hypot(dx, dy)
    if (len < 1e-6) return
    const unit = { x: dx / len, y: dy / len }
    // 鼠标在尺寸线方向上的投影偏移(以 a 为原点)
    const proj = (mousePos.x - a.x) * unit.x + (mousePos.y - a.y) * unit.y
    if (endSide === 'start') {
      const ext = -proj
      dim.extensionStartPx = Math.max(0, ext)
    } else {
      const ext = proj - len
      dim.extensionEndPx = Math.max(0, ext)
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
    getMotorEnvelopeOffsetFromMouse,
    buildLinearSingleGeometry,
    buildLinearParallelGeometry,
    buildLinearCenterGeometry,
    buildLinearCircleEdgeGeometry,
    buildCenterMarkGeometry,
    buildDiameterGeometry,
    buildDiameterLeaderGeometry,
    buildAngleGeometry,
    buildMotorEnvelopeGeometry,
    // 放置
    placeLinearDimSingle,
    placeLinearDimParallel,
    placeLinearCenterDim,
    placeLinearCircleEdgeDim,
    placeMotorEnvelopeDim,
    placeCenterMarkDim,
    placeDiameterDim,
    placeDiameterLeaderDim,
    placeAngleDim,
    // 渲染与拖拽
    renderDimension,
    updateDimDrag,
    updateDimTextDrag,
    updateDimExtensionDrag,
    previewBuilders
  }
}