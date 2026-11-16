<template>
  <!-- 标注右键菜单：切换线性标注箭头方向 -->
  <ul
    v-if="menu"
    class="dim-ctx-menu"
    :style="{ left: menu.x + 'px', top: menu.y + 'px' }"
    @click.stop @contextmenu.prevent
  >
    <li :class="{ active: menu.currentMode === 'outward' }" @click="emit('set-mode', 'outward')">
      箭头向外（中间指向两边）
    </li>
    <li :class="{ active: menu.currentMode === 'inward' }" @click="emit('set-mode', 'inward')">
      箭头向内（两边指向中间）
    </li>
    <li class="ctx-sep"></li>
    <li :class="{ active: menu.currentMode === 'auto' }" @click="emit('set-mode', 'auto')">
      自动
    </li>
  </ul>
</template>

<script setup>
defineProps({ menu: { type: Object, default: null } })  // {x, y, currentMode}
const emit = defineEmits(['set-mode'])
</script>

<style scoped>
.dim-ctx-menu {
  position: fixed; z-index: 3000; margin: 0; padding: 4px 0;
  list-style: none; background: #fff; border: 1px solid #dcdfe6;
  border-radius: 4px; box-shadow: 0 2px 12px rgba(0, 0, 0, .15);
  min-width: 160px; font-size: 13px;
}
.dim-ctx-menu li {
  padding: 6px 16px; cursor: pointer; color: #303133;
}
.dim-ctx-menu li:hover { background: #ecf5ff; color: #409eff; }
.dim-ctx-menu li.active {
  color: #409eff; font-weight: 600; background: #f5f7fa;
}
.dim-ctx-menu .ctx-sep {
  height: 1px; padding: 0; margin: 4px 0; background: #ebeef5;
}
</style>
