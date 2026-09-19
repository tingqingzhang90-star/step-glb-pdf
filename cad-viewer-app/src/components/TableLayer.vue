<template>
  <!-- 表格渲染层:网格 + 合并格 + 文字 + 手柄 + inline 编辑 -->
  <g @mouseleave="emit('cell-mouseleave')">
    <g
      v-for="t in tables"
      :key="t.id"
      :class="['placed-table', { selected: selectedId === t.id }]"
      @mousedown.stop="!readonly && emit('table-mousedown', $event, t)"
    >
      <template v-for="lc in tableLogicalCells(t)" :key="`${t.id}-${lc.r}-${lc.c}`">
        <!-- 左上角格:画边框+文字;被覆盖格:透明只做命中,避免合并区内部出网格线 -->
        <rect
          v-if="lc.isOrigin"
          v-bind="originRectAttrs(t, lc)"
          @mousedown="!readonly && emit('cell-mousedown', $event, t, lc.r, lc.c)"
          @mouseenter="!readonly && emit('cell-mouseenter', $event, t, lc.r, lc.c)"
          @click.stop="!readonly && emit('cell-click', $event, t, lc.r, lc.c)"
          @dblclick.stop="!readonly && emit('cell-dblclick', $event, t, lc.r, lc.c)"
          @contextmenu.prevent.stop="!readonly && emit('cell-contextmenu', $event, t, lc.r, lc.c)"
        />
        <rect
          v-else
          :x="tableColLefts(t)[lc.c]"
          :y="tableRowTops(t)[lc.r]"
          :width="t.col_widths[lc.c]"
          :height="t.row_heights[lc.r]"
          fill="transparent"
          stroke="none"
          @mousedown="!readonly && emit('cell-mousedown', $event, t, lc.r, lc.c)"
          @mouseenter="!readonly && emit('cell-mouseenter', $event, t, lc.r, lc.c)"
          @click.stop="!readonly && emit('cell-click', $event, t, lc.r, lc.c)"
          @dblclick.stop="!readonly && emit('cell-dblclick', $event, t, lc.r, lc.c)"
          @contextmenu.prevent.stop="!readonly && emit('cell-contextmenu', $event, t, lc.r, lc.c)"
        />
        <TableSplitParts
          v-if="lc.isOrigin && isSplit(lc.cell)"
          :table="t" :cell="lc.cell" :readonly="readonly"
          :active-part="activePartOf(t, lc)"
          @part="onPartEvent($event, t, lc)"
        />
        <text
          v-if="lc.isOrigin && lc.cell.text && !isTextCoveredByInput(t, lc)"
          :x="cellTextX(t, lc.cell)"
          :y="cellTextY(t, lc.cell)"
          :font-size="cellFontSize(lc.cell)"
          :fill="t.text_color || TABLE_STYLE.textColor"
          :text-anchor="cellTextAnchor(lc.cell)"
          :dominant-baseline="cellTextBaseline(lc.cell)"
          :style="{ fontWeight: lc.cell.bold ? 'bold' : 'normal' }"
        >
          <template v-if="cellLineCount(lc.cell) > 1">
            <tspan
              v-for="(ln, i) in cellLines(lc.cell)" :key="i"
              :x="cellTextX(t, lc.cell)"
              :y="multiLineYs(cellRect(t, lc.cell), lc.cell, cellLineCount(lc.cell))[i]"
              dominant-baseline="central"
            >{{ ln || '\u00a0' }}</tspan>
          </template>
          <template v-else>{{ lc.cell.text }}</template>
        </text>
        <!-- 单元格符号(SVG):居中适配于格内(内边距 1.5mm),不拦截鼠标 -->
        <image
          v-if="lc.isOrigin && lc.cell.symbol"
          :href="symbolUrl(lc.cell.symbol)"
          :x="cellRect(t, lc.cell).x + 1.5"
          :y="cellRect(t, lc.cell).y + 1.5"
          :width="Math.max(1, cellRect(t, lc.cell).w - 3)"
          :height="Math.max(1, cellRect(t, lc.cell).h - 3)"
          preserveAspectRatio="xMidYMid meet"
          pointer-events="none"
        />
      </template>

      <!-- 选中外框:吸附命中时变品红加粗,提示"这张表吸上了" -->
      <rect
        v-if="selectedId === t.id && !readonly"
        :x="t.x" :y="t.y" :width="tableW(t)" :height="tableH(t)"
        fill="none"
        :stroke="snapGuides.length ? '#e84393' : '#409eff'"
        :stroke-width="snapGuides.length ? 2 : 1"
        stroke-dasharray="4,2" vector-effect="non-scaling-stroke"
        pointer-events="none"
      />

      <template v-if="selectedId === t.id && !readonly">
        <!-- 四角 L 形缩放手柄:视觉路径 + 透明大命中区 -->
        <g v-for="cr in cornerHandles(t)" :key="`ch-${t.id}-${cr.corner}`">
          <circle :cx="cr.x" :cy="cr.y" r="5" fill="transparent"
            @mousedown.stop.prevent="emit('corner-mousedown', $event, t, cr.corner)"
            @click.stop
          />
          <path :d="cornerHandlePath(t, cr.corner)" fill="none" stroke="#409eff"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
            vector-effect="non-scaling-stroke" pointer-events="none"
          />
        </g>
        <!-- 列宽手柄(竖网格线顶端) / 行高手柄(水平网格线左端) -->
        <circle v-for="c in colResizeHandles(t)" :key="`cr-${t.id}-${c}`"
          :cx="tableColLefts(t)[c]" :cy="t.y" r="2.5"
          fill="#67c23a" stroke="#fff" stroke-width="0.5"
          vector-effect="non-scaling-stroke"
          @mousedown.stop.prevent="emit('col-mousedown', $event, t, c - 1)"
          @click.stop
        />
        <circle v-for="r in rowResizeHandles(t)" :key="`rr-${t.id}-${r}`"
          :cx="t.x" :cy="tableRowTops(t)[r]" r="2.5"
          fill="#e6a23c" stroke="#fff" stroke-width="0.5"
          vector-effect="non-scaling-stroke"
          @mousedown.stop.prevent="emit('row-mousedown', $event, t, r - 1)"
          @click.stop
        />
      </template>

      <!-- inline 编辑:悬浮预览 + 单击进入。activeCell = 编辑中优先,其次悬浮格 -->
      <foreignObject
        v-if="activeCellOf(t)"
        v-bind="editRectAttrsFor(t, activeCellOf(t))"
        :style="foreignObjectStyleFor(t, activeCellOf(t))"
      >
        <div
          class="cell-edit-wrapper"
          :style="wrapperStyleFor(t, activeCellOf(t))"
        >
          <textarea
            ref="cellEditInput"
            class="cell-edit-input"
            rows="1"
            :key="`${activeCellOf(t).r}-${activeCellOf(t).c}-${activeCellOf(t).part ?? -1}`"
            :style="inputStyleFor(t, activeCellOf(t))"
            :defaultValue="editTextFor(t, activeCellOf(t))"
            @keydown.ctrl.enter.prevent="emit('edit-commit', $event)"
            @keydown.meta.enter.prevent="emit('edit-commit', $event)"
            @keydown.esc.prevent="emit('edit-cancel')"
            @input="onEditInput"
            @blur="emit('edit-commit', $event)"
            @mousedown.stop
            @contextmenu.prevent.stop="emit('cell-contextmenu', $event, t, activeCellOf(t).r, activeCellOf(t).c)"
          ></textarea>
        </div>
      </foreignObject>
    </g>
  </g>
