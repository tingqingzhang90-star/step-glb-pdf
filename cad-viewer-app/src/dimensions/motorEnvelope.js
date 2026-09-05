// 电机包络标注几何:减速机两端面按包络真实轮廓贴合,换型号自动跟随
// 输入 envelope 来自后端 /api/drawing-view-palette 的 motor_envelope 字段,
// 各字段为模型 mm 投影坐标,与 palette 边线 meta.mm_coords 同源。

import { lineBasis, extendExtEnd, linearTextAngle, linearTextPos } from './geometry.js'
import { buildLinearArrows } from './arrow.js'

function pickEnvelopeEndpoint(face, orientation, offset) {
  const [a, b] = face
  const ax = a.x, ay = a.y, bx = b.x, by = b.y
  if (orientation === 'horizontal') {
    return { x: ax, y: offset >= 0 ? Math.max(ay, by) : Math.min(ay, by) }
  }
  return { x: offset >= 0 ? Math.max(ax, bx) : Math.min(ax, bx), y: ay }
}

// 将包络端点吸附到视图中最接近的真实边线端点,同时修正 x(端面位置) 和 y(延伸线端点),
// 避免 bbox 估算的端点悬空或落在法兰凸缘内部。
function snapEndpointToViewEdge(view, pt, orientation, offset) {
  const k = view.scale ?? 1
  const threshold = 30  // 图纸像素
  const edges = [...(view.edges || []), ...(view.hiddenEdges || [])]
  let best = null
  let bestDist = Infinity
  for (const seg of edges) {
    if (seg.type !== 'line') continue
    const x1 = seg.x1 * k + view.x
    const y1 = seg.y1 * k + view.y
    const x2 = seg.x2 * k + view.x
    const y2 = seg.y2 * k + view.y
    if (orientation === 'horizontal') {
      // 端面线为竖直边线;根据 offset 方向取边线的上/下端点作为延伸线起点
      if (Math.abs(x2 - x1) > 2) continue
      const dist = Math.abs(x1 - pt.x)
      if (dist < bestDist && dist < threshold) {
        bestDist = dist
        best = {
          x: x1,
          y: offset >= 0 ? Math.max(y1, y2) : Math.min(y1, y2)
        }
      }
    } else {
      // 端面线为水平边线;根据 offset 方向取边线的左/右端点
      if (Math.abs(y2 - y1) > 2) continue
      const dist = Math.abs(y1 - pt.y)
      if (dist < bestDist && dist < threshold) {
        bestDist = dist
        best = {
          x: offset >= 0 ? Math.max(x1, x2) : Math.min(x1, x2),
          y: y1
        }
      }
    }
  }
  return best || pt
}

// envelope 坐标为模型 mm 投影坐标。
// palette 视图把边线从 mm 变换到 400x300 框内时用了 scale + offset,
// 电机包络必须走同一变换,才能与视图边线重合。
// 最终图纸坐标 = view.x + (mm * scale + offset) * view.scale,与边线渲染一致。
function faceToSheet(face, view, getSheetPoint) {
  const k = view.bbox?.scale ?? 1
  const ox = view.bbox?.offset_x ?? 0
  const oy = view.bbox?.offset_y ?? 0
  return face.map(([x, y]) => getSheetPoint(view, x * k + ox, y * k + oy))
}

