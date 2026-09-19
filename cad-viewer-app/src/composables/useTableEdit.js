// 表格编辑交互:inline 编辑 / 右键行列菜单 / 样式 / 键盘 / 插入
// 依赖 usePlacedTables 的能力,由外部注入
import { ref, watch } from 'vue'
import { TABLE_STYLE } from '@/composables/useStyleConfig'

const DEFAULT_COL_W = TABLE_STYLE.colWidth
const DEFAULT_ROW_H = TABLE_STYLE.rowHeight

export function useTableEdit(tables, { sheetWidth, sheetHeight }) {
  const {
    placedTables, selectedTableId, selectedTable, selectedCells,
    selectTable, focusTable, deleteSelectedTable, updateCellText, toggleCellSelect,
    insertRow, deleteRow, insertCol, deleteCol,
    setCellFontSize, setCellAlign, setTableBorder, placeTable
  } = tables

  // 当前字号“画笔”:用户设置一次后保持,切换到其他单元格时不再被该单元格原字号覆盖
  const activeFontSize = ref(TABLE_STYLE.fontPx)

  // ---- inline 编辑 ----
  // editingCell 只标记"哪个格在编辑",input 的聚焦由渲染层(TableLayer)
  // 监听该状态自行处理,避免跨组件传 element ref
  const editingCell = ref(null)      // {tableId, r, c}
  // 悬浮预览格:鼠标移到格上即显示输入框外观,单击才真正进入编辑
  const hoverCell = ref(null)        // {tableId, r, c}

  /** 进入编辑:聚焦指定格(选中样式由 selectedCells/editingCell 共同体现)。
   *  part 为拆分子格下标,未拆分时不传 */
  function editCell(table, r, c, part) {
    focusTable(table.id)
    selectedCells.value = [{ r, c }]
    editingCell.value = { tableId: table.id, r, c, part: part == null ? undefined : part }
  }

  function startEdit(event, table, r, c, part) {
    event.stopPropagation()
    editCell(table, r, c, part)
  }

  /** 回车或失焦提交:取 input 当前值写回单元格(或拆分子格) */
  function commitEdit(event) {
    const v = event?.target?.value
    const ec = editingCell.value
    if (ec && v !== undefined) updateCellText(ec.tableId, ec.r, ec.c, v, ec.part)
    editingCell.value = null
  }

  /** Esc 取消编辑:丢弃输入,不写回(失焦随之触发的 commit 会因 editingCell 为空而跳过) */
  function cancelEdit() {
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
  function onCellHover(table, r, c, part) {
    if (selDragging.value) {
      extendCellSelect(table, r, c)
      return
    }
    hoverCell.value = { tableId: table.id, r, c, part: part == null ? undefined : part }
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
    // 右键目标格如果没有在选区里,把它作为当前选区,否则对齐/字号等样式操作没目标
    const inSelection = selectedCells.value.some(x => x.r === r && x.c === c)
    if (!inSelection) {
      selectedCells.value = [{ r, c }]
    }
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
  function setAlignOfSelected(align) {
    const t = selectedTable.value
    const cells = selectedCells.value
    if (!t || !cells.length) return
    for (const { r, c } of cells) {
      setCellAlign(t.id, r, c, align)
    }
    closeContextMenu()
  }

  function setFontOfSelected(v) {
    activeFontSize.value = Number(v) || TABLE_STYLE.fontPx
    const t = selectedTable.value
    const cells = selectedCells.value
    if (!t || !cells.length) return
    for (const { r, c } of cells) {
      setCellFontSize(t.id, r, c, activeFontSize.value)
    }
  }

  // 切换单元格时把当前字号刷过去,避免到下一格就“变回”原字号
  watch(selectedCells, (cells) => {
    const t = selectedTable.value
    if (!t || !cells.length) return
    for (const { r, c } of cells) {
      setCellFontSize(t.id, r, c, activeFontSize.value)
    }
  }, { deep: true })
  function setBorderWidth(v) {
    const t = selectedTable.value
    if (!t) return
    setTableBorder(t.id, Number(v) || TABLE_STYLE.borderWidth,
      t.border?.color || TABLE_STYLE.borderColor)
  }
  function setBorderColor(v) {
    const t = selectedTable.value
    if (!t) return
    setTableBorder(t.id, t.border?.width ?? TABLE_STYLE.borderWidth, v)
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
        cells.push({ r, c, text: '', align: 'h-center v-center' })
    const preset = {
      col_widths: Array(cols).fill(DEFAULT_COL_W),
      row_heights: Array(rows).fill(DEFAULT_ROW_H),
      border: { width: TABLE_STYLE.borderWidth, color: TABLE_STYLE.borderColor },
      text_color: TABLE_STYLE.textColor,
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
    editingCell, hoverCell, contextMenu, activeFontSize,
    startEdit, editCell, commitEdit, cancelEdit, onCellClick,
    startCellSelect, extendCellSelect, endCellSelect,
    onCellHover, clearHover,
    openContextMenu, closeContextMenu,
    ctxInsertRow, ctxDeleteRow, ctxInsertCol, ctxDeleteCol,
    setAlignOfSelected, setFontOfSelected, setBorderWidth, setBorderColor,
    handleKeydown, insertEmptyTable, insertPresetTable
  }
}
