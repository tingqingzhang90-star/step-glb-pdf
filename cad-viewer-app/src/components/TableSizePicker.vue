<template>
  <!-- Office 风格插入表格:悬停选行列,点击直接插入 -->
  <div class="table-size-picker" @mouseleave="reset">
    <div class="picker-label">{{ rows }} 行 × {{ cols }} 列</div>
    <svg :width="cell * maxCols" :height="cell * maxRows">
      <rect
        v-for="p in grid"
        :key="`${p.r}-${p.c}`"
        :x="(p.c - 1) * cell + 1"
        :y="(p.r - 1) * cell + 1"
        :width="cell - 2"
        :height="cell - 2"
        :fill="p.c <= cols && p.r <= rows ? '#409eff' : '#fff'"
        stroke="#dcdfe6"
        @mouseenter="rows = p.r; cols = p.c"
        @click="confirm"
      />
    </svg>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  maxRows: { type: Number, default: 8 },
  maxCols: { type: Number, default: 10 },
  cell: { type: Number, default: 20 },
  defaultRows: { type: Number, default: 4 },
  defaultCols: { type: Number, default: 4 }
})

const emit = defineEmits(['confirm'])

const rows = ref(props.defaultRows)
const cols = ref(props.defaultCols)

const grid = computed(() => {
  const out = []
  for (let r = 1; r <= props.maxRows; r++)
    for (let c = 1; c <= props.maxCols; c++) out.push({ r, c })
  return out
})

function confirm() {
  emit('confirm', rows.value, cols.value)
}

function reset() {
  rows.value = props.defaultRows
  cols.value = props.defaultCols
}
</script>

<style scoped>
.picker-label {
  font-size: 12px; color: #606266; margin-bottom: 6px; text-align: center;
}
.table-size-picker svg { display: block; cursor: pointer; }
</style>
