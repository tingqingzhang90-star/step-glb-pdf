<template>
  <!-- 表格右键菜单:插入/删除行列、单元格对齐。fixed 定位,横向网格排列,
       自动检测视口边界避免拖到底部时选项被截断。 -->
  <ul
    v-if="menu"
    ref="menuEl"
    class="table-ctx-menu"
    :style="style"
    @click.stop @contextmenu.prevent
  >
    <li @click="emit('insert-row', 'above')">上方插入行</li>
    <li @click="emit('insert-row', 'below')">下方插入行</li>
    <li @click="emit('delete-row')">删除行</li>
    <li class="ctx-sep"></li>
    <li @click="emit('insert-col', 'left')">左侧插入列</li>
    <li @click="emit('insert-col', 'right')">右侧插入列</li>
    <li @click="emit('delete-col')">删除列</li>
    <li class="ctx-sep"></li>
    <li class="ctx-group-title">水平对齐</li>
    <li @click="emit('set-align', 'h-left')">左对齐</li>
    <li @click="emit('set-align', 'h-center')">水平居中</li>
    <li @click="emit('set-align', 'h-right')">右对齐</li>
    <li class="ctx-sep"></li>
    <li class="ctx-group-title">垂直对齐</li>
    <li @click="emit('set-align', 'v-top')">顶端对齐</li>
    <li @click="emit('set-align', 'v-center')">垂直居中</li>
    <li @click="emit('set-align', 'v-bottom')">底端对齐</li>
  </ul>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({ menu: { type: Object, default: null } })  // {x, y}
const emit = defineEmits(['insert-row', 'delete-row', 'insert-col', 'delete-col', 'set-align'])

const menuEl = ref(null)
const adjust = ref({ x: 0, y: 0 })
const ready = ref(false)

watch(() => props.menu, async (v) => {
  ready.value = false
  adjust.value = { x: 0, y: 0 }
  if (!v) return
  await nextTick()
  const el = menuEl.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const margin = 8
  let dx = 0, dy = 0
  const maxX = window.innerWidth - rect.width - margin
  const maxY = window.innerHeight - rect.height - margin
  if (v.x > maxX) dx = maxX - v.x
  if (v.y > maxY) dy = maxY - v.y
  if (v.x + dx < margin) dx = margin - v.x
  if (v.y + dy < margin) dy = margin - v.y
  adjust.value = { x: dx, y: dy }
  ready.value = true
}, { immediate: true, flush: 'post' })

const style = computed(() => {
  const v = props.menu
  if (!v) return {}
  return {
    left: `${v.x + adjust.value.x}px`,
    top: `${v.y + adjust.value.y}px`,
    opacity: ready.value ? 1 : 0,
    transition: 'opacity 0.05s'
  }
})
</script>

<style scoped>
.table-ctx-menu {
  position: fixed; z-index: 3000; margin: 0; padding: 4px;
  list-style: none; background: #fff; border: 1px solid #dcdfe6;
  border-radius: 4px; box-shadow: 0 2px 12px rgba(0, 0, 0, .15);
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 2px;
  width: 246px;
  font-size: 13px;
  user-select: none;
}
.table-ctx-menu li {
  padding: 6px 4px; cursor: pointer; color: #303133;
  text-align: center; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
  border-radius: 2px;
}
.table-ctx-menu li:hover { background: #ecf5ff; color: #409eff; }
.table-ctx-menu .ctx-sep { display: none; }
.table-ctx-menu .ctx-group-title {
  grid-column: 1 / -1;
  padding: 4px 8px;
  font-size: 12px;
  color: #909399;
  text-align: left;
  cursor: default;
  background: transparent;
}
.table-ctx-menu .ctx-group-title:hover {
  background: transparent;
  color: #909399;
}
</style>
