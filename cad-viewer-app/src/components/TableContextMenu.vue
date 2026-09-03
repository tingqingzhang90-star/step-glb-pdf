<template>
  <!-- 表格右键菜单:插入/删除行列。fixed 定位,点页面别处关闭 -->
  <ul
    v-if="menu"
    class="table-ctx-menu"
    :style="{ left: menu.x + 'px', top: menu.y + 'px' }"
    @click.stop @contextmenu.prevent
  >
    <li @click="emit('insert-row', 'above')">上方插入行</li>
    <li @click="emit('insert-row', 'below')">下方插入行</li>
    <li @click="emit('delete-row')">删除行</li>
    <li class="ctx-sep"></li>
    <li @click="emit('insert-col', 'left')">左侧插入列</li>
    <li @click="emit('insert-col', 'right')">右侧插入列</li>
    <li @click="emit('delete-col')">删除列</li>
  </ul>
</template>

<script setup>
defineProps({ menu: { type: Object, default: null } })  // {x, y}
const emit = defineEmits(['insert-row', 'delete-row', 'insert-col', 'delete-col'])
</script>

<style scoped>
.table-ctx-menu {
  position: fixed; z-index: 3000; margin: 0; padding: 4px 0;
  list-style: none; background: #fff; border: 1px solid #dcdfe6;
  border-radius: 4px; box-shadow: 0 2px 12px rgba(0, 0, 0, .15);
  min-width: 120px; font-size: 13px;
}
.table-ctx-menu li {
  padding: 6px 16px; cursor: pointer; color: #303133;
}
.table-ctx-menu li:hover { background: #ecf5ff; color: #409eff; }
.table-ctx-menu .ctx-sep {
  height: 1px; padding: 0; margin: 4px 0; background: #ebeef5;
}
</style>
