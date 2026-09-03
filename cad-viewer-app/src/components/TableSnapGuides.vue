<template>
  <!-- 表格吸附引导线:命中时贯穿图纸,两端加端点标记;
       品红与蓝/绿/橙手柄区分开,2px 加粗便于看清 -->
  <g v-if="guides.length > 0" class="table-snap-guides" pointer-events="none">
    <template v-for="(g, i) in guides" :key="`ts-${i}`">
      <line
        v-if="g.axis === 'vertical'"
        :x1="g.pos" :y1="inset" :x2="g.pos" :y2="sheetHeight - inset"
        stroke="#e84393" stroke-width="2" stroke-dasharray="10,4"
        vector-effect="non-scaling-stroke"
      />
      <line
        v-else
        :x1="inset" :y1="g.pos" :x2="sheetWidth - inset" :y2="g.pos"
        stroke="#e84393" stroke-width="2" stroke-dasharray="10,4"
        vector-effect="non-scaling-stroke"
      />
      <circle
        v-if="g.axis === 'vertical'"
        :cx="g.pos" :cy="inset" r="3" fill="#e84393"
        vector-effect="non-scaling-stroke"
      />
      <circle
        v-else
        :cx="inset" :cy="g.pos" r="3" fill="#e84393"
        vector-effect="non-scaling-stroke"
      />
    </template>
  </g>
</template>

<script setup>
defineProps({
  guides: { type: Array, default: () => [] },   // {axis, pos}
  sheetWidth: { type: Number, required: true },
  sheetHeight: { type: Number, required: true },
  inset: { type: Number, default: 20 }          // 与图框内缩一致
})
</script>