</template>

<script setup>
// 表格 SVG 渲染层:只负责画与事件转发,状态与逻辑在 composable 里
import { nextTick, ref, watch } from 'vue'
import { TABLE_STYLE } from '@/composables/useStyleConfig'
import { symbolUrl } from '@/api/symbols'
import {
  tableColLefts, tableRowTops, tableW, tableH, tableLogicalCells,
  cornerHandles, cornerHandlePath, colResizeHandles, rowResizeHandles,
  cellRect, cellRectAt, cellPartRects, cellTextX, cellTextY, cellTextAnchor, cellTextBaseline, cellFontSize,
  textLines, multiLineYs,
  findCellAt
} from '@/tables/tableGeometry'
import TableSplitParts from '@/components/TableSplitParts.vue'

const props = defineProps({
  tables: { type: Array, required: true },
  selectedId: { type: String, default: null },
  selectedCells: { type: Array, default: () => [] },
  editingCell: { type: Object, default: null },
  hoverCell: { type: Object, default: null },
  readonly: { type: Boolean, default: false },
  snapGuides: { type: Array, default: () => [] }
})

const emit = defineEmits([
  'table-mousedown', 'cell-click', 'cell-dblclick', 'cell-contextmenu',
  'cell-mousedown', 'cell-mouseenter', 'cell-mouseleave',
  'corner-mousedown', 'col-mousedown', 'row-mousedown', 'edit-commit', 'edit-cancel'
])

