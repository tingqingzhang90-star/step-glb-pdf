// 已放置表格管理:放置/选择/删除、单元格文本编辑、合并/拆分
// 与 usePlacedViews 并列,表格是独立元素类型,不混进 views
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { findCellAt } from '@/tables/tableGeometry'

let tableIdCounter = 0

export function usePlacedTables() {
  const placedTables = ref([])
  const selectedTableId = ref(null)
  // 选中的逻辑格坐标 [{r,c}],用于合并;点格切换,Shift+点追加
  const selectedCells = ref([])

  const selectedTable = computed(() =>
    placedTables.value.find(t => t.id === selectedTableId.value))

  /** 放置一个表格(深拷贝预设,互不影响),返回新表格 */
  function placeTable(template, x, y) {
    const t = {
      id: `table_${++tableIdCounter}`,
      x, y,
      col_widths: [...template.col_widths],
      row_heights: [...template.row_heights],
      border: { ...template.border },
      text_color: template.text_color || '#303133',
      cells: template.cells.map(c => ({ ...c }))
    }
    placedTables.value.push(t)
    selectedTableId.value = t.id
    selectedCells.value = []
    return t
  }

  /** 选中表格并清空格选择。用于切换表格、移动、改样式等整体操作 */
  function selectTable(id) {
    selectedTableId.value = id
    selectedCells.value = []
  }

  /** 聚焦到某表但不清空格选择:仅当切换到不同表时才清空。
   *  用于单元格点击/框选,避免切换表格前已选中的格被误清空 */
  function focusTable(id) {
    if (selectedTableId.value !== id) {
      selectedTableId.value = id
      selectedCells.value = []
    }
  }

  function deleteSelectedTable() {
    const id = selectedTableId.value
    if (!id) return
    placedTables.value = placedTables.value.filter(t => t.id !== id)
    selectedTableId.value = null
    selectedCells.value = []
  }

  function clearTables() {
    placedTables.value = []
    selectedTableId.value = null
    selectedCells.value = []
  }

  function updateCellText(tableId, r, c, text) {
    const t = placedTables.value.find(t => t.id === tableId)
    if (!t) return
    const cell = findCellAt(t, r, c)
    if (cell) cell.text = text
  }

  /** 切换/追加选中格;Shift 追加,普通点击单选 */
  function toggleCellSelect(r, c, shiftKey) {
    if (!shiftKey) {
      selectedCells.value = [{ r, c }]
      return
    }
    const idx = selectedCells.value.findIndex(s => s.r === r && s.c === c)
    if (idx >= 0) selectedCells.value.splice(idx, 1)
    else selectedCells.value.push({ r, c })
  }

  /** 合并选中的多格:要求是完整矩形区域 */
  function mergeSelected() {
    const t = selectedTable.value
    if (!t || selectedCells.value.length < 2) return
    const rs = selectedCells.value.map(s => s.r)
    const cs = selectedCells.value.map(s => s.c)
    const r0 = Math.min(...rs), r1 = Math.max(...rs)
    const c0 = Math.min(...cs), c1 = Math.max(...cs)
    // 选中格必须是完整矩形(无遗漏),否则合并后会有空洞
    const expected = (r1 - r0 + 1) * (c1 - c0 + 1)
    if (selectedCells.value.length !== expected) {
      ElMessage.warning('请选择完整的矩形区域再合并')
      return
    }
    // 移除区域内所有现有 cell(要求其矩形完全落在选中区内,避免半截合并)
    t.cells = t.cells.filter(cell => {
      const cs2 = cell.colspan || 1, rs2 = cell.rowspan || 1
      const er = cell.r + rs2 - 1, ec = cell.c + cs2 - 1
      const inside = cell.r >= r0 && er <= r1 && cell.c >= c0 && ec <= c1
      return !inside
    })
    t.cells.push({
      r: r0, c: c0,
      colspan: c1 - c0 + 1, rowspan: r1 - r0 + 1,
      text: '', align: 'h-center v-center'
    })
    selectedCells.value = []
  }

  /** 拆分选中格(仅当该格是合并格) */
  function splitSelected() {
    const t = selectedTable.value
    if (!t || selectedCells.value.length !== 1) return
    const { r, c } = selectedCells.value[0]
    const cell = findCellAt(t, r, c)
    if (!cell) return
    const cs = cell.colspan || 1, rs = cell.rowspan || 1
    if (cs === 1 && rs === 1) return
    const r0 = cell.r, c0 = cell.c
    t.cells = t.cells.filter(x => x !== cell)
    for (let i = 0; i < rs; i++)
      for (let j = 0; j < cs; j++)
        t.cells.push({ r: r0 + i, c: c0 + j, text: '', align: 'h-left' })
    selectedCells.value = []
  }

  // ---- 行列增删:跨该行/列的合并格自动扩展或收缩 ----
  function insertRow(tableId, r, dir) {       // dir: 'above' | 'below'
    const t = placedTables.value.find(x => x.id === tableId)
    if (!t) return
    const newR = dir === 'above' ? r : r + 1
    // 跨越 newR 的合并格 rowspan+1(用原始坐标判断,先于 r 偏移)
    for (const cell of t.cells) {
      const rs = cell.rowspan || 1
      if (cell.r < newR && cell.r + rs > newR) cell.rowspan = rs + 1
    }
    for (const cell of t.cells) {
      if (cell.r >= newR) cell.r += 1
    }
    t.row_heights.splice(newR, 0, 8)
    // 为新行补空 cell(除非已被扩展的合并格覆盖)
    for (let c = 0; c < t.col_widths.length; c++) {
      if (!findCellAt(t, newR, c)) {
        t.cells.push({ r: newR, c, text: '', align: 'h-left' })
      }
    }
    selectedCells.value = []
  }

  function deleteRow(tableId, r) {
    const t = placedTables.value.find(x => x.id === tableId)
    if (!t || t.row_heights.length <= 1) return
    // 跨越 r 的合并格(起点在上方)收缩
    for (const cell of t.cells) {
      const rs = cell.rowspan || 1
      if (cell.r < r && cell.r + rs > r) cell.rowspan = rs - 1
    }
    // 删除起点在 r 的 cell;r>r 的下移
    t.cells = t.cells
      .filter(cell => cell.r !== r)
      .map(cell => cell.r > r ? { ...cell, r: cell.r - 1 } : cell)
    t.row_heights.splice(r, 1)
    selectedCells.value = []
  }

  function insertCol(tableId, c, dir) {        // dir: 'left' | 'right'
    const t = placedTables.value.find(x => x.id === tableId)
    if (!t) return
    const newC = dir === 'left' ? c : c + 1
    for (const cell of t.cells) {
      const cs = cell.colspan || 1
      if (cell.c < newC && cell.c + cs > newC) cell.colspan = cs + 1
    }
    for (const cell of t.cells) {
      if (cell.c >= newC) cell.c += 1
    }
    t.col_widths.splice(newC, 0, 40)
    for (let r = 0; r < t.row_heights.length; r++) {
      if (!findCellAt(t, r, newC)) {
        t.cells.push({ r, c: newC, text: '', align: 'h-left' })
      }
    }
    selectedCells.value = []
  }

  function deleteCol(tableId, c) {
    const t = placedTables.value.find(x => x.id === tableId)
    if (!t || t.col_widths.length <= 1) return
    for (const cell of t.cells) {
      const cs = cell.colspan || 1
      if (cell.c < c && cell.c + cs > c) cell.colspan = cs - 1
    }
    t.cells = t.cells
      .filter(cell => cell.c !== c)
      .map(cell => cell.c > c ? { ...cell, c: cell.c - 1 } : cell)
    t.col_widths.splice(c, 1)
    selectedCells.value = []
  }

  // ---- 尺寸调整 ----
  function resizeCol(tableId, c, newW) {
    const t = placedTables.value.find(x => x.id === tableId)
    if (!t) return
    t.col_widths[c] = Math.max(2, newW)
  }
  function resizeRow(tableId, r, newH) {
    const t = placedTables.value.find(x => x.id === tableId)
    if (!t) return
    t.row_heights[r] = Math.max(2, newH)
  }

  /** 四角拖拽:等比缩放所有列宽/行高(外层负责调 x/y) */
  function resizeTable(tableId, newW, newH) {
    const t = placedTables.value.find(x => x.id === tableId)
    if (!t) return
    const oldW = t.col_widths.reduce((a, b) => a + b, 0)
    const oldH = t.row_heights.reduce((a, b) => a + b, 0)
    if (oldW < 1 || oldH < 1) return
    const sx = newW / oldW, sy = newH / oldH
    t.col_widths = t.col_widths.map(w => Math.max(2, w * sx))
    t.row_heights = t.row_heights.map(h => Math.max(2, h * sy))
  }

  /** 左上角拖拽:平移 x/y 并缩放(右下角锚定) */
  function resizeFromTopLeft(tableId, dx, dy, newW, newH) {
    const t = placedTables.value.find(x => x.id === tableId)
    if (!t) return
    t.x += dx
    t.y += dy
    resizeTable(tableId, newW, newH)
  }

  // ---- 样式 ----
  function setCellFontSize(tableId, r, c, size) {
    const t = placedTables.value.find(x => x.id === tableId)
    if (!t) return
    const cell = findCellAt(t, r, c)
    if (cell) cell.font_size = size
  }
  function setTableBorder(tableId, width, color) {
    const t = placedTables.value.find(x => x.id === tableId)
    if (!t) return
    t.border = { width, color }
  }

  return {
    placedTables, selectedTableId, selectedTable, selectedCells,
    placeTable, selectTable, focusTable, deleteSelectedTable, clearTables,
    updateCellText, toggleCellSelect, mergeSelected, splitSelected,
    findCellAt,
    insertRow, deleteRow, insertCol, deleteCol,
    resizeCol, resizeRow, resizeTable, resizeFromTopLeft,
    setCellFontSize, setTableBorder
  }
}
