<template>
  <!-- 表格样式工具:选中格可改字号/字体色,选中表格可改边框 -->
  <template v-if="selectedId">
    <el-input-number
      v-if="selectedCells.length === 1" size="small" :min="4" :max="40"
      :model-value="fontSize" @update:model-value="emit('font-size', $event)"
      controls-position="right" style="width:96px" aria-label="字号"
    />
    <el-color-picker
      v-if="selectedCells.length > 0" size="small"
      :model-value="cellColor" @update:model-value="emit('cell-color', $event)"
      aria-label="字体颜色"
    />
    <el-input-number size="small" :min="0.1" :max="3" :step="0.1"
      :model-value="borderWidth" @update:model-value="emit('border-width', $event)"
      controls-position="right" style="width:96px" aria-label="边框宽"
    />
    <el-color-picker size="small" :model-value="borderColor"
      @update:model-value="emit('border-color', $event)" />
  </template>
</template>

<script setup>
defineProps({
  selectedId: { type: String, default: null },
  selectedCells: { type: Array, default: () => [] },
  fontSize: { type: Number, default: 13 },
  cellColor: { type: String, default: '#303133' },
  borderWidth: { type: Number, default: 0.3 },
  borderColor: { type: String, default: '#303133' }
})

const emit = defineEmits(['font-size', 'cell-color', 'border-width', 'border-color'])
</script>