const cellEditInput = ref(null)

// 进入编辑时自动聚焦并全选,省掉一次点击
// cellEditInput 在 v-for 内可能是数组,统一取首个元素
watch(() => props.editingCell, async (v) => {
  if (!v) return
  await nextTick()
  const inp = Array.isArray(cellEditInput.value) ? cellEditInput.value[0] : cellEditInput.value
  inp?.focus()
  inp?.select()
})

function isCellActive(t, r, c) {
  // 必须限定在当前选中的表内:selectedCells 只带 r/c,若不按表 id 过滤,
  // 另一张同尺寸表格的相同坐标格会被一起染成选中蓝底,看起来像"串表"。
  if (props.selectedId !== t.id) return false
  if (props.selectedCells.some(s => s.r === r && s.c === c)) return true
  return !!(props.editingCell && props.editingCell.r === r && props.editingCell.c === c)
}

/** 左上角格(含合并格)的绘制属性 */
function originRectAttrs(t, lc) {
  const rect = cellRect(t, lc.cell)
  return {
    x: rect.x, y: rect.y, width: rect.w, height: rect.h,
    fill: isCellActive(t, lc.r, lc.c) ? '#ecf5ff' : 'white',
    stroke: (t.border && t.border.color) || TABLE_STYLE.borderColor,
    'stroke-width': (t.border && t.border.width) || TABLE_STYLE.borderWidth
  }
}

function isSplit(cell) {
  return !!(cell && cell.split_dir && (cell.split_count || 0) >= 2)
}

function cellLines(cell) {
  return textLines(cell.text)
}
function cellLineCount(cell) {
  return textLines(cell.text).length
}

/** 当前悬浮/编辑命中的子格下标;不落在该格则返回 -1 */
function activePartOf(t, lc) {
  const ac = activeCellOf(t)
  if (!ac || findCellAt(t, ac.r, ac.c) !== lc.cell) return -1
  return ac.part == null ? -1 : ac.part
}

function onPartEvent({ type, event, part }, t, lc) {
  emit(type, event, t, lc.r, lc.c, part)
}
// ---- 悬浮预览 / 编辑态共用的定位与样式 ----
function activeCellOf(t) {
  if (props.readonly) return null
  if (props.editingCell && props.editingCell.tableId === t.id) return props.editingCell
  if (props.hoverCell && props.hoverCell.tableId === t.id) return props.hoverCell
  return null
}

function isEditingCell(ac) {
  return !!(props.editingCell &&
    props.editingCell.tableId === ac.tableId &&
    props.editingCell.r === ac.r && props.editingCell.c === ac.c)
}

/** 该格的文字是否正被 inline input 覆盖。
 *  按解析出的 cell 对象比较(而非 r/c),合并格的任意子格都能命中同一个 cell,
 *  否则悬浮合并格下半部分时会出现 SVG 文字与 input 文字叠字。 */
