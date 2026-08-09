<template>
  <div class="app-container">
    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <span style="font-weight:600;font-size:15px;">工程图编辑器</span>
      <el-select v-model="selectedModel" placeholder="选择型号" filterable @change="onModelChange">
        <el-option v-for="m in models" :key="m" :label="m" :value="m" />
      </el-select>
      <el-button type="primary" :loading="loading" @click="loadDXF" :disabled="!selectedModel">
        加载工程图
      </el-button>
      <el-button @click="downloadDXF" :disabled="!selectedModel">下载 DXF</el-button>
      <div class="status">
        <span v-if="loadingText" class="text">{{ loadingText }}</span>
        <span v-if="lastElapsed" class="ok">耗时 {{ lastElapsed }}s</span>
        <span v-if="error" class="err">{{ error }}</span>
      </div>
    </div>

    <!-- CAD 查看器 -->
    <!--
      关键 props 说明：
      1. 不设置 useMainThreadDraw（默认 true）：使用主线程渲染。
         原先 :useMainThreadDraw="false" 启用 worker 模式，会请求
         /assets/mtext-renderer-worker.js，但 @mlightcad/mtext-renderer 包未安装，
         worker 文件不存在，Vite dev server 返回 HTML SPA fallback，触发
         "non-JavaScript MIME type text/html" 严格 MIME 检查错误。
      2. baseUrl 末尾必须带 "/"：修复 cad-simple-viewer 内部 BUG。
         AcApDocManager.js 中 DEFAULT_BASE_URL = '.../cad-data'（末尾无 /），
         第 250 行 this._fontLoader.baseUrl = this._baseUrl + 'fonts/'
         拼接后变成 '.../cad-datafonts/'，请求 fonts.json 时返回 404。
         显式传入带 "/" 结尾的 baseUrl，拼接后正确为 '.../cad-data/fonts/'。
    -->
    <div class="cad-container">
      <MlCadViewer
        ref="cadViewer"
        locale="zh"
        theme="light"
        :mode="8"
        :url="dxfUrl"
        baseUrl="https://cdn.jsdelivr.net/gh/mlightcad/cad-data/"
        @create="onViewerCreate"
      />
      <!-- 加载遮罩 -->
      <div v-if="loading" class="loading-overlay">
        <el-icon class="is-loading"><Loading /></el-icon>
        <div class="text">{{ loadingText || '正在生成工程图...' }}</div>
        <div class="sub">STEP → HLR投影 → 模板匹配 → DXF导出</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { MlCadViewer } from '@mlightcad/cad-viewer'

const models = ref([])
const selectedModel = ref('')
const loading = ref(false)
const loadingText = ref('')
const error = ref('')
const lastElapsed = ref(null)
const dxfUrl = ref('')
const cadViewer = ref(null)

// 加载型号列表
onMounted(async () => {
  try {
    const res = await fetch('/api/files')
    const data = await res.json()
    if (data.ok && data.groups) {
      const all = []
      for (const g of data.groups) {
        for (const f of g.files || []) {
          if (f.name === 'assembly.step') {
            all.push(g.model)
          }
        }
      }
      models.value = all
    }
  } catch (e) {
    error.value = '获取型号列表失败'
  }
})

function onModelChange() {
  dxfUrl.value = ''
  error.value = ''
  lastElapsed.value = null
}

// 加载 DXF 工程图
async function loadDXF() {
  if (!selectedModel.value) return
  loading.value = true
  loadingText.value = '正在生成工程图 (STEP→投影→标注→DXF)...'
  error.value = ''

  try {
    // 先调用生成 API(会生成 drawing.dxf 文件)
    const res = await fetch(`/api/drawing-dxf/${selectedModel.value}`)
    if (!res.ok) {
      const err = await res.json()
      error.value = err.error || '生成失败'
      loading.value = false
      return
    }

    // 获取 blob 并创建本地 URL
    const blob = await res.blob()
    if (dxfUrl.value) URL.revokeObjectURL(dxfUrl.value)
    dxfUrl.value = URL.createObjectURL(blob)

    loadingText.value = '正在加载到 cad-viewer...'
    // cad-viewer 会自动加载 url prop 指向的文件
    setTimeout(() => {
      loading.value = false
      loadingText.value = ''
    }, 2000)

  } catch (e) {
    error.value = e.message || '加载失败'
    loading.value = false
  }
}

// 下载 DXF 文件
function downloadDXF() {
  if (!selectedModel.value) return
  window.open(`/api/drawing-dxf/${selectedModel.value}`, '_blank')
}

function onViewerCreate() {
  console.log('cad-viewer 已创建')
}
</script>
