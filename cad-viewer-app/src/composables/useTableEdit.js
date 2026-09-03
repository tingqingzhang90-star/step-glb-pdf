// 表格编辑交互:inline 编辑 / 右键行列菜单 / 样式 / 键盘 / 插入
// 依赖 usePlacedTables 的能力,由外部注入
import { ref } from 'vue'

const DEFAULT_COL_W = 30
const DEFAULT_ROW_H = 8

export function useTableEdit(tables, { sheetWidth, sheetHeight }) {
  const {
    placedTables, selectedTableId, selectedTable, selectedCells,
    selectTable, focusTable, deleteSelectedTable, updateCellText, toggleCellSelect,
    insertRow, deleteRow, insertCol, deleteCol,
    setCellFontSize, setTableBorder, placeTable
  } = tables

  // ---- inline 编辑 ----
  // editingCell 只标记"哪个格在编辑",input 的聚焦由渲染层(TableLayer)
  // 监听该状态自行处理,避免跨组件传 element ref
  const editingCell = ref(null)      // {tableId, r, c}
  // 悬浮预览格:鼠标移到格上即显示输入框外观,单击才真正进入编辑
  const hoverCell = ref(null)        // {tableId, r, c}

  /** 进入编辑:聚焦指定格(选中样式由 selectedCells/editingCell 共同体现) */
  function editCell(table, r, c) {
    focusTable(table.id)
    selectedCells.value = [{ r, c }]
    editingCell.value = { tableId: table.id, r, c }
  }

  function startEdit(event, table, r, c) {
    event.stopPropagation()
    editCell(table, r, c)
  }

  /** 回车或失焦提交:取 input 当前值写回单元格 */
  function commitEdit(event) {
    const v = event?.target?.value
    const ec = editingCell.value
    if (ec && v !== undefined) updateCellText(ec.tableId, ec.r, ec.c, v)
    editingCell.value = null
  }

  function onCellClick(event, table, r, c) {
    event.stopPropagation()
    focusTable(table.id)
    toggleCellSelect(r, c, event.shiftKey)
  }

  // ---- 框选:Shift+按住拖拽在表格上拉出矩形选区(普通拖拽仍用于移动表格) ----
  const selAnchor = ref(null)   // { tableId, r, c }
  const selDragging = ref(false)

  /** mousedown 在格上:Shift 才进入框选,否则交给表格拖动 */
  function startCellSelect(event, table, r, c) {
    if (!event.shiftKey) return
    event.stopPropagation()
    event.preventDefault()
    focusTable(table.id)
    selAnchor.value = { tableId: table.id, r, c }
    selDragging.value = true
  }

  /** 拖拽过程中经过的格:以锚点拉出完整矩形选区 */
  function extendCellSelect(table, r, c) {
    if (!selDragging.value || !selAnchor.value) return
    if (selAnchor.value.tableId !== table.id) return
    const { r: r0, c: c0 } = selAnchor.value
    const cells = []
    for (let rr = Math.min(r0, r); rr <= Math.max(r0, r); rr++)
      for (let cc = Math.min(c0, c); cc <= Math.max(c0, c); cc++)
        cells.push({ r: rr, c: cc })
    selectedCells.value = cells
  }

  function endCellSelect() {
    selDragging.value = false
    selAnchor.value = null
  }

  // ---- 悬浮预览:移到格上显示输入框外观,离开清除(编辑中不清除) ----
  function onCellHover(table, r, c) {
    if (selDragging.value) {
      extendCellSelect(table, r, c)
      return
    }
    hoverCell.value = { tableId: table.id, r, c }
  }
  function clearHover() {
    if (!editingCell.value) hoverCell.value = null
  }

  // ---- 右键菜单:插入/删除行列 ----
  const contextMenu = ref(null)      // {x, y, tableId, r, c}

  function openContextMenu(event, table, r, c) {
    event.preventDefault()
    event.stopPropagation()
    selectTable(table.id)
    contextMenu.value = {
      x: event.clientX, y: event.clientY, tableId: table.id, r, c
    }
  }
  function closeContextMenu() { contextMenu.value = null }

  function ctxInsertRow(dir) {
    const m = contextMenu.value
    if (m) insertRow(m.tableId, m.r, dir)
    closeContextMenu()
  }
  function ctxDeleteRow() {
    const m = contextMenu.value
    if (m) deleteRow(m.tableId, m.r)
    closeContextMenu()
  }
  function ctxInsertCol(dir) {
    const m = contextMenu.value
    if (m) insertCol(m.tableId, m.c, dir)
    closeContextMenu()
  }
  function ctxDeleteCol() {
    const m = contextMenu.value
    if (m) deleteCol(m.tableId, m.c)
    closeContextMenu()
  }

  // ---- 样式(作用于选中格 / 选中表) ----
  function setFontOfSelected(v) {
    const t = selectedTable.value
    const cells = selectedCells.value
    if (!t || cells.length !== 1) return
    setCellFontSize(t.id, cells[0].r, cells[0].c, Number(v) || 13)
  }
  function setBorderWidth(v) {
    const t = selectedTable.value
    if (!t) return
    setTableBorder(t.id, Number(v) || 0.3, t.border?.color || '#303133')
  }
  function setBorderColor(v) {
    const t = selectedTable.value
    if (!t) return
    setTableBorder(t.id, t.border?.width ?? 0.3, v)
  }

  // ---- 键盘:Delete 删选中表(编辑中或焦点在输入框时不拦截) ----
  function handleKeydown(event) {
    if (event.key !== 'Delete' && event.key !== 'Backspace') return
    if (editingCell.value) return
    if (!selectedTableId.value) return
    const tag = event.target?.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA') return
    event.preventDefault()
    deleteSelectedTable()
  }

  // ---- 插入 ----
  /** 插入完全空的表格(无占位文字),居中放置 */
  function insertEmptyTable(rows, cols) {
    const cells = []
    for (let r = 0; r < rows; r++)
      for (let c = 0; c < cols; c++)
        cells.push({ r, c, text: '', align: 'h-left' })
    const preset = {
      col_widths: Array(cols).fill(DEFAULT_COL_W),
      row_heights: Array(rows).fill(DEFAULT_ROW_H),
      border: { width: 0.3, color: '#303133' },
      text_color: '#303133',
      cells
    }
    const w = DEFAULT_COL_W * cols, h = DEFAULT_ROW_H * rows
    placeTable(preset,
      (sheetWidth.value - w) / 2,
      (sheetHeight.value - h) / 2)
  }

  /** 插入预设表格(如"技术参数"表) */
  function insertPresetTable(preset) {
    placeTable(preset, sheetWidth.value - 180, 50)
  }

  return {
    editingCell, hoverCell, contextMenu,
    startEdit, editCell, commitEdit, onCellClick,
    startCellSelect, extendCellSelect, endCellSelect,
    onCellHover, clearHover,
    openContextMenu, closeContextMenu,
    ctxInsertRow, ctxDeleteRow, ctxInsertCol, ctxDeleteCol,
    setFontOfSelected, setBorderWidth, setBorderColor,
    handleKeydown, insertEmptyTable, insertPresetTable
  }
}
