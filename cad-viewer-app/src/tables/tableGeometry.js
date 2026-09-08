// 表格几何计算(纯函数,不持有状态)
// 坐标单位:mm。表格 x/y 是 SVG 左上角,与 views 同坐标系。
// 合并格只在其左上角声明 colspan/rowspan,被覆盖格由 findCellAt 反查。

import { PX_TO_MM, TABLE_STYLE } from '@/composables/useStyleConfig'

/** 各列左边的 x(长度 = 列数+1,末位是表格右边界) */
export function tableColLefts(t) {
  const a = [t.x]
  for (const w of t.col_widths) a.push(a[a.length - 1] + w)
  return a
}

/** 各行顶部的 y(长度 = 行数+1,末位是表格下边界) */
export function tableRowTops(t) {
  const a = [t.y]
  for (const h of t.row_heights) a.push(a[a.length - 1] + h)
  return a
}

export function tableW(t) {
  return t.col_widths.reduce((a, b) => a + b, 0)
}

export function tableH(t) {
  return t.row_heights.reduce((a, b) => a + b, 0)
}

/** (r,c) 所属的左上角 cell;被合并覆盖时返回覆盖它的那个 cell */
export function findCellAt(table, r, c) {
  for (const cell of table.cells) {
    const cs = cell.colspan || 1
    const rs = cell.rowspan || 1
    if (r >= cell.r && r < cell.r + rs && c >= cell.c && c < cell.c + cs) {
      return cell
    }
  }
  return null
}

/** 渲染用的"逻辑格"列表:每个 (r,c) 一个,被覆盖格也列出(只做命中) */
export function tableLogicalCells(t) {
  const out = []
  for (let r = 0; r < t.row_heights.length; r++) {
    for (let c = 0; c < t.col_widths.length; c++) {
      const cell = findCellAt(t, r, c)
      out.push({
        r, c, cell,
        isOrigin: !!(cell && cell.r === r && cell.c === c)
      })
    }
  }
  return out
}

/** 四角缩放手柄位置 */
export function cornerHandles(t) {
  const w = tableW(t), h = tableH(t)
  return [
    { corner: 'nw', x: t.x, y: t.y },
    { corner: 'ne', x: t.x + w, y: t.y },
    { corner: 'sw', x: t.x, y: t.y + h },
    { corner: 'se', x: t.x + w, y: t.y + h }
  ]
}

/** 列宽手柄所在的列索引(内部竖网格线,1..cols-1) */
export function colResizeHandles(t) {
  return Array.from({ length: t.col_widths.length - 1 }, (_, i) => i + 1)
}

/** 行高手柄所在的行索引(内部水平网格线,1..rows-1) */
export function rowResizeHandles(t) {
  return Array.from({ length: t.row_heights.length - 1 }, (_, i) => i + 1)
}

/** 合并格的实际矩形(按 colspan/rowspan 累加) */
export function cellRect(t, cell) {
  const lefts = tableColLefts(t)
  const tops = tableRowTops(t)
  const cs = cell.colspan || 1
  const rs = cell.rowspan || 1
  return {
    x: lefts[cell.c],
    y: tops[cell.r],
    w: lefts[cell.c + cs] - lefts[cell.c],
    h: tops[cell.r + rs] - tops[cell.r]
  }
}

/** (r,c) 所在格的矩形(供 inline 编辑定位) */
export function cellRectAt(t, r, c) {
  const cell = findCellAt(t, r, c)
  if (!cell) return { r, c, x: 0, y: 0, w: 0, h: 0, text: '' }
  const rect = cellRect(t, cell)
  return { r, c, ...rect, text: cell.text || '' }
}



/** 单元格文字水平对齐 → SVG text-anchor */
export function cellTextAnchor(cell) {
  const a = hAlign(cell)
  if (a === 'h-center') return 'middle'
  if (a === 'h-right') return 'end'
  return 'start'
}

/** 单元格文字 x(合并格按其完整矩形算) */
export function cellTextX(t, cell) {
  const r = cellRect(t, cell)
  const a = hAlign(cell)
  if (a === 'h-center') return r.x + r.w / 2
  if (a === 'h-right') return r.x + r.w - 1
  return r.x + 1
}

/** 单元格文字 y(baseline,垂直居中近似) */
export function cellTextY(t, cell) {
  const r = cellRect(t, cell)
  const fs = cellFontSize(cell)
  return r.y + r.h / 2 + fs * 0.35
}

/** 单元格文字字号(mm)。cell 未指定 font_size 时取 cad_viewer_style.json 的 table.text.font_px */
export function cellFontSize(cell) {
  return (cell.font_size || TABLE_STYLE.fontPx) * PX_TO_MM
}

function hAlign(cell) {
  return (cell.align || 'h-left').split(' ').find(s => s.startsWith('h-')) || 'h-left'
}

/** sheet 坐标点 → 最近格 (r,c)(合并格归到其左上角所在行列) */
export function cellRCAtPoint(t, pt) {
  const lefts = tableColLefts(t)
  const tops = tableRowTops(t)
  let c = -1
  for (let i = 0; i < t.col_widths.length; i++) {
    if (pt.x >= lefts[i] && pt.x < lefts[i + 1]) { c = i; break }
  }
  let r = -1
  for (let i = 0; i < t.row_heights.length; i++) {
    if (pt.y >= tops[i] && pt.y < tops[i + 1]) { r = i; break }
  }
  if (r < 0 || c < 0) return null
  return { r, c }
}
