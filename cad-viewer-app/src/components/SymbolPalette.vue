<template>
  <div class="symbol-palette">
    <div class="panel-header">符号库</div>

    <div class="symbol-actions">
      <el-button size="small" type="primary" @click="fileInput?.click()">上传 SVG</el-button>
      <input
        ref="fileInput"
        type="file"
        accept=".svg,image/svg+xml"
        hidden
        @change="onFileChange"
      />
    </div>

    <div v-if="loading" class="panel-empty"><p>加载中…</p></div>
    <div v-else-if="!symbols.length" class="panel-empty">
      <p>暂无符号</p>
      <p class="sub">上传 SVG 后可拖入单元格</p>
    </div>
    <div v-else class="symbol-grid">
      <div
        v-for="s in symbols"
        :key="s.file"
        class="symbol-item"
        :title="`拖入单元格：${s.name}`"
        @pointerdown="onThumbPointerDown(s.file, $event)"
      >
        <img class="symbol-thumb" :src="symbolUrl(s.file)" :alt="s.name" draggable="false" />
        <span class="symbol-name">{{ s.name }}</span>
      </div>
    </div>

    <!-- 拖拽浮动预览:跟随光标,pointer-events:none 不挡命中 -->
    <div
      v-if="draggingFile && previewPos"
      class="symbol-drag-ghost"
      :style="{ left: previewPos.x + 'px', top: previewPos.y + 'px' }"
    >
      <img :src="symbolUrl(draggingFile)" draggable="false" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listSymbols, uploadSymbol, symbolUrl } from '@/api/symbols'

const props = defineProps({
  draggingFile: { type: String, default: null },
  previewPos: { type: Object, default: null }
})
const emit = defineEmits(['symbol-pointerdown'])

const symbols = ref([])
const loading = ref(false)
const fileInput = ref(null)

async function refresh() {
  loading.value = true
  try {
    const res = await listSymbols()
    if (res.ok) symbols.value = res.symbols || []
  } catch {
    // 忽略:面板加载失败不应阻塞编辑器
  } finally {
    loading.value = false
  }
}

async function onFileChange(e) {
  const f = e.target.files && e.target.files[0]
  if (!f) return
  try {
    const res = await uploadSymbol(f)
    if (res.ok) {
      ElMessage.success(`已上传符号「${res.name}」`)
      await refresh()
    } else {
      ElMessage.error(res.error || '上传失败')
    }
  } catch (err) {
    ElMessage.error(`上传失败: ${err.message}`)
  } finally {
    e.target.value = ''
  }
}

function onThumbPointerDown(file, event) {
  emit('symbol-pointerdown', file, event)
}

onMounted(refresh)
</script>

<style scoped>
.symbol-palette {
  margin-top: 12px;
  padding: 0 12px;
}
.panel-header {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}
.symbol-actions {
  margin-bottom: 8px;
}
.panel-empty {
  text-align: center;
  padding: 20px 0;
  color: #909399;
  font-size: 13px;
  line-height: 1.6;
}
.panel-empty .sub {
  font-size: 12px;
  color: #c0c4cc;
}
.symbol-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px;
  max-height: 220px;
  overflow-y: auto;
}
.symbol-item {
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 4px;
  cursor: grab;
  background: #fff;
  text-align: center;
  user-select: none;
}
.symbol-item:active {
  cursor: grabbing;
}
.symbol-thumb {
  width: 100%;
  height: 48px;
  object-fit: contain;
  pointer-events: none;
}
.symbol-name {
  display: block;
  font-size: 11px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.symbol-drag-ghost {
  position: fixed;
  width: 56px;
  height: 56px;
  transform: translate(-50%, -50%);
  pointer-events: none;
  z-index: 9999;
  opacity: 0.85;
  border: 1px dashed #409eff;
  background: #fff;
  border-radius: 4px;
  padding: 2px;
}
.symbol-drag-ghost img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
</style>