function isTextCoveredByInput(t, lc) {
  const ac = activeCellOf(t)
  if (!ac) return false
  return findCellAt(t, ac.r, ac.c) === lc.cell
}

function editRectAttrsFor(t, ac) {
  const cell = findCellAt(t, ac.r, ac.c)
  const partRect = (ac.part != null && cell) ? cellPartRects(t, cell)[ac.part] : null
  const r = partRect || cellRectAt(t, ac.r, ac.c)
  return { x: r.x, y: r.y, width: r.w, height: r.h }
}

// 预览(悬浮)态 foreignObject 必须完全穿透,否则它会盖在单元格矩形之上
// 截走 mousedown,导致点格变成拖动整表、无法进入编辑。
function foreignObjectStyleFor(t, ac) {
  return {
    overflow: 'visible',
    pointerEvents: isEditingCell(ac) ? 'all' : 'none'
  }
}

function editTextFor(t, ac) {
  const cell = findCellAt(t, ac.r, ac.c)
  if (ac.part != null && cell && cell.parts && cell.parts[ac.part]) return cell.parts[ac.part].text || ''
  return cellRectAt(t, ac.r, ac.c).text
}

function wrapperStyleFor(t, ac) {
  const cell = findCellAt(t, ac.r, ac.c)
  if (!cell) return {}
  const h = ((cell.align || '').split(/\s+/).find(s => s.startsWith('h-')) || 'h-center')
  const v = ((cell.align || '').split(/\s+/).find(s => s.startsWith('v-')) || 'v-center')
  return {
    width: '100%',
    height: '100%',
    display: 'flex',
    justifyContent: h === 'h-center' ? 'center' : h === 'h-right' ? 'flex-end' : 'flex-start',
    alignItems: v === 'v-top' ? 'flex-start' : v === 'v-bottom' ? 'flex-end' : 'center',
    boxSizing: 'border-box',
    // 编辑时允许多行输入框溢出格高,避免换行内容被裁掉
    overflow: isEditingCell(ac) ? 'visible' : 'hidden'
  }
}

/** 换行输入时让 textarea 随内容增高(第一行以外不再被裁切) */
function onEditInput(event) {
  const el = event && event.target
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight}px`
}

function inputStyleFor(t, ac) {
  const cell = findCellAt(t, ac.r, ac.c)
  if (!cell) return {}
  const h = ((cell.align || '').split(/\s+/).find(s => s.startsWith('h-')) || 'h-center')
  const v = ((cell.align || '').split(/\s+/).find(s => s.startsWith('v-')) || 'v-center')
  const editing = isEditingCell(ac)
  return {
    color: t.text_color || TABLE_STYLE.textColor,
    // foreignObject 内 CSS px 等价于 SVG 用户单位(mm),故字号须用 mm 值,与单元格文字一致
    fontSize: `${cellFontSize(cell)}px`,
    fontWeight: cell.bold ? 'bold' : 'normal',
    textAlign: h === 'h-center' ? 'center' : h === 'h-right' ? 'right' : 'left',
    lineHeight: '1.25',
    padding: v === 'v-top' ? '1px 1px 0 1px' : v === 'v-bottom' ? '0 1px 1px 1px' : '0 1px',
    whiteSpace: 'pre-wrap',
    resize: 'none',
    overflow: 'hidden',
    fontFamily: 'inherit',
    // 预览态不拦截鼠标(点击穿透到单元格矩形触发编辑);编辑态可点击定位光标
    pointerEvents: editing ? 'auto' : 'none',
    cursor: editing ? 'text' : 'pointer'
  }
}
</script>

<style scoped>
.cell-edit-input {
  /* 必须 block:input 默认按行内替换元素排版,下边缘对齐 foreignObject 行盒的
     基线,会被 strut 的下伸空间顶下去约 6mm,而行高只有 8mm——文字就落到下一格了 */
  display: block;
  width: 100%;
  height: auto;
  margin: 0;
  border: none; outline: none;
  background: transparent; box-sizing: border-box;
}
.cell-edit-wrapper {
  overflow: hidden;
}
</style>
