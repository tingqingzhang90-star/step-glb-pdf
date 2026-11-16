// 表格拖拽:状态机(move/corner/col/row) + 吸附
// 依赖全部由外部注入,本模块不直接依赖 store 或坐标模块
import { ref } from 'vue'
import { tableW, tableH } from '@/tables/tableGeometry'

const FRAME_INSET = 20     // 与 App.vue 图框 x=20 对齐
const SNAP_MM = 2          // 吸附阈值(mm)
// 点击/拖拽判定用屏幕像素,与缩放无关:
// 2mm≈2px(zoom=1) 远低于点击时的自然抖动,会把普通点击误判成拖拽,
// 从而按光标位移重设表格位置并触发吸附(尤其吸到顶部图框上沿)。
const CLICK_PX = 4

export function useTableDrag({ placedTables, sheetWidth, sheetHeight,
  toSheetPoint, resizeCol, resizeRow, resizeTable }) {
  const tableDrag = ref(null)        // {type, tableId, corner?, c?, r?, start}
  const tableSnapGuides = ref([])    // {axis:'vertical'|'horizontal', pos}

  function startMove(event, table) {
    const p = toSheetPoint(event)
    tableDrag.value = {
      type: 'move', tableId: table.id,
      start: { x: p?.x ?? event.clientX, y: p?.y ?? event.clientY,
        tx: table.x, ty: table.y,
        cx: event.clientX, cy: event.clientY }
    }
  }

  function startCornerResize(event, table, corner) {
    const p = toSheetPoint(event)
    tableDrag.value = {
      type: 'corner', tableId: table.id, corner,
      start: { x: p?.x ?? 0, y: p?.y ?? 0,
        tx: table.x, ty: table.y, w: tableW(table), h: tableH(table),
        cx: event.clientX, cy: event.clientY }
    }
  }

  function startColResize(event, table, c) {
    const p = toSheetPoint(event)
    tableDrag.value = {
      type: 'col', tableId: table.id, c,
      start: { x: p?.x ?? 0, w: table.col_widths[c],
        cx: event.clientX, cy: event.clientY }
    }
  }

  function startRowResize(event, table, r) {
    const p = toSheetPoint(event)
    tableDrag.value = {
      type: 'row', tableId: table.id, r,
      start: { y: p?.y ?? 0, h: table.row_heights[r],
        cx: event.clientX, cy: event.clientY }
    }
  }

  function move(event) {
    const d = tableDrag.value
    if (!d) return
    const t = placedTables.value.find(x => x.id === d.tableId)
    if (!t) return
    const p = toSheetPoint(event)
    const px = p?.x ?? event.clientX
    const py = p?.y ?? event.clientY

    // 用屏幕像素差判定点击,与缩放无关:位移不足视为点击(浏览器点击也带
    // 1~3px 微动),恢复起始状态且不吸附,否则点一下表格就被吸到参考线上
    const screenDelta = Math.hypot(
      event.clientX - d.start.cx, event.clientY - d.start.cy)
    if (screenDelta < CLICK_PX) {
      if (d.type === 'col') resizeCol(t.id, d.c, d.start.w)
      else if (d.type === 'row') resizeRow(t.id, d.r, d.start.h)
      else {
        t.x = d.start.tx
        t.y = d.start.ty
        if (d.type === 'corner') resizeTable(t.id, d.start.w, d.start.h)
      }
      tableSnapGuides.value = []
      return
    }

    if (d.type === 'move') {
      t.x = d.start.tx + (px - d.start.x)
      t.y = d.start.ty + (py - d.start.y)
    } else if (d.type === 'corner') {
      applyCorner(t, d, px, py)
    } else if (d.type === 'col') {
      resizeCol(t.id, d.c, Math.max(2, d.start.w + (px - d.start.x)))
    } else if (d.type === 'row') {
      resizeRow(t.id, d.r, Math.max(2, d.start.h + (py - d.start.y)))
    }

    // 吸附:用最新的 t.x/y/w/h 检测与候选参考线对齐,2mm 内贴齐
    const snap = snapGuidesFor(t)
    if (snap.dx || snap.dy) {
      t.x += snap.dx
      t.y += snap.dy
    }
    tableSnapGuides.value = snap.guides
  }

  function applyCorner(t, d, px, py) {
    const s = d.start
    let newW = s.w, newH = s.h
    // 右下角锚定左上;左上角锚定右下并平移
    if (d.corner === 'se') {
      newW = Math.max(20, s.w + px - s.x)
      newH = Math.max(20, s.h + py - s.y)
    } else if (d.corner === 'ne') {
      newW = Math.max(20, s.w + px - s.x)
      newH = Math.max(20, s.h - (py - s.y))
      t.y = s.ty + (s.h - newH)
    } else if (d.corner === 'sw') {
      newW = Math.max(20, s.w - (px - s.x))
      newH = Math.max(20, s.h + py - s.y)
      t.x = s.tx + (s.w - newW)
    } else if (d.corner === 'nw') {
      newW = Math.max(20, s.w - (px - s.x))
      newH = Math.max(20, s.h - (py - s.y))
      t.x = s.tx + (s.w - newW)
      t.y = s.ty + (s.h - newH)
    }
    resizeTable(t.id, newW, newH)
  }

  function end() {
    tableDrag.value = null
    tableSnapGuides.value = []
  }

  // ---- 吸附 ----

  /** 候选参考线只取"边界":图框 4 边 + 其他表格 4 边。
   *  不纳入其他表格的内部行/列网格线:行高仅 6~10mm,线间距太密,
   *  2mm 阈值下几乎处处命中,拖动会被强行拉到任意近邻线,表现为位置乱跳 */
  function snapCandidates(t) {
    const xs = [FRAME_INSET, sheetWidth.value - FRAME_INSET]
    const ys = [FRAME_INSET, sheetHeight.value - FRAME_INSET]
    for (const o of placedTables.value) {
      if (o.id === t.id) continue
      xs.push(o.x, o.x + tableW(o))
      ys.push(o.y, o.y + tableH(o))
    }
    return { xs, ys }
  }

  function bestSnapDelta(myArr, candArr) {
    let best = Infinity, delta = 0
    for (const m of myArr)
      for (const c of candArr)
        if (Math.abs(m - c) < best) { best = Math.abs(m - c); delta = c - m }
    return best <= SNAP_MM ? delta : 0
  }

  function snapGuidesFor(t) {
    const { xs, ys } = snapCandidates(t)
    const w = tableW(t), h = tableH(t)
    // 只用自己的两条边去贴参考线(边贴边),不用中心:中心对齐在边界密集时
    // 会带来难以预期的吸附
    const myX = [t.x, t.x + w]
    const myY = [t.y, t.y + h]
    const dx = bestSnapDelta(myX, xs)
    const dy = bestSnapDelta(myY, ys)
    const guides = []
    for (const m of myX) {
      const c = m + dx
      if (dx !== 0 && xs.includes(c)) {
        guides.push({ axis: 'vertical', pos: c }); break
      }
    }
    for (const m of myY) {
      const c = m + dy
      if (dy !== 0 && ys.includes(c)) {
        guides.push({ axis: 'horizontal', pos: c }); break
      }
    }
    return { dx, dy, guides }
  }

  return {
    tableDrag, tableSnapGuides,
    startMove, startCornerResize, startColResize, startRowResize,
    move, end
  }
}
