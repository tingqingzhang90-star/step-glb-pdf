<template>
  <!-- 单元格"格内子分割"渲染:等分线 + 子格文字 + 子格命中区(承载带 part 的单元格事件) -->
  <g>
    <line
      v-for="(d, i) in dividers" :key="`sd-${i}`"
      :x1="d.x1" :y1="d.y1" :x2="d.x2" :y2="d.y2"
      :stroke="borderColor" :stroke-width="borderWidth"
      pointer-events="none"
    />
    <template v-for="pt in parts" :key="`st-${pt.i}`">
      <text
        v-if="pt.i !== activePart && pt.text"
        :x="textAnchorXInRect(pt, cell)"
        :y="textAnchorYInRect(pt, cell)"
        :font-size="cellFontSize(cell)"
        :fill="table.text_color || TABLE_STYLE.textColor"
        :text-anchor="cellTextAnchor(cell)"
        :dominant-baseline="cellTextBaseline(cell)"
        :style="{ fontWeight: cell.bold ? 'bold' : 'normal' }"
        pointer-events="none"
      >
        <template v-if="lineCount(pt) > 1">
          <tspan
            v-for="(ln, i) in lines(pt)" :key="i"
            :x="textAnchorXInRect(pt, cell)"
            :y="multiLineYs(pt, cell, lineCount(pt))[i]"
            dominant-baseline="central"
          >{{ ln || '\u00a0' }}</tspan>
        </template>
        <template v-else>{{ pt.text }}</template>
      </text>
    </template>
    <rect
      v-for="pt in parts" :key="`sh-${pt.i}`"
      :x="pt.x" :y="pt.y" :width="pt.w" :height="pt.h"
      fill="transparent" stroke="none"
      @mousedown="!readonly && fire('cell-mousedown', $event, pt.i)"
      @mouseenter="!readonly && fire('cell-mouseenter', $event, pt.i)"
      @click.stop="!readonly && fire('cell-click', $event, pt.i)"
      @dblclick.stop="!readonly && fire('cell-dblclick', $event, pt.i)"
      @contextmenu.prevent.stop="!readonly && fire('cell-contextmenu', $event, pt.i)"
    />
  </g>
</template>

<script setup>
// 一个已拆分单元格内的所有子格;part 事件由父层(TableLayer)补上 table/行列后转发
import { computed } from 'vue'
import {
  cellPartRects, textAnchorXInRect, textAnchorYInRect,
  cellFontSize, cellTextAnchor, cellTextBaseline, textLines, multiLineYs
} from '@/tables/tableGeometry'
import { TABLE_STYLE } from '@/composables/useStyleConfig'

const props = defineProps({
  table: { type: Object, required: true },
  cell: { type: Object, required: true },
  readonly: { type: Boolean, default: false },
  activePart: { type: Number, default: -1 }   // 正在悬浮/编辑的子格下标,用于隐藏其 SVG 文字
})
const emit = defineEmits(['part'])

const borderColor = computed(() => (props.table.border && props.table.border.color) || TABLE_STYLE.borderColor)
const borderWidth = computed(() => (props.table.border && props.table.border.width) || TABLE_STYLE.borderWidth)

const parts = computed(() =>
  cellPartRects(props.table, props.cell).map(p => ({
    ...p,
    text: (props.cell.parts && props.cell.parts[p.i] && props.cell.parts[p.i].text) || ''
  }))
)

/** 子格之间的等分线:'h' 竖线,'v' 横线 */
const dividers = computed(() => {
  const rs = cellPartRects(props.table, props.cell)
  const out = []
  for (let i = 1; i < rs.length; i++) {
    const b = rs[i]
    if (props.cell.split_dir === 'h') out.push({ x1: b.x, y1: b.y, x2: b.x, y2: b.y + b.h })
    else out.push({ x1: b.x, y1: b.y, x2: b.x + b.w, y2: b.y })
  }
  return out
})

function fire(type, event, part) {
  emit('part', { type, event, part })
}

function lines(pt) {
  return textLines(pt.text)
}
function lineCount(pt) {
  return textLines(pt.text).length
}
</script>