export function buildMotorEnvelopeGeometry(view, envelope, getSheetPoint, offset = 50, customText = '', arrowMode = 'auto') {
  const face1 = faceToSheet(envelope.face_min, view, getSheetPoint)
  const face2 = faceToSheet(envelope.face_max, view, getSheetPoint)
  const orientation = envelope.orientation
  let ext1 = pickEnvelopeEndpoint(face1, orientation, offset)
  let ext2 = pickEnvelopeEndpoint(face2, orientation, offset)
  // 把包络端点吸附到视图真实边线端点,修正 x 端面位置并补齐 y 延伸线
  ext1 = snapEndpointToViewEdge(view, ext1, orientation, offset)
  ext2 = snapEndpointToViewEdge(view, ext2, orientation, offset)
  // 吸附后边线端点 y/x 可能不同,必须统一才能保证尺寸线水平/竖直,
  // 并向下/向右补齐延伸线(取最外侧)。
  if (orientation === 'horizontal') {
    const y = Math.max(ext1.y, ext2.y)
    ext1 = { x: ext1.x, y }
    ext2 = { x: ext2.x, y }
  } else {
    const x = Math.max(ext1.x, ext2.x)
    ext1 = { x, y: ext1.y }
    ext2 = { x, y: ext2.y }
  }

  const basis = lineBasis(ext1, ext2)
  if (!basis) return null

  // 尺寸线法向统一朝"下/右":与工程图习惯一致,也与后端 envelope_endpoints 约定相同。
  // horizontal 时 offset 正 → 尺寸线在包络下方;vertical 时 offset 正 → 尺寸线在包络右方。
  const normal = orientation === 'horizontal'
    ? { x: 0, y: 1 }
    : { x: 1, y: 0 }
  const dimStart = { x: ext1.x + normal.x * offset, y: ext1.y + normal.y * offset }
  const dimEnd = { x: ext2.x + normal.x * offset, y: ext2.y + normal.y * offset }

  const text = customText || `${envelope.span_mm}mm`
  const arrows = buildLinearArrows(dimStart, dimEnd, basis.unit, text, arrowMode)
  const mid = { x: (dimStart.x + dimEnd.x) / 2, y: (dimStart.y + dimEnd.y) / 2 }

  return {
    type: 'linear',
    mode: 'motor-envelope',
    ext1,
    ext1End: extendExtEnd(ext1, dimStart),
    ext2,
    ext2End: extendExtEnd(ext2, dimEnd),
    dimStart,
    dimEnd,
    ...arrows,
    textPos: linearTextPos(basis.unit, mid),
    textAngle: linearTextAngle(basis.unit),
    text,
    centerMarks: [],
    spanMm: envelope.span_mm
  }
}

// 计算渲染时尺寸线所依附的包络外侧边：
// offset 为负时尺寸线在包络上/左侧，offset 为正时在下/右侧。
function envelopeBaseLine(view, face1, face2, orientation, sign) {
  const s = sign >= 0 ? 1 : -1
  let e1 = pickEnvelopeEndpoint(face1, orientation, s)
  let e2 = pickEnvelopeEndpoint(face2, orientation, s)
  e1 = snapEndpointToViewEdge(view, e1, orientation, s)
  e2 = snapEndpointToViewEdge(view, e2, orientation, s)
  return orientation === 'horizontal'
    ? Math.max(e1.y, e2.y)
    : Math.max(e1.x, e2.x)
}

export function getMotorEnvelopeOffsetFromMouse(view, envelope, getSheetPoint, mousePos) {
  const face1 = faceToSheet(envelope.face_min, view, getSheetPoint)
  const face2 = faceToSheet(envelope.face_max, view, getSheetPoint)
  const orientation = envelope.orientation

  // 渲染时尺寸线基准边随 offset 符号变化：
  // horizontal 为负 → 依附顶边，为正 → 依附底边；
  // vertical   为负 → 依附左边，为正 → 依附右边。
  // 拖拽按鼠标位于包络中线的哪一侧决定符号，保证尺寸线精确跟随鼠标。
  const baseNear = envelopeBaseLine(view, face1, face2, orientation, -1)
  const baseFar = envelopeBaseLine(view, face1, face2, orientation, 1)

  if (orientation === 'horizontal') {
    const mid = (baseNear + baseFar) / 2
    const base = mousePos.y < mid ? baseNear : baseFar
    const raw = mousePos.y - base
    return Math.max(2, Math.abs(raw)) * (raw >= 0 ? 1 : -1)
  }
  const mid = (baseNear + baseFar) / 2
  const base = mousePos.x < mid ? baseNear : baseFar
  const raw = mousePos.x - base
  return Math.max(2, Math.abs(raw)) * (raw >= 0 ? 1 : -1)
}
